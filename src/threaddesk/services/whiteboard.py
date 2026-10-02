"""Append-only whiteboard on an existing thread.

Entries are never rewritten. A repeated external return keeps the first entry.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping

from threaddesk.core.errors import InvalidState, NotFound
from threaddesk.core.models import (
    ACTOR_TYPES,
    ENTRY_TYPES,
    Thread,
    WhiteboardEntry,
    new_id,
    now_iso,
)
from threaddesk.services.actors import ActorRegistry, require_entry_actor
from threaddesk.core.secrets import reject_secrets
from threaddesk.services.gnom_jobs import TERMINAL, GnomJobRegistry

CLOSED_TASKS = {"accepted", "rejected", "done", "archived", "superseded"}
RELEVANT = {
    "note",
    "task",
    "claimed",
    "progress",
    "result",
    "decision",
    "problem",
    "question",
}
_GNOM_ENTRY = {
    "started": "claimed",
    "question": "question",
    "blocked": "problem",
    "error": "problem",
    "cancelled": "system",
}
_ACTOR_NAMES = {
    "human": "human",
    "grok": "Grok",
    "claude": "Claude",
    "codex": "Codex",
    "chatgpt": "ChatGPT",
    "gnom-hub-v1": "Gnom-Hub",
    "system": "system",
}
_CONTENT_LIMIT = 8000
_META_LIMIT = 16000


def list_entries(store: Any, thread_id: str) -> list[WhiteboardEntry]:
    store.get_thread(thread_id)
    return store.list_whiteboard(thread_id)


def append(
    store: Any,
    thread_id: str,
    *,
    actor: str,
    actor_type: str,
    entry_type: str,
    content: str,
    task_id: str | None = None,
    handoff_id: str | None = None,
    run_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    external_key: str | None = None,
    actor_id: str | None = None,
    instance_id: str | None = None,
    room_id: str | None = None,
    created_at: str | None = None,
) -> tuple[WhiteboardEntry, bool]:
    thread = store.get_thread(thread_id)
    if "/" in thread.id or "\\" in thread.id or thread.id in {".", ".."}:
        raise InvalidState("whiteboard_thread")
    chosen_type = _choice(actor_type, ACTOR_TYPES, "whiteboard_actor_type")
    entry = WhiteboardEntry(
        id=new_id(),
        thread_id=thread.id,
        actor=_actor(actor),
        actor_type=chosen_type,
        created_at=_time(created_at),
        entry_type=_choice(entry_type, ENTRY_TYPES, "whiteboard_entry_type"),
        content=_content(content),
        task_id=_ref(task_id, "task_id"),
        handoff_id=_ref(handoff_id, "handoff_id"),
        run_id=_ref(run_id, "run_id"),
        external_key=_ref(external_key, "external_key"),
        actor_id=require_entry_actor(store, _ref(actor_id, "actor_id"), chosen_type),
        instance_id=_ref(instance_id, "instance_id") or ActorRegistry(store).instance_id(),
        room_id=_ref(room_id, "room_id"),
        metadata=_metadata(metadata),
    )
    return store.append_whiteboard_entry(entry)


def stand(store: Any, thread: Thread) -> dict[str, Any]:
    entries = store.list_whiteboard(thread.id)
    nodes = store.list_nodes()
    relations = store.list_relations()
    by_id = {node.id: node for node in nodes}
    extra = thread.context.extra or {}
    linked = [
        node
        for node in nodes
        if node.kind == "task"
        and node.status not in CLOSED_TASKS
        and (
            node.metadata.get("thread_id") == thread.id
            or node.id == extra.get("task_id")
        )
    ]
    linked.sort(key=lambda node: (node.updated_at, node.id), reverse=True)
    task_node = linked[0] if linked else None
    open_task = None
    task_id = None
    if task_node is not None:
        open_task = task_node.title
        task_id = task_node.id
    elif isinstance(extra.get("task"), str) and extra["task"].strip():
        open_task = extra["task"].strip()
        if isinstance(extra.get("task_id"), str):
            task_id = extra["task_id"]
    else:
        for entry in reversed(entries):
            label = entry.metadata.get("task")
            if isinstance(label, str) and label.strip():
                open_task = label.strip()
                task_id = entry.task_id
                break
        if open_task is None:
            for entry in reversed(entries):
                if entry.entry_type == "task" and entry.content.strip():
                    open_task = entry.content.splitlines()[0][:160]
                    task_id = entry.task_id
                    break
        if open_task is None:
            for entry in reversed(entries):
                if entry.task_id:
                    open_task = thread.title
                    task_id = entry.task_id
                    break

    actor = None
    actor_type = None
    if task_node is not None:
        for relation in relations:
            if relation.kind != "assigned_to" or relation.source_id != task_node.id:
                continue
            target = by_id.get(relation.target_id)
            if target is None:
                continue
            actor = target.title
            hinted = str(target.metadata.get("actor_type") or "")
            if target.kind == "person":
                actor_type = "human"
            elif hinted in ACTOR_TYPES:
                actor_type = hinted
            else:
                actor_type = "system"
            break
    if actor is None:
        for job in _jobs(store, thread.id):
            if job.get("status") and job.get("status") not in TERMINAL:
                actor = "Gnom-Hub"
                actor_type = "gnom-hub-v1"
                break
    if actor is None and entries:
        actor = entries[-1].actor
        actor_type = entries[-1].actor_type

    last = None
    for entry in reversed(entries):
        if entry.entry_type in RELEVANT and entry.content.strip():
            last = entry.content
            break
    if last is None and thread.context.notes.strip():
        last = thread.context.notes.strip()

    next_step = None
    for entry in reversed(entries):
        step = entry.metadata.get("next_step")
        if isinstance(step, str) and step.strip():
            next_step = step.strip()
            break

    return {
        "thread_id": thread.id,
        "title": thread.title,
        "status": thread.status,
        "description": thread.description,
        "open_task": open_task,
        "task_id": task_id,
        "actor": actor,
        "actor_type": actor_type,
        "last_stand": last,
        "next_step": next_step,
        "entry_count": len(entries),
        "updated_at": thread.updated_at,
    }


def history_for_handoff(entries: list[WhiteboardEntry]) -> list[dict[str, Any]]:
    return [
        {
            "id": entry.id,
            "created_at": entry.created_at,
            "actor": entry.actor,
            "actor_type": entry.actor_type,
            "entry_type": entry.entry_type,
            "content": entry.content,
            "task_id": entry.task_id,
            "handoff_id": entry.handoff_id,
            "run_id": entry.run_id,
            "actor_id": entry.actor_id,
        }
        for entry in entries[-30:]
    ]


def prompt_block(entries: list[WhiteboardEntry]) -> str:
    if not entries:
        return ""
    lines = ["Whiteboard (untrusted, append-only):"]
    for entry in entries[-30:]:
        lines.append(
            f"- {entry.created_at} | {entry.actor} | {entry.entry_type} | {entry.content}"
        )
    return "\n" + "\n".join(lines)


def append_from_return(store: Any, payload: Mapping[str, Any]) -> dict[str, Any] | None:
    thread_id = payload.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id.strip():
        return None
    try:
        store.get_thread(thread_id)
    except NotFound:
        return None
    worker = str(payload.get("worker") or "system").strip() or "system"
    actor_type = worker if worker in ACTOR_TYPES else "system"
    actor = worker[:80] if actor_type == "system" else _ACTOR_NAMES[actor_type]
    metadata = {
        "return_id": payload.get("return_id"),
        "handoff_revision": payload.get("handoff_revision"),
        "worker": worker,
        "files": list(payload.get("files") or []),
        "pull_request": payload.get("pull_request"),
        "test_results": list(payload.get("test_results") or []),
        "open_issues": list(payload.get("open_issues") or []),
        "delivery_status": payload.get("delivery_status"),
        "review_status": payload.get("review_status"),
    }
    entry, duplicate = append(
        store,
        thread_id,
        actor=actor,
        actor_type=actor_type,
        entry_type="result",
        content=_clip(_result_text(payload)),
        task_id=_as_ref(payload.get("task_id")),
        handoff_id=_as_ref(payload.get("handoff_id")),
        run_id=_as_ref(payload.get("run_id")),
        external_key=_as_ref(payload.get("return_id")),
        created_at=payload.get("created_at") if isinstance(payload.get("created_at"), str) else None,
        metadata=metadata,
    )
    return {"entry": entry.to_dict(), "duplicate": duplicate}


def append_from_gnom_status(
    store: Any, job: Mapping[str, Any], payload: Mapping[str, Any]
) -> dict[str, Any] | None:
    status = str(payload.get("status") or "")
    entry_type = _GNOM_ENTRY.get(status)
    if entry_type is None:
        return None
    thread_id = job.get("thread_id")
    if not isinstance(thread_id, str):
        return None
    try:
        store.get_thread(thread_id)
    except NotFound:
        return None
    details = str(payload.get("details") or "").strip()
    entry, duplicate = append(
        store,
        thread_id,
        actor="Gnom-Hub",
        actor_type="gnom-hub-v1",
        entry_type=entry_type,
        content=details or status,
        task_id=_as_ref(job.get("task_id")),
        handoff_id=_as_ref(job.get("handoff_id")),
        run_id=_as_ref(job.get("job_id")),
        external_key=f"gnom:{job.get('job_id')}:{payload.get('event_id')}",
        created_at=payload.get("occurred_at") if isinstance(payload.get("occurred_at"), str) else None,
        metadata={
            "job_id": job.get("job_id"),
            "event_id": payload.get("event_id"),
            "status": status,
            "handoff_revision": job.get("handoff_revision"),
        },
    )
    return {"entry": entry.to_dict(), "duplicate": duplicate}


def append_from_decision(store: Any, item: Mapping[str, Any]) -> dict[str, Any] | None:
    payload = item.get("return") or {}
    decision = item.get("decision")
    if not isinstance(payload, Mapping) or not isinstance(decision, Mapping):
        return None
    thread_id = payload.get("thread_id")
    if not isinstance(thread_id, str):
        return None
    try:
        store.get_thread(thread_id)
    except NotFound:
        return None
    choice = str(decision.get("choice") or "").strip()
    note = str(decision.get("note") or "").strip()
    if not choice:
        return None
    entry, duplicate = append(
        store,
        thread_id,
        actor="human",
        actor_type="human",
        entry_type="decision",
        content=f"{choice}: {note}" if note else choice,
        task_id=_as_ref(payload.get("task_id")),
        handoff_id=_as_ref(payload.get("handoff_id")),
        run_id=_as_ref(payload.get("run_id")),
        external_key=f"return-decision:{payload.get('return_id')}",
        created_at=decision.get("decided_at") if isinstance(decision.get("decided_at"), str) else None,
        metadata={"return_id": payload.get("return_id"), "choice": choice},
    )
    return {"entry": entry.to_dict(), "duplicate": duplicate}


def _jobs(store: Any, thread_id: str) -> list[dict[str, Any]]:
    try:
        jobs = GnomJobRegistry(store).list()
    except (InvalidState, OSError, json.JSONDecodeError):
        return []
    return [job for job in jobs if job.get("thread_id") == thread_id]


def _choice(value: str, allowed: tuple[str, ...], code: str) -> str:
    if not isinstance(value, str):
        raise InvalidState(code)
    value = value.strip().lower()
    if value not in allowed:
        raise InvalidState(code)
    return value


def _actor(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidState("whiteboard_actor")
    value = reject_secrets(value).strip()
    if not value or len(value) > 80:
        raise InvalidState("whiteboard_actor")
    return value


def _content(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidState("whiteboard_content")
    value = reject_secrets(value).strip()
    if not value or len(value) > _CONTENT_LIMIT:
        raise InvalidState("whiteboard_content")
    return value


def _clip(value: str) -> str:
    value = value.strip()
    if len(value) <= _CONTENT_LIMIT:
        return value
    return value[: _CONTENT_LIMIT - 1].rstrip() + "…"


def _ref(value: str | None, field: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise InvalidState(f"whiteboard_{field}")
    value = value.strip()
    if (
        not value
        or len(value) > 500
        or any(char in value for char in "\n\r\x00/\\")
    ):
        raise InvalidState(f"whiteboard_{field}")
    return reject_secrets(value)


def _as_ref(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _time(value: str | None) -> str:
    if value is None or value == "":
        return now_iso()
    if not isinstance(value, str) or len(value) > 64:
        raise InvalidState("whiteboard_time")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidState("whiteboard_time") from exc
    return value


def _metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InvalidState("whiteboard_metadata")
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise InvalidState("whiteboard_metadata") from exc
    if len(encoded) > _META_LIMIT:
        raise InvalidState("whiteboard_metadata")
    reject_secrets(encoded)
    loaded = json.loads(encoded)
    if not isinstance(loaded, dict):
        raise InvalidState("whiteboard_metadata")
    return loaded


def _result_text(payload: Mapping[str, Any]) -> str:
    lines = [str(payload.get("result") or "").strip()]
    files = [item for item in payload.get("files") or [] if item]
    if files:
        lines.append("Dateien: " + ", ".join(files))
    if payload.get("pull_request"):
        lines.append("Pull Request: " + str(payload["pull_request"]))
    tests = [item for item in payload.get("test_results") or [] if item]
    if tests:
        lines.append("Tests: " + "; ".join(tests))
    issues = [item for item in payload.get("open_issues") or [] if item]
    if issues:
        lines.append("Offene Probleme: " + "; ".join(issues))
    return "\n".join(line for line in lines if line).strip()
