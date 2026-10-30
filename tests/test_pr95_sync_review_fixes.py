"""Regressions for metadata merges with retained and newly received tombstones."""
from copy import deepcopy

import pytest
from test_server_sync_metadata import Wire

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.core.models import KnowledgeNode, Relation
from threaddesk.server_sync.metadata import (
    MetadataReplica,
    export_document,
    synchronize,
)
from threaddesk.services.trash import TrashService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def stores(request, tmp_path):
    pair = request.param(tmp_path / "local"), request.param(tmp_path / "remote")
    yield pair
    for store in pair:
        if hasattr(store, "connection"):
            store.connection.close()


def graph(core, thread_id):
    project = core.create_node("project", "Project", metadata={"thread_id": thread_id})
    task = core.create_node("task", "Task", metadata={"thread_id": thread_id})
    relation = Relation("project_task", project.id, task.id, "contains")
    core.store.save_relation(relation)
    return project, task, relation


def move(store, kind, obj):
    return TrashService(store).move(kind=kind, object_id=obj.id,
        expected_revision=obj.revision, operation_id="move-" + kind)["entry"]


@pytest.mark.parametrize("kind", ["node", "relation"])
def test_unrelated_note_merge_preserves_trashed_graph_payloads_and_restore(stores, kind):
    store, _ = stores
    core = ThreadService(store)
    thread = core.create("Project")
    project, _, relation = graph(core, thread.id)
    entry = move(store, kind, project if kind == "node" else relation)
    before_nodes = [node.to_dict() for node in store.list_nodes(include_trashed=True)]
    before_relations = [item.to_dict() for item in store.list_relations(include_trashed=True)]
    base = export_document(core, thread.id)
    incoming = deepcopy(base)
    incoming["thread"]["notes"] = "Unrelated synchronized note"

    result = synchronize(core, thread.id, "unrelated-note", base, incoming)

    assert result["state"] == "synced"
    assert core.get(thread.id).context.notes == incoming["thread"]["notes"]
    assert [node.to_dict() for node in store.list_nodes(include_trashed=True)] == before_nodes
    assert [item.to_dict() for item in store.list_relations(include_trashed=True)] == before_relations
    assert TrashService(store).get(entry["trash_id"]) == entry
    restored = TrashService(store).restore(trash_id=entry["trash_id"], generation=1,
        expected_revision=1, operation_id="restore-" + kind)
    assert restored["entry"]["state"] == "restored"
    assert {node.id for node in store.list_nodes()} == {node["id"] for node in before_nodes}
    assert [item.to_dict() for item in store.list_relations()] == before_relations


@pytest.mark.parametrize("kind", ["node", "relation"])
def test_actual_edits_to_trashed_payloads_remain_conflicts(stores, kind):
    store, _ = stores
    core = ThreadService(store)
    thread = core.create("Project")
    project, _, relation = graph(core, thread.id)
    entry = move(store, kind, project if kind == "node" else relation)
    base = export_document(core, thread.id)
    incoming = deepcopy(base)
    section = kind + "s"
    origin = next(iter(base["lifecycle"][section]))
    incoming[section][origin]["title" if kind == "node" else "kind"] = "Changed" if kind == "node" else "blocks"
    incoming["thread"]["notes"] = "Must not partially apply"

    result = synchronize(core, thread.id, "invalid-trashed-edit", base, incoming)

    assert result["state"] == "conflict"
    assert result["conflicts"][0]["reason"] == "edit_of_trashed_object"
    assert export_document(core, thread.id) == base
    assert TrashService(store).get(entry["trash_id"]) == entry


@pytest.mark.parametrize("kind", ["node", "relation"])
def test_new_graph_object_can_arrive_trashed_then_restore_with_same_ids(stores, tmp_path, kind):
    local, remote = (ThreadService(store) for store in stores)
    tid, pid = local.create("Project").id, remote.create("Project").id
    wire = Wire(remote, pid)
    replica = MetadataReplica(local, tid, tmp_path / "checkpoint", remote_identity=pid)
    try:
        replica.sync_once(wire.http, pid, "token")
        project, _, relation = graph(local, tid)
        entry = move(local.store, kind, project if kind == "node" else relation)

        result = replica.sync_once(wire.http, pid, "token")

        assert result["state"] == "synced" and result["conflicts"] == []
        origin = next(iter(result["document"]["lifecycle"][kind + "s"]))
        remote_items = (remote.store.list_nodes(include_trashed=True) if kind == "node"
                        else remote.store.list_relations(include_trashed=True))
        imported = next(item for item in remote_items if item.metadata.get("sync_origin") == origin)
        remote_entry = remote.store.get_object_lifecycle(kind, imported.id)
        assert remote_entry["state"] == "trashed"
        nodes_before = {item.id for item in remote.store.list_nodes(include_trashed=True)}
        relations_before = {item.id for item in remote.store.list_relations(include_trashed=True)}
        if kind == "node":
            assert remote_entry["references"]["relations"] == list(relations_before)
        TrashService(local.store).restore(trash_id=entry["trash_id"], generation=1,
            expected_revision=1, operation_id="restore-new-" + kind)

        restored = replica.sync_once(wire.http, pid, "token")

        assert restored["state"] == "synced" and restored["conflicts"] == []
        assert remote.store.get_object_lifecycle(kind, imported.id)["state"] == "restored"
        assert {item.id for item in remote.store.list_nodes()} == nodes_before
        assert {item.id for item in remote.store.list_relations()} == relations_before
    finally:
        replica.close()
        wire.http.close()


def test_lifecycle_failure_rolls_back_new_payloads_and_metadata_together(stores, monkeypatch):
    local, remote = (ThreadService(store) for store in stores)
    tid, pid = local.create("Project").id, remote.create("Project").id
    project, _, _ = graph(local, tid)
    move(local.store, "node", project)
    base = export_document(remote, pid)
    document = export_document(local, tid)
    snapshots = remote.store.list_snapshots(pid)

    def fail(_):
        raise OSError("lifecycle persistence interrupted")

    monkeypatch.setattr(remote.store, "save_trash_entry", fail)
    with pytest.raises(OSError, match="lifecycle persistence interrupted"):
        synchronize(remote, pid, "interrupted-new-tombstone", base, document)

    assert export_document(remote, pid) == base
    assert remote.store.list_nodes(include_trashed=True) == []
    assert remote.store.list_relations(include_trashed=True) == []
    assert remote.store.list_trash_entries() == []
    assert remote.store.list_snapshots(pid) == snapshots


def test_graph_lists_see_transaction_creates_and_rollback_hides_them(stores):
    store, _ = stores
    with pytest.raises(OSError, match="rollback graph"), store.transaction():
        store.save_node(KnowledgeNode("new_project", "project", "New project"))
        store.save_node(KnowledgeNode("new_task", "task", "New task"))
        store.save_relation(Relation("new_relation", "new_project", "new_task", "contains"))
        assert {node.id for node in store.list_nodes()} == {"new_project", "new_task"}
        assert [relation.id for relation in store.list_relations()] == ["new_relation"]
        raise OSError("rollback graph")
    assert store.list_nodes(include_trashed=True) == []
    assert store.list_relations(include_trashed=True) == []


def test_changed_incident_relation_of_trashed_node_is_rejected_atomically(stores):
    store, _ = stores
    core = ThreadService(store)
    thread = core.create("Project")
    project, _, _ = graph(core, thread.id)
    move(store, "node", project)
    base = export_document(core, thread.id)
    incoming = deepcopy(base)
    next(iter(incoming["relations"].values()))["kind"] = "blocks"
    incoming["thread"]["notes"] = "Must roll back with relation change"

    with pytest.raises(ManagementError) as error:
        synchronize(core, thread.id, "hidden-incident-edit", base, incoming)

    assert error.value.code == "object_in_trash"
    assert export_document(core, thread.id) == base


def test_graph_lists_exclude_transaction_deletes_and_rollback_restores_them(stores):
    store, _ = stores
    core = ThreadService(store)
    thread = core.create("Project")
    project, task, relation = graph(core, thread.id)
    move(store, "relation", relation)
    move(store, "node", task)
    with pytest.raises(OSError, match="rollback deletion"), store.transaction():
        store.purge_trash_object("relation", relation.id)
        store.purge_trash_object("node", task.id)
        assert [node.id for node in store.list_nodes(include_trashed=True)] == [project.id]
        assert store.list_relations(include_trashed=True) == []
        raise OSError("rollback deletion")
    assert {node.id for node in store.list_nodes(include_trashed=True)} == {project.id, task.id}
    assert [item.id for item in store.list_relations(include_trashed=True)] == [relation.id]
