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
        actor_id=extra.pop("actor_id", None),
        task_id=extra.pop("task_id", None),
        handoff_id=extra.pop("handoff_id", None),
        run_id=extra.pop("run_id", None),
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
    merged = left.list_whiteboard(thread.id)
    second = merge_stores(left, right)
    again = left.list_whiteboard(thread.id)

    assert first == {"added": 1, "kept": 0, "conflicts": 1}
    assert second == {"added": 0, "kept": 1, "conflicts": 0}
    assert len(again) == len(merged)
    own = [entry for entry in again if entry.metadata.get("role") != "merge_conflict"]
    assert [entry.content for entry in own] == ["zuerst", "danach"]
    assert [entry.id for entry in own] == ["early01", "later01"]
    assert left.get_thread(thread.id).context.notes == "Notiz auf diesem Rechner"
    notes = [entry for entry in again if entry.metadata.get("field") == "notes"]
    assert len(notes) == 1
    assert notes[0].content == "Andere Notiz"
    assert notes[0].metadata["kept_text"] == "Notiz auf diesem Rechner"
    assert notes[0].metadata["incoming_text"] == "Andere Notiz"
    assert notes[0].metadata["role"] == "merge_conflict"
    assert notes[0].metadata["origin"] == "thread-notes"
    assert notes[0].metadata["kept_id"] == thread.id
    assert notes[0].metadata["kept_hash"] != notes[0].metadata["incoming_hash"]
    assert left.get_thread(other.id).title == "Nur rechts"
    assert right.get_thread(thread.id).context.notes == "Andere Notiz"


def test_divergent_copies_stay_and_record_one_conflict(roots) -> None:
    left, right = roots
    thread = new_thread("Konflikt")
    left.save_thread(thread)
    right.save_thread(thread)
    kept = _entry(
        thread.id, "same0001", "Original", "2026-10-02T08:00:00+00:00",
        external_key="ext-1", actor_id="actor-a", task_id="task-1", instance_id="machine-a",
    )
    changed = _entry(
        thread.id, "same0001", "Abweichung", "2026-10-02T08:05:00+00:00",
        external_key="ext-1", actor_id="actor-b", task_id="task-9", instance_id="machine-b",
    )
    other_id = _entry(thread.id, "other0001", "Zweite Fassung", "2026-10-02T09:00:00+00:00", external_key="ext-2")
    twin = _entry(thread.id, "twin000001", "Zweite Fassung", "2026-10-02T09:00:00+00:00", external_key="ext-2")
    _put(left, kept)
    _put(left, other_id)
    _put(right, changed)
    _put(right, twin)

    before = len(left.list_whiteboard(thread.id))
    report = merge_stores(left, right)
    entries = left.list_whiteboard(thread.id)
    again = merge_stores(left, right)
    repeated = left.list_whiteboard(thread.id)
    conflicts = [entry for entry in repeated if entry.metadata.get("field") != "notes" and entry.metadata.get("role") == "merge_conflict"]

    assert report["conflicts"] == 1
    assert report["added"] == 0
    assert again == {"added": 0, "kept": 2, "conflicts": 0}
    assert len(repeated) == len(entries) == before + 1
    assert next(entry.content for entry in repeated if entry.id == "same0001") == "Original"
    assert len(conflicts) == 1
    conflict = conflicts[0]
    incoming = conflict.metadata["incoming"]
    assert conflict.content == "Abweichung"
    assert conflict.actor_id == "actor-b"
    assert conflict.task_id == "task-9"
    assert conflict.instance_id == "machine-b"
    assert conflict.created_at == "2026-10-02T08:05:00+00:00"
    assert conflict.room_id is None
    assert conflict.metadata["role"] == "merge_conflict"
    assert conflict.metadata["kept_id"] == "same0001"
    assert conflict.metadata["incoming_id"] == "same0001"
    assert conflict.metadata["actor_id"] == "actor-b"
    assert conflict.metadata["task_id"] == "task-9"
    assert conflict.metadata["instance_id"] == "machine-b"
    assert conflict.metadata["created_at"] == "2026-10-02T08:05:00+00:00"
    assert conflict.metadata["origin"] == "machine-b"
    assert conflict.metadata["kept_hash"] != conflict.metadata["incoming_hash"]
    assert incoming["content"] == "Abweichung"
    assert incoming["id"] == "same0001"
    assert incoming["actor_id"] == "actor-b"
    assert incoming["task_id"] == "task-9"
    assert incoming["instance_id"] == "machine-b"
    assert incoming["created_at"] == "2026-10-02T08:05:00+00:00"
    assert any(entry.id == "other0001" and entry.content == "Zweite Fassung" for entry in repeated)
    assert not any(entry.id == "twin000001" for entry in repeated)


def test_same_external_key_keeps_the_incoming_body(roots) -> None:
    left, right = roots
    thread = new_thread("Schlüssel")
    left.save_thread(thread)
    right.save_thread(thread)
    _put(left, _entry(
        thread.id, "left000001", "Links", "2026-10-02T08:00:00+00:00",
        external_key="ext-x", actor_id="actor-a", instance_id="machine-a",
    ))
    _put(right, _entry(
        thread.id, "right00001", "Rechts", "2026-10-02T08:05:00+00:00",
        external_key="ext-x", actor_id="actor-b", task_id="task-2", instance_id="machine-b",
    ))

    first = merge_stores(left, right)
    count = len(left.list_whiteboard(thread.id))
    second = merge_stores(left, right)
    entries = left.list_whiteboard(thread.id)
    conflict = next(entry for entry in entries if entry.metadata.get("role") == "merge_conflict")

    assert first == {"added": 0, "kept": 0, "conflicts": 1}
    assert second == {"added": 0, "kept": 1, "conflicts": 0}
    assert len(entries) == count
    assert next(entry.content for entry in entries if entry.id == "left000001") == "Links"
    assert not any(entry.id == "right00001" for entry in entries)
    assert conflict.content == "Rechts"
    assert conflict.metadata["incoming"]["id"] == "right00001"
    assert conflict.metadata["incoming"]["content"] == "Rechts"
    assert conflict.metadata["incoming"]["task_id"] == "task-2"
    assert conflict.actor_id == "actor-b"
    assert conflict.instance_id == "machine-b"


def test_different_description_is_kept_beside_the_original(roots) -> None:
    left, right = roots
    thread = new_thread("Beschreibung", "Stand A")
    left.save_thread(thread)
    right.save_thread(thread)
    stored = right.get_thread(thread.id)
    stored.description = "Stand B"
    right.save_thread(stored)

    merge_stores(left, right)
    size = len(left.list_whiteboard(thread.id))
    merge_stores(left, right)
    entries = left.list_whiteboard(thread.id)
    conflict = next(entry for entry in entries if entry.metadata.get("field") == "description")

    assert left.get_thread(thread.id).description == "Stand A"
    assert right.get_thread(thread.id).description == "Stand B"
    assert len(entries) == size
    assert conflict.content == "Stand B"
    assert conflict.metadata["kept_text"] == "Stand A"
    assert conflict.metadata["role"] == "merge_conflict"
    assert conflict.metadata["origin"] == "thread-description"


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

    json_store = JsonStore(tmp_path / "json-old")
    json_store.save_thread(thread)
    folder = json_store.whiteboard_dir / thread.id
    folder.mkdir(parents=True)
    (folder / "legacy01.json").write_text(json.dumps(payload), encoding="utf-8")
    from_json = json_store.list_whiteboard(thread.id)[0]
    assert from_json.content == "ohne neue felder"
    assert from_json.instance_id is None
    assert from_json.room_id is None
    assert from_json.content_hash is None
    other = SQLiteStore(tmp_path / "merged-old")
    merge_stores(other, store)
    moved = {entry.id: entry for entry in other.list_whiteboard(thread.id)}
    assert moved["legacy01"].content == "ohne neue felder"
    assert moved["legacy01"].instance_id is None
    assert moved["legacy01"].room_id is None

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
