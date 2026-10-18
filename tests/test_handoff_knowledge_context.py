"""Only new issued packets receive bounded local knowledge; old receipts stay fixed."""

import json

import pytest
from test_issued_handoffs import binding, returned
from test_knowledge_memory import record

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.services.issued_handoffs import digest
from threaddesk.services.knowledge_memory import (
    HANDOFF_MAX_BYTES,
    HANDOFF_MAX_ITEMS,
    handoff_context,
)
from threaddesk.services.mcp import McpBridge
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def svc(request, tmp_path):
    value = ThreadService(request.param(tmp_path))
    value.gate_set(cooldown_seconds=0)
    yield value
    if isinstance(value.store, SQLiteStore):
        value.store.connection.close()


def issue(svc, thread, operation):
    return svc.issue_handoff(
        {
            "operation_id": operation,
            "id": thread.id,
            "expected_revision": svc.get(thread.id).revision,
            "target": "codex",
        }
    )


def test_new_context_carries_current_and_historical_knowledge_without_foreign_thread(
    svc,
):
    thread = svc.create("Synthetic new issued context")
    other = svc.create("Other")
    record(
        svc,
        other.id,
        "foreign",
        kind="decision",
        status="confirmed",
        title="Must stay local",
    )
    original = record(
        svc, thread.id, "old", kind="decision", status="confirmed", title="Earlier"
    )
    record(
        svc,
        thread.id,
        "replace",
        "supersede",
        node_id=original["node_id"],
        expected_node_revision=1,
        title="Current",
    )
    record(svc, thread.id, "question", kind="question", title="Still open?")
    record(
        svc,
        thread.id,
        "reject",
        kind="decision",
        status="rejected",
        title="Rejected idea",
    )
    before = svc.get(thread.id).revision
    handoff = issue(svc, thread, "issue-new")
    knowledge = handoff["context"]["knowledge"]
    assert knowledge["provenance"] == "source_local" and knowledge["total"] == 4
    assert knowledge["items"][0]["title"] == "Current"
    assert {item["status"] for item in knowledge["items"]} == {
        "confirmed",
        "superseded",
        "waiting",
        "rejected",
    }
    assert "Must stay local" not in json.dumps(knowledge)
    assert all(
        item["source_verification"] == "referenced_unverified"
        for item in knowledge["items"]
    )
    assert all(
        item["id"] and item["revision"] and item["source_revision"]
        for item in knowledge["items"]
    )
    assert handoff["source"]["knowledge_hash"]
    assert handoff["source"]["knowledge_provenance"] == "source_local"
    assert handoff["sent"] is handoff["ran"] is False
    assert svc.get(thread.id).revision == before
    existing = svc.get_issued_handoff(operation_id="issue-new")["issued"]
    assert existing["content_hash"] == digest(existing["handoff"])


def test_projection_has_explicit_item_byte_text_limits_and_reference_only_sources(svc):
    thread = svc.create("Bounded")
    # Generic existing graph writes intentionally exercise older local writers too.
    for number in range(HANDOFF_MAX_ITEMS + 8):
        svc.create_node(
            "decision",
            f"Decision {number}",
            status="confirmed",
            details="x" * 4000,
            source="/synthetic/reference-only/no-io",
            metadata={"thread_id": thread.id, "source_revision": "claimed"},
        )

    knowledge = handoff_context(svc, thread.id)
    assert knowledge["truncated"] and knowledge["included"] < knowledge["total"] == 40
    assert len(knowledge["items"]) <= HANDOFF_MAX_ITEMS
    assert (
        len(json.dumps(knowledge, ensure_ascii=False, sort_keys=True).encode())
        <= HANDOFF_MAX_BYTES
    )
    assert all(
        len(item["details"]) == 2000 and item["content_truncated"]
        for item in knowledge["items"]
    )
    assert knowledge["limits"] == {"items": 32, "bytes": 32768, "text_characters": 2000}


def test_legacy_graph_change_without_thread_revision_is_stale(svc):
    thread = svc.create("Legacy local graph writer")
    node = svc.create_node(
        "decision", "Initial", status="proposed", metadata={"thread_id": thread.id}
    )
    handoff = issue(svc, thread, "issue-before-graph-change")
    svc.bind_handoff_run(binding(handoff))
    before = svc.get(thread.id).revision
    svc.transition_node(node.id, "confirmed", expected_revision=1)
    assert svc.get(thread.id).revision == before
    with pytest.raises(ManagementError) as failure:
        svc.receive_return(returned(handoff), strict_binding=True)
    assert failure.value.code == "return_stale" and svc.returns() == []


def test_prior_issued_payload_and_content_hash_remain_exact_after_later_knowledge(svc):
    thread = svc.create("Historical issued receipt")
    first = issue(svc, thread, "historical")
    old = svc.store.get_issued_handoff(first["handoff_id"])
    # Simulate a genuinely older issued packet lacking the additive context.
    old["handoff"]["context"].pop("knowledge")
    old["handoff"]["source"].pop("knowledge_hash")
    old["handoff"]["source"].pop("knowledge_provenance")
    old["source"].pop("knowledge_hash")
    old["source"].pop("knowledge_provenance")
    old["content_hash"] = digest(old["handoff"])
    svc.store.save_issued_handoff(first["handoff_id"], old)
    before = json.dumps(old, sort_keys=True)
    record(
        svc,
        thread.id,
        "later-knowledge",
        kind="decision",
        title="After historical export",
    )
    replay = svc.issue_handoff(
        {
            "operation_id": "historical",
            "id": thread.id,
            "expected_revision": first["source"]["thread_revision"],
            "target": "codex",
        }
    )
    assert replay["duplicate"] and "knowledge" not in replay["context"]
    assert replay["content_hash"] == old["content_hash"]
    assert (
        json.dumps(svc.store.get_issued_handoff(first["handoff_id"]), sort_keys=True)
        == before
    )
    newer = issue(svc, thread, "new-current-context")
    assert newer["context"]["knowledge"]["included"] == 1


def test_recovery_reads_same_packet_context_after_restart(svc):
    thread = svc.create("Persisted projection")
    record(svc, thread.id, "remember", kind="question", title="Which next step?")
    issued = issue(svc, thread, "once")
    reopened = ThreadService(type(svc.store)(svc.store.root))
    found = McpBridge(reopened).call("get_issued_handoff", {"operation_id": "once"})[
        "result"
    ]["issued"]
    assert found["handoff"]["context"]["knowledge"] == issued["context"]["knowledge"]
    assert found["content_hash"] == issued["content_hash"]
    if isinstance(reopened.store, SQLiteStore):
        reopened.store.connection.close()


@pytest.mark.parametrize("phase", ["before_binding", "before_question"])
def test_graph_change_blocks_new_binding_or_question(svc, phase):
    thread = svc.create("Graph source guard")
    node = svc.create_node(
        "decision", "Before", status="proposed", metadata={"thread_id": thread.id}
    )
    handoff = issue(svc, thread, "guarded")
    if phase == "before_question":
        svc.bind_handoff_run(binding(handoff))
    svc.transition_node(node.id, "confirmed", expected_revision=1)
    if phase == "before_binding":
        with pytest.raises(ManagementError) as failure:
            svc.bind_handoff_run(binding(handoff))
        assert failure.value.code == "revision_conflict"
    else:
        response = McpBridge(svc).call(
            "record_handoff_question",
            {
                "handoff_id": handoff["handoff_id"],
                "handoff_revision": handoff["revision"],
                "run_id": "accepted-run-1",
                "question_id": "question-1",
                "text": "Should not record?",
            },
        )
        assert response["code"] == "return_stale"


def test_resolved_question_carries_its_separate_referenced_answer(svc):
    thread = svc.create("Answer context")
    question = record(
        svc, thread.id, "ask", kind="question", title="Original question?"
    )
    record(
        svc,
        thread.id,
        "answer",
        "resolve_question",
        node_id=question["node_id"],
        expected_node_revision=1,
        text="Explicit answer",
    )
    item = issue(svc, thread, "answered-context")["context"]["knowledge"]["items"][0]
    assert item["title"] == "Original question?" and item["status"] == "done"
    assert item["resolution"]["text"] == "Explicit answer"
    assert item["resolution"]["source_verification"] == "referenced_unverified"
