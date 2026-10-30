"""Explicit adoption of new graph objects whose first sync carries restored history."""
from copy import deepcopy

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.core.models import Relation
from threaddesk.server_sync import metadata
from threaddesk.server_sync.lifecycle import conflict_value
from threaddesk.server_sync.metadata import (
    SyncError,
    export_document,
    list_conflicts,
    resolve_conflict,
    synchronize,
)
from threaddesk.services.trash import TrashService
from threaddesk.services.trash_receipts import MARKER, receipt_plan
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def pair(request, tmp_path):
    local, remote = (ThreadService(request.param(tmp_path / name)) for name in ("local", "remote"))
    tid, pid = local.create("Project").id, remote.create("Project").id
    yield local, tid, remote, pid
    for core in (local, remote):
        if hasattr(core.store, "connection"):
            core.store.connection.close()


def pending(pair, kind, *, generations=1):
    local, tid, remote, pid = pair
    preserved = remote.create_node("project", "Receiver context", details="Receiver detail preserved", metadata={"thread_id": pid})
    base = export_document(remote, pid)
    project = local.create_node("project", "New source project", metadata={"thread_id": tid})
    task = local.create_node("task", "New source task", details="restoredhistoryneedle", metadata={"thread_id": tid, "project_id": project.id})
    relation = Relation("new_source_relation", project.id, task.id, "contains")
    local.store.save_relation(relation)
    local.create_node("task", "Unrelated incoming object", metadata={"thread_id": tid})
    obj = task if kind == "node" else relation
    service = TrashService(local.store)
    for generation in range(1, generations + 1):
        entry = service.move(kind=kind, object_id=obj.id, expected_revision=obj.revision,
                             operation_id="source-trash-" + str(generation))["entry"]
        service.restore(trash_id=entry["trash_id"], generation=generation, expected_revision=1,
                        operation_id="source-restore-" + str(generation))
    incoming = export_document(local, tid)
    result = synchronize(remote, pid, "new-restored-history", base, incoming)
    conflict = next(c for c in result["conflicts"] if c["path"].startswith("lifecycle/" + kind + "s/"))
    assert conflict["reason"] == "restore_without_matching_generation"
    assert export_document(remote, pid) == base  # No implicit history or payload adoption.
    return remote, pid, preserved, base, incoming, conflict


@pytest.mark.parametrize("kind", ["node", "relation"])
def test_explicit_adoption_imports_only_required_payload_and_is_replayable(pair, kind):
    remote, pid, preserved, base, incoming, conflict = pending(pair, kind)
    before_preserved = remote.store.get_node(preserved.id).to_dict()
    observed = conflict_value(base, conflict["path"])
    thread = remote.get(pid)
    thread.context.notes = "Receiver changed while conflict was open"
    remote.store.save_thread(thread)
    with pytest.raises(SyncError) as stale:
        resolve_conflict(remote, pid, conflict["id"], observed, conflict["incoming"], "stale-adoption")
    assert stale.value.code == "metadata_conflict"
    fresh = conflict_value(export_document(remote, pid), conflict["path"])

    resolved = resolve_conflict(remote, pid, conflict["id"], fresh, conflict["incoming"], "adopt-new-history")

    assert resolved["state"] == "synced" and not list_conflicts(remote, pid)
    assert remote.get(pid).context.notes == "Receiver changed while conflict was open"
    assert remote.store.get_node(preserved.id).to_dict() == before_preserved
    nodes = remote.store.list_nodes()
    assert {node.title for node in nodes} == {"Receiver context", "New source project", "New source task"}
    assert len(remote.store.list_relations()) == (1 if kind == "relation" else 0)
    origin = conflict["path"].split("/", 2)[2]
    identity = metadata._local_id(pid, origin, kind)
    entry = remote.store.get_object_lifecycle(kind, identity)
    assert {k: entry[k] for k in ("generation", "revision", "state")} == {"generation": 1, "revision": 2, "state": "restored"}
    assert resolve_conflict(remote, pid, conflict["id"], fresh, conflict["incoming"], "adopt-new-history") == resolved
    assert remote.store.get_object_lifecycle(kind, identity) == entry
    with pytest.raises(SyncError) as reused:
        resolve_conflict(remote, pid, conflict["id"], fresh, conflict["current"], "adopt-new-history")
    assert reused.value.code == "metadata_operation_conflict"
    after = synchronize(remote, pid, "unchanged-history-after-adoption", incoming, incoming)
    assert not any(c["path"] == conflict["path"] for c in after["conflicts"])
    # The new journal payload must use the existing ID-attributed reducer,
    # rather than leaving an unbound copy of a future local object's content.
    plan = receipt_plan(remote.store, kind, identity)
    owner_key = conflict["id"].rsplit(":", 1)[0]
    change = next(item for item in plan.changes if item["storage_operation_id"] == owner_key)
    payload = change["result"]["restored_history_payloads"][kind + "s"][origin]
    assert payload["schema"] == MARKER and payload["id"] == identity


@pytest.mark.parametrize("kind", ["node", "relation"])
def test_keep_current_does_not_import_missing_graph_payload(pair, kind):
    remote, pid, _, base, _, conflict = pending(pair, kind)
    actual = conflict_value(base, conflict["path"])
    resolved = resolve_conflict(remote, pid, conflict["id"], actual, conflict["current"], "keep-receiver")
    assert resolved["document"] == base
    assert export_document(remote, pid) == base
    assert len(remote.store.list_nodes()) == 1 and not remote.store.list_relations()


@pytest.mark.parametrize("kind", ["node", "relation"])
def test_generation_gap_cannot_create_missing_restored_history(pair, kind):
    remote, pid, _, base, _, conflict = pending(pair, kind, generations=2)
    actual = conflict_value(base, conflict["path"])
    with pytest.raises(SyncError) as error:
        resolve_conflict(remote, pid, conflict["id"], actual, conflict["incoming"], "invalid-generation-adoption")
    assert error.value.code == "metadata_lifecycle_conflict"
    assert export_document(remote, pid) == base
    assert len(remote.store.list_nodes()) == 1 and not remote.store.list_relations()


@pytest.mark.parametrize("kind", ["node", "relation"])
def test_restored_history_adoption_and_new_payloads_roll_back_together(pair, kind, monkeypatch):
    remote, pid, _, base, _, conflict = pending(pair, kind)
    actual = conflict_value(base, conflict["path"])
    original = remote.store.save_trash_entry
    attempts = []

    def fail_restore(entry):
        attempts.append(entry["state"])
        if entry["state"] == "restored":
            raise OSError("restore persistence interrupted")
        original(entry)

    monkeypatch.setattr(remote.store, "save_trash_entry", fail_restore)
    with pytest.raises(OSError, match="restore persistence interrupted"):
        resolve_conflict(remote, pid, conflict["id"], actual, conflict["incoming"], "atomic-adoption")
    assert attempts == ["trashed", "restored"]
    assert export_document(remote, pid) == base and not remote.store.list_trash_entries()
    assert len(remote.store.list_nodes()) == 1 and not remote.store.list_relations()
    assert any(c["id"] == conflict["id"] for c in list_conflicts(remote, pid))
    monkeypatch.setattr(remote.store, "save_trash_entry", original)
    assert resolve_conflict(remote, pid, conflict["id"], actual, conflict["incoming"], "atomic-adoption")["state"] == "synced"


def test_relation_adoption_preserves_concurrent_existing_endpoint(pair):
    local, tid, remote, pid = pair
    source_project = local.create_node("project", "Existing source project", metadata={"thread_id": tid})
    initial = export_document(local, tid)
    synchronize(remote, pid, "initial-project", export_document(remote, pid), initial)
    receiver_project = remote.store.list_nodes()[0]
    receiver_project.title = "Receiver's later title"
    receiver_project.details = "Receiver endpoint edit must survive"
    remote.store.save_node(receiver_project)
    preserved = remote.store.get_node(receiver_project.id).to_dict()
    task = local.create_node("task", "New task", metadata={"thread_id": tid, "project_id": source_project.id})
    relation = Relation("new_relation", source_project.id, task.id, "contains")
    local.store.save_relation(relation)
    trash = TrashService(local.store)
    entry = trash.move(kind="relation", object_id=relation.id, expected_revision=relation.revision,
                       operation_id="trash-new-relation")["entry"]
    trash.restore(trash_id=entry["trash_id"], generation=1, expected_revision=1, operation_id="restore-new-relation")
    before = export_document(remote, pid)
    result = synchronize(remote, pid, "relation-history", initial, export_document(local, tid))
    conflict = next(c for c in result["conflicts"] if c["path"].startswith("lifecycle/relations/"))
    assert export_document(remote, pid) == before
    actual = conflict_value(before, conflict["path"])

    resolve_conflict(remote, pid, conflict["id"], actual, conflict["incoming"], "adopt-only-new-relation")

    assert remote.store.get_node(receiver_project.id).to_dict() == preserved
    assert len(remote.store.list_nodes()) == 2 and len(remote.store.list_relations()) == 1


def test_adoption_payload_budget_rejects_without_receipt_or_partial_import(pair, monkeypatch):
    local, tid, remote, pid = pair
    task = local.create_node("task", "Payload budget", metadata={"thread_id": tid})
    trash = TrashService(local.store)
    entry = trash.move(kind="node", object_id=task.id, expected_revision=task.revision,
                       operation_id="budget-trash")["entry"]
    trash.restore(trash_id=entry["trash_id"], generation=1, expected_revision=1, operation_id="budget-restore")
    base = export_document(remote, pid)
    receipts = remote.store.list_management_operations()
    monkeypatch.setattr(metadata, "MAX_HISTORY_PAYLOAD_BYTES", 1)

    with pytest.raises(SyncError) as error:
        synchronize(remote, pid, "over-budget-history", base, export_document(local, tid))

    assert error.value.code == "metadata_too_large" and error.value.status == 413
    assert export_document(remote, pid) == base
    assert remote.store.list_management_operations() == receipts
    assert remote.store.list_nodes(include_trashed=True) == []


def test_combined_resolved_document_budget_keeps_conflict_and_current_objects(pair, monkeypatch):
    local, tid, remote, pid = pair
    remote.create_node("task", "Existing receiver payload", details="r" * 700, metadata={"thread_id": pid})
    task = local.create_node("task", "Incoming payload", details="i" * 700, metadata={"thread_id": tid})
    service = TrashService(local.store)
    entry = service.move(kind="node", object_id=task.id, expected_revision=task.revision,
                         operation_id="combined-budget-trash")["entry"]
    service.restore(trash_id=entry["trash_id"], generation=1, expected_revision=1, operation_id="combined-budget-restore")
    before, incoming = export_document(remote, pid), export_document(local, tid)
    limit = max(len(metadata._canonical(doc).encode()) for doc in (before, incoming)) + 50
    monkeypatch.setattr(metadata, "MAX_DOCUMENT_BYTES", limit)
    result = synchronize(remote, pid, "combined-budget-history", before, incoming)
    conflict = result["conflicts"][0]
    with pytest.raises(SyncError) as error:
        resolve_conflict(remote, pid, conflict["id"], conflict_value(before, conflict["path"]),
                         conflict["incoming"], "combined-budget-adoption")
    assert error.value.code == "metadata_too_large" and error.value.status == 413
    assert export_document(remote, pid) == before
    assert len(remote.store.list_nodes()) == 1 and not remote.store.list_trash_entries()
    assert any(c["id"] == conflict["id"] for c in list_conflicts(remote, pid))


@pytest.mark.parametrize("kind", ["node", "relation"])
def test_reduced_history_payload_is_not_guessed_or_resurrected(pair, kind, monkeypatch):
    remote, pid, _, base, _, conflict = pending(pair, kind)
    owner_key = conflict["id"].rsplit(":", 1)[0]
    original = remote.store.get_management_operation
    reduced = deepcopy(original(owner_key))
    origin = conflict["path"].split("/", 2)[2]
    identity = metadata._local_id(pid, origin, kind)
    reduced["result"]["restored_history_payloads"][kind + "s"][origin] = {
        "schema": MARKER, "kind": kind, "id": identity, "object_id": identity, "content_purged": True}
    monkeypatch.setattr(remote.store, "get_management_operation", lambda key: reduced if key == owner_key else original(key))
    actual = conflict_value(base, conflict["path"])

    with pytest.raises(SyncError) as error:
        resolve_conflict(remote, pid, conflict["id"], actual, conflict["incoming"], "reject-reduced-history")

    assert error.value.code == "metadata_lifecycle_conflict"
    assert export_document(remote, pid) == base
    assert not remote.store.list_trash_entries() and not remote.store.list_relations()


@pytest.mark.parametrize("dependency_state", ["trashed", "restored"])
def test_dependency_lifecycle_is_preserved_and_never_implicitly_adopts_another_history(pair, dependency_state):
    local, tid, remote, pid = pair
    project = local.create_node("project", "Dependency project", metadata={"thread_id": tid})
    task = local.create_node("task", "Dependency task", metadata={"thread_id": tid, "project_id": project.id})
    relation = Relation("dependent_relation", project.id, task.id, "contains")
    local.store.save_relation(relation)
    service = TrashService(local.store)
    moved_relation = service.move(kind="relation", object_id=relation.id, expected_revision=relation.revision,
                                  operation_id="relation-trash")["entry"]
    service.restore(trash_id=moved_relation["trash_id"], generation=1, expected_revision=1, operation_id="relation-restore")
    moved_project = service.move(kind="node", object_id=project.id, expected_revision=project.revision,
                                 operation_id="project-trash")["entry"]
    if dependency_state == "restored":
        service.restore(trash_id=moved_project["trash_id"], generation=1, expected_revision=1, operation_id="project-restore")
    before = export_document(remote, pid)
    result = synchronize(remote, pid, "dependent-history", before, export_document(local, tid))
    conflict = next(c for c in result["conflicts"] if c["path"].startswith("lifecycle/relations/"))
    if dependency_state == "restored":
        with pytest.raises(SyncError) as error:
            resolve_conflict(remote, pid, conflict["id"], conflict_value(before, conflict["path"]),
                             conflict["incoming"], "do-not-adopt-other-history")
        assert error.value.code == "metadata_lifecycle_conflict"
        assert export_document(remote, pid) == before
        project_conflict = next(c for c in result["conflicts"] if c["path"].startswith("lifecycle/nodes/"))
        resolve_conflict(remote, pid, project_conflict["id"], conflict_value(before, project_conflict["path"]),
                         project_conflict["incoming"], "explicit-project-history")

    current = export_document(remote, pid)
    resolve_conflict(remote, pid, conflict["id"], conflict_value(current, conflict["path"]),
                     conflict["incoming"], "explicit-relation-history")

    imported_project = next(node for node in remote.store.list_nodes(include_trashed=True) if node.title == "Dependency project")
    assert remote.store.get_object_lifecycle("node", imported_project.id)["state"] == dependency_state
    imported_relation = remote.store.list_relations(include_trashed=True)[0]
    assert remote.store.get_object_lifecycle("relation", imported_relation.id)["state"] == "restored"
    assert bool(remote.store.list_relations()) is (dependency_state == "restored")


def test_concurrent_endpoint_trash_is_not_restored_by_relation_history_choice(pair):
    local, tid, remote, pid = pair
    project = local.create_node("project", "Existing endpoint", metadata={"thread_id": tid})
    initial = export_document(local, tid)
    synchronize(remote, pid, "initial-endpoint", export_document(remote, pid), initial)
    endpoint = remote.store.list_nodes()[0]
    task = local.create_node("task", "New endpoint", metadata={"thread_id": tid})
    relation = Relation("raced_relation", project.id, task.id, "contains")
    local.store.save_relation(relation)
    trash = TrashService(local.store)
    moved = trash.move(kind="relation", object_id=relation.id, expected_revision=relation.revision, operation_id="race-source-trash")["entry"]
    trash.restore(trash_id=moved["trash_id"], generation=1, expected_revision=1, operation_id="race-source-restore")
    result = synchronize(remote, pid, "race-history", initial, export_document(local, tid))
    conflict = next(c for c in result["conflicts"] if c["path"].startswith("lifecycle/relations/"))
    TrashService(remote.store).move(kind="node", object_id=endpoint.id, expected_revision=endpoint.revision,
                                    operation_id="concurrent-endpoint-trash")
    before = export_document(remote, pid)
    with pytest.raises(ManagementError) as error:
        resolve_conflict(remote, pid, conflict["id"], conflict_value(before, conflict["path"]),
                         conflict["incoming"], "never-resurrect-endpoint")
    assert error.value.code == "object_in_trash"
    assert export_document(remote, pid) == before
    assert len(remote.store.list_nodes(include_trashed=True)) == 1
    assert remote.store.list_relations(include_trashed=True) == []


def source_graph(local, thread_id):
    project = local.create_node("project", "Shared source project", metadata={"thread_id": thread_id})
    task = local.create_node("task", "Shared source task", metadata={"thread_id": thread_id, "project_id": project.id})
    relation = Relation("shared_source_relation", project.id, task.id, "contains")
    local.store.save_relation(relation)
    return project, task, relation, export_document(local, thread_id)


def graph_snapshot(core, thread_id, document):
    """Select known native IDs directly, independently of origin lookup code."""
    nodes = [metadata._local_id(thread_id, origin, "node") for origin in document["nodes"]]
    relations = [metadata._local_id(thread_id, origin, "relation") for origin in document["relations"]]
    all_relations = {relation.id: relation for relation in core.store.list_relations(include_trashed=True)}
    return {"thread": core.store.get_thread(thread_id, include_trashed=True).to_dict(),
            "nodes": {identity: core.store.get_node(identity, include_trashed=True).to_dict() for identity in nodes},
            "relations": {identity: all_relations[identity].to_dict() for identity in relations},
            "lifecycles": {kind + "/" + identity: core.store.get_object_lifecycle(kind, identity)
                           for kind, identities in (("node", nodes), ("relation", relations)) for identity in identities},
            "snapshots": [snapshot.to_dict() for snapshot in core.store.list_snapshots(thread_id, include_trashed=True)],
            "document": export_document(core, thread_id)}


def restored_source(local, kind, obj, prefix):
    service = TrashService(local.store)
    entry = service.move(kind=kind, object_id=obj.id, expected_revision=obj.revision,
                         operation_id=prefix + "-move")["entry"]
    service.restore(trash_id=entry["trash_id"], generation=1, expected_revision=1, operation_id=prefix + "-restore")


@pytest.mark.parametrize("order", [("a", "b"), ("b", "a")], ids=["a-first", "b-first"])
@pytest.mark.parametrize("kind", ["node", "relation"])
def test_restored_history_adoption_is_bound_to_native_thread_graph(pair, order, kind):
    local, tid, remote, aid = pair
    threads = {"a": aid, "b": remote.create("Project").id}
    _, task, relation, plain = source_graph(local, tid)
    restored_source(local, kind, task if kind == "node" else relation, "scoped-source")
    incoming = export_document(local, tid)
    conflict = None
    for label in order:
        identity = threads[label]
        result = synchronize(remote, identity, "first-scope-" + label, export_document(remote, identity),
                             incoming if label == "a" else plain)
        if label == "a":
            conflict = next(c for c in result["conflicts"] if c["path"].startswith("lifecycle/" + kind + "s/"))
        else:
            assert result["state"] == "synced"
    before_b = graph_snapshot(remote, threads["b"], plain)
    before_a = export_document(remote, threads["a"])

    resolve_conflict(remote, threads["a"], conflict["id"], conflict_value(before_a, conflict["path"]),
                     conflict["incoming"], "adopt-only-a")

    origin = conflict["path"].split("/", 2)[2]
    aid_object = metadata._local_id(threads["a"], origin, kind)
    bid_object = metadata._local_id(threads["b"], origin, kind)
    assert aid_object != bid_object
    assert remote.store.get_object_lifecycle(kind, aid_object)["state"] == "restored"
    assert remote.store.get_object_lifecycle(kind, bid_object) is None
    assert export_document(remote, threads["a"])["lifecycle"][kind + "s"][origin]["state"] == "restored"
    assert graph_snapshot(remote, threads["b"], plain) == before_b


@pytest.mark.parametrize("order", [("a", "b"), ("b", "a")], ids=["a-first", "b-first"])
@pytest.mark.parametrize("kind", ["node", "relation"])
@pytest.mark.parametrize("effect", ["edit", "trash"])
def test_regular_edit_and_tombstone_never_select_another_replica_with_same_origin(pair, order, kind, effect):
    local, tid, remote, aid = pair
    threads = {"a": aid, "b": remote.create("Project").id}
    _, _, _, plain = source_graph(local, tid)
    for label in order:
        synchronize(remote, threads[label], "plain-import-" + label, export_document(remote, threads[label]), plain)
    before_b = graph_snapshot(remote, threads["b"], plain)
    before_a = export_document(remote, threads["a"])
    incoming = deepcopy(before_a)
    section = kind + "s"
    origin = (next(key for key, value in plain["nodes"].items() if value["title"] == "Shared source task")
              if kind == "node" else next(iter(plain["relations"])))
    if effect == "edit":
        incoming[section][origin]["details" if kind == "node" else "kind"] = "Only A changed" if kind == "node" else "blocks"
    else:
        incoming.update(format="threaddesk.metadata.v2", lifecycle={"thread": None, "nodes": {}, "relations": {}})
        incoming["lifecycle"][section][origin] = {"generation": 1, "revision": 1, "state": "trashed"}

    result = synchronize(remote, threads["a"], "change-only-a", before_a, incoming)

    assert result["state"] == "synced"
    native_a = metadata._local_id(threads["a"], origin, kind)
    if effect == "edit":
        after = export_document(remote, threads["a"])
        assert after[section][origin] == incoming[section][origin]
    else:
        entry = remote.store.get_object_lifecycle(kind, native_a)
        assert entry and entry["state"] == "trashed"
        assert graph_snapshot(remote, threads["b"], plain) == before_b
        trashed_document = export_document(remote, threads["a"])
        restored_document = deepcopy(trashed_document)
        restored_document["lifecycle"][section][origin] = {"generation": 1, "revision": 2, "state": "restored"}
        synchronize(remote, threads["a"], "restore-only-a", trashed_document, restored_document)
        assert remote.store.get_object_lifecycle(kind, native_a)["state"] == "restored"
    assert graph_snapshot(remote, threads["b"], plain) == before_b


@pytest.mark.parametrize("order", [("a", "b"), ("b", "a")], ids=["a-first", "b-first"])
def test_retained_relation_endpoint_ids_use_the_current_native_replica(pair, order):
    local, tid, remote, aid = pair
    threads = {"a": aid, "b": remote.create("Project").id}
    project = local.create_node("project", "Existing project", metadata={"thread_id": tid})
    initial = export_document(local, tid)
    project_origin = next(iter(initial["nodes"]))
    for label in order:
        synchronize(remote, threads[label], "endpoint-import-" + label, export_document(remote, threads[label]), initial)
    before_b = graph_snapshot(remote, threads["b"], initial)
    task = local.create_node("task", "New task", metadata={"thread_id": tid, "project_id": project.id})
    relation = Relation("new_endpoint_relation", project.id, task.id, "contains")
    local.store.save_relation(relation)
    restored_source(local, "relation", relation, "endpoint-source")
    before_a = export_document(remote, threads["a"])
    result = synchronize(remote, threads["a"], "endpoint-history-a", before_a, export_document(local, tid))
    conflict = next(c for c in result["conflicts"] if c["path"].startswith("lifecycle/relations/"))
    origin = conflict["path"].split("/", 2)[2]
    retained = result["restored_history_payloads"]["relations"][origin]
    assert retained["source_id"] == metadata._local_id(threads["a"], project_origin, "node")
    assert retained["source_id"] != metadata._local_id(threads["b"], project_origin, "node")
    assert project_origin not in result["restored_history_payloads"]["nodes"]
    resolve_conflict(remote, threads["a"], conflict["id"], conflict_value(before_a, conflict["path"]),
                     conflict["incoming"], "adopt-endpoint-history-a")
    native_relation = next(relation for relation in remote.store.list_relations()
                           if relation.id == metadata._local_id(threads["a"], origin, "relation"))
    assert native_relation.source_id == retained["source_id"]
    assert graph_snapshot(remote, threads["b"], initial) == before_b


@pytest.mark.parametrize("kind", ["node", "relation"])
def test_explicitly_shared_native_graph_ids_stay_shared(pair, kind):
    local, tid, remote, aid = pair
    _, _, _, plain = source_graph(local, tid)
    synchronize(remote, aid, "shared-native-import", export_document(remote, aid), plain)
    bid = remote.create("Shared Project").id
    project_origin = next(origin for origin, node in plain["nodes"].items() if node["kind"] == "project")
    project_id = metadata._local_id(aid, project_origin, "node")
    thread = remote.get(bid)
    thread.context.extra["organization"] = {"project_id": project_id}
    remote.store.save_thread(thread)
    before = export_document(remote, bid)
    origin = (next(origin for origin, node in plain["nodes"].items() if node["kind"] == "task")
              if kind == "node" else next(iter(plain["relations"])))
    incoming = deepcopy(before)
    incoming.update(format="threaddesk.metadata.v2", lifecycle={"thread": None, "nodes": {}, "relations": {}})
    incoming["lifecycle"][kind + "s"][origin] = {"generation": 1, "revision": 1, "state": "trashed"}

    synchronize(remote, bid, "shared-native-trash", before, incoming)

    object_id = metadata._local_id(aid, origin, kind)
    entry = remote.store.get_object_lifecycle(kind, object_id)
    assert entry["state"] == "trashed"
    for identity in (aid, bid):
        assert export_document(remote, identity)["lifecycle"][kind + "s"][origin]["state"] == "trashed"
    assert remote.store.get_object_lifecycle(kind, metadata._local_id(bid, origin, kind)) is None
    assert len(remote.store.list_nodes(include_trashed=True)) == 2
    assert len(remote.store.list_relations(include_trashed=True)) == 1


@pytest.mark.parametrize("kind", ["node", "relation"])
def test_ambiguous_origins_inside_one_native_scope_are_rejected(pair, kind):
    _, _, core, thread_id = pair
    project = core.create_node("project", "Project", metadata={"thread_id": thread_id})
    task = core.create_node("task", "First task", metadata={"thread_id": thread_id, "sync_origin": "source:duplicate"})
    if kind == "node":
        core.create_node("task", "Second task", metadata={"thread_id": thread_id, "sync_origin": "source:duplicate"})
    else:
        core.store.save_relation(Relation("r1", project.id, task.id, "contains", metadata={"sync_origin": "source:duplicate-relation"}))
        core.store.save_relation(Relation("r2", project.id, task.id, "contains", metadata={"sync_origin": "source:duplicate-relation"}))
    with pytest.raises(SyncError) as error:
        export_document(core, thread_id)
    assert error.value.code == "metadata_scope"
