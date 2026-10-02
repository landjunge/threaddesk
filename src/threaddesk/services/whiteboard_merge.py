"""Merge two local whiteboard states. Nothing is overwritten."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from threaddesk.core.errors import NotFound
from threaddesk.core.models import WhiteboardEntry, new_id, now_iso

CONFLICT_ROLE = "merge_conflict"


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
    """Union source into target. Existing threads and entries stay as they are."""
    added = 0
    kept = 0
    conflicts = 0
    for thread in source.list_threads(include_archived=True):
        try:
            target.get_thread(thread.id)
        except NotFound:
            target.save_thread(thread)
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
            if _record_conflict(target, known, incoming_hash):
                conflicts += 1
            else:
                kept += 1
            continue
        twin = _by_external_key(current, entry.external_key)
        if twin is not None:
            if body_hash(twin) == incoming_hash:
                kept += 1
                continue
            if _record_conflict(target, twin, incoming_hash):
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


def _record_conflict(store: Any, kept: WhiteboardEntry, incoming_hash: str) -> bool:
    marker_key = f"merge-conflict:{kept.id}:{incoming_hash[:16]}"
    existing = _by_id(store, kept.thread_id)
    if any(entry.external_key == marker_key for entry in existing.values()):
        return False
    marker = WhiteboardEntry(
        id=new_id(),
        thread_id=kept.thread_id,
        actor="system",
        actor_type="system",
        created_at=now_iso(),
        entry_type="problem",
        content=f"Eintrag {kept.id} blieb unverändert. Eine abweichende Fassung wurde nicht übernommen.",
        external_key=marker_key,
        instance_id=kept.instance_id,
        room_id=kept.room_id,
        metadata={
            "role": CONFLICT_ROLE,
            "kept_id": kept.id,
            "kept_hash": body_hash(kept),
            "incoming_hash": incoming_hash,
        },
    )
    marker.content_hash = body_hash(marker)
    store.append_whiteboard_entry(marker)
    return True


def _copy(entry: WhiteboardEntry, digest: str) -> WhiteboardEntry:
    copied = WhiteboardEntry.from_dict(entry.to_dict())
    copied.content_hash = entry.content_hash or digest
    copied.ordinal = 0
    return copied
