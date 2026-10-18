"""M2 V02–06: first stale return, source binding, identities and persistence."""

import json

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.services.mcp import McpBridge
from threaddesk.services.return_contract import build
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore])
def svc(request, tmp_path, monkeypatch):
    monkeypatch.delenv("THREADDESK_SOURCE_ROOTS", raising=False)
    service = ThreadService(request.param(tmp_path))
    service.gate_set(cooldown_seconds=0)
    return service


def issue(svc, operation="issue-1"):
    thread = svc.current() or svc.create("Synthetic task", "No execution")
    return svc.issue_handoff(
        {
            "operation_id": operation,
            "id": thread.id,
            "expected_revision": thread.revision,
            "target": "codex",
        }
    )


def binding(handoff):
    return {
        "handoff_id": handoff["handoff_id"],
        "handoff_revision": handoff["revision"],
        "task_id": handoff["task_id"],
        "bridge_task_id": "kb-task-1",
        "run_id": "accepted-run-1",
        "worker": "codex",
        "expected_thread_revision": handoff["source"]["thread_revision"],
        "principal_ref": "configured-chatgpt",
        "operator_scope": "synthetic-workspace",
        "request_hash": "a" * 64,
    }


def returned(handoff, **changes):
    return {
        **build(
            handoff_id=handoff["handoff_id"],
            handoff_revision=handoff["revision"],
            thread_id=handoff["thread_id"],
            task_id=handoff["task_id"],
            worker="codex",
            run_id="accepted-run-1",
            result="Synthetic delivery only",
            return_id="return-1",
        ),
        **changes,
    }


def test_issue_is_durable_and_separate_from_thread_revision(svc):
    handoff = issue(svc)
    before = svc.get(handoff["thread_id"]).revision
    assert handoff["revision"] == 1 and handoff["source"]["thread_revision"] == before
    assert (
        svc.store.get_snapshot(handoff["source"]["snapshot_id"]).thread_id
        == handoff["thread_id"]
    )
    again = issue(svc)
    assert again["duplicate"] and again["handoff_id"] == handoff["handoff_id"]
    reopened = ThreadService(type(svc.store)(svc.store.root))
    assert (
        reopened.get_issued_handoff(operation_id="issue-1")["issued"]["handoff"]
        == svc.get_issued_handoff(handoff_id=handoff["handoff_id"])["issued"]["handoff"]
    )
    with pytest.raises(ManagementError, match="anderem Auftrag"):
        svc.issue_handoff(
            {
                "operation_id": "issue-1",
                "id": handoff["thread_id"],
                "expected_revision": before,
                "target": "generic",
            }
        )
    assert svc.get(handoff["thread_id"]).revision == before


def test_binding_and_delivery_remain_unverified(svc):
    handoff = issue(svc)
    proposed = binding(handoff)
    assert svc.bind_handoff_run(proposed)["duplicate"] is False
    assert svc.bind_handoff_run(proposed)["duplicate"] is True
    with pytest.raises(ManagementError):
        svc.bind_handoff_run({**proposed, "run_id": "other-run"})
    payload = returned(handoff)
    item = svc.receive_return(payload, strict_binding=True)
    assert item["binding_status"] == "issued_bound" and item["decision"] is None
    assert item["return"]["review_status"] == "unverified"
    svc.set_note("Subsequent user work", handoff["thread_id"])
    # Known identical delivery stays the original receipt after later user work.
    assert svc.receive_return(payload, strict_binding=True)["duplicate"]
    assert len(svc.returns()) == 1


def test_first_stale_return_rejected_without_any_newer_return(svc):
    handoff = issue(svc)
    svc.bind_handoff_run(binding(handoff))
    svc.set_note("Changed AFTER issuing", handoff["thread_id"])
    with pytest.raises(ManagementError) as failure:
        svc.receive_return(returned(handoff), strict_binding=True)
    assert failure.value.code == "return_stale" and svc.returns() == []


def test_foreign_owner_thread_task_handoff_and_run_never_bound(svc):
    handoff = issue(svc)
    with pytest.raises(ManagementError) as missing:
        svc.receive_return(returned(handoff), strict_binding=True)
    assert missing.value.code == "unbound_run"
    svc.bind_handoff_run(binding(handoff))
    for fields in (
        {"thread_id": "foreign-thread"},
        {"task_id": "foreign:task"},
        {"handoff_revision": 2},
        {"run_id": "other-run"},
        {"worker": "other"},
        {"handoff_id": "unknown-handoff"},
    ):
        with pytest.raises(ManagementError):
            svc.receive_return(returned(handoff, **fields), strict_binding=True)
    with pytest.raises(ManagementError):
        svc.bind_handoff_run({**binding(handoff), "principal_ref": "other-owner"})
    assert svc.returns() == []


def test_file_change_outside_thread_revision_is_stale(svc, tmp_path, monkeypatch):
    root = tmp_path / "permitted"
    root.mkdir()
    source = root / "dummy.md"
    source.write_text("synthetic original")
    monkeypatch.setenv("THREADDESK_SOURCE_ROOTS", json.dumps([str(root)]))
    thread = svc.create("Bound source")
    svc.add_file(str(source), thread.id)
    handoff = issue(svc)
    assert handoff["source"]["source_refs"][0]["verification"] == "verified"
    svc.bind_handoff_run(binding(handoff))
    source.write_text("synthetic changed")
    with pytest.raises(ManagementError) as failure:
        svc.receive_return(returned(handoff), strict_binding=True)
    assert failure.value.code == "return_stale_source"
    assert svc.returns() == []


def test_source_roots_missing_and_symlinks_are_not_verified(svc, tmp_path, monkeypatch):
    root = tmp_path / "approved"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("synthetic only")
    (root / "link.md").symlink_to(outside)
    thread = svc.create("Source limits")
    svc.add_file(str(outside), thread.id)
    missing = issue(svc)
    assert missing["source"]["source_refs"][0]["verification"] == "unsupported"
    monkeypatch.setenv("THREADDESK_SOURCE_ROOTS", json.dumps([str(root)]))
    svc.add_file(str(root / "link.md"), thread.id)
    bound = issue(svc, "issue-2")
    sources = bound["source"]["source_refs"]
    assert sources[0]["reason"] == "source_ambiguous_or_outside_scope"
    assert sources[1]["verification"] == "unverified"
    svc.bind_handoff_run(binding(bound))
    item = svc.receive_return(returned(bound), strict_binding=True)
    assert item["source_verification"] == "partial_unverified"


def test_mcp_explicit_issue_bind_strict_return(svc):
    bridge = McpBridge(svc)
    thread = svc.create("MCP dummy")
    handoff = bridge.call(
        "issue_handoff",
        {
            "operation_id": "mcp-issue",
            "id": thread.id,
            "expected_revision": thread.revision,
        },
    )["result"]
    assert bridge.call("get_issued_handoff", {"operation_id": "mcp-issue"})["result"][
        "found"
    ]
    assert bridge.call("bind_handoff_run", binding(handoff))["ok"]
    assert (
        bridge.call(
            "import_return", {"payload": returned(handoff), "strict_binding": True}
        )["result"]["decision"]
        is None
    )


def test_question_answer_requires_waiting_run_and_is_not_adapter_delivery(svc):
    bridge = McpBridge(svc)
    handoff = issue(svc)
    svc.bind_handoff_run(binding(handoff))
    common = {
        "handoff_id": handoff["handoff_id"],
        "handoff_revision": 1,
        "run_id": "accepted-run-1",
        "question_id": "q-1",
    }
    unknown = bridge.call(
        "answer_handoff_question",
        {**common, "answer_id": "answer-1", "text": "No waiting step"},
    )
    assert unknown["code"] == "question_not_waiting"
    question = bridge.call(
        "record_handoff_question", {**common, "text": "Which dummy option?"}
    )
    assert question["result"]["question"]["status"] == "awaiting_answer"
    assert bridge.call(
        "record_handoff_question", {**common, "text": "Which dummy option?"}
    )["result"]["duplicate"]
    assert (
        bridge.call(
            "record_handoff_question", {**common, "text": "Different question"}
        )["code"]
        == "question_conflict"
    )
    assert (
        bridge.call(
            "answer_handoff_question",
            {**common, "run_id": "foreign", "answer_id": "answer-1", "text": "A"},
        )["code"]
        == "binding_conflict"
    )
    answer = bridge.call(
        "answer_handoff_question", {**common, "answer_id": "answer-1", "text": "A"}
    )
    assert answer["result"]["delivery_status"] == "recorded_for_run"
    assert bridge.call(
        "answer_handoff_question", {**common, "answer_id": "answer-1", "text": "A"}
    )["result"]["duplicate"]
    assert (
        bridge.call(
            "answer_handoff_question", {**common, "answer_id": "answer-2", "text": "B"}
        )["code"]
        == "answer_conflict"
    )
    board = svc.whiteboard(handoff["thread_id"])
    assert len(board) == 2
    assert all(
        entry.run_id == "accepted-run-1"
        and entry.metadata["adapter_delivery_verified"] is False
        for entry in board
    )
    assert (
        svc.receive_return(returned(handoff), strict_binding=True)["decision"] is None
    )


def test_source_byte_count_and_regular_file_limits(tmp_path):
    from threaddesk.services.issued_handoffs import capture_sources

    root = tmp_path / "scope"
    root.mkdir()
    too_large = root / "oversized"
    too_large.write_bytes(b"x" * (1024 * 1024 + 1))
    captured = capture_sources([str(too_large)] * 40, (root,))
    assert len(captured) == 33
    assert captured[-1]["omitted_count"] == 8
    assert not any(item["verification"] == "verified" for item in captured)
    fifo = root / "fifo"
    import os

    os.mkfifo(fifo)
    assert capture_sources([str(fifo)], (root,))[0]["verification"] == "unverified"
    from unittest.mock import patch

    with patch(
        "threaddesk.services.issued_handoffs.os.open",
        side_effect=AssertionError("must not open"),
    ):
        unknown = capture_sources(["any-reference"], ())
    assert unknown[0]["verification"] == "unsupported"
