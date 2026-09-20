"""G2: ThreadDesk imports Gnom JSONL without touching knowledge SQLite."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from threaddesk.ui import cli


def test_import_jsonl_builds_graph(tmp_path: Path, capsys) -> None:
    src = Path(__file__).resolve().parents[1] / "docs" / "authority" / "fixtures" / "example-trace.json"
    out = tmp_path / "snap.json"
    rc = cli.cmd_authority(argparse.Namespace(path=str(src), output=str(out)))
    assert rc == 0
    snap = json.loads(out.read_text(encoding="utf-8"))
    assert snap["imported"] == 5
    assert snap["counts"]["nodes"] >= 4
    assert not list(tmp_path.glob("*.sqlite"))
    assert not list(tmp_path.glob("threads/*.json"))


def test_import_gnom_jsonl_chain(tmp_path: Path) -> None:
    # Two chained events as Gnom would append.
    from threaddesk.core.authority_event import compute_event_hash

    e1 = {
        "schema_version": "1",
        "event_id": "g1",
        "timestamp": "2026-09-21T12:00:00Z",
        "trace_id": "ho-1",
        "span_id": "s1",
        "workflow_id": "ho-1",
        "project_id": "gnom-hub-v1",
        "source_tool": "gnom-hub-v1",
        "event_type": "work.started",
        "actor": {"agent_id": "coordinator", "role": "coordinator"},
        "action": "execute",
        "resource": "pipeline:execute",
        "previous_event_hash": None,
        "data_labels": ["PUBLIC"],
    }
    e1["event_hash"] = compute_event_hash(e1)
    e2 = {
        **e1,
        "event_id": "g2",
        "span_id": "s2",
        "event_type": "work.finished",
        "previous_event_hash": e1["event_hash"],
        "result_ref": "UNGEPRÜFT",
    }
    e2.pop("event_hash")
    e2["event_hash"] = compute_event_hash(e2)
    jsonl = tmp_path / "authority-events.jsonl"
    jsonl.write_text(json.dumps(e1) + "\n" + json.dumps(e2) + "\n", encoding="utf-8")
    out = tmp_path / "snap.json"
    rc = cli.cmd_authority(argparse.Namespace(path=str(jsonl), output=str(out)))
    assert rc == 0
    snap = json.loads(out.read_text(encoding="utf-8"))
    assert snap["imported"] == 2
    assert snap["event_ids"] == ["g1", "g2"]
