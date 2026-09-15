from pathlib import Path

from threaddesk.api.service import ThreadService
from threaddesk.services.mcp import McpBridge
from threaddesk.storage.json_store import JsonStore


def test_controlled_mcp_round_trip_never_auto_executes_or_accepts(tmp_path: Path) -> None:
    svc = ThreadService(store=JsonStore(tmp_path)); svc.create("Round trip")
    bridge = McpBridge(svc)
    exported = bridge.call("export_gnom", {"mode": "brainstorm"})["result"]
    assert exported["sent"] is False and exported["ran"] is False

    bound = bridge.call("bind_gnom_job", {"job_id": "job-rt", "packet": exported})["result"]
    revision = bound["handoff_revision"]
    started = {"format": "threaddesk.gnom-callback.v1", "event_id": "start",
               "job_id": "job-rt", "handoff_revision": revision, "status": "started",
               "occurred_at": "2026-09-15T20:00:00+00:00"}
    assert bridge.call("receive_gnom_callback", {"payload": started})["ok"]
    delivered = {**started, "event_id": "done", "status": "delivered",
                 "occurred_at": "2026-09-15T20:01:00+00:00", "result": "Completed",
                 "artifacts": ["result.txt"], "test_results": ["12 passed"], "open_issues": []}
    returned = bridge.call("receive_gnom_callback", {"payload": delivered})["result"]["return"]

    assert returned["return"]["review_status"] == "unverified"
    assert returned["decision"] is None
    assert bridge.call("list_gnom_jobs", {})["result"][0]["status"] == "delivered"
    assert svc.gate()["today"]["execute"] == 0
