"""A thread snapshot captures and restores its knowledge graph."""

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def svc(request, tmp_path):
    service = ThreadService(request.param(tmp_path))
    yield service
    if isinstance(service.store, SQLiteStore):
        service.store.connection.close()


def test_snapshot_restores_graph_and_trashes_newer_nodes(svc):
    thread = svc.create("Graph snapshot")
    plan = svc.create_node(
        "task",
        "First plan",
        status="ready",
        details="Before snapshot",
        metadata={"thread_id": thread.id},
    )
    decision = svc.create_node(
        "decision",
        "First decision",
        status="confirmed",
        metadata={"thread_id": thread.id},
    )
    original_relation = svc.connect(plan.id, decision.id, "supports")
    snapshot = svc.snapshot("Before edits", thread.id)
    assert {item["id"] for item in snapshot.knowledge_nodes} == {
        plan.id,
        decision.id,
    }
    assert snapshot.knowledge_relations[0]["id"] == original_relation.id

    changed = svc.get_node(plan.id)
    changed.title = "Changed plan"
    changed.details = "After snapshot"
    changed.revision += 1
    svc.store.save_node(changed)
    later = svc.create_node(
        "task",
        "Added later",
        status="ready",
        metadata={"thread_id": thread.id},
    )
    later_relation = svc.connect(later.id, plan.id, "related_to")

    svc.restore(snapshot.id)

    restored = svc.get_node(plan.id)
    trashed = svc.get_node(later.id)
    assert restored.title == "First plan"
    assert restored.details == "Before snapshot"
    assert restored.revision > changed.revision
    assert trashed.status == "archived"
    assert trashed.metadata["archived_from"] == "ready"
    relations = svc.relations_for(plan.id)
    assert [item.id for item in relations] == [original_relation.id]
    assert later_relation.id not in {item.id for item in relations}

    trashed.metadata.update({"thread_id": thread.id})
    svc.store.save_node(trashed)
    from threaddesk.services.mcp import McpBridge

    restored_from_trash = McpBridge(svc).call(
        "knowledge_manage",
        {
            "operation_id": "restore-post-snapshot-node",
            "id": thread.id,
            "expected_revision": svc.get(thread.id).revision,
            "action": "unarchive",
            "data": {
                "node_id": trashed.id,
                "expected_node_revision": trashed.revision,
                "source_ref": "test snapshot",
                "source_revision": "1",
            },
        },
    )
    assert restored_from_trash["ok"] is True
    assert later_relation.id in {item.id for item in svc.relations_for(plan.id)}
