from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import InvalidState
from threaddesk.storage.json_store import JsonStore


def service(tmp_path: Path) -> ThreadService:
    svc = ThreadService(store=JsonStore(tmp_path)); svc.create("Bound work")
    svc.gnom(mode="brainstorm")
    return svc


def test_job_is_bound_to_all_handoff_identities_and_survives_restart(tmp_path: Path) -> None:
    svc = service(tmp_path)
    bound = svc.bind_gnom_job("job-1")
    assert bound["thread_id"] and bound["task_id"] and bound["handoff_id"]
    assert bound["handoff_revision"] == 1
    restarted = ThreadService(store=JsonStore(tmp_path))
    assert restarted.gnom_jobs()[0]["job_id"] == "job-1"


def test_binding_and_events_are_idempotent_but_conflicts_are_rejected(tmp_path: Path) -> None:
    svc = service(tmp_path)
    packet = svc.gnom()
    svc.bind_gnom_job("job-1", packet)
    assert svc.bind_gnom_job("job-1", packet)["job_id"] == "job-1"
    with pytest.raises(InvalidState, match="already_bound"):
        svc.bind_gnom_job("job-2", packet)
    first = svc.record_gnom_event("job-1", "event-1", "started")
    again = svc.record_gnom_event("job-1", "event-1", "started")
    assert len(first["events"]) == len(again["events"]) == 1
    with pytest.raises(InvalidState, match="event_conflict"):
        svc.record_gnom_event("job-1", "event-1", "blocked")
