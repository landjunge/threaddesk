"""Stable local people and agents. Old whiteboard entries stay readable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import InvalidState, SecretRejected
from threaddesk.core.models import new_thread
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def svc(request, tmp_path: Path) -> ThreadService:
    return ThreadService(store=request.param(tmp_path))


def test_id_survives_rename_and_recolor_and_reload(svc: ThreadService, tmp_path: Path) -> None:
    human = svc.register_human("Ada", "plum")
    agent = svc.register_agent(
        "Grok", human["id"], "grok", model="grok-4", provider="xai"
    )
    instance = svc.instance_id()

    renamed = svc.rename_actor(human["id"], "Augusta")
    recolored = svc.recolor_actor(human["id"], "sea")

    assert renamed["id"] == human["id"]
    assert recolored["id"] == human["id"]
    assert recolored["color_token"] == "sea"
    assert svc.instance_id() == instance

    again = ThreadService(store=type(svc.store)(tmp_path))
    people = {item["id"]: item for item in again.actors()}
    assert people[human["id"]]["name"] == "Augusta"
    assert people[human["id"]]["color_token"] == "sea"
    assert people[agent["id"]]["person_id"] == human["id"]
    assert people[agent["id"]]["model"] == "grok-4"
    assert again.instance_id() == instance

    person = again.actor_appearance(human["id"])
    assistant = again.actor_appearance(agent["id"])
    assert person["color_token"] == assistant["color_token"] == "sea"
    assert person["ai"] is False and assistant["ai"] is True
    assert person["kind"] == "human" and assistant["kind"] == "agent"


def test_invalid_agent_links_are_rejected(svc: ThreadService) -> None:
    human = svc.register_human("Ada", "moss")
    other = svc.register_agent("Hilf", human["id"], "local-assistant")
    before = [item["id"] for item in svc.actors()]

    with pytest.raises(InvalidState, match="actor_unassigned"):
        svc.register_agent("Los", "missing-person", "grok")
    with pytest.raises(InvalidState, match="actor_unassigned"):
        svc.register_agent("Los", other["id"], "claude")
    with pytest.raises(InvalidState, match="actor_agent_type"):
        svc.register_agent("Los", human["id"], "system")
    with pytest.raises(InvalidState, match="actor_agent_type"):
        svc.register_agent("Los", human["id"], "human")
    with pytest.raises(InvalidState, match="actor_color"):
        svc.recolor_actor(other["id"], "sand")
    with pytest.raises(SecretRejected):
        svc.register_human("api_key=abcdefghijklmnopqrstuvwxyz", "ink")

    assert [item["id"] for item in svc.actors()] == before
    assert other["agent_type"] == "local-assistant"
    assert other["kind"] == "agent"


def test_legacy_whiteboard_entry_without_actor_id_stays_readable(
    svc: ThreadService, tmp_path: Path
) -> None:
    thread = new_thread("Bestand")
    svc.store.save_thread(thread)
    payload = {
        "id": "legacy01",
        "thread_id": thread.id,
        "actor": "Mensch",
        "actor_type": "human",
        "created_at": "2026-01-01T00:00:00+00:00",
        "entry_type": "note",
        "content": "ohne akteur",
        "ordinal": 1,
        "metadata": {},
    }
    if isinstance(svc.store, JsonStore):
        folder = tmp_path / "whiteboard" / thread.id
        folder.mkdir(parents=True)
        (folder / "legacy01.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
    else:
        svc.store.connection.execute(
            """INSERT INTO whiteboard_entries(
                   id, thread_id, created_at, ordinal, external_key, payload
               ) VALUES (?,?,?,?,?,?)""",
            (payload["id"], thread.id, payload["created_at"], 1, None, json.dumps(payload)),
        )
        svc.store.connection.commit()

    loaded = svc.whiteboard(thread.id)[0]
    assert loaded.actor_id is None
    assert loaded.content == "ohne akteur"
    assert loaded.actor == "Mensch"


def test_entry_keeps_actor_id_and_rejects_a_mismatched_kind(
    svc: ThreadService, tmp_path: Path
) -> None:
    thread = svc.create("Auftrag")
    human = svc.register_human("Ada", "plum")
    agent = svc.register_agent("Assistent", human["id"], "local-assistant")

    noted = svc.append_whiteboard(
        thread.id,
        actor="Ada",
        actor_type="human",
        entry_type="note",
        content="von der person",
        actor_id=human["id"],
    )
    spoken = svc.append_whiteboard(
        thread.id,
        actor="Assistent",
        actor_type="local-assistant",
        entry_type="progress",
        content="von der ki",
        actor_id=agent["id"],
    )
    assert noted["entry"]["actor_id"] == human["id"]
    assert spoken["entry"]["actor_id"] == agent["id"]

    with pytest.raises(InvalidState, match="actor_kind_mismatch"):
        svc.append_whiteboard(
            thread.id,
            actor="Assistent",
            actor_type="system",
            entry_type="note",
            content="nicht system",
            actor_id=agent["id"],
        )
    with pytest.raises(InvalidState, match="actor_kind_mismatch"):
        svc.append_whiteboard(
            thread.id,
            actor="Ada",
            actor_type="human",
            entry_type="note",
            content="nicht mensch",
            actor_id=agent["id"],
        )

    again = ThreadService(store=type(svc.store)(tmp_path))
    entries = again.whiteboard(thread.id)
    assert [entry.actor_id for entry in entries] == [human["id"], agent["id"]]
    assert entries[0].content == "von der person"


def test_rendered_marks_share_a_color_and_distinguish_the_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from threaddesk.ui.server import create_app

    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    monkeypatch.delenv("THREADDESK_STORAGE", raising=False)
    svc = ThreadService(store=JsonStore(tmp_path))
    thread = svc.create("Sicht")
    human = svc.register_human("Ada", "plum")
    agent = svc.register_agent("Assistent", human["id"], "local-assistant")
    svc.append_whiteboard(
        thread.id, actor="Ada", actor_type="human", entry_type="note",
        content="menschenwort", actor_id=human["id"],
    )
    svc.append_whiteboard(
        thread.id, actor="Assistent", actor_type="local-assistant", entry_type="note",
        content="kiwort", actor_id=agent["id"],
    )
    svc.append_whiteboard(
        thread.id, actor="Gast", actor_type="human", entry_type="note",
        content="ohne verzeichnis",
    )

    page = TestClient(create_app()).get("/").text
    assert page.count("tone-plum") == 2
    assert 'data-actor-kind="human"' in page
    assert 'data-actor-kind="agent"' in page
    assert 'data-ai="0"' in page and 'data-ai="1"' in page
    assert ">KI<" in page
    assert page.count("is-ai") == 1
    assert "ohne verzeichnis" in page
