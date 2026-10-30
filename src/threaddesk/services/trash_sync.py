"""Versioned, conservative lifecycle exchange for the existing room transport.

Only authenticated RoomBook calls this module. Content hashes expose no private
payload. Concurrent content changes become durable review items; timestamps do
not decide which peer wins. Purge is always local and never propagates deletion.
"""
from __future__ import annotations

from copy import deepcopy

from threaddesk.core.errors import InvalidState, ManagementError, NotFound
from threaddesk.core.models import now_iso
from threaddesk.services.trash import TrashService, _hash, _id
from threaddesk.storage.operation_results import result_object

ROOM_SCHEMA = "threaddesk.room.v2"


def room_thread_owned(store, thread_id, room_id):
    """Only retained local contributions establish a room's thread scope."""
    try:
        return any(entry.room_id == room_id for entry in
                   store.list_whiteboard(thread_id, include_trashed=True))
    except NotFound:
        return False


def validate_room_scope(store, room_id, records, thread_ids=()):
    """Preflight original local scope; the caller owns observation rollback."""
    for thread_id in sorted(set(thread_ids)):
        try:
            store.get_thread(thread_id, include_trashed=True)
        except NotFound:
            continue  # A new remote room thread may receive a local shell.
        if not room_thread_owned(store, thread_id, room_id):
            raise InvalidState("room_thread_scope")
    for incoming in records:
        if not room_thread_owned(store, incoming["thread_id"], room_id):
            raise InvalidState("room_lifecycle_scope")


def content_digest(store, thread_id, room_id):
    thread = store.get_thread(thread_id, include_trashed=True)
    payload = thread.to_dict()
    for key in ("id", "created_at", "updated_at", "revision", "current_snapshot_id"):
        payload.pop(key, None)
    # The local snapshot cursor is not shared content; private content changes
    # still cause a conflict rather than silently hiding a colleague's edit.
    entries = [entry.to_dict() for entry in store.list_whiteboard(thread_id, include_trashed=True)
               if entry.room_id == room_id]
    for entry in entries:
        entry.pop("ordinal", None)
    entries.sort(key=lambda item: item["id"])
    return _hash([payload, entries])


def record_conflict(store, *, thread_id, source, reason, incoming):
    request = {"thread_id": thread_id, "source": source, "reason": reason, "incoming": incoming}
    key = "lifecycle_conflict_" + _hash(request)
    if store.get_management_operation(key) is None:
        with store.transaction():
            if store.get_management_operation(key) is None:
                store.save_management_operation(key, {
                    "request_hash": _hash(request), "recorded_at": now_iso(),
                    "kind": "lifecycle_conflict", "thread_id": thread_id,
                    "result": {"operation_id": key, **request, "state": "conflict"}})
    return key


def conflict_is_resolved(store, key):
    return any(result_object(item).get("resolved_conflict") == key
               for item in store.list_management_operations())


def export_room_lifecycle(store, room_id):
    latest = {}
    for entry in store.list_trash_entries():
        if entry["kind"] != "thread":
            continue
        previous = latest.get(entry["object_id"])
        if previous is None or previous["generation"] < entry["generation"]:
            latest[entry["object_id"]] = entry
    result = []
    for thread_id, entry in sorted(latest.items()):
        # Only room-owned contributions establish a sharing scope.
        try:
            if not room_thread_owned(store, thread_id, room_id):
                continue
            digest = content_digest(store, thread_id, room_id)
        except NotFound:
            # A local purge retained only a tombstone; it does not grant a
            # peer permission to erase its remaining content.
            continue
        result.append({"thread_id": thread_id, "generation": entry["generation"],
                       "revision": entry["revision"], "state": entry["state"],
                       "content_digest": digest})
    return result


def validate_room_lifecycle(value):
    if not isinstance(value, list) or len(value) > 2000:
        raise InvalidState("room_lifecycle")
    seen = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"thread_id", "generation", "revision", "state", "content_digest"}:
            raise InvalidState("room_lifecycle")
        _id(item["thread_id"])
        if (item["thread_id"] in seen or type(item["generation"]) is not int or item["generation"] < 1
                or type(item["revision"]) is not int or item["revision"] < 1
                or item["state"] not in {"trashed", "restored", "purged"}
                or not isinstance(item["content_digest"], str) or len(item["content_digest"]) != 64
                or any(char not in "0123456789abcdef" for char in item["content_digest"])):
            raise InvalidState("room_lifecycle")
        seen.add(item["thread_id"])
    return deepcopy(value)


def apply_room_lifecycle(store, room_id, records):
    # The authenticated room, not a peer's digest or accompanying bundle rows,
    # must already own a local contribution. Include retained contributions so
    # legitimate trash/restore history keeps its scope. Preflight every target
    # before any operation (including replay shortcuts or conflict receipts).
    validate_room_scope(store, room_id, records)
    conflicts = 0
    service = TrashService(store)
    for incoming in records:
        thread_id = incoming["thread_id"]
        latest = store.get_object_lifecycle("thread", thread_id)
        if latest and incoming["generation"] == latest["generation"] and incoming["state"] == latest["state"]:
            continue
        reason = None
        try:
            current = store.get_thread(thread_id, include_trashed=True)
            if content_digest(store, thread_id, room_id) != incoming["content_digest"]:
                reason = "concurrent_content_change"
        except NotFound:
            current = None
            reason = "missing_lifecycle_original"
        if incoming["state"] == "purged":
            reason = "remote_purge_requires_local_review"
        elif latest and incoming["generation"] < latest["generation"]:
            reason = "stale_generation"
        elif incoming["state"] == "restored" and (latest is None or incoming["generation"] != latest["generation"]):
            reason = "restore_without_matching_generation"
        elif incoming["state"] == "trashed" and incoming["generation"] != ((latest["generation"] if latest else 0) + 1):
            reason = "generation_gap"
        if reason:
            key = record_conflict(store, thread_id=thread_id, source="room:" + room_id, reason=reason, incoming=incoming)
            conflicts += not conflict_is_resolved(store, key)
            continue
        operation_id = "room_lifecycle_" + _hash([room_id, incoming])[:64]
        try:
            if incoming["state"] == "trashed":
                service.move(kind="thread", object_id=thread_id, expected_revision=current.revision,
                             operation_id=operation_id, actor="authenticated_room_peer")
            elif latest and latest["state"] == "trashed":
                service.restore(trash_id=latest["trash_id"], generation=latest["generation"],
                                expected_revision=latest["revision"], operation_id=operation_id)
            else:
                raise ManagementError("lifecycle_conflict", "Lebenszykluszustand stimmt nicht überein.")
        except ManagementError as exc:
            key = record_conflict(store, thread_id=thread_id, source="room:" + room_id,
                                  reason=exc.code, incoming=incoming)
            conflicts += not conflict_is_resolved(store, key)
    return conflicts
