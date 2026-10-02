"""Two offline whiteboards merge by union. Nothing is overwritten."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.models import WhiteboardEntry, new_thread
from threaddesk.services.whiteboard_merge import merge_stores, room_entries
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.storage.workspace_backup import WorkspaceBackup


def _entry(thread_id: str, entry_id: str, content: str, created_at: str, **extra) -> WhiteboardEntry:
    return WhiteboardEntry(
        id=entry_id,
        thread_id=thread_id,
        actor=extra.pop("actor", "Ada"),
        actor_type=extra.pop("actor_type", "human"),
        created_at=created_at,
        entry_type="note",
        content=content,
        ordinal=1,
        external_key=extra.pop("external_key", None),
        instance_id=extra.pop("instance_id", None),
        room_id=extra.pop("room_id", None),
        metadata=extra.pop("metadata", {}),
    )


def _put(store, entry: WhiteboardEntry) -> None:
    store.append_whiteboard_entry(entry)


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def roots(request, tmp_path: Path):
    left = request.param(tmp_path / "left")
    right = request.param(tmp_path / "right")
    return left, right


def test_disjoint_entries_merge_without_loss_or_overwrite(roots) -> None:
    left, right = roots
    thread = new_thread("Gemeinsam")
    thread.context.notes = "Notiz auf diesem Rechner"
    left.save_thread(thread)
    other = new_thread("Nur rechts")
    right.save_thread(thread)
    stored = right.get_thread(thread.id)
    stored.context.notes = "Andere Notiz"
    right.save_thread(stored)
    right.save_thread(other)
    early = _entry(thread.id, "early01", "zuerst", "2026-10-02T08:00:00+00:00", instance_id="machine-b")
    later = _entry(thread.id, "later01", "danach", "2026-10-02T10:00:00+00:00", instance_id="machine-a")
    _put(right, early)
    _put(left, later)

    first = merge_stores(left, right)
    second = merge_stores(left, right)

    assert first == {"added": 1, "kept": 0, "conflicts": 0}
    assert second == {"added": 0, "kept": 1, "conflicts": 0}
    merged = left.list_whiteboard(thread.id)
    assert [entry.content for entry in merged if entry.metadata.get("role") != "merge_conflict"] == [
        "zuerst",
        "danach",
    ]
    assert [entry.id for entry in merged] == ["early01", "later01"]
    assert left.get_thread(thread.id).context.notes == "Notiz auf diesem Rechner"
    assert left.get_thread(other.id).title == "Nur rechts"
    assert right.get_thread(thread.id).context.notes == "Andere Notiz"


def test_divergent_copies_stay_and_record_one_conflict(roots) -> None:
    left, right = roots
    thread = new_thread("Konflikt")
    left.save_thread(thread)
    right.save_thread(thread)
    kept = _entry(thread.id, "same0001", "Original", "2026-10-02T08:00:00+00:00", external_key="ext-1")
    changed = _entry(thread.id, "same0001", "Abweichung", "2026-10-02T08:05:00+00:00", external_key="ext-1")
    other_id = _entry(thread.id, "other0001", "Zweite Fassung", "2026-10-02T09:00:00+00:00", external_key="ext-2")
    twin = _entry(thread.id, "twin000001", "Zweite Fassung", "2026-10-02T09:00:00+00:00", external_key="ext-2")
    _put(left, kept)
    _put(left, other_id)
    _put(right, changed)
    _put(right, twin)

    report = merge_stores(left, right)
    again = merge_stores(left, right)
    entries = left.list_whiteboard(thread.id)
    conflicts = [entry for entry in entries if entry.metadata.get("role") == "merge_conflict"]

    assert report["conflicts"] == 1
    assert report["added"] == 0
    assert again == {"added": 0, "kept": 2, "conflicts": 0}
    assert next(entry.content for entry in entries if entry.id == "same0001") == "Original"
    assert len(conflicts) == 1
    assert conflicts[0].metadata["kept_id"] == "same0001"
    assert any(entry.id == "other0001" and entry.content == "Zweite Fassung" for entry in entries)
    assert not any(entry.id == "twin000001" for entry in entries)


def test_private_entries_do_not_enter_a_room(roots) -> None:
    left, right = roots
    thread = new_thread("Räume")
    left.save_thread(thread)
    right.save_thread(thread)
    private = _entry(thread.id, "private01", "nur hier", "2026-10-02T08:00:00+00:00")
    shared = _entry(thread.id, "shared001", "im Raum", "2026-10-02T09:00:00+00:00", room_id="room-1")
    _put(right, private)
    _put(right, shared)
    merge_stores(left, right)
    entries = left.list_whiteboard(thread.id)
    assert [entry.id for entry in room_entries(entries, "room-1")] == ["shared001"]
    assert all(entry.room_id in {None, "room-1"} for entry in entries)
    assert next(entry.room_id for entry in entries if entry.id == "private01") is None


def test_old_entry_without_merge_fields_stays_readable(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "old")
    thread = new_thread("Bestand")
    store.save_thread(thread)
    payload = {
        "id": "legacy01",
        "thread_id": thread.id,
        "actor": "Mensch",
        "actor_type": "human",
        "created_at": "2026-01-01T00:00:00+00:00",
        "entry_type": "note",
        "content": "ohne neue felder",
        "ordinal": 1,
        "metadata": {},
    }
    store.connection.execute(
        """INSERT INTO whiteboard_entries(
               id, thread_id, created_at, ordinal, external_key, payload
           ) VALUES (?,?,?,?,?,?)""",
        (payload["id"], thread.id, payload["created_at"], 1, None, json.dumps(payload)),
    )
    store.connection.commit()
    loaded = store.list_whiteboard(thread.id)[0]
    assert loaded.content == "ohne neue felder"
    assert loaded.instance_id is None
    assert loaded.room_id is None
    assert loaded.content_hash is None

    fresh = _entry(thread.id, "fresh0001", "mit feldern", "2026-10-02T08:00:00+00:00", instance_id="machine-a")
    _put(store, fresh)
    backup = WorkspaceBackup(tmp_path / "backups").create(store)
    restored_root = tmp_path / "restored"
    WorkspaceBackup(tmp_path / "backups").restore_verified(backup, restored_root)
    restored = SQLiteStore(restored_root)
    again = {entry.id: entry for entry in restored.list_whiteboard(thread.id)}
    assert again["legacy01"].content == "ohne neue felder"
    assert again["fresh0001"].instance_id == "machine-a"
    assert ThreadService(store=restored).get(thread.id).title == "Bestand"
