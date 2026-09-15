"""Untrusted result contract for work returned to ThreadDesk."""

from __future__ import annotations

from typing import Any, Mapping

from threaddesk.core.errors import InvalidState
from threaddesk.core.models import new_id, now_iso

FORMAT = "threaddesk.return.v1"
REQUIRED = (
    "format", "return_id", "handoff_id", "handoff_revision", "thread_id", "task_id",
    "worker", "run_id", "result", "files", "pull_request", "test_results",
    "open_issues", "delivery_status", "review_status", "created_at",
)


def _strings(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise InvalidState(f"return_{field}")
    return [item.strip() for item in value if item.strip()]


def build(
    *, handoff_id: str, handoff_revision: int, thread_id: str, task_id: str,
    worker: str, run_id: str, result: str, files: list[str] | None = None,
    pull_request: str | None = None, test_results: list[str] | None = None,
    open_issues: list[str] | None = None, return_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    return validate({
        "format": FORMAT,
        "return_id": return_id or new_id(),
        "handoff_id": handoff_id,
        "handoff_revision": handoff_revision,
        "thread_id": thread_id,
        "task_id": task_id,
        "worker": worker,
        "run_id": run_id,
        "result": result,
        "files": files or [],
        "pull_request": pull_request,
        "test_results": test_results or [],
        "open_issues": open_issues or [],
        "delivery_status": "delivered",
        "review_status": "unverified",
        "created_at": created_at or now_iso(),
    })


def validate(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    if payload.get("format") != FORMAT or any(field not in payload for field in REQUIRED):
        raise InvalidState("return_contract")
    for field in ("return_id", "handoff_id", "thread_id", "task_id", "worker", "run_id", "result", "created_at"):
        if not isinstance(payload[field], str) or not payload[field].strip():
            raise InvalidState(f"return_{field}")
    if not isinstance(payload["handoff_revision"], int) or payload["handoff_revision"] < 1:
        raise InvalidState("return_revision")
    for field in ("files", "test_results", "open_issues"):
        payload[field] = _strings(payload[field], field)
    if payload["pull_request"] is not None and not isinstance(payload["pull_request"], str):
        raise InvalidState("return_pull_request")
    if payload["delivery_status"] != "delivered" or payload["review_status"] != "unverified":
        raise InvalidState("return_status")
    return payload
