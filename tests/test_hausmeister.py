"""The local housekeeper appends its own notes and stays on the machine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import SecretRejected
from threaddesk.services.hausmeister import Hausmeister
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
