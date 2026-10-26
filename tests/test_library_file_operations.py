"""File lifecycle changes preserve imported originals and shared CAS bytes."""
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError, NotFound
from threaddesk.services.library_import import LibraryImporter
from threaddesk.services.library_files import LibraryFileService
from threaddesk.services.library_files.state import STATE_NAME, read_state
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def example(tmp_path, request):
    store = request.param(tmp_path / "desk")
    threads = ThreadService(store=store)
    first = threads.create("Project A")
    second = threads.create("Project B")
    source = tmp_path / "source" / "Project A"
    source.mkdir(parents=True)
    original = source / "note.txt"
    original.write_text("some original content", encoding="utf-8")
    importer = LibraryImporter(store)
    result = importer.import_tree(source.parent)
    assert result["stored"] == 1
    record = importer.catalog()["records"][0]
    yield store, LibraryFileService(store), record, original, first, second
    if isinstance(store, SQLiteStore):
        store.connection.close()


def command(files, record, action, data=None, op=None):
    return files.manage({"operation_id": op or action + "-op", "action": action,
                         "id": record["id"], "expected_revision": record["revision"],
                         "data": data or {}})


def test_rename_move_copy_keep_originals_and_restart(example):
    store, files, old, original, _a, target = example
    raw_record = (files.importer.records / (old["id"] + ".json")).read_bytes()
    old_bytes = original.read_bytes()
    changed = command(files, old, "rename", {"filename": "renamed.txt"})["record"]
    assert changed["revision"] == 2
    assert changed["logical_path"] == "Project A/renamed.txt"
    moved = command(files, changed, "move", {"folder": "Sorted/2026", "thread_id": target.id})["record"]
    assert moved["thread_id"] == target.id
    assert moved["origin_path"] == old["origin_path"]
    assert not files.importer.for_thread(old["thread_id"])
    assert files.importer.for_thread(target.id)[0]["id"] == old["id"]
    copied = command(files, moved, "copy")["record"]
    assert copied["id"] != moved["id"] and copied["sha256"] == moved["sha256"]
    assert copied["origin_path"] == old["origin_path"]
    assert len(list(files.importer.blobs.glob("*"))) == 1
    again = LibraryFileService(store)
    assert again.info(moved["id"])["filename"] == "renamed.txt"
    assert again.info(copied["id"])["revision"] == 1
    assert original.read_bytes() == old_bytes
    assert (files.importer.records / (old["id"] + ".json")).read_bytes() == raw_record
    assert again.importer.open_record(copied["id"])[0].read_bytes() == old_bytes
    another = command(again, moved, "copy", op="copy-again")["record"]
    assert another["filename"] != copied["filename"]


def test_revision_idempotency_and_operation_status(example):
    _store, files, old, *_ = example
    first = command(files, old, "rename", {"filename": "new.txt"}, op="stable")
    duplicate = command(files, old, "rename", {"filename": "new.txt"}, op="stable")
    assert duplicate["duplicate"] is True
    assert duplicate["record"] == first["record"]
    with pytest.raises(ManagementError, match="Operationskennung") as conflict:
        command(files, old, "rename", {"filename": "other.txt"}, op="stable")
    assert conflict.value.code == "operation_conflict"
    with pytest.raises(ManagementError) as stale:
        command(files, old, "rename", {"filename": "stale.txt"}, op="stale")
    assert stale.value.code == "revision_conflict"
    assert files.operation_status("stable")["found"]
    assert files.operation_status("missing")["found"] is False


def test_trash_restore_stable_ids_and_new_generation(example):
    _store, files, old, *_ = example
    first = command(files, old, "trash")["record"]
    assert first["trashed"] and first["trash_generation"] == 1
    assert files.list()["records"] == []
    assert files.importer.catalog()["records"] == []
    assert not files.importer.for_thread(old["thread_id"])
    with pytest.raises(ManagementError) as error:
        files.info(old["id"])
    assert error.value.code == "object_in_trash"
    with pytest.raises(NotFound):
        files.importer.open_record(old["id"])
    assert files.list(include_trashed=True)["records"][0]["id"] == old["id"]
    preview = files.preview(old["id"])
    assert preview["kind"] == "metadata" and not preview["can_open"]
    assert preview["content_url"] is None and preview["text"] == ""
    restored = command(files, first, "restore", {"trash_generation": 1})["record"]
    assert restored["id"] == old["id"] and not restored["trashed"]
    second = command(files, restored, "trash", op="trash-second")["record"]
    assert second["trash_generation"] == 2
    with pytest.raises(ManagementError) as stale:
        command(files, second, "restore", {"trash_generation": 1}, op="restore-wrong")
    assert stale.value.code == "trash_generation_conflict"


def test_conflicting_destination_and_invalid_paths_leave_state(example):
    _store, files, old, *_ = example
    copied = command(files, old, "copy", {"filename": "other.txt"})["record"]
    before = read_state(files.root)
    with pytest.raises(ManagementError) as conflict:
        command(files, copied, "rename", {"filename": old["filename"]})
    assert conflict.value.code == "name_conflict"
    for data in [{"filename": "../escape"}, {"filename": "bad/filename"}]:
        with pytest.raises(ManagementError):
            command(files, copied, "rename", data)
    with pytest.raises(ManagementError):
        command(files, copied, "move", {"folder": "../outside"})
    assert read_state(files.root) == before


def test_list_folders_sort_and_record_node_navigation(example):
    _store, files, old, *_ = example
    assert files.list(folder="")["folders"] == ["Project A"]
    assert files.list(folder="Project A")["records"][0]["id"] == old["id"]
    assert files.list(node_id=old["id"])["records"][0]["id"] == old["id"]
    moved = command(files, old, "move", {"folder": ""})["record"]
    assert files.list(folder="")["records"][0]["id"] == moved["id"]
    assert files.list(folder="Project A")["records"] == []


def test_readonly_preview_is_bounded_and_does_not_open(example, monkeypatch):
    _store, files, old, *_ = example
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("preview launched a program"))
    info = files.preview(old["id"])
    assert info["kind"] == "text"
    assert info["text"] == "some original content"
    assert info["integrity"] == "verified"
    assert not (Path(files.store.workspace_path) / STATE_NAME).exists()


def test_explicit_open_receipt_once_and_readonly_copy(example):
    store, _files, old, original, *_ = example
    calls = []
    def opener(argv, **kwargs):
        calls.append(argv)
        opened = Path(argv[-1])
        assert opened.name == old["filename"]
        assert opened.read_bytes() == original.read_bytes()
        assert opened.stat().st_mode & 0o222 == 0
        assert argv[:4] == ["/usr/bin/open", "-a", "/System/Applications/TextEdit.app", "--"]
        return SimpleNamespace(returncode=0)
    files = LibraryFileService(store, opener=opener,
                               handler_resolver=lambda _path: "/System/Applications/TextEdit.app")
    first = files.open(old["id"], operation_id="open-once", expected_revision=1)
    second = files.open(old["id"], operation_id="open-once", expected_revision=1)
    assert len(calls) == 1 and second["duplicate"]
    assert first["status"] == "launch_requested" and not first["human_read_confirmed"]
    assert files.operation_status("open-once")["result"]["status"] == "launch_requested"
    another = files.open(old["id"], operation_id="open-another", expected_revision=1)
    assert len(calls) == 2 and another["opened_path"] == first["opened_path"]


def test_missing_handler_and_unknown_open_are_not_launched(example):
    store, files, old, *_ = example
    def missing(_path):
        raise ManagementError("no_default_application", "No app")
    files = LibraryFileService(store, opener=lambda *a, **k: pytest.fail("unexpected open"),
                               handler_resolver=missing)
    with pytest.raises(ManagementError) as error:
        files.open(old["id"], operation_id="open-missing", expected_revision=1)
    assert error.value.code == "no_default_application"
    script = command(files, old, "rename", {"filename": "script.py"})["record"]
    with pytest.raises(ManagementError) as blocked:
        files.open(script["id"], operation_id="open-script", expected_revision=script["revision"])
    assert blocked.value.code == "external_open_blocked"


def test_open_timeout_stays_unknown_and_is_not_replayed(example):
    store, _files, old, *_ = example
    calls = []
    def timeout(*args, **kwargs):
        calls.append(1)
        raise subprocess.TimeoutExpired("open", 15)
    files = LibraryFileService(store, opener=timeout,
                               handler_resolver=lambda _path: "/System/Applications/TextEdit.app")
    result = files.open(old["id"], operation_id="open-timeout", expected_revision=1)
    assert result["status"] == "unknown"
    assert files.open(old["id"], operation_id="open-timeout", expected_revision=1)["duplicate"]
    assert len(calls) == 1


def test_state_symlink_refused_without_mutating_target(example, tmp_path):
    store, files, old, *_ = example
    target = tmp_path / "outside.json"
    target.write_text("{}")
    (Path(store.workspace_path) / STATE_NAME).symlink_to(target)
    with pytest.raises(ManagementError):
        command(files, old, "trash")
    assert target.read_text() == "{}"


def test_index_failure_does_not_rollback_a_committed_operation(example, monkeypatch):
    _store, files, old, *_ = example
    from threaddesk.services.library_index import LibraryIndex
    def broken(*args, **kwargs):
        raise OSError("disk unavailable")
    monkeypatch.setattr(LibraryIndex, "rebuild", broken)
    result = command(files, old, "rename", {"filename": "committed.txt"})
    assert result["record"]["filename"] == "committed.txt"
    assert files.info(old["id"])["filename"] == "committed.txt"
    assert files.operation_status("rename-op")["found"]
