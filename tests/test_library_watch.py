"""Explicit source watches use real resumable imports and temporary workspaces."""

from pathlib import Path

import pytest

from threaddesk.services.library_batch import LibraryBatchImporter
from threaddesk.services.library_import import LibraryImporter, LibraryImportError
from threaddesk.services.library_watch import LibrarySourceWatch
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def context(tmp_path, request, monkeypatch):
    store = request.param(tmp_path / "workspace")
    source = tmp_path / "selected"
    source.mkdir()
    # Root owns the not-yet-integrated graph projection; byte import and FTS are real.
    monkeypatch.setattr(
        LibraryBatchImporter, "_project", lambda self: {"status": "ready"}
    )
    yield store, source
    if isinstance(store, SQLiteStore):
        store.connection.close()


def only(result):
    return result["watches"][0]


def test_change_add_rename_and_external_delete_keep_originals_and_stored_bytes(context):
    store, source = context
    file = source / "first.md"
    file.write_text("first content")
    watch = LibrarySourceWatch(store)
    watch.register(source)
    first = only(watch.poll_once())
    assert first["status"] == "ready"
    old = first["operation_id"]
    file.write_text("changed content")
    assert only(watch.poll_once())["operation_id"] != old
    second = source / "new.md"
    second.write_text("new content")
    assert only(watch.poll_once())["receipt"]["counts"]["stored"] >= 1
    file.rename(source / "renamed.md")
    renamed = only(watch.poll_once())
    assert "first.md" in {row["path"] for row in renamed["missing_sources"]}
    second.unlink()
    removed = only(watch.poll_once())
    assert {"first.md", "new.md"} <= {row["path"] for row in removed["missing_sources"]}
    importer = LibraryImporter(store)
    assert all(
        (importer.blobs / row["sha256"]).exists() for row in importer._read_records()
    )
    assert (source / "renamed.md").read_text() == "changed content"


def test_unchanged_source_has_no_hash_import_index_or_registry_write(
    context, monkeypatch
):
    store, source = context
    (source / "file.md").write_text("unchanged")
    watch = LibrarySourceWatch(store)
    watch.register(source)
    watch.poll_once()
    artifact = Path(store.workspace_path) / "library-watch.json"
    before = artifact.read_bytes(), artifact.stat().st_mtime_ns

    def forbidden(*args, **kwargs):
        raise AssertionError("unchanged source must not enter importer")

    monkeypatch.setattr(LibraryBatchImporter, "manifest_for_folder", forbidden)
    monkeypatch.setattr(LibraryBatchImporter, "run", forbidden)
    assert watch.poll_once()["outcomes"][0]["status"] == "unchanged"
    assert (artifact.read_bytes(), artifact.stat().st_mtime_ns) == before


def test_restart_and_reverted_content_get_new_transition_receipt(context):
    store, source = context
    file = source / "file.md"
    file.write_text("version A")
    watch = LibrarySourceWatch(store)
    watch.register(source)
    first = only(watch.poll_once())
    file.write_text("version B")
    middle = only(LibrarySourceWatch(store).poll_once())
    file.write_text("version A")
    last = only(LibrarySourceWatch(store).poll_once())
    assert (
        len({first["operation_id"], middle["operation_id"], last["operation_id"]}) == 3
    )
    assert last["sequence"] == 3
    assert last["last_success"] is not None


def test_offline_then_same_root_return_recovers_without_deleting_copy(context):
    store, source = context
    (source / "file.md").write_text("local preserved")
    watch = LibrarySourceWatch(store)
    watch.register(source)
    success = only(watch.poll_once())["last_success"]
    moved = source.with_name("offline")
    source.rename(moved)
    unavailable = only(watch.poll_once())
    assert unavailable["status"] == "unavailable"
    assert unavailable["last_success"] == success
    assert len(LibraryImporter(store)._read_records()) == 1
    moved.rename(source)
    # A return may be delayed by the documented error backoff, not re-imported blindly.
    import threaddesk.services.library_watch.service as module

    original = module.time
    module.time = lambda: original() + 31
    try:
        assert only(watch.poll_once())["status"] == "ready"
    finally:
        module.time = original


def test_symlinks_and_replaced_root_never_follow_new_sources(context):
    store, source = context
    outside = source.with_name("outside")
    outside.mkdir()
    (outside / "secret.md").write_text("outside")
    link = source.with_name("linked")
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(LibraryImportError, match="source_symlink"):
        LibrarySourceWatch(store).register(link)
    watch = LibrarySourceWatch(store)
    watch.register(source)
    source.rename(source.with_name("original-folder"))
    source.mkdir()
    (source / "new.md").write_text("not the authorized inode")
    assert only(watch.poll_once())["last_error"] == "source_replaced"
    assert not LibraryImporter(store)._read_records()


def test_partial_secret_failure_isolated_with_same_error_backoff(context, monkeypatch):
    store, source = context
    (source / "good.md").write_text("good content")
    (source / ".env").write_text("SECRET=ignored")
    watch = LibrarySourceWatch(store)
    watch.register(source)
    result = only(watch.poll_once())
    assert result["status"] == "partial"
    assert result["receipt"]["counts"]["stored"] == 1
    assert result["receipt"]["counts"]["blocked"] == 1
    job = LibraryBatchImporter(store).status(result["receipt"]["operation_id"])
    assert any(item.get("error") == "secret_name" for item in job["files"])
    assert result["last_success"] is None

    def forbidden(*args, **kwargs):
        raise AssertionError("same failure should back off")

    monkeypatch.setattr(LibraryBatchImporter, "resume", forbidden)
    assert watch.poll_once()["outcomes"][0]["status"] == "backoff"


def test_incomplete_scan_budget_never_hashes_or_imports(context, monkeypatch):
    store, source = context
    (source / "one.md").write_text("one")
    (source / "two.md").write_text("two")
    watch = LibrarySourceWatch(store)
    watch.register(source)
    monkeypatch.setattr("threaddesk.services.library_watch.scan.MAX_SCAN_ENTRIES", 1)

    def forbidden(*args, **kwargs):
        raise AssertionError("an incomplete snapshot must not become an import")

    monkeypatch.setattr(LibraryBatchImporter, "manifest_for_folder", forbidden)
    assert only(watch.poll_once())["last_error"] == "watch_scan_budget"
    assert not LibraryImporter(store)._read_records()


def test_registration_limit_and_idempotent_registration(tmp_path):
    store = JsonStore(tmp_path / "workspace")
    watch = LibrarySourceWatch(store)
    for i in range(8):
        folder = tmp_path / str(i)
        folder.mkdir()
        assert watch.register(folder) == watch.register(folder)
    ninth = tmp_path / "ninth"
    ninth.mkdir()
    with pytest.raises(LibraryImportError, match="watch_limit"):
        watch.register(ninth)
    assert len(watch.status()["watches"]) == 8


def test_crash_before_batch_receipt_reuses_durable_operation(context, monkeypatch):
    store, source = context
    (source / "file.md").write_text("durable source")
    watch = LibrarySourceWatch(store)
    watch.register(source)
    original = LibraryBatchImporter.run

    def interrupted(*args, **kwargs):
        raise RuntimeError("process interruption before batch receipt")

    monkeypatch.setattr(LibraryBatchImporter, "run", interrupted)
    with pytest.raises(RuntimeError):
        watch.poll_once()
    pending = only(watch.status())
    assert pending["status"] == "running"
    monkeypatch.setattr(LibraryBatchImporter, "run", original)
    resumed = only(LibrarySourceWatch(store).poll_once())
    assert resumed["status"] == "ready"
    assert resumed["operation_id"] == pending["operation_id"]
    assert resumed["sequence"] == pending["sequence"]
    assert len(LibraryImporter(store)._read_records()) == 1


def test_source_change_during_import_is_not_published_as_current(context, monkeypatch):
    store, source = context
    file = source / "file.md"
    file.write_text("before import")
    watch = LibrarySourceWatch(store)
    watch.register(source)
    original = LibraryBatchImporter.run

    def changed(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        file.write_text("after import content")
        return result

    monkeypatch.setattr(LibraryBatchImporter, "run", changed)
    first = only(watch.poll_once())
    assert first["status"] == "partial"
    assert first["receipt"]["source_current"] is False
    monkeypatch.setattr(LibraryBatchImporter, "run", original)
    second = only(watch.poll_once())
    assert second["status"] == "ready"
    assert second["operation_id"] != first["operation_id"]


def test_round_robin_does_not_starve_other_registered_roots(context):
    store, source = context
    (source / "one.md").write_text("one")
    second = source.with_name("second")
    second.mkdir()
    (second / "two.md").write_text("two")
    watch = LibrarySourceWatch(store)
    first_id = watch.register(source)["id"]
    second_id = watch.register(second)["id"]
    assert watch.poll_once()["outcomes"][0]["id"] == first_id
    (source / "one.md").write_text("changed while second still pending")
    outcome = watch.poll_once()["outcomes"][0]
    assert outcome["id"] == second_id
    assert outcome["status"] == "ready"


def test_same_size_change_with_preserved_mtime_is_detected(context):
    import os

    store, source = context
    file = source / "preserved.md"
    file.write_text("version A")
    watch = LibrarySourceWatch(store)
    watch.register(source)
    first = only(watch.poll_once())
    old = file.stat()
    file.write_text("version B")
    os.utime(file, ns=(old.st_atime_ns, old.st_mtime_ns))
    second = only(watch.poll_once())
    assert second["operation_id"] != first["operation_id"]
    assert second["status"] == "ready"
