from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import InvalidState
from threaddesk.services.return_contract import build
from threaddesk.storage.json_store import JsonStore
from threaddesk.services.mcp import McpBridge


def returned(revision=1):
    return build(handoff_id="h1", handoff_revision=revision, thread_id="t1", task_id="task1", worker="grok", run_id=f"run-{revision}", result="Done")


def test_receive_is_local_unverified_and_idempotent(tmp_path: Path) -> None:
    svc = ThreadService(store=JsonStore(tmp_path))
    payload = returned()
    first = svc.receive_return(payload)
    again = svc.receive_return(payload)
    assert first["duplicate"] is False and again["duplicate"] is True
    assert len(svc.returns()) == 1
    assert svc.returns()[0]["return"]["review_status"] == "unverified"


def test_stale_or_conflicting_return_never_overwrites(tmp_path: Path) -> None:
    svc = ThreadService(store=JsonStore(tmp_path))
    newer = returned(2)
    svc.receive_return(newer)
    with pytest.raises(InvalidState, match="return_stale"):
        svc.receive_return(returned(1))
    changed = dict(newer, result="Different")
    with pytest.raises(InvalidState, match="return_id_conflict"):
        svc.receive_return(changed)
    assert svc.returns()[0]["return"]["result"] == "Done"


def test_review_requires_one_visible_final_choice(tmp_path: Path) -> None:
    svc = ThreadService(store=JsonStore(tmp_path))
    payload = returned()
    svc.receive_return(payload)
    decided = svc.decide_return(payload["return_id"], "rework", "Tests fehlen")
    assert decided["decision"]["choice"] == "rework"
    assert svc.decide_return(payload["return_id"], "rework", "Tests fehlen") == decided
    with pytest.raises(InvalidState, match="return_already_decided"):
        svc.decide_return(payload["return_id"], "accepted")


def test_mcp_inbox_never_auto_accepts(tmp_path: Path) -> None:
    svc = ThreadService(store=JsonStore(tmp_path))
    bridge = McpBridge(svc)
    payload = returned()
    received = bridge.call("import_return", {"payload": payload})
    assert received["result"]["decision"] is None
    listed = bridge.call("list_returns", {})
    assert listed["result"][0]["return"]["return_id"] == payload["return_id"]
    reviewed = bridge.call("review_return", {"return_id": payload["return_id"], "choice": "accepted"})
    assert reviewed["result"]["decision"]["choice"] == "accepted"
