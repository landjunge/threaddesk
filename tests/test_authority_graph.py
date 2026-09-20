"""G1: ingest Authority Envelope → queryable graph + incident."""

from __future__ import annotations

import json
from pathlib import Path

from threaddesk.core.authority_event import AuthorityEventError
from threaddesk.graph import AuthorityGraph

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "docs" / "authority" / "fixtures" / "example-trace.json"


def test_ingest_example_trace_is_reproducible() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    g1 = AuthorityGraph()
    g2 = AuthorityGraph()
    assert g1.ingest_payload(payload) == 5
    assert g2.ingest_payload(payload) == 5
    assert g1.snapshot().to_dict() == g2.snapshot().to_dict()
    snap = g1.snapshot()
    counts = snap.to_dict()["counts"]
    assert counts["nodes"] >= 4
    assert counts["edges"] >= 3
    kinds = {n.kind for n in snap.nodes}
    assert "agent" in kinds
    assert "workflow" in kinds
    listed = snap.as_list()
    assert {row["id"] for row in listed if row["object"] == "node"} == {
        n.id for n in snap.nodes
    }
    assert {row["id"] for row in listed if row["object"] == "edge"} == {
        e.id for e in snap.edges
    }


def test_ingest_is_idempotent() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    g = AuthorityGraph()
    assert g.ingest_payload(payload) == 5
    assert g.ingest_payload(payload) == 0
    assert len(g.snapshot().event_ids) == 5


def test_query_filters_agent_and_decision() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    g = AuthorityGraph()
    g.ingest_payload(payload)
    builder = g.query(agent_id="builder")
    assert builder.event_ids
    allow = g.query(decision="ALLOW")
    assert allow.event_ids
    deny = g.query(decision="DENY")
    assert deny.event_ids == []


def test_secret_event_never_enters_graph() -> None:
    g = AuthorityGraph()
    bad = {
        "schema_version": "1",
        "event_id": "ev-secret",
        "timestamp": "2026-09-21T12:00:00Z",
        "trace_id": "tr-x",
        "span_id": "s1",
        "source_tool": "4allpass",
        "event_type": "capability.granted",
        "api_key": "sk-abcdefghijklmnop",
        "event_hash": "x" * 32,
    }
    try:
        g.ingest([bad])
        raise AssertionError("expected reject")
    except AuthorityEventError:
        pass
    assert g.snapshot().event_ids == []


def test_deny_opens_incident() -> None:
    from threaddesk.core.authority_event import compute_event_hash

    g = AuthorityGraph()
    ev = {
        "schema_version": "1",
        "event_id": "ev-deny",
        "timestamp": "2026-09-21T12:00:00Z",
        "trace_id": "tr-deny",
        "span_id": "s1",
        "source_tool": "agent-authority-lab",
        "event_type": "authority.denied",
        "decision": "DENY",
        "reason_code": "IFC_EGRESS",
        "actor": {"agent_id": "worker1", "role": "worker"},
        "resource": "url:https://example.com",
    }
    ev["event_hash"] = compute_event_hash(ev)
    g.ingest([ev])
    incidents = g.incidents()
    assert len(incidents) == 1
    assert incidents[0].reason.startswith("authority.denied")
    assert incidents[0].snapshot.event_ids == ["ev-deny"]
