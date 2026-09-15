"""Strict local return channel from Gnom-Hub into the review inbox."""

from __future__ import annotations

from typing import Any, Mapping

from threaddesk.core.errors import InvalidState
from threaddesk.core.secrets import reject_secrets
from threaddesk.services.gnom_jobs import GnomJobRegistry, STATUSES
from threaddesk.services.return_contract import build as build_return
from threaddesk.services.return_inbox import ReturnInbox

FORMAT = "threaddesk.gnom-callback.v1"
ALLOWED = {
    "format", "event_id", "job_id", "status", "occurred_at", "details",
    "result", "artifacts", "test_results", "open_issues", "pull_request",
}


def receive(store: Any, value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    if set(payload) - ALLOWED:
        raise InvalidState("gnom_callback_fields")
    if payload.get("format") != FORMAT or payload.get("status") not in STATUSES:
        raise InvalidState("gnom_callback")
    for field in ("event_id", "job_id", "occurred_at"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise InvalidState(f"gnom_callback_{field}")
    for field in ("details", "result", "pull_request"):
        if payload.get(field) is not None and not isinstance(payload[field], str):
            raise InvalidState(f"gnom_callback_{field}")
    for field in ("artifacts", "test_results", "open_issues"):
        items = payload.get(field, [])
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
            raise InvalidState(f"gnom_callback_{field}")
        payload[field] = items
    reject_secrets(str(payload))
    if payload["status"] == "delivered" and not (payload.get("result") or "").strip():
        raise InvalidState("gnom_callback_result")

    registry = GnomJobRegistry(store)
    job = registry.get(payload["job_id"])
    registry.record(payload["job_id"], payload["event_id"], payload["status"], payload.get("details") or "")
    result = {"job": registry.get(payload["job_id"]), "return": None}
    if payload["status"] == "delivered":
        returned = build_return(
            handoff_id=job["handoff_id"], handoff_revision=job["handoff_revision"],
            thread_id=job["thread_id"], task_id=job["task_id"], worker="gnom-hub-v1",
            run_id=job["job_id"], result=payload["result"], files=payload["artifacts"],
            pull_request=payload.get("pull_request"), test_results=payload["test_results"],
            open_issues=payload["open_issues"],
            return_id=f"gnom:{job['job_id']}:{payload['event_id']}", created_at=payload["occurred_at"],
        )
        result["return"] = ReturnInbox(store).receive(returned)
    return result
