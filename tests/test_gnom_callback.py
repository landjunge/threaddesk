from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import InvalidState
from threaddesk.storage.json_store import JsonStore


def setup(tmp_path: Path):
    svc = ThreadService(store=JsonStore(tmp_path)); svc.create("Callback")
    packet = svc.gnom(); svc.bind_gnom_job("job-1", packet)
    return svc


def callback(status="started", event_id="e1", **extra):
    return {"format": "threaddesk.gnom-callback.v1", "event_id": event_id,
            "job_id": "job-1", "status": status, "occurred_at": "2026-09-15T19:00:00+00:00", **extra}


def test_status_callback_updates_only_bound_job(tmp_path: Path) -> None:
    svc = setup(tmp_path)
    result = svc.receive_gnom_callback(callback(details="Working"))
    assert result["job"]["status"] == "started"
    assert result["return"] is None
    assert svc.returns() == []


def test_delivered_callback_enters_unverified_inbox_idempotently(tmp_path: Path) -> None:
    svc = setup(tmp_path)
    value = callback("delivered", result="Done", artifacts=["out.txt"],
                     test_results=["8 passed"], open_issues=[])
    first = svc.receive_gnom_callback(value)
    again = svc.receive_gnom_callback(value)
    assert first["return"]["return"]["review_status"] == "unverified"
    assert again["return"]["duplicate"] is True
    assert len(svc.returns()) == 1


def test_callback_rejects_unknown_fields_and_missing_delivery_result(tmp_path: Path) -> None:
    svc = setup(tmp_path)
    with pytest.raises(InvalidState, match="fields"):
        svc.receive_gnom_callback(callback(admin=True))
    with pytest.raises(InvalidState, match="result"):
        svc.receive_gnom_callback(callback("delivered"))
