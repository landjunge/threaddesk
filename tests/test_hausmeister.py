"""The local housekeeper appends its own notes and stays on the machine."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import InvalidState, SecretRejected
from threaddesk.services.hausmeister import (
    ACTIVITY_GAP_SECONDS,
    Hausmeister,
    IdleSnapshot,
    activity_is_due,
    live_snapshot,
    note_activity,
)
from threaddesk.services.ollama_local import OllamaError, default_transport, local_url
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


def _transport(models: list[str], reply: dict | str):
    def call(url: str, body=None, timeout: float = 0.4):
        assert url.startswith("http://127.0.0.1:11434/")
        assert "/api/pull" not in url
        if url.endswith("/api/tags"):
            return {"models": [{"name": name} for name in models]}
        text = reply if isinstance(reply, str) else json.dumps(reply)
        return {"message": {"content": text}}

    return call


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def svc(request, tmp_path: Path) -> ThreadService:
    return ThreadService(store=request.param(tmp_path))


def test_local_ollama_urls_never_leave_the_machine() -> None:
    assert local_url("/api/tags") == "http://127.0.0.1:11434/api/tags"
    assert local_url("/api/chat") == "http://127.0.0.1:11434/api/chat"
    with pytest.raises(OllamaError, match="ollama_forbidden"):
        local_url("/api/pull")
    with pytest.raises(OllamaError, match="ollama_forbidden"):
        default_transport("http://example.com/api/tags", None)


def test_agent_id_stays_and_is_not_system(svc: ThreadService, tmp_path: Path) -> None:
    home = Hausmeister(svc.store, _transport(["demo"], {"summary": "x", "suggestions": []}))
    person = svc.register_human("Ada", "plum")
    home.set_enabled(True)
    actor = home.ensure_actor()

    assert actor["kind"] == "agent"
    assert actor["agent_type"] == "local-assistant"
    assert actor["agent_type"] != "system"
    assert actor["person_id"] == person["id"]

    again = Hausmeister(type(svc.store)(tmp_path), _transport(["demo"], {"summary": "x"}))
    kept = again.ensure_actor()
    assert kept["id"] == actor["id"]
    assert kept["kind"] == "agent"


def test_job_appends_several_notes_without_touching_the_original(svc: ThreadService, tmp_path: Path) -> None:
    thread = svc.create("Aufräumen")
    svc.set_note("Benutzertext bleibt.")
    user = svc.append_whiteboard(
        thread.id,
        actor="Ada",
        actor_type="human",
        entry_type="note",
        content="Original bleibt stehen.",
        task_id="task-haus",
    )
    if isinstance(svc.store, JsonStore):
        original_path = tmp_path / "whiteboard" / thread.id / f"{user['entry']['id']}.json"
        before = original_path.read_bytes()
    else:
        before = svc.store.connection.execute(
            "SELECT payload FROM whiteboard_entries WHERE id = ?",
            (user["entry"]["id"],),
        ).fetchone()[0]
    note_before = svc.get(thread.id).context.notes

    home = Hausmeister(svc.store, _transport(["demo"], {
        "summary": "Der Stand ist aufgeräumt.",
        "suggestions": ["Nächsten Schritt notieren"],
    }))
    home.set_enabled(True)
    home.set_model("demo")
    result = home.run(thread.id, "Räum diesen Thread auf und fasse den Stand zusammen")

    assert result["ok"] is True
    assert len(result["entries"]) == 3
    assert {item["metadata"]["role"] for item in result["entries"]} == {"summary", "suggestion", "note"}
    assert {item["actor_id"] for item in result["entries"]} == {result["actor_id"]}
    assert {item["actor_type"] for item in result["entries"]} == {"local-assistant"}
    assert all(item["task_id"] == "task-haus" for item in result["entries"])
    assert "system" not in {item["actor_type"] for item in result["entries"]}
    entries = svc.whiteboard(thread.id)
    assert entries[0].content == "Original bleibt stehen."
    assert entries[0].actor_type == "human"
    assert svc.get(thread.id).context.notes == note_before
    if isinstance(svc.store, JsonStore):
        assert original_path.read_bytes() == before
    else:
        payload = svc.store.connection.execute(
            "SELECT payload FROM whiteboard_entries WHERE id = ?",
            (user["entry"]["id"],),
        ).fetchone()[0]
        assert payload == before


def test_disabled_housekeeper_does_not_call_ollama(svc: ThreadService) -> None:
    thread = svc.create("Still")
    called = []

    def transport(url, body=None, timeout=0.4):
        called.append(url)
        raise AssertionError(url)

    result = Hausmeister(svc.store, transport).run(thread.id, "Fasse zusammen")
    assert result["ok"] is False
    assert result["error"] == "module_disabled"
    assert called == []
    assert svc.whiteboard(thread.id) == []


def test_missing_ollama_and_missing_model_stay_quiet(svc: ThreadService) -> None:
    thread = svc.create("Leer")
    down = Hausmeister(svc.store, lambda *args, **kwargs: (_ for _ in ()).throw(OllamaError("ollama_unavailable")))
    down.set_enabled(True)
    down.store.write_json_artifact("hausmeister.json", {"version": 1, "model": "demo"})
    missing_runtime = down.run(thread.id, "Fasse zusammen")
    assert missing_runtime["error"] == "ollama_unavailable"
    assert svc.whiteboard(thread.id) == []

    home = Hausmeister(svc.store, _transport(["other"], {"summary": "nein"}))
    home.set_enabled(True)
    with pytest.raises(OllamaError, match="ollama_model_missing"):
        home.set_model("demo")
    home.store.write_json_artifact("hausmeister.json", {"version": 1, "model": "demo"})
    refused = home.run(thread.id, "Fasse zusammen")
    assert refused["error"] == "ollama_model_missing"
    assert svc.whiteboard(thread.id) == []


def _quiet() -> IdleSnapshot:
    return IdleSnapshot(idle_seconds=601, user_active=False, load=0.2)


def _busy() -> IdleSnapshot:
    return IdleSnapshot(idle_seconds=5, user_active=True, load=0.2)


def _heavy() -> IdleSnapshot:
    return IdleSnapshot(idle_seconds=601, user_active=False, load=4.0)


def test_manual_start_ignores_idle_and_blocks_a_later_automatic_run(svc: ThreadService, tmp_path: Path) -> None:
    thread = svc.create("Sofort")
    svc.set_note("Original bleibt.")
    user = svc.append_whiteboard(
        thread.id, actor="Ada", actor_type="human", entry_type="note", content="Original bleibt stehen."
    )
    calls = []
    home = Hausmeister(svc.store, _counting(calls))
    home.set_enabled(True)
    home.set_model("demo")
    queued = home.enqueue(thread.id, "Fasse den Stand zusammen")
    assert home.run_now(thread.id, "Fasse den Stand zusammen")["ok"] is True
    assert calls.count("chat") == 1
    assert home.jobs()[0]["id"] == queued["job"]["id"]
    assert home.jobs()[0]["status"] == "done"
    assert home.tick(_quiet())["started"] is False
    assert calls.count("chat") == 1
    assert svc.whiteboard(thread.id)[0].id == user["entry"]["id"]
    assert svc.whiteboard(thread.id)[0].content == "Original bleibt stehen."
    again = Hausmeister(type(svc.store)(tmp_path), _counting(calls))
    assert again.jobs()[0]["status"] == "done"
    assert again.jobs()[0]["id"] == queued["job"]["id"]


def test_automatic_start_waits_for_quiet_and_can_resume(svc: ThreadService) -> None:
    thread = svc.create("Ruhe")
    calls = []
    state = {"active": False}

    def snap() -> IdleSnapshot:
        return _busy() if state["active"] else _quiet()

    home = Hausmeister(svc.store, _counting(calls), snapshot_fn=snap)
    home.set_enabled(True)
    home.set_model("demo")
    job = home.enqueue(thread.id, "Fasse den Stand zusammen")["job"]
    assert home.tick(_busy())["started"] is False
    assert home.tick(_heavy())["started"] is False
    assert calls.count("chat") == 0
    assert home.jobs()[0]["status"] == "waiting"
    state["active"] = True
    paused = home.tick(_quiet())
    assert paused["phase"] == "paused"
    assert paused["started"] is False
    assert calls.count("chat") == 0
    assert home.jobs()[0]["status"] == "paused"
    state["active"] = False
    started = home.tick(_quiet())
    assert started["started"] is True
    assert started["job_id"] == job["id"]
    assert home.jobs()[0]["status"] == "done"
    assert {item["actor_type"] for item in started["entries"]} == {"local-assistant"}
    assert home.tick(_quiet())["started"] is False
    assert calls.count("chat") == 1


def test_disabled_housekeeper_does_not_queue_or_tick(svc: ThreadService) -> None:
    thread = svc.create("Aus")
    calls = []
    home = Hausmeister(svc.store, _counting(calls))
    assert home.enqueue(thread.id, "Fasse zusammen")["error"] == "module_disabled"
    assert home.run_now(thread.id, "Fasse zusammen")["error"] == "module_disabled"
    assert home.tick(_quiet())["error"] == "module_disabled"
    assert calls == []
    assert home.jobs() == []


def _counting(calls: list[str]):
    def call(url: str, body=None, timeout: float = 0.4):
        assert url.startswith("http://127.0.0.1:11434/")
        assert "/api/pull" not in url
        if url.endswith("/api/tags"):
            calls.append("tags")
            return {"models": [{"name": "demo"}]}
        calls.append("chat")
        return {"message": {"content": json.dumps({"summary": "Kurz gefasst.", "suggestions": ["Weiter notieren"]})}}

    return call


def _from_activity(store) -> IdleSnapshot:
    """Use the recorded desk time and a light load. No real waiting."""
    live = live_snapshot(store)
    return IdleSnapshot(idle_seconds=live.idle_seconds, user_active=live.user_active, load=0.2)


def _armed(svc: ThreadService):
    thread = svc.create("Aktiv")
    calls: list[str] = []
    home = Hausmeister(svc.store, _counting(calls))
    home.set_enabled(True)
    home.set_model("demo")
    home.enqueue(thread.id, "Fasse den Stand zusammen")
    return thread, calls, home


def _kind(store, kind: str) -> None:
    assert note_activity(store, now=time.time(), kind=kind) is True
    saved = json.loads(store.artifact_path("hausmeister-activity.json").read_text(encoding="utf-8"))
    assert saved["kind"] == kind


def test_pointer_and_key_activity_block_automatic_start(svc: ThreadService) -> None:
    _thread, calls, home = _armed(svc)
    for kind in ("pointer", "click", "key", "touch"):
        _kind(svc.store, kind)
        snapshot = _from_activity(svc.store)
        assert snapshot.user_active is True
        assert snapshot.idle_seconds < 600
        assert home.tick(snapshot)["started"] is False
    assert calls.count("chat") == 0
    assert home.jobs()[0]["status"] == "waiting"


def test_scroll_activity_blocks_automatic_start(svc: ThreadService) -> None:
    _thread, calls, home = _armed(svc)
    _kind(svc.store, "scroll")
    assert home.tick(_from_activity(svc.store))["started"] is False
    assert calls.count("chat") == 0
    assert home.jobs()[0]["status"] == "waiting"


def test_simulated_quiet_allows_automatic_start(svc: ThreadService) -> None:
    _thread, calls, home = _armed(svc)
    _kind(svc.store, "scroll")
    assert home.tick(_from_activity(svc.store))["started"] is False
    assert note_activity(svc.store, now=time.time() - 700, kind="scroll") is True
    quiet = _from_activity(svc.store)
    assert quiet.user_active is False
    assert quiet.idle_seconds >= 600
    started = home.tick(quiet)
    assert started["started"] is True
    assert calls.count("chat") == 1
    assert home.jobs()[0]["status"] == "done"


def test_manual_start_still_runs_while_the_surface_is_active(svc: ThreadService) -> None:
    thread, calls, home = _armed(svc)
    _kind(svc.store, "key")
    assert home.tick(_from_activity(svc.store))["started"] is False
    assert home.run_now(thread.id, "Fasse den Stand zusammen")["ok"] is True
    assert calls.count("chat") == 1
    home.enqueue(thread.id, "Später noch einmal")
    assert home.tick(_from_activity(svc.store))["started"] is False
    assert calls.count("chat") == 1
    assert any(job["status"] == "waiting" for job in home.jobs())


def test_surface_pings_are_throttled_without_waiting(svc: ThreadService) -> None:
    assert activity_is_due(None, 1000) is True
    assert activity_is_due(1000, 1000 + ACTIVITY_GAP_SECONDS - 0.1) is False
    assert activity_is_due(1000, 1000 + ACTIVITY_GAP_SECONDS) is True
    assert note_activity(svc.store, kind="pointer") is True
    assert note_activity(svc.store, kind="key") is False
    saved = json.loads(svc.store.artifact_path("hausmeister-activity.json").read_text(encoding="utf-8"))
    assert saved["kind"] == "pointer"
    with pytest.raises(InvalidState, match="activity_kind"):
        note_activity(svc.store, kind="network")


def test_desk_script_throttles_surface_activity() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "src" / "threaddesk" / "ui" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    for name in ("pointermove", "mousedown", "keydown", "wheel", "scroll", "touchstart", "touchmove"):
        assert name in script
    assert "ACTIVITY_GAP_MS = 15000" in script
    assert "/hausmeister/activity" in script
    assert "waitingKind" in script


def test_activity_route_records_one_surface_ping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from threaddesk.ui.server import create_app

    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    client = TestClient(create_app())
    assert client.post("/hausmeister/activity", json={"kind": "page"}).status_code == 400
    recorded = client.post("/hausmeister/activity", json={"kind": "scroll"})
    assert recorded.status_code == 200
    assert recorded.json()["recorded"] is True
    held = client.post("/hausmeister/activity", json={"kind": "pointer"})
    assert held.status_code == 200
    assert held.json()["recorded"] is False
    saved = json.loads((tmp_path / "hausmeister-activity.json").read_text(encoding="utf-8"))
    assert saved["kind"] == "scroll"


def test_secrets_from_the_model_are_not_stored(svc: ThreadService) -> None:
    thread = svc.create("Geheim")
    home = Hausmeister(svc.store, _transport(["demo"], {
        "summary": "api_key=abcdefghijklmnopqrstuvwxyz",
        "suggestions": ["Nur den Stand merken"],
    }))
    home.set_enabled(True)
    home.set_model("demo")
    result = home.run(thread.id, "Fasse zusammen")
    assert result["ok"] is True
    stored = " ".join(entry.content for entry in svc.whiteboard(thread.id))
    assert "api_key" not in stored
    assert "Nur den Stand merken" in stored
    with pytest.raises(SecretRejected):
        home.run(thread.id, "api_key=abcdefghijklmnopqrstuvwxyz")
