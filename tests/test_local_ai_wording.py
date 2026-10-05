"""Sichtbare Bezeichnung der lokalen KI, ohne gespeicherte Historie umzuschreiben."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core import i18n
from threaddesk.services.actors import ActorRegistry
from threaddesk.services.hausmeister import (
    ACTOR_NAME,
    AGENT_TYPE,
    MANIFEST,
    SETTINGS,
    Hausmeister,
)
from threaddesk.services.modules import ModuleRegistry
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]
OLD_LABELS = ("Hausmeister", "Housekeeper", "caretaker", "Caretaker")
DOCS = (
    ROOT / "README.md",
    ROOT / "docs" / "TEAMPLAN.md",
    ROOT / "docs" / "usability" / "GOLDENRULES.MD",
)


def _transport(models: list[str], reply: dict | str):
    def call(url: str, body=None, timeout: float = 0.4):
        assert url.startswith("http://127.0.0.1:11434/")
        if url.endswith("/api/tags"):
            return {"models": [{"name": name} for name in models]}
        text = reply if isinstance(reply, str) else json.dumps(reply)
        return {"message": {"content": text}}

    return call


def _stored_payload(store, tmp_path: Path, thread_id: str, entry_id: str) -> bytes:
    if isinstance(store, JsonStore):
        return (tmp_path / "whiteboard" / thread_id / f"{entry_id}.json").read_bytes()
    return store.connection.execute(
        "SELECT payload FROM whiteboard_entries WHERE id = ?",
        (entry_id,),
    ).fetchone()[0]


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def svc(request, tmp_path: Path) -> ThreadService:
    return ThreadService(store=request.param(tmp_path))


def test_order_placeholder_asks_for_summary_or_next_steps() -> None:
    german = i18n.translate("hausmeister.order_placeholder", "de")
    english = i18n.translate("hausmeister.order_placeholder", "en")
    assert german == "Zusammenfassung oder nächste Schritte?"
    assert english == "Summary or next steps?"
    assert "aufgeräumt" not in german
    assert "tidied" not in english
    assert "hausmeister.order_placeholder" in i18n.CATALOG


def test_catalog_uses_direct_names_and_keeps_the_keys() -> None:
    assert i18n.translate("hausmeister.title", "de") == "lokale KI"
    assert i18n.translate("hausmeister.title", "en") == "local AI assistant"
    assert i18n.translate("hausmeister.disabled", "de") == "lokale KI ist aus"
    assert i18n.translate("hausmeister.disabled", "en") == "local AI assistant is off"
    german = i18n.translate("data.private", "de")
    english = i18n.translate("data.private", "en")
    assert "Die lokale KI bleibt nach dem Wiederherstellen ausgeschaltet." in german
    assert "The local AI assistant stays disabled after restoring." in english
    for label in OLD_LABELS:
        assert label not in german
        assert label not in english
    assert "hausmeister.title" in i18n.CATALOG
    assert MANIFEST.id == "local-assistant"
    assert MANIFEST.name == "lokale KI"
    assert ACTOR_NAME == "lokale KI"
    assert AGENT_TYPE == "local-assistant"
    assert SETTINGS == "hausmeister.json"
    assert MANIFEST.views == ("hausmeister:desk",)


def test_named_docs_use_direct_names() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    german_docs = [
        (ROOT / "docs" / "TEAMPLAN.md").read_text(encoding="utf-8"),
        (ROOT / "docs" / "usability" / "GOLDENRULES.MD").read_text(encoding="utf-8"),
    ]
    assert "lokale KI" in readme
    assert "local AI assistant" in readme
    for text in (readme, *german_docs):
        for label in OLD_LABELS:
            assert label not in text
    for text in german_docs:
        assert "lokale KI" in text


def test_pages_show_both_languages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    monkeypatch.delenv("THREADDESK_STORAGE", raising=False)
    fastapi_testclient = pytest.importorskip("fastapi.testclient")
    from threaddesk.ui.server import create_app

    client = fastapi_testclient.TestClient(create_app())
    created = client.post("/threads", data={"title": "Sprachregel", "description": ""})
    assert created.status_code == 200

    german = client.get("/?lang=de")
    english = client.get("/?lang=en")
    assert german.status_code == 200
    assert english.status_code == 200
    assert 'data-disclosure="hausmeister"' in german.text
    assert "/hausmeister/toggle" in german.text
    enabled = Hausmeister(
        JsonStore(tmp_path),
        _transport(["demo"], {"summary": "Stand", "suggestions": []}),
    )
    enabled.set_enabled(True)
    german_order = client.get("/?lang=de")
    english_order = client.get("/?lang=en")
    assert 'placeholder="Zusammenfassung oder nächste Schritte?"' in german_order.text
    assert 'placeholder="Summary or next steps?"' in english_order.text
    assert "Was soll aufgeräumt werden?" not in german_order.text
    assert "What should be tidied?" not in english_order.text
    assert "lokale KI" in german.text
    assert "local AI assistant" not in german.text
    assert "local AI assistant" in english.text
    assert "lokale KI" not in english.text
    for page in (german, english):
        for label in OLD_LABELS:
            assert label not in page.text

    german_data = client.get("/data?lang=de")
    english_data = client.get("/data?lang=en")
    assert "Die lokale KI bleibt nach dem Wiederherstellen ausgeschaltet." in german_data.text
    assert "The local AI assistant stays disabled after restoring." not in german_data.text
    assert "The local AI assistant stays disabled after restoring." in english_data.text
    assert "Die lokale KI bleibt nach dem Wiederherstellen ausgeschaltet." not in english_data.text
    for page in (german_data, english_data):
        for label in OLD_LABELS:
            assert label not in page.text


def test_existing_local_assistant_entry_stays_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    monkeypatch.delenv("THREADDESK_STORAGE", raising=False)
    svc = ThreadService(store=JsonStore(tmp_path))
    thread = svc.create("Bestand")
    saved = svc.append_whiteboard(
        thread.id,
        actor="Hausmeister",
        actor_type="local-assistant",
        entry_type="note",
        content="Historischer Eintrag bleibt stehen.",
    )
    entry_id = saved["entry"]["id"]
    before = _stored_payload(svc.store, tmp_path, thread.id, entry_id)

    fastapi_testclient = pytest.importorskip("fastapi.testclient")
    from threaddesk.ui.server import create_app

    client = fastapi_testclient.TestClient(create_app())
    for language in ("de", "en"):
        page = client.get(f"/?lang={language}")
        assert page.status_code == 200
        start = page.text.index('data-hausmeister-entry="1"')
        block = page.text[start:start + 900]
        assert "Hausmeister" in block
        assert "Historischer Eintrag bleibt stehen." in block
        assert "Housekeeper" not in page.text
        assert "caretaker" not in page.text
        assert "Caretaker" not in page.text

    assert _stored_payload(svc.store, tmp_path, thread.id, entry_id) == before
    kept = svc.whiteboard(thread.id)
    assert [(item.actor, item.actor_type, item.content) for item in kept] == [
        ("Hausmeister", "local-assistant", "Historischer Eintrag bleibt stehen.")
    ]


def test_existing_actor_and_manifest_are_not_renamed(svc: ThreadService) -> None:
    registry = ActorRegistry(svc.store)
    person = registry.add_human("Ada", "sea")
    actor = registry.add_agent("Hausmeister", person["id"], "local-assistant", provider="ollama")
    modules = ModuleRegistry(svc.store)
    modules.install(replace(MANIFEST, name="Hausmeister"))

    home = Hausmeister(svc.store, _transport(["demo"], {"summary": "x", "suggestions": []}))
    home.set_enabled(True)

    assert registry.get(actor["id"])["name"] == "Hausmeister"
    assert modules.get(MANIFEST.id).manifest.name == "Hausmeister"
    assert home.ensure_actor()["id"] == actor["id"]


def test_new_actor_and_new_note_use_the_new_name(svc: ThreadService, tmp_path: Path) -> None:
    thread = svc.create("Neu")
    saved = svc.append_whiteboard(
        thread.id,
        actor="Hausmeister",
        actor_type="local-assistant",
        entry_type="note",
        content="Alter Urheber bleibt.",
    )
    entry_id = saved["entry"]["id"]
    before = _stored_payload(svc.store, tmp_path, thread.id, entry_id)

    home = Hausmeister(svc.store, _transport(["demo"], {
        "summary": "Neuer Stand.",
        "suggestions": [],
    }))
    home.set_enabled(True)
    home.set_model("demo")
    result = home.run(thread.id, "Fasse den Stand zusammen")

    assert result["ok"] is True
    assert result["entries"]
    assert {item["actor"] for item in result["entries"]} == {"lokale KI"}
    assert {item["actor_type"] for item in result["entries"]} == {"local-assistant"}
    assert home.ensure_actor()["name"] == "lokale KI"
    assert ModuleRegistry(svc.store).get(MANIFEST.id).manifest.name == "lokale KI"
    assert _stored_payload(svc.store, tmp_path, thread.id, entry_id) == before
    history = svc.whiteboard(thread.id)
    assert history[0].actor == "Hausmeister"
    assert history[0].content == "Alter Urheber bleibt."
