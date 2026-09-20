"""G0: Authority Event Envelope — valid trace, no secrets."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from threaddesk.core.authority_event import (
    SCHEMA_PATH,
    AuthorityEventError,
    compute_event_hash,
    validate_event,
    validate_trace,
)

REPO = Path(__file__).resolve().parents[1]


def _stamp(event: dict) -> dict:
    ev = deepcopy(event)
    ev.pop("event_hash", None)
    ev["event_hash"] = compute_event_hash(ev)
    return ev


def _example_trace() -> list[dict]:
    """Planer → Builder → TollGate → Tool → Ergebnis."""
    base = {
        "schema_version": "1",
        "timestamp": "2026-09-21T12:00:00Z",
        "trace_id": "tr-example-001",
        "workflow_id": "wf-105",
        "project_id": "gnom-hub-v1",
        "data_labels": ["PUBLIC"],
    }
    events: list[dict] = []
    prev = None
    steps = [
        {
            "event_id": "ev-01",
            "span_id": "s1",
            "source_tool": "gnom-hub-v1",
            "event_type": "work.started",
            "actor": {"agent_id": "planer", "role": "planer"},
            "action": "plan",
            "resource": "issue:105",
        },
        {
            "event_id": "ev-02",
            "span_id": "s2",
            "parent_span_id": "s1",
            "source_tool": "gnom-hub-v1",
            "event_type": "agent.invoked",
            "actor": {"agent_id": "builder", "role": "builder"},
            "action": "implement",
            "resource": "issue:123",
        },
        {
            "event_id": "ev-03",
            "span_id": "s3",
            "parent_span_id": "s2",
            "source_tool": "tollgate",
            "event_type": "budget.checked",
            "decision": "ALLOW",
            "budget_ref": "budget:anon",
            "action": "llm.chat",
            "resource": "model:deepseek",
        },
        {
            "event_id": "ev-04",
            "span_id": "s4",
            "parent_span_id": "s3",
            "source_tool": "gnom-hub-v1",
            "event_type": "tool.intent",
            "actor": {"agent_id": "worker1", "role": "worker"},
            "action": "file.write",
            "resource": "repo:src/gnom_hub/llm/manager.py",
        },
        {
            "event_id": "ev-05",
            "span_id": "s5",
            "parent_span_id": "s4",
            "source_tool": "gnom-hub-v1",
            "event_type": "work.finished",
            "actor": {"agent_id": "builder", "role": "builder"},
            "result_ref": "pr:125",
            "decision": "ALLOW",
        },
    ]
    for step in steps:
        ev = {**base, **step, "previous_event_hash": prev}
        stamped = _stamp(ev)
        events.append(stamped)
        prev = stamped["event_hash"]
    return events


def test_schema_file_exists() -> None:
    assert SCHEMA_PATH.is_file()
    data = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert data["title"].startswith("Authority Event")


def test_example_trace_valid() -> None:
    trace = _example_trace()
    validate_trace(trace)
    assert [e["event_type"] for e in trace] == [
        "work.started",
        "agent.invoked",
        "budget.checked",
        "tool.intent",
        "work.finished",
    ]


def test_fixture_file_matches_validator() -> None:
    path = REPO / "docs" / "authority" / "fixtures" / "example-trace.json"
    if not path.is_file():
        pytest.skip("fixture written after first stamp")
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_trace(data["events"])


def test_secret_field_rejected() -> None:
    ev = _stamp(
        {
            "schema_version": "1",
            "event_id": "ev-bad",
            "timestamp": "2026-09-21T12:00:00Z",
            "trace_id": "tr-x",
            "span_id": "s1",
            "source_tool": "4allpass",
            "event_type": "capability.granted",
            "capability_id": "cap-1",
            "api_key": "sk-should-never-appear",
        }
    )
    with pytest.raises(AuthorityEventError, match="forbidden"):
        validate_event(ev)


def test_secret_like_value_rejected() -> None:
    ev = _stamp(
        {
            "schema_version": "1",
            "event_id": "ev-bad2",
            "timestamp": "2026-09-21T12:00:00Z",
            "trace_id": "tr-x",
            "span_id": "s1",
            "source_tool": "4allpass",
            "event_type": "capability.granted",
            "resource": "sk-abcdefghijklmnop",
        }
    )
    with pytest.raises(AuthorityEventError, match="secret-like"):
        validate_event(ev)


def test_unknown_producer_rejected() -> None:
    ev = _stamp(
        {
            "schema_version": "1",
            "event_id": "ev-bad3",
            "timestamp": "2026-09-21T12:00:00Z",
            "trace_id": "tr-x",
            "span_id": "s1",
            "source_tool": "chatgpt",
            "event_type": "work.started",
        }
    )
    with pytest.raises(AuthorityEventError, match="source_tool"):
        validate_event(ev)


def test_broken_hash_chain_rejected() -> None:
    trace = _example_trace()
    trace[2]["previous_event_hash"] = "deadbeef" * 8
    trace[2]["event_hash"] = compute_event_hash(trace[2])
    with pytest.raises(AuthorityEventError, match="hash chain"):
        validate_trace(trace)


def test_capability_grant_without_secret_ok() -> None:
    ev = _stamp(
        {
            "schema_version": "1",
            "event_id": "ev-grant",
            "timestamp": "2026-09-21T12:00:00Z",
            "trace_id": "tr-cap",
            "span_id": "s1",
            "source_tool": "4allpass",
            "event_type": "capability.granted",
            "capability_id": "cap-device-1",
            "action": "secret.read",
            "resource": "vault:item:42",
            "decision": "ALLOW",
        }
    )
    validate_event(ev)
