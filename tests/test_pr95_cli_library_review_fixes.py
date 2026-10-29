"""Explicit CLI revisions and trash-owned projections preserve current data."""
from types import SimpleNamespace

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.services.library_batch import LibraryBatchImporter
from threaddesk.services.library_files import LibraryFileService
from threaddesk.services.library_links import sync_file_nodes
from threaddesk.services.trash import TrashService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.ui.thread_cli_mutations import change


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def store(tmp_path, request):
    value = request.param(tmp_path / "workspace")
    yield value
    if isinstance(value, SQLiteStore):
        value.connection.close()


def test_stale_explicit_cli_revision_without_id_preserves_newer_edit(store):
    service = ThreadService(store)
    thread = service.create("Current thread")
    stale_revision = thread.revision
    service.set_note("Newer edit must survive", thread.id)
    before = service.get(thread.id).to_dict()

    with pytest.raises(ManagementError) as error:
        change(service, SimpleNamespace(expected_revision=stale_revision, operation_id=None),
               "set_note", {"text": "Stale edit"})

    assert error.value.code == "revision_conflict"
    assert service.get(thread.id).to_dict() == before


@pytest.mark.parametrize("explicit_revision", [True, False], ids=["explicit", "legacy-auto"])
def test_current_cli_edit_keeps_explicit_or_automatic_revision(store, explicit_revision):
    service = ThreadService(store)
    thread = service.create("Current thread")
    expected = thread.revision if explicit_revision else None

    result = change(service, SimpleNamespace(expected_revision=expected, operation_id=None),
                    "set_note", {"text": "Accepted edit"})

    assert result["thread"]["id"] == thread.id
    assert result["thread"]["revision"] == thread.revision + 1
    assert service.get(thread.id).context.notes == "Accepted edit"


def test_live_file_rename_keeps_trashed_node_restorable_and_refreshes_after_restore(store, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    original = source / "original.txt"
    original.write_bytes(b"Original bytes remain unchanged.\n")
    batch = LibraryBatchImporter(store)
    imported = batch.run(batch.manifest_for_folder(source.resolve()), operation_id="initial-import")
    identity = imported["files"][0]["record_id"]
    node = store.get_node(identity)
    before = node.to_dict()
    trash = TrashService(store)
    entry = trash.move(kind="node", object_id=identity, expected_revision=node.revision,
                       operation_id="trash-generated-node")["entry"]
    files = LibraryFileService(store)
    record = files.info(identity)

    renamed = files.manage({"action": "rename", "id": identity,
                            "expected_revision": record["revision"],
                            "operation_id": "rename-live-record", "data": {"filename": "renamed.txt"}})

    assert renamed["record"]["filename"] == "renamed.txt"
    assert not renamed["record"]["trashed"]
    assert store.get_node(identity, include_trashed=True).to_dict() == before
    assert sync_file_nodes(store) == {"created": 0, "updated": 0}
    assert store.get_node(identity, include_trashed=True).to_dict() == before
    assert trash.get(entry["trash_id"]) == entry
    assert identity not in {item.id for item in store.list_nodes()}

    restored = trash.restore(trash_id=entry["trash_id"], generation=entry["generation"],
                             expected_revision=entry["revision"], operation_id="restore-generated-node")
    assert restored["entry"]["state"] == "restored"
    # The existing restore callback refreshes live projections after checking
    # their trash-bound digest; the restored identity gets the current name.
    assert store.get_node(identity).title == "renamed.txt"
    assert sync_file_nodes(store) == {"created": 0, "updated": 0}
    blob, _record = files.importer.open_record(identity)
    assert blob.read_bytes() == original.read_bytes() == b"Original bytes remain unchanged.\n"
