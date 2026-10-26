"""Actual byte imports and restart recovery, isolated from every user workspace."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.services.library_batch import LibraryBatchImporter
from threaddesk.services.library_import import LibraryImportError, LibraryImporter
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def setup(tmp_path, request, monkeypatch):
    store = request.param(tmp_path / "workspace")
    monkeypatch.setattr(LibraryBatchImporter, "_project", lambda self: {"status": "ready", "created": 0, "updated": 0})
    yield store, tmp_path / "sources"
    if hasattr(store, "connection"):
        store.connection.close()


def row(source, *, name="document.txt", source_ref="library-source-1", **kwargs):
    source.mkdir(parents=True, exist_ok=True)
    path = source / name
    path.write_text("Eine vollständige lokale Originaldatei.\n", encoding="utf-8")
    return {"path": str(path), "original_path": "/Originals/" + name,
            "source_ref": source_ref, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size, **kwargs}


def test_verified_import_receipts_metadata_assignment_and_restart(setup):
    store, source = setup
    svc = ThreadService(store=store)
    project = svc.create("Zielprojekt")
    node = svc.create_node("project", "Graphprojekt")
    entry = row(source, thread_id=project.id, node_id=node.id, historical_identity="unverified")
    origin = Path(entry["path"])
    before = origin.read_bytes(), origin.stat().st_mtime_ns
    first = LibraryBatchImporter(store).run({"files": [entry]}, operation_id="import-once")
    assert first["complete"]
    receipt = first["files"][0]
    assert receipt["status"] == "stored"
    assert receipt["thread_id"] == project.id
    importer = LibraryImporter(store)
    blob, record = importer.open_record(receipt["record_id"])
    assert blob.read_bytes() == before[0]
    assert record["node_id"] == node.id
    assert record["source_refs"] == [entry["source_ref"]]
    assert record["source_metadata"][entry["source_ref"]]["historical_identity"] == "unverified"
    assert (origin.read_bytes(), origin.stat().st_mtime_ns) == before
    assert LibraryBatchImporter(store).resume("import-once") == first
    assert len(importer._read_records()) == 1


def test_missing_blocked_checksum_conflict_do_not_block_good_file(setup):
    store, source = setup
    valid = row(source)
    bad = row(source, name="bad.txt", source_ref="bad", sha256="0" * 64)
    missing = dict(valid, source_ref="missing", path=str(source / "gone.txt"))
    protected = dict(valid, source_ref="protected")
    result = LibraryBatchImporter(store).run(
        {"files": [valid, bad, missing, protected], "protected_exclusions": [{"source_ref": "protected"}]},
        operation_id="partial-import")
    assert [x["status"] for x in result["files"]] == ["stored", "conflict", "missing", "blocked"]
    assert not result["complete"]
    assert len(LibraryImporter(store)._read_records()) == 1


def test_missing_source_can_be_supplied_and_resumed(setup):
    store, source = setup
    entry = row(source)
    content = Path(entry["path"]).read_bytes()
    Path(entry["path"]).unlink()
    first = LibraryBatchImporter(store).run({"files": [entry]}, operation_id="resume-source")
    assert first["files"][0]["status"] == "missing"
    Path(entry["path"]).write_bytes(content)
    resumed = LibraryBatchImporter(store).resume("resume-source")
    assert resumed["complete"]
    assert len(LibraryImporter(store)._read_records()) == 1


def test_operation_conflict_and_cross_job_source_deduplication(setup):
    store, source = setup
    entry = row(source)
    batch = LibraryBatchImporter(store)
    first = batch.run({"files": [entry]}, operation_id="first")
    second = batch.run({"files": [entry]}, operation_id="second")
    assert second["files"][0]["status"] == "duplicate"
    assert second["files"][0]["record_id"] == first["files"][0]["record_id"]
    assert len(LibraryImporter(store)._read_records()) == 1
    with pytest.raises(LibraryImportError, match="operation_conflict"):
        batch.run({"files": [dict(entry, source_ref="other")]}, operation_id="first")


def test_unversioned_source_tracks_current_bytes_and_explicit_versions_are_bound(setup):
    store, source = setup
    entry = row(source)
    batch = LibraryBatchImporter(store)
    first = batch.run({"files": [entry]}, operation_id="first")
    Path(entry["path"]).write_text("Andere aktuelle Version\n")
    revised = {k: v for k, v in entry.items() if k not in {"sha256", "size"}}
    current = batch.run({"files": [revised]}, operation_id="current-source")
    assert current["complete"]
    assert current["files"][0]["predecessor_record_id"] == first["files"][0]["record_id"]
    # The historical operation keeps its original snapshot and receipt.
    assert batch.resume("first") == first
    versioned = dict(revised, source_version="v2")
    batch.run({"files": [versioned]}, operation_id="versioned")
    Path(entry["path"]).write_text("Anderer Inhalt unter gleicher Quellversion\n")
    conflict = batch.run({"files": [versioned]}, operation_id="version-conflict")
    assert conflict["files"][0]["error"] == "source_ref_conflict"
    assert len(LibraryImporter(store)._read_records()) == 2


def test_fresh_folder_snapshot_includes_additions_and_changed_versions(setup):
    store, source = setup
    entry = row(source)
    batch = LibraryBatchImporter(store)
    before = batch.manifest_for_folder(source)
    first = batch.run(before, operation_id="folder-before")
    Path(entry["path"]).write_text("Aktueller Inhalt\n")
    row(source, name="new.txt", source_ref="new")
    after = batch.manifest_for_folder(source)
    assert after["expected_count"] == 2
    second = batch.run(after, operation_id="folder-after")
    assert second["complete"]
    assert len(LibraryImporter(store)._read_records()) == 3
    assert first["files"][0]["sha256"] != next(x["sha256"] for x in second["files"] if x["original_path"] == "document.txt")


def test_restart_reconciles_record_published_before_metadata_checkpoint(setup, monkeypatch):
    store, source = setup
    project = ThreadService(store=store).create("Explizites Ziel")
    entry = row(source, thread_id=project.id)
    batch = LibraryBatchImporter(store)
    def crash(*args, **kwargs):
        raise RuntimeError("simulated process interruption after CAS publication")
    monkeypatch.setattr(batch, "_metadata", crash)
    with pytest.raises(RuntimeError):
        batch.run({"files": [entry]}, operation_id="interrupted")
    assert batch.status("interrupted")["files"][0]["status"] == "processing"
    assert len(LibraryImporter(store)._read_records()) == 1
    resumed = LibraryBatchImporter(store).resume("interrupted")
    assert resumed["complete"]
    assert resumed["files"][0]["thread_id"] == project.id
    assert len(LibraryImporter(store)._read_records()) == 1


def test_projection_failure_is_explicit_and_resumable(setup, monkeypatch):
    store, source = setup
    batch = LibraryBatchImporter(store)
    monkeypatch.setattr(batch, "_project", lambda: {"status": "failed", "error": "offline"})
    first = batch.run({"files": [row(source)]}, operation_id="projection-retry")
    assert not first["complete"] and first["projection"]["error"] == "offline"
    assert LibraryBatchImporter(store).resume("projection-retry")["complete"]
    assert len(LibraryImporter(store)._read_records()) == 1


def test_unknown_assignment_goes_to_intake_and_existing_assignment_is_preserved(setup):
    store, source = setup
    entry = row(source, thread_id="absent-thread")
    first = LibraryBatchImporter(store).run({"files": [entry]}, operation_id="intake")
    receipt = first["files"][0]
    assert store.get_thread(receipt["thread_id"]).title == "Nicht zugeordnet"
    other = ThreadService(store=store).create("Neues Ziel")
    second = LibraryBatchImporter(store).run({"files": [dict(entry, thread_id=other.id)]}, operation_id="preserve-assignment")
    assert second["files"][0]["thread_id"] == receipt["thread_id"]
    assert len(LibraryImporter(store)._read_records()) == 1


def test_symlinks_missing_node_and_source_size_conflict_are_isolated(setup):
    store, source = setup
    entry = row(source)
    link = source / "link.txt"
    link.symlink_to(entry["path"])
    rows = [dict(entry, source_ref="link", path=str(link)),
            dict(entry, source_ref="node", node_id="missing-node"),
            dict(entry, source_ref="size", size=999)]
    result = LibraryBatchImporter(store).run({"files": rows}, operation_id="isolate")
    assert [x["error"] for x in result["files"]] == ["source_symlink", "attachment_node_missing", "source_size"]
    assert not LibraryImporter(store)._read_records()


def test_checksum_binding_survives_change_between_hash_and_publication(setup, monkeypatch):
    store, source = setup
    entry = row(source)
    batch = LibraryBatchImporter(store)
    original = batch.importer._import_one
    def change(path, relative, journal):
        path.write_text("Changed while being imported\n")
        return original(path, relative, journal)
    monkeypatch.setattr(batch.importer, "_import_one", change)
    result = batch.run({"files": [entry]}, operation_id="source-race")
    assert result["files"][0]["error"] == "source_changed_during_import"
    assert not LibraryImporter(store)._read_records()


def test_expected_inventory_count_does_not_fake_missing_files(setup):
    store, source = setup
    result = LibraryBatchImporter(store).run({"files": [row(source)], "expected_count": 275}, operation_id="inventory")
    assert result["counts"]["unavailable"] == 274
    assert not result["complete"]


def test_manifest_and_receipt_paths_reject_unsafe_inputs(setup):
    store, source = setup
    batch = LibraryBatchImporter(store)
    entry = row(source)
    for manifest in [{"files": [dict(entry, original_path="../escape.txt")]},
                     {"files": [dict(entry, unknown=True)]},
                     {"files": [entry, entry]}]:
        with pytest.raises(LibraryImportError):
            batch.run(manifest, operation_id="invalid")
    with pytest.raises(LibraryImportError):
        batch.run({"files": [entry]}, operation_id="../outside")
    outside = source / "outside.json"
    outside.write_text("{}")
    (Path(store.workspace_path) / "library-batch-symlink.json").symlink_to(outside)
    with pytest.raises(LibraryImportError, match="batch_store_path"):
        batch.status("symlink")
    assert outside.read_text() == "{}"


def test_recognized_interrupted_blob_publication_is_recovered(setup):
    import os
    store, source = setup
    entry = row(source)
    batch = LibraryBatchImporter(store)
    first = batch.run({"files": [entry]}, operation_id="before-publication-recovery")
    blob = batch.importer.blobs / entry["sha256"]
    partial = blob.with_name("." + blob.name + ".abcd1234")
    os.link(blob, partial)
    assert blob.stat().st_nlink == 2
    second = LibraryBatchImporter(store).run({"files": [entry]}, operation_id="after-publication-recovery")
    assert second["complete"]
    assert second["files"][0]["record_id"] == first["files"][0]["record_id"]
    assert blob.stat().st_nlink == 1
    assert not partial.exists()


def test_new_current_source_version_inherits_existing_assignment(setup):
    store, source = setup
    service = ThreadService(store=store)
    thread = service.create("Vorhandene Zuordnung")
    node = service.create_node("project", "Vorhandener Graphknoten")
    entry = row(source, thread_id=thread.id, node_id=node.id)
    batch = LibraryBatchImporter(store)
    first = batch.run({"files": [entry]}, operation_id="assigned-before")
    Path(entry["path"]).write_text("Neue aktuelle Dateiinhalte\n")
    current_entry = {k: v for k, v in entry.items() if k not in {"sha256", "size", "thread_id", "node_id"}}
    updated = batch.run({"files": [current_entry]}, operation_id="assigned-after")
    assert updated["complete"]
    assert updated["files"][0]["thread_id"] == thread.id
    assert updated["files"][0]["node_id"] == node.id
    assert updated["files"][0]["predecessor_record_id"] == first["files"][0]["record_id"]


def test_source_reverting_to_old_bytes_keeps_acyclic_version_history(setup):
    store, source = setup
    entry = row(source)
    path = Path(entry["path"])
    original_bytes = path.read_bytes()
    batch = LibraryBatchImporter(store)
    original = batch.run({"files": [entry]}, operation_id="history-first")
    current = {k: v for k, v in entry.items() if k not in {"sha256", "size"}}
    path.write_text("Andere aktuelle Version\n")
    batch.run({"files": [current]}, operation_id="history-second")
    path.write_bytes(original_bytes)
    reverted = batch.run({"files": [current]}, operation_id="history-revert")
    assert reverted["files"][0]["record_id"] == original["files"][0]["record_id"]
    _, record = LibraryImporter(store).open_record(original["files"][0]["record_id"])
    assert not record.get("predecessor_record_id")
    assert len(LibraryImporter(store)._read_records()) == 2


def test_source_change_after_copy_preserves_snapshot_and_reports_conflict(setup, monkeypatch):
    store, source = setup
    entry = row(source)
    path = Path(entry["path"])
    original_bytes = path.read_bytes()
    batch = LibraryBatchImporter(store)
    original_metadata = batch._metadata
    def change_after_copy(*args, **kwargs):
        result = original_metadata(*args, **kwargs)
        path.write_text("Geändert nach der CAS-Veröffentlichung\n")
        return result
    monkeypatch.setattr(batch, "_metadata", change_after_copy)
    result = batch.run({"files": [entry]}, operation_id="change-after-copy")
    receipt = result["files"][0]
    assert not result["complete"]
    assert receipt["error"] == "source_changed_after_copy"
    blob, record = LibraryImporter(store).open_record(receipt["record_id"])
    assert blob.read_bytes() == original_bytes
    current = {k: v for k, v in entry.items() if k not in {"sha256", "size"}}
    updated = LibraryBatchImporter(store).run({"files": [current]}, operation_id="fresh-after-copy")
    assert updated["complete"]
    assert updated["files"][0]["predecessor_record_id"] == record["id"]
