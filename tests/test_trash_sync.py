"""Tombstones, matching restores and concurrent edits over existing sync paths."""
from copy import deepcopy

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.core.models import Thread, new_thread
from threaddesk.services.trash import TrashService
from threaddesk.server_sync.metadata import MetadataReplica, export_document, synchronize, list_conflicts, resolve_conflict, SyncError
from threaddesk.server_sync.lifecycle import conflict_value
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from test_room_sync import _books, _pair, _entry
from test_server_sync_metadata import Wire, change


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def pair(request, tmp_path):
    return request.param(tmp_path / "a"), request.param(tmp_path / "b")


def paired_room(pair):
    left, right = pair
    books = _books(left, right)
    room_id = _pair(books)
    thread = new_thread("Gemeinsam")
    for store in pair:
        store.save_thread(Thread.from_dict(thread.to_dict()))
    entry = _entry(thread.id, "shared1", "Erhalten", room_id)
    for store in pair:
        store.append_whiteboard_entry(deepcopy(entry))
    return books, room_id, thread.id


def test_room_v2_trash_restore_and_stale_v1_never_resurrect(pair):
    left, right = pair
    books, room_id, thread_id = paired_room(pair)
    stale = books["a"].export_bundle(room_id)
    service = TrashService(left)
    entry = service.move(kind="thread", object_id=thread_id,
        expected_revision=left.get_thread(thread_id).revision, operation_id="move")["entry"]
    bundle = books["a"].export_bundle(room_id)
    assert bundle["schema"] == "threaddesk.room.v2"
    assert books["b"].apply_bundle(bundle)["conflicts"] == 0
    assert right.object_in_trash("thread", thread_id)
    assert books["b"].apply_bundle(stale)["conflicts"] == 1
    assert right.object_in_trash("thread", thread_id)
    assert TrashService(right).sync_conflicts()[0]["reason"] == "late_room_data_after_lifecycle_change"
    service.restore(trash_id=entry["trash_id"], generation=1, expected_revision=1, operation_id="restore")
    assert books["b"].apply_bundle(books["a"].export_bundle(room_id))["conflicts"] == 0
    assert right.get_thread(thread_id).title == "Gemeinsam"
    assert right.list_whiteboard(thread_id)[0].id == "shared1"
    assert right.get_current_id() is None
    old_restore = books["a"].export_bundle(room_id)
    service.move(kind="thread", object_id=thread_id, expected_revision=left.get_thread(thread_id).revision, operation_id="move2")
    books["b"].apply_bundle(books["a"].export_bundle(room_id))
    assert books["b"].apply_bundle(old_restore)["conflicts"] > 0
    assert right.get_object_lifecycle("thread", thread_id)["generation"] == 2
    assert right.object_in_trash("thread", thread_id)


def test_room_delete_edit_conflict_keeps_private_data_and_is_durable(pair):
    left, right = pair
    books, room_id, thread_id = paired_room(pair)
    edited = right.get_thread(thread_id)
    edited.context.notes = "Private concurrent edit"
    right.save_thread(edited)
    TrashService(left).move(kind="thread", object_id=thread_id,
        expected_revision=left.get_thread(thread_id).revision, operation_id="move")
    result = books["b"].apply_bundle(books["a"].export_bundle(room_id))
    assert result["conflicts"] == 1
    assert right.get_thread(thread_id).context.notes == "Private concurrent edit"
    restarted = type(right)(right.root)
    assert TrashService(restarted).sync_conflicts()[0]["reason"] == "concurrent_content_change"


@pytest.mark.parametrize("choice", ["keep_local", "adopt_incoming"])
def test_room_conflict_resolution_is_exact_replayable_and_keeps_private_payload(pair, choice):
    left, right = pair
    books, room_id, thread_id = paired_room(pair)
    edited = right.get_thread(thread_id)
    edited.context.notes = "Private version"
    right.save_thread(edited)
    TrashService(left).move(kind="thread", object_id=thread_id,
        expected_revision=left.get_thread(thread_id).revision, operation_id="move")
    incoming = books["a"].export_bundle(room_id)
    books["b"].apply_bundle(incoming)
    service = TrashService(right)
    conflict = service.sync_conflicts()[0]
    request = dict(conflict_id=conflict["operation_id"], expected_object_digest=conflict["expected_object_digest"],
                   choice=choice, operation_id="resolve")
    with pytest.raises(ManagementError) as error:
        service.resolve_sync_conflict(**{**request, "expected_object_digest": "stale"})
    assert error.value.code == "revision_conflict"
    result = service.resolve_sync_conflict(**request)
    assert result["state"] == "resolved"
    assert service.resolve_sync_conflict(**request)["duplicate"]
    assert not service.sync_conflicts()
    assert books["b"].apply_bundle(incoming)["conflicts"] == 0
    assert right.get_thread(thread_id, include_trashed=True).context.notes == "Private version"
    assert right.object_in_trash("thread", thread_id) is (choice == "adopt_incoming")


def setup_metadata(pair, tmp_path):
    local, remote = (ThreadService(store) for store in pair)
    tid, pid = local.create("Projekt").id, remote.create("Projekt").id
    wire = Wire(remote, pid)
    replica = MetadataReplica(local, tid, tmp_path / "checkpoint", remote_identity=pid)
    replica.sync_once(wire.http, pid, "token")
    return local, tid, remote, pid, wire, replica


def test_metadata_tombstone_restore_and_late_legacy_edit(pair, tmp_path):
    local, tid, remote, pid, wire, replica = setup_metadata(pair, tmp_path)
    stale = export_document(local, tid)
    service = TrashService(local.store)
    entry = service.move(kind="thread", object_id=tid, expected_revision=local.get(tid).revision,
                         operation_id="move")["entry"]
    result = replica.sync_once(wire.http, pid, "token")
    assert result["state"] == "synced"
    assert remote.store.object_in_trash("thread", pid)
    legacy = deepcopy(stale)
    legacy["thread"]["notes"] = "Delayed old writer"
    late = synchronize(remote, pid, "legacy-late", stale, legacy)
    assert late["state"] == "conflict"
    assert late["conflicts"][0]["reason"] == "legacy_or_stale_lifecycle_writer"
    assert remote.store.object_in_trash("thread", pid)
    service.restore(trash_id=entry["trash_id"], generation=1, expected_revision=1, operation_id="restore")
    result = replica.sync_once(wire.http, pid, "token")
    assert remote.get(pid).title == "Projekt"
    assert remote.get(pid).context.notes == ""
    assert result["document"]["lifecycle"]["thread"]["state"] == "restored"
    assert remote.store.get_current_id() is None
    replica.close()


def test_metadata_delete_edit_conflict_keeps_both_versions(pair, tmp_path):
    local, tid, remote, pid, wire, replica = setup_metadata(pair, tmp_path)
    change(remote, pid, notes="Concurrent remote note")
    TrashService(local.store).move(kind="thread", object_id=tid,
        expected_revision=local.get(tid).revision, operation_id="move")
    result = replica.sync_once(wire.http, pid, "token")
    assert result["state"] == "conflict"
    assert remote.get(pid).context.notes == "Concurrent remote note"
    assert local.store.object_in_trash("thread", tid)
    assert any(c["reason"] == "concurrent_delete_edit" for c in list_conflicts(remote, pid))
    assert any(c["reason"] == "legacy_or_stale_lifecycle_writer" for c in list_conflicts(local, tid))
    replica.close()


def test_metadata_lifecycle_resolution_binds_full_current_document(pair, tmp_path):
    local, tid, remote, pid, wire, replica = setup_metadata(pair, tmp_path)
    change(remote, pid, notes="Keep this concurrent version")
    TrashService(local.store).move(kind="thread", object_id=tid,
        expected_revision=local.get(tid).revision, operation_id="move")
    replica.sync_once(wire.http, pid, "token")
    conflict = list_conflicts(remote, pid)[0]
    observed = conflict_value(export_document(remote, pid), conflict["path"])
    change(remote, pid, notes="Even newer concurrent version")
    with pytest.raises(SyncError, match="changed"):
        resolve_conflict(remote, pid, conflict["id"], observed, conflict["incoming"], "stale-resolve")
    fresh = conflict_value(export_document(remote, pid), conflict["path"])
    resolved = resolve_conflict(remote, pid, conflict["id"], fresh, conflict["incoming"], "accept-exact-trash")
    assert resolved["state"] == "synced"
    assert not list_conflicts(remote, pid)
    entry = remote.store.get_object_lifecycle("thread", pid)
    TrashService(remote.store).restore(trash_id=entry["trash_id"], generation=entry["generation"],
                                      expected_revision=entry["revision"], operation_id="restore")
    assert remote.get(pid).context.notes == "Even newer concurrent version"
    replica.close()


def test_metadata_restored_history_requires_explicit_adoption_and_no_stale_restore(pair, tmp_path):
    local, tid, remote, pid, wire, replica = setup_metadata(pair, tmp_path)
    service = TrashService(local.store)
    entry = service.move(kind="thread", object_id=tid, expected_revision=local.get(tid).revision,
                         operation_id="move")["entry"]
    service.restore(trash_id=entry["trash_id"], generation=1, expected_revision=1, operation_id="restore")
    replica.sync_once(wire.http, pid, "token")
    conflict = list_conflicts(remote, pid)[0]
    assert conflict["reason"] == "restore_without_matching_generation"
    current = conflict_value(export_document(remote, pid), conflict["path"])
    resolve_conflict(remote, pid, conflict["id"], current, conflict["incoming"], "adopt-history")
    assert remote.store.get_object_lifecycle("thread", pid)["state"] == "restored"
    assert remote.get(pid).title == "Projekt"
    old_restore = export_document(local, tid)
    second = TrashService(remote.store).move(kind="thread", object_id=pid,
        expected_revision=remote.get(pid).revision, operation_id="second-move")["entry"]
    result = synchronize(remote, pid, "late-restored-history", old_restore, old_restore)
    stale = result["conflicts"][0]
    assert stale["reason"] == "stale_generation"
    actual = conflict_value(export_document(remote, pid), stale["path"])
    with pytest.raises(SyncError):
        resolve_conflict(remote, pid, stale["id"], actual, stale["incoming"], "reject-stale-restore")
    assert remote.store.get_object_lifecycle("thread", pid)["trash_id"] == second["trash_id"]
    assert remote.store.object_in_trash("thread", pid)
    replica.close()


def test_metadata_node_tombstone_keeps_relation_ids_and_restores(pair, tmp_path):
    local, tid, remote, pid, wire, replica = setup_metadata(pair, tmp_path)
    node = local.create_node("project", "Graph", metadata={"thread_id": tid})
    replica.sync_once(wire.http, pid, "token")
    remote_node_id = next(n.id for n in remote.store.list_nodes() if n.title == "Graph")
    service = TrashService(local.store)
    entry = service.move(kind="node", object_id=node.id, expected_revision=node.revision, operation_id="node-move")["entry"]
    result = replica.sync_once(wire.http, pid, "token")
    assert result["state"] == "synced"
    assert not remote.store.list_nodes()
    assert remote.store.get_node(remote_node_id, include_trashed=True).title == "Graph"
    service.restore(trash_id=entry["trash_id"], generation=1, expected_revision=1, operation_id="node-restore")
    replica.sync_once(wire.http, pid, "token")
    assert remote.store.list_nodes()[0].id == remote_node_id
    replica.close()
