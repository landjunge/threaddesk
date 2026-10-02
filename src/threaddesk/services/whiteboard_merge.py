"""Merge two local whiteboard states. Both versions stay."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from threaddesk.core.errors import NotFound
from threaddesk.core.models import Thread, WhiteboardEntry, new_id, now_iso

CONFLICT_ROLE = "merge_conflict"
THREAD_FIELDS = ("title", "description", "notes")


def body_hash(entry: WhiteboardEntry) -> str:
    payload = {
        "thread_id": entry.thread_id,
        "actor": entry.actor,
        "actor_type": entry.actor_type,
        "entry_type": entry.entry_type,
        "content": entry.content,
        "task_id": entry.task_id,
        "handoff_id": entry.handoff_id,
        "run_id": entry.run_id,
        "external_key": entry.external_key,
        "actor_id": entry.actor_id,
        "metadata": entry.metadata,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def room_entries(entries: list[WhiteboardEntry], room_id: str) -> list[WhiteboardEntry]:
    """Private entries have no room id and never appear in a room view."""
    if not room_id:
        return []
    return [entry for entry in entries if entry.room_id == room_id]


def merge_stores(target: Any, source: Any) -> dict[str, int]:
    """Union source into target. An existing version is never replaced."""
    added = 0
    kept = 0
    conflicts = 0
    for thread in source.list_threads(include_archived=True):
        try:
            current = target.get_thread(thread.id)
        except NotFound:
            target.save_thread(thread)
        else:
            conflicts += _preserve_thread_fields(target, current, thread)
        report = merge_whiteboard(target, source.list_whiteboard(thread.id))
        added += report["added"]
        kept += report["kept"]
        conflicts += report["conflicts"]
    return {"added": added, "kept": kept, "conflicts": conflicts}


def merge_whiteboard(target: Any, incoming: list[WhiteboardEntry]) -> dict[str, int]:
    added = 0
    kept = 0
    conflicts = 0
    for entry in sorted(incoming, key=lambda item: (item.created_at, item.id)):
        current = _by_id(target, entry.thread_id)
        known = current.get(entry.id)
        incoming_hash = body_hash(entry)
        if known is not None:
            if body_hash(known) == incoming_hash:
                kept += 1
                continue
            if _record_conflict(target, known, entry, incoming_hash):
                conflicts += 1
            else:
                kept += 1
            continue
        twin = _by_external_key(current, entry.external_key)
        if twin is not None:
            if body_hash(twin) == incoming_hash:
                kept += 1
                continue
            if _record_conflict(target, twin, entry, incoming_hash):
                conflicts += 1
            else:
                kept += 1
            continue
        stored = _copy(entry, incoming_hash)
        target.append_whiteboard_entry(stored)
        added += 1
    return {"added": added, "kept": kept, "conflicts": conflicts}


def _by_id(store: Any, thread_id: str) -> dict[str, WhiteboardEntry]:
    try:
        entries = store.list_whiteboard(thread_id)
    except NotFound:
        return {}
    return {entry.id: entry for entry in entries}


def _by_external_key(entries: dict[str, WhiteboardEntry], key: str | None) -> WhiteboardEntry | None:
    if not key:
        return None
    for entry in entries.values():
        if entry.external_key == key:
            return entry
    return None


def _record_conflict(
    store: Any,
    kept: WhiteboardEntry,
    incoming: WhiteboardEntry,
    incoming_hash: str,
) -> bool:
    marker_key = f"merge-conflict:{kept.id}:{incoming_hash}"
    existing = _by_id(store, kept.thread_id)
    if any(entry.external_key == marker_key for entry in existing.values()):
        return False
    kept_hash = body_hash(kept)
    # A private side stays private. The room id remains inside the record.
    room_id = incoming.room_id if incoming.room_id and incoming.room_id == kept.room_id else None
    marker = WhiteboardEntry(
        id=new_id(),
        thread_id=kept.thread_id,
        actor=incoming.actor,
        actor_type=incoming.actor_type,
        created_at=incoming.created_at,
        entry_type="problem",
        content=incoming.content,
        task_id=incoming.task_id,
        handoff_id=incoming.handoff_id,
        run_id=incoming.run_id,
        external_key=marker_key,
        actor_id=incoming.actor_id,
        instance_id=incoming.instance_id,
        room_id=room_id,
        metadata={
            "role": CONFLICT_ROLE,
            "kept_id": kept.id,
            "incoming_id": incoming.id,
            "actor_id": incoming.actor_id,
            "task_id": incoming.task_id,
            "instance_id": incoming.instance_id,
            "created_at": incoming.created_at,
            "kept_hash": kept_hash,
            "incoming_hash": incoming_hash,
            "origin": incoming.instance_id or "local",
            "incoming": _contribution(incoming),
        },
    )
    marker.content_hash = body_hash(marker)
    store.append_whiteboard_entry(marker)
    return True


def _contribution(entry: WhiteboardEntry) -> dict[str, Any]:
    """The incoming version in full. Identity of the stored row stays separate."""
    return {
        "id": entry.id,
        "thread_id": entry.thread_id,
        "actor": entry.actor,
        "actor_type": entry.actor_type,
        "actor_id": entry.actor_id,
        "entry_type": entry.entry_type,
        "content": entry.content,
        "created_at": entry.created_at,
        "task_id": entry.task_id,
        "handoff_id": entry.handoff_id,
        "run_id": entry.run_id,
        "external_key": entry.external_key,
        "instance_id": entry.instance_id,
        "room_id": entry.room_id,
        "metadata": entry.metadata,
    }


def _preserve_thread_fields(store: Any, current: Thread, incoming: Thread) -> int:
    """Keep the target text. A different incoming text is stored beside it."""
    made = 0
    filled = False
    for name in THREAD_FIELDS:
        kept = _read_field(current, name)
        other = _read_field(incoming, name)
        if kept == other or not other:
            continue
        if not kept:
            _write_field(current, name, other)
            filled = True
            continue
        if _record_field_conflict(store, current, incoming, name, kept, other):
            made += 1
    if filled:
        store.save_thread(current)
    return made


def _record_field_conflict(
    store: Any,
    current: Thread,
    incoming: Thread,
    name: str,
    kept: str,
    other: str,
) -> bool:
    incoming_hash = _text_hash(other)
    marker_key = f"merge-conflict:{name}:{current.id}:{incoming_hash}"
    existing = _by_id(store, current.id)
    if any(entry.external_key == marker_key for entry in existing.values()):
        return False
    marker = WhiteboardEntry(
        id=new_id(),
        thread_id=current.id,
        actor="system",
        actor_type="system",
        created_at=incoming.updated_at or now_iso(),
        entry_type="problem",
        content=other,
        external_key=marker_key,
        metadata={
            "role": CONFLICT_ROLE,
            "field": name,
            "kept_id": current.id,
            "incoming_id": incoming.id,
            "actor_id": None,
            "task_id": None,
            "instance_id": None,
            "created_at": incoming.updated_at or "",
            "kept_hash": _text_hash(kept),
            "incoming_hash": incoming_hash,
            "origin": f"thread-{name}",
            "kept_text": kept,
            "incoming_text": other,
        },
    )
    marker.content_hash = body_hash(marker)
    store.append_whiteboard_entry(marker)
    return True


def _read_field(thread: Thread, name: str) -> str:
    if name == "notes":
        return thread.context.notes or ""
    return getattr(thread, name) or ""


def _write_field(thread: Thread, name: str, value: str) -> None:
    if name == "notes":
        thread.context.notes = value
        return
    setattr(thread, name, value)


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _copy(entry: WhiteboardEntry, digest: str) -> WhiteboardEntry:
    copied = WhiteboardEntry.from_dict(entry.to_dict())
    copied.content_hash = entry.content_hash or digest
    copied.ordinal = 0
    return copied
