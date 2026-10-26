"""Retained source versions are history, not unrelated destination conflicts."""
from pathlib import Path

import pytest

from threaddesk.core.errors import ManagementError
from threaddesk.services.library_batch import LibraryBatchImporter
from threaddesk.services.library_files import LibraryFileService
from threaddesk.services.library_files.state import state_path
from threaddesk.services.library_import import LibraryImporter
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def source_versions(tmp_path, request):
    store = request.param(tmp_path / "desk")
    original = tmp_path / "fixture.txt"
    original.write_text("Version one", encoding="utf-8")
    entry = {"path": str(original), "original_path": "fixture.txt", "source_ref": "stable-source"}
    batch = LibraryBatchImporter(store)
    first = batch.run({"files": [entry]}, operation_id="first-source-version")
    first_id = first["files"][0]["record_id"]
    original.write_text("Version two", encoding="utf-8")
    second = batch.run({"files": [entry]}, operation_id="second-source-version")
    second_id = second["files"][0]["record_id"]
    assert first_id != second_id
    yield store, original, first_id, second_id
    if hasattr(store, "connection"):
        store.connection.close()


def change(files, record, action, data=None, operation=None):
    return files.manage({"action": action, "operation_id": operation or action,
                         "id": record["id"], "expected_revision": record["revision"],
                         "data": data or {}})["record"]


def test_current_version_restores_without_deleting_its_history(source_versions):
    store, original, previous_id, current_id = source_versions
    files = LibraryFileService(store)
    importer = LibraryImporter(store)
    older_record = (importer.records / f"{previous_id}.json").read_bytes()
    older_blob = importer.open_record(previous_id)[0].read_bytes()
    current = files.info(current_id)
    assert current["current_version"]
    trashed = change(files, current, "trash")
    restored = change(files, trashed, "restore", {"trash_generation": trashed["trash_generation"]})
    assert restored["id"] == current_id and not restored["trashed"]
    assert original.read_text() == "Version two"
    assert (importer.records / f"{previous_id}.json").read_bytes() == older_record
    assert importer.open_record(previous_id)[0].read_bytes() == older_blob
    assert not files.info(previous_id)["current_version"]
    assert {row["id"] for row in files.list()["records"]} == {previous_id, current_id}


def test_independent_copy_still_blocks_restore_into_its_path(source_versions):
    store, _original, previous_id, current_id = source_versions
    files = LibraryFileService(store)
    current = files.info(current_id)
    # Move the retained old display entry away explicitly, without deleting its
    # bytes/history, so an independent copy can legitimately occupy this path.
    change(files, files.info(previous_id), "rename", {"filename": "retained-history.txt"}, operation="history-display-name")
    copied = change(files, current, "copy", {"filename": "independent.txt"})
    trashed = change(files, current, "trash")
    copy_at_target = change(files, copied, "rename", {"filename": "fixture.txt"}, operation="copy-takes-path")
    before = state_path(files.root).read_bytes()
    with pytest.raises(ManagementError) as conflict:
        change(files, trashed, "restore", {"trash_generation": trashed["trash_generation"]})
    assert conflict.value.code == "name_conflict"
    assert state_path(files.root).read_bytes() == before
    assert files.info(current_id, include_trashed=True)["trashed"]
    assert files.info(copy_at_target["id"])["copied_from"] == current_id


def test_unrelated_record_is_not_a_predecessor_just_because_name_matches(source_versions):
    store, _original, _previous_id, current_id = source_versions
    files = LibraryFileService(store)
    current = files.info(current_id)
    trashed = change(files, current, "trash")
    # The legacy importer can retain another source snapshot at the same path.
    # It has no common source receipt, so matching names/versions prove nothing.
    importer = LibraryImporter(store)
    path = Path(store.workspace_path).parent / "unrelated.txt"
    path.write_text("Independent source", encoding="utf-8")
    record = importer.import_files([("fixture.txt", path)])["results"][0]
    unrelated = files.info(record["record_id"])
    with pytest.raises(ManagementError) as conflict:
        change(files, trashed, "restore", {"trash_generation": trashed["trash_generation"]})
    assert conflict.value.code == "name_conflict"
    assert files.info(unrelated["id"])["logical_path"] == "fixture.txt"
