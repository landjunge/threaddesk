"""Append-only whiteboard on the thread that already exists."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import InvalidState, NotFound, SecretRejected
from threaddesk.core.models import ACTOR_TYPES, new_thread
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.schema import ARTIFACTS_SQL, SOURCE_RECORDS_SQL, V1_SCHEMA_SQL
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def svc(request: pytest.FixtureRequest, tmp_path: Path) -> ThreadService:
    return ThreadService(store=request.param(tmp_path))


def _add(svc: ThreadService, thread_id: str, content: str, **extra) -> dict:
    fields = {
        "actor": extra.pop("actor", "Mensch"),
        "actor_type": extra.pop("actor_type", "human"),
        "entry_type": extra.pop("entry_type", "note"),
        "content": content,
    }
    fields.update(extra)
    return svc.append_whiteboard(thread_id, **fields)


def test_append_keeps_order_actors_and_old_entries(svc: ThreadService) -> None:
    thread = svc.create("Projektakte")
    svc.set_note("alte notiz")
    first = _add(svc, thread.id, "Architektur geprüft.", actor="ChatGPT", actor_type="chatgpt")
    second = _add(
        svc,
        thread.id,
        "Rückkanal geprüft.",
        actor="Grok",
        actor_type="grok",
        entry_type="progress",
        metadata={"next_step": "Rückkanal testen"},
    )

    entries = svc.whiteboard(thread.id)
    assert [entry.content for entry in entries] == [
        "Architektur geprüft.",
        "Rückkanal geprüft.",
    ]
    assert entries[0].to_dict() == first["entry"]
    assert entries[0].id != entries[1].id
    assert entries[1].metadata["next_step"] == "Rückkanal testen"
    assert svc.get(thread.id).context.notes == "alte notiz"
    assert second["duplicate"] is False

    for actor_type in ACTOR_TYPES:
        added = _add(
            svc,
            thread.id,
            f"von {actor_type}",
            actor=actor_type,
            actor_type=actor_type,
        )
        assert added["entry"]["actor_type"] == actor_type

    with pytest.raises(InvalidState, match="whiteboard_actor_type"):
        _add(svc, thread.id, "nein", actor_type="stranger")
    with pytest.raises(NotFound):
        _add(svc, "missing-thread", "nein")

    again = svc.whiteboard(thread.id)
    assert again[0].to_dict() == first["entry"]
    assert again[1].content == "Rückkanal geprüft."


def test_external_return_is_idempotent_and_does_not_overwrite(svc: ThreadService) -> None:
    thread = svc.create("Rücklauf")
    first = _add(svc, thread.id, "fertig", external_key="ext-1", entry_type="result")
    again = _add(svc, thread.id, "fertig", external_key="ext-1", entry_type="result")
    assert again["duplicate"] is True
    assert again["entry"]["id"] == first["entry"]["id"]
    assert len(svc.whiteboard(thread.id)) == 1

    with pytest.raises(InvalidState, match="whiteboard_conflict"):
        _add(svc, thread.id, "anders", external_key="ext-1", entry_type="result")
    assert svc.whiteboard(thread.id)[0].content == "fertig"


def test_json_file_is_not_rewritten_on_duplicate(tmp_path: Path) -> None:
    svc = ThreadService(store=JsonStore(tmp_path))
    thread = svc.create("Datei")
    first = _add(svc, thread.id, "bleib stehen", external_key="ext-datei")
    path = tmp_path / "whiteboard" / thread.id / f"{first['entry']['id']}.json"
    before = path.read_bytes()

    _add(svc, thread.id, "bleib stehen", external_key="ext-datei")

    assert path.read_bytes() == before
    assert list((tmp_path / "whiteboard" / thread.id).glob("*.json")) == [path]


def test_reload_keeps_whiteboard_and_notes(svc: ThreadService, tmp_path: Path) -> None:
    thread = svc.create("Bleibt")
    svc.set_note("Notiz bleibt")
    _add(svc, thread.id, "erster")
    _add(svc, thread.id, "zweiter", actor="Claude", actor_type="claude", entry_type="progress")
    store_type = type(svc.store)

    reopened = ThreadService(store=store_type(tmp_path))
    restored = reopened.whiteboard(thread.id)
    assert [entry.content for entry in restored] == ["erster", "zweiter"]
    assert restored[1].actor_type == "claude"
    assert reopened.get(thread.id).context.notes == "Notiz bleibt"


def test_snapshot_restore_does_not_touch_the_whiteboard(svc: ThreadService) -> None:
    thread = svc.create("Snapshot")
    svc.set_note("vor dem Snapshot")
    _add(svc, thread.id, "vor dem Snapshot")
    snap = svc.snapshot("Stand", thread.id)
    svc.set_note("danach")
    _add(svc, thread.id, "nach dem Snapshot")

    restored = svc.restore(snap.id)

    assert restored.context.notes == "vor dem Snapshot"
    assert [entry.content for entry in svc.whiteboard(thread.id)] == [
        "vor dem Snapshot",
        "nach dem Snapshot",
    ]


def test_thread_without_whiteboard_still_opens(svc: ThreadService) -> None:
    bare = new_thread("Ohne Verlauf")
    bare.context.notes = "nur eine Notiz"
    svc.store.save_thread(bare)

    assert svc.whiteboard(bare.id) == []
    assert svc.get(bare.id).context.notes == "nur eine Notiz"
    stand = svc.working_stand(bare.id)
    assert stand["entry_count"] == 0
    assert stand["last_stand"] == "nur eine Notiz"


def test_secrets_and_path_fields_stay_rejected(svc: ThreadService) -> None:
    thread = svc.create("Geheim")
    with pytest.raises(SecretRejected):
        _add(svc, thread.id, "api_key=abcdefghijklmnopqrstuvwxyz")
    assert svc.whiteboard(thread.id) == []


def test_gnom_callback_returns_to_the_same_thread(svc: ThreadService, tmp_path: Path) -> None:
    origin = svc.create("Ursprung")
    other = svc.create("Daneben")
    svc.switch(origin.id)
    svc.set_note("Kontext bleibt")
    packet = svc.gnom()
    svc.bind_gnom_job("job-42", packet)
    handoff = packet["handoff"]
    started = {
        "format": "threaddesk.gnom-callback.v1",
        "event_id": "e-start",
        "job_id": "job-42",
        "handoff_revision": handoff["revision"],
        "status": "started",
        "occurred_at": "2026-10-02T08:40:00+00:00",
        "details": "Arbeit übernommen.",
    }
    delivered = {
        "format": "threaddesk.gnom-callback.v1",
        "event_id": "e-done",
        "job_id": "job-42",
        "handoff_revision": handoff["revision"],
        "status": "delivered",
        "occurred_at": "2026-10-02T08:55:00+00:00",
        "result": "Aufgabe erledigt",
        "artifacts": ["src/app.py", "tests/test_app.py"],
        "test_results": ["3 passed"],
        "open_issues": ["ein offenes Problem"],
        "pull_request": "https://example.local/pr/9",
    }

    svc.receive_gnom_callback(started)
    first = svc.receive_gnom_callback(delivered)
    again = svc.receive_gnom_callback(delivered)

    entries = svc.whiteboard(origin.id)
    assert [entry.entry_type for entry in entries] == ["claimed", "result"]
    result = entries[1]
    assert result.thread_id == origin.id
    assert result.task_id == handoff["task_id"]
    assert result.handoff_id == handoff["handoff_id"]
    assert result.run_id == "job-42"
    assert result.actor_type == "gnom-hub-v1"
    assert "Aufgabe erledigt" in result.content
    assert "src/app.py" in result.content
    assert "3 passed" in result.content
    assert "ein offenes Problem" in result.content
    assert "https://example.local/pr/9" in result.content
    assert again["return"]["duplicate"] is True
    assert again["whiteboard"]["duplicate"] is True
    assert len(svc.returns()) == 1
    assert svc.returns()[0]["return"]["review_status"] == "unverified"
    assert svc.whiteboard(other.id) == []
    assert svc.get(origin.id).context.notes == "Kontext bleibt"
    assert first["return"]["return"]["thread_id"] == origin.id

    store_type = type(svc.store)
    reopened = ThreadService(store=store_type(tmp_path))
    kept = reopened.whiteboard(origin.id)
    assert [entry.id for entry in kept] == [entry.id for entry in entries]
    assert kept[1].handoff_id == handoff["handoff_id"]
    assert len(reopened.returns()) == 1

    follow = reopened.handoff(origin.id)
    assert follow["thread_id"] == origin.id
    assert follow["context"]["notes"] == "Kontext bleibt"
    assert [item["id"] for item in follow["context"]["whiteboard"]] == [
        entry.id for entry in entries
    ]


def test_return_inbox_still_accepts_a_direct_return(svc: ThreadService) -> None:
    thread = svc.create("Direkt")
    from threaddesk.services.return_contract import build

    payload = build(
        handoff_id="h-direct",
        handoff_revision=1,
        thread_id=thread.id,
        task_id="task-direct",
        worker="grok",
        run_id="run-direct",
        result="Grok ist fertig",
    )
    first = svc.receive_return(payload)
    second = svc.receive_return(payload)

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert len(svc.returns()) == 1
    entries = svc.whiteboard(thread.id)
    assert len(entries) == 1
    assert entries[0].actor_type == "grok"
    assert entries[0].task_id == "task-direct"
    assert entries[0].handoff_id == "h-direct"
    assert entries[0].run_id == "run-direct"
    assert second["whiteboard"]["entry"]["id"] == entries[0].id


def test_sqlite_v3_threads_survive_and_can_take_entries(tmp_path: Path) -> None:
    database = tmp_path / "threaddesk.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(V1_SCHEMA_SQL + SOURCE_RECORDS_SQL + ARTIFACTS_SQL)
    connection.execute("INSERT INTO schema_info(version) VALUES (3)")
    thread = new_thread("Bestand")
    thread.context.notes = "alte notiz"
    connection.execute(
        "INSERT INTO threads(id, status, updated_at, payload) VALUES (?,?,?,?)",
        (
            thread.id,
            thread.status,
            thread.updated_at,
            json.dumps(thread.to_dict(), ensure_ascii=False, sort_keys=True),
        ),
    )
    connection.commit()
    connection.close()

    store = SQLiteStore(tmp_path)
    version = store.connection.execute("SELECT version FROM schema_info").fetchone()[0]
    assert version == 4
    assert store.get_thread(thread.id).context.notes == "alte notiz"
    assert store.list_whiteboard(thread.id) == []

    svc = ThreadService(store=store)
    _add(svc, thread.id, "nach der Migration")
    assert svc.whiteboard(thread.id)[0].content == "nach der Migration"
    assert svc.get(thread.id).context.notes == "alte notiz"


def test_api_reads_and_appends_without_leaving_the_thread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from threaddesk.ui.server import create_app

    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    monkeypatch.delenv("THREADDESK_STORAGE", raising=False)
    svc = ThreadService(store=JsonStore(tmp_path))
    thread = svc.create("API")
    svc.set_note("sichtbare notiz")
    client = TestClient(create_app())

    loaded = client.get(f"/api/threads/{thread.id}")
    assert loaded.status_code == 200
    assert loaded.json()["thread"]["context"]["notes"] == "sichtbare notiz"
    assert loaded.json()["stand"]["entry_count"] == 0

    rejected = client.post(
        "/api/threads/does-not-exist/whiteboard",
        json={
            "actor": "Mensch",
            "actor_type": "human",
            "entry_type": "note",
            "content": "nein",
        },
    )
    assert rejected.status_code == 404

    leaked = client.post(
        f"/api/threads/{thread.id}/whiteboard",
        json={
            "actor": "Mensch",
            "actor_type": "human",
            "entry_type": "note",
            "content": "nein",
            "path": "/etc/passwd",
        },
    )
    assert leaked.status_code == 400
    secret = client.post(
        f"/api/threads/{thread.id}/whiteboard",
        json={
            "actor": "Mensch",
            "actor_type": "human",
            "entry_type": "note",
            "content": "token=supersecrettokenvalue",
        },
    )
    assert secret.status_code == 400

    created = client.post(
        f"/api/threads/{thread.id}/whiteboard",
        json={
            "actor": "Codex",
            "actor_type": "codex",
            "entry_type": "progress",
            "content": "API-Beitrag",
            "task_id": "task-api",
            "handoff_id": "hand-api",
            "run_id": "run-api",
            "metadata": {"next_step": "im Thread bleiben"},
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["duplicate"] is False
    assert body["entry"]["thread_id"] == thread.id
    assert body["entry"]["task_id"] == "task-api"

    listed = client.get(f"/api/threads/{thread.id}/whiteboard")
    assert [entry["content"] for entry in listed.json()["entries"]] == ["API-Beitrag"]
    stand = client.get(f"/api/threads/{thread.id}/stand")
    assert stand.json()["next_step"] == "im Thread bleiben"
    assert stand.json()["actor"] == "Codex"
    page = client.get("/")
    assert "API-Beitrag" in page.text
    assert "sichtbare notiz" in page.text


def test_api_sqlite_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from threaddesk.ui.server import create_app

    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    monkeypatch.setenv("THREADDESK_STORAGE", "sqlite")
    thread = ThreadService(store=SQLiteStore(tmp_path)).create("SQLite API")
    client = TestClient(create_app())
    created = client.post(
        f"/api/threads/{thread.id}/whiteboard",
        json={
            "actor": "Mensch",
            "actor_type": "human",
            "entry_type": "note",
            "content": "sqlite bleibt",
            "external_key": "sql-1",
        },
    )
    assert created.status_code == 200
    duplicate = client.post(
        f"/api/threads/{thread.id}/whiteboard",
        json={
            "actor": "Mensch",
            "actor_type": "human",
            "entry_type": "note",
            "content": "sqlite bleibt",
            "external_key": "sql-1",
        },
    )
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["entry"]["id"] == created.json()["entry"]["id"]

    reopened = ThreadService(store=SQLiteStore(tmp_path))
    assert [entry.content for entry in reopened.whiteboard(thread.id)] == ["sqlite bleibt"]
