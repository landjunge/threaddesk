"""Persistent identity binding between Gnom jobs and ThreadDesk handoffs."""

from __future__ import annotations

import json
from typing import Any, Mapping

from threaddesk.core.errors import InvalidState, NotFound
from threaddesk.core.models import now_iso
from threaddesk.services.gnom_bridge import validate_packet

STATUSES = ("started", "question", "blocked", "error", "delivered", "cancelled")


class GnomJobRegistry:
    def __init__(self, store: Any) -> None:
        self.store = store
        self.path = store.artifact_path("gnom-jobs.json")

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "jobs": []}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("version") != 1 or not isinstance(value.get("jobs"), list):
            raise InvalidState("gnom_jobs")
        return value

    def list(self) -> list[dict[str, Any]]:
        return list(self._read()["jobs"])

    def bind(self, job_id: str, packet: Mapping[str, Any]) -> dict[str, Any]:
        job_id = job_id.strip()
        if not job_id:
            raise InvalidState("gnom_job_id")
        checked = validate_packet(dict(packet))
        handoff = checked["handoff"]
        binding = {
            "job_id": job_id, "thread_id": handoff["thread_id"],
            "task_id": handoff["task_id"], "handoff_id": handoff["handoff_id"],
            "handoff_revision": handoff["revision"], "bound_at": now_iso(),
            "status": None, "events": [],
        }
        state = self._read()
        for current in state["jobs"]:
            if current["job_id"] == job_id:
                same = all(current[key] == binding[key] for key in ("thread_id", "task_id", "handoff_id", "handoff_revision"))
                if not same:
                    raise InvalidState("gnom_job_conflict")
                return current
            if current["handoff_id"] == binding["handoff_id"]:
                raise InvalidState("gnom_handoff_already_bound")
        state["jobs"].append(binding)
        self.store.write_json_artifact("gnom-jobs.json", state)
        return binding

    def record(self, job_id: str, event_id: str, status: str, details: str = "") -> dict[str, Any]:
        if status not in STATUSES or not event_id.strip():
            raise InvalidState("gnom_job_event")
        event = {"event_id": event_id.strip(), "status": status, "details": details, "occurred_at": now_iso()}
        state = self._read()
        for job in state["jobs"]:
            if job["job_id"] != job_id:
                continue
            for existing in job["events"]:
                if existing["event_id"] == event["event_id"]:
                    if existing["status"] != status or existing["details"] != details:
                        raise InvalidState("gnom_event_conflict")
                    return job
            job["events"].append(event); job["status"] = status
            self.store.write_json_artifact("gnom-jobs.json", state)
            return job
        raise NotFound(f"Gnom-Job nicht gefunden: {job_id}")
