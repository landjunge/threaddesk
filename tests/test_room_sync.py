"""Two local desks share one room and nothing private."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import InvalidState
from threaddesk.core.models import WhiteboardEntry, new_thread
from threaddesk.services.room_sync import RoomBook, RoomDown, local_base_url
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore

A_URL = "http://127.0.0.1:8765"
B_URL = "http://127.0.0.1:8766"


def _pipe(books: dict[str, RoomBook], origin: str):
    def transport(url: str, payload: dict, headers: dict) -> dict:
        target = books["b" if origin == "a" else "a"]
        path = urlparse(url).path
        instance = headers.get("X-ThreadDesk-Instance", "")
        token = headers.get("X-ThreadDesk-Token", "")
        if path.endswith("/pair"):
            return target.accept(payload["code"], payload["instance_id"], payload["base_url"])
        if path.endswith("/pull"):
            return target.serve_pull(instance, token, payload["room_id"])
        if path.endswith("/push"):
            return target.serve_push(instance, token, payload)
        raise AssertionError(path)

    return transport


def _books(left, right) -> dict[str, RoomBook]:
    books: dict[str, RoomBook] = {}
    books["a"] = RoomBook(left, transport=_pipe(books, "a"))
    books["b"] = RoomBook(right, transport=_pipe(books, "b"))
    return books


def _pair(books: dict[str, RoomBook], role: str = "member") -> str:
    room = books["a"].create_room("Werkstatt")
    code = books["a"].invite(role)
    books["b"].join(code, A_URL, B_URL)
    return room["id"]


def _entry(thread_id: str, entry_id: str, content: str, room_id: str | None, **extra) -> WhiteboardEntry:
    return WhiteboardEntry(
        id=entry_id,
        thread_id=thread_id,
        actor=extra.pop("actor", "Ada"),
        actor_type=extra.pop("actor_type", "human"),
        created_at=extra.pop("created_at", "2026-10-02T08:00:00+00:00"),
        entry_type="note",
        content=content,
        external_key=extra.pop("external_key", None),
        actor_id=extra.pop("actor_id", None),
        task_id=extra.pop("task_id", None),
        instance_id=extra.pop("instance_id", None),
        room_id=room_id,
    )


def _texts(store, thread_id: str) -> list[str]:
    try:
        entries = store.list_whiteboard(thread_id)
    except Exception:
        return []
    return [entry.content for entry in entries]


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def desks(request, tmp_path: Path):
    left = request.param(tmp_path / "a")
    right = request.param(tmp_path / "b")
    return left, right


def test_instance_id_is_stable_and_different_per_desk(desks) -> None:
    left, right = desks
    first = RoomBook(left).instance_id()
    assert RoomBook(left).instance_id() == first
    assert RoomBook(right).instance_id() not in {"", first}


def test_local_addresses_only() -> None:
    assert local_base_url("http://127.0.0.1:8765") == "http://127.0.0.1:8765"
    assert local_base_url("http://192.168.1.20:8765/") == "http://192.168.1.20:8765"
    with pytest.raises(InvalidState, match="room_address"):
        local_base_url("http://8.8.8.8:8765")
    with pytest.raises(InvalidState, match="room_address"):
        local_base_url("https://127.0.0.1:8765")


def test_pairing_needs_consent_and_blocks_strangers(desks) -> None:
    left, right = desks
    books = _books(left, right)
    room_id = _pair(books)
    with pytest.raises(InvalidState, match="room_forbidden"):
        books["a"].serve_pull("not-a-peer", "no-token", room_id)
    with pytest.raises(InvalidState, match="room_forbidden"):
        books["b"].join("falscher-code", A_URL, B_URL)
    assert books["a"].view()["current"]["id"] == room_id
    assert {item["instance_id"] for item in books["b"].view()["current"]["members"]} == {
        books["a"].instance_id(),
        books["b"].instance_id(),
    }


def test_only_the_room_moves_and_both_directions_stay_idempotent(desks) -> None:
    left, right = desks
    books = _books(left, right)
    room_id = _pair(books)
    thread = new_thread("Gemeinsam")
    thread.context.notes = "Nur auf A"
    left.save_thread(thread)
    private = _entry(thread.id, "private01", "nur privat", None, instance_id="local-a")
    shared = _entry(
        thread.id, "shared001", "von A", room_id,
        actor_id="actor-a", task_id="task-1", instance_id=books["a"].instance_id(),
    )
    house = _entry(
        thread.id, "house0001", "Zusammenfassung", room_id,
        actor="Hausmeister", actor_type="local-assistant", actor_id="haus-1",
        instance_id=books["a"].instance_id(), created_at="2026-10-02T09:00:00+00:00",
    )
    loose = _entry(
        thread.id, "legacy001", "ohne instanz", room_id,
        created_at="2026-10-02T07:00:00+00:00",
    )
    for entry in (private, shared, house, loose):
        left.append_whiteboard_entry(entry)
    left.write_json_artifact("hausmeister.json", {"version": 1, "model": "demo"})

    first = books["a"].sync()
    assert first["ok"] is True
    assert left.get_thread(thread.id).context.notes == "Nur auf A"
    arrived = {item.id: item for item in right.list_whiteboard(thread.id)}
    assert right.get_thread(thread.id).context.notes == ""
    assert "nur privat" not in _texts(right, thread.id)
    assert arrived["shared001"].content == "von A"
    assert arrived["shared001"].actor_id == "actor-a"
    assert arrived["shared001"].task_id == "task-1"
    assert arrived["shared001"].instance_id == books["a"].instance_id()
    assert arrived["house0001"].actor_type == "local-assistant"
    assert arrived["house0001"].actor_id == "haus-1"
    assert arrived["house0001"].instance_id == books["a"].instance_id()
    assert arrived["legacy001"].content == "ohne instanz"
    assert arrived["legacy001"].instance_id is None
    assert not right.artifact_path("hausmeister.json").exists()

    back = new_thread("Antwort")
    right.save_thread(back)
    back_entry = _entry(
        back.id, "back000001", "von B", room_id,
        actor_id="actor-b", instance_id=books["b"].instance_id(),
    )
    right.append_whiteboard_entry(back_entry)
    assert books["b"].sync()["ok"] is True
    echoed = {item.id: item for item in left.list_whiteboard(back.id)}
    assert echoed["back000001"].content == "von B"
    assert echoed["back000001"].actor_id == "actor-b"
    assert echoed["back000001"].instance_id == books["b"].instance_id()
    assert left.get_thread(thread.id).context.notes == "Nur auf A"

    again = books["a"].sync()
    third = books["a"].sync()
    assert again["conflicts"] == 0
    assert third == {"ok": True, "state": "synced", "conflicts": 0}
    assert _texts(right, thread.id).count("von A") == 1
    assert _texts(left, back.id).count("von B") == 1


def test_conflict_keeps_both_versions_and_offline_recovers(desks) -> None:
    left, right = desks
    books = _books(left, right)
    room_id = _pair(books)
    thread = new_thread("Streit")
    left.save_thread(thread)
    right.save_thread(thread)
    right.get_thread(thread.id)
    stored = right.get_thread(thread.id)
    stored.context.notes = "Notiz auf B"
    right.save_thread(stored)
    left.append_whiteboard_entry(_entry(
        thread.id, "same000001", "Fassung A", room_id, instance_id=books["a"].instance_id(), actor_id="actor-a",
    ))
    right.append_whiteboard_entry(_entry(
        thread.id, "same000001", "Fassung B", room_id, instance_id=books["b"].instance_id(), actor_id="actor-b",
    ))

    books["a"].transport = lambda *_args, **_kwargs: (_ for _ in ()).throw(RoomDown("room_offline"))
    failed = books["a"].sync()
    assert failed["state"] == "peer_down"
    assert _texts(left, thread.id) == ["Fassung A"]
    assert _texts(right, thread.id) == ["Fassung B"]
    assert right.get_thread(thread.id).context.notes == "Notiz auf B"

    books["a"].transport = _pipe(books, "a")
    later = _entry(thread.id, "later0001", "nach der Pause", room_id, instance_id=books["a"].instance_id())
    left.append_whiteboard_entry(later)
    report = books["a"].sync()
    books["b"].sync()
    books["a"].sync()
    quiet = books["b"].sync()
    left_text = " ".join(_texts(left, thread.id))
    right_text = " ".join(_texts(right, thread.id))
    assert "Fassung A" in left_text and "Fassung B" in left_text
    assert "Fassung A" in right_text and "Fassung B" in right_text
    assert "nach der Pause" in right_text
    assert report["conflicts"] >= 1
    size_left = len(left.list_whiteboard(thread.id))
    size_right = len(right.list_whiteboard(thread.id))
    assert quiet["conflicts"] == 0
    assert books["a"].sync()["conflicts"] == 0
    assert len(left.list_whiteboard(thread.id)) == size_left
    assert len(right.list_whiteboard(thread.id)) == size_right
    assert right.get_thread(thread.id).context.notes == "Notiz auf B"
    assert left.get_thread(thread.id).context.notes == ""


def test_read_only_can_receive_but_not_publish(desks) -> None:
    left, right = desks
    books = _books(left, right)
    room_id = _pair(books, role="read_only")
    thread = new_thread("Lesen")
    left.save_thread(thread)
    own = new_thread("Eigen")
    right.save_thread(own)
    left.append_whiteboard_entry(_entry(thread.id, "owner0001", "fuer alle", room_id))
    right.append_whiteboard_entry(_entry(own.id, "guest0001", "nicht senden", room_id))
    assert books["b"].view()["role"] == "read_only"
    books["a"].sync()
    assert "fuer alle" in _texts(right, thread.id)
    owned = " ".join(
        entry.content
        for item in left.list_threads(include_archived=True)
        for entry in left.list_whiteboard(item.id)
    )
    assert "nicht senden" not in owned
    with pytest.raises(InvalidState, match="room_forbidden"):
        books["a"].serve_push(
            books["b"].instance_id(),
            books["a"]._peers_for(room_id)[0]["token"],
            {
                "schema": "threaddesk.room.v1",
                "room_id": room_id,
                "instance_id": books["b"].instance_id(),
                "entries": [{
                    "id": "guest0001",
                    "thread_id": own.id,
                    "actor": "B",
                    "actor_type": "human",
                    "created_at": "2026-10-02T08:00:00+00:00",
                    "entry_type": "note",
                    "content": "nicht senden",
                    "room_id": room_id,
                    "metadata": {},
                }],
                "threads": [{"id": own.id, "title": "Eigen"}],
            },
        )
    assert "nicht senden" not in " ".join(
        entry.content
        for item in left.list_threads(include_archived=True)
        for entry in left.list_whiteboard(item.id)
    )


def test_unpaired_http_route_returns_no_room_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from threaddesk.ui.server import create_app

    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    client = TestClient(create_app())
    secret = "nur-lokal-bleiben"
    response = client.post("/api/rooms/push", json={
        "schema": "threaddesk.room.v1",
        "room_id": "room-1",
        "entries": [{"content": secret}],
    })
    assert response.status_code == 403
    assert secret not in response.text
    assert response.json() == {"ok": False}
