"""Modules reach a thread whiteboard only through ModuleContext."""

from __future__ import annotations

from pathlib import Path

import pytest

from threaddesk.core.models import new_thread
from threaddesk.services.modules import ModuleManifest, ModuleRegistry, ModuleRuntime
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


def manifest(**changes) -> ModuleManifest:
    values = {
        "id": "board-probe",
        "name": "Board probe",
        "version": "1.0.0",
        "read_scopes": ("thread:read", "whiteboard:read"),
        "write_actions": ("whiteboard:append",),
        "approvals": (),
        "uninstall": "retain-data",
    }
    values.update(changes)
    return ModuleManifest(**values)


def runtime(store, **changes) -> ModuleRuntime:
    registry = ModuleRegistry(store)
    registry.install(manifest(**changes))
    if changes.get("enabled", True):
        registry.set_enabled("board-probe", True)
    return ModuleRuntime(store, registry)


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def store(request, tmp_path: Path):
    opened = request.param(tmp_path)
    thread = new_thread("Projektakte", "Gemeinsamer Stand")
    thread.context.notes = "alte notiz"
    opened.save_thread(thread)
    opened._thread = thread  # test handle, not part of the store contract
    return opened


def test_missing_scope_rejects_reads_and_does_not_expose_the_store(store) -> None:
    limited = runtime(
        store,
        read_scopes=(),
        write_actions=("whiteboard:append",),
    )
    thread_id = store._thread.id

    denied_thread = limited.run(
        "board-probe",
        "whiteboard:append",
        lambda context: context.read_thread(thread_id),
    )
    denied_board = limited.run(
        "board-probe",
        "whiteboard:append",
        lambda context: context.read_whiteboard(thread_id),
    )
    surface = limited.run(
        "board-probe",
        "whiteboard:append",
        lambda context: hasattr(context, "store"),
    )

    assert denied_thread.ok is False and denied_thread.error == "module_read_scope"
    assert denied_board.ok is False and denied_board.error == "module_read_scope"
    assert surface.ok is True and surface.value is False
    assert store.list_whiteboard(thread_id) == []


def test_declared_scope_returns_thread_text_and_whiteboard_order(store) -> None:
    gate = runtime(store)
    thread_id = store._thread.id
    gate.run(
        "board-probe",
        "whiteboard:append",
        lambda context: context.append_whiteboard(
            thread_id,
            actor="Mensch",
            actor_type="human",
            entry_type="note",
            content="erster",
        ),
    )
    gate.run(
        "board-probe",
        "whiteboard:append",
        lambda context: context.append_whiteboard(
            thread_id,
            actor="Grok",
            actor_type="grok",
            entry_type="progress",
            content="zweiter",
        ),
    )

    result = gate.run(
        "board-probe",
        "whiteboard:append",
        lambda context: {
            "thread": context.read_thread(thread_id),
            "entries": context.read_whiteboard(thread_id),
        },
    )

    assert result.ok is True
    assert result.value["thread"] == {
        "id": thread_id,
        "title": "Projektakte",
        "status": "idea",
        "description": "Gemeinsamer Stand",
        "notes": "alte notiz",
    }
    assert [item["content"] for item in result.value["entries"]] == ["erster", "zweiter"]
    assert "files" not in result.value["thread"]


def test_disabled_module_cannot_append(store) -> None:
    registry = ModuleRegistry(store)
    registry.install(manifest())
    called = []
    result = ModuleRuntime(store, registry).run(
        "board-probe",
        "whiteboard:append",
        lambda context: called.append(context.append_whiteboard(
            store._thread.id,
            actor="Mensch",
            actor_type="human",
            entry_type="note",
            content="nicht schreiben",
        )),
    )

    assert result.ok is False and result.error == "module_disabled"
    assert called == []
    assert store.list_whiteboard(store._thread.id) == []


def test_append_keeps_the_previous_entry_and_duplicate_key(store, tmp_path: Path) -> None:
    gate = runtime(store)
    thread_id = store._thread.id

    def add(content: str, **extra):
        return gate.run(
            "board-probe",
            "whiteboard:append",
            lambda context: context.append_whiteboard(
                thread_id,
                actor="Mensch",
                actor_type="human",
                entry_type="note",
                content=content,
                **extra,
            ),
        )

    first = add("bleib stehen", external_key="ext-1")
    assert first.ok is True and first.value["duplicate"] is False
    original = dict(first.value["entry"])
    if isinstance(store, JsonStore):
        path = tmp_path / "whiteboard" / thread_id / f"{original['id']}.json"
        before = path.read_bytes()
    else:
        before = store.connection.execute(
            "SELECT payload FROM whiteboard_entries WHERE id = ?",
            (original["id"],),
        ).fetchone()[0]

    second = add("danach")
    again = add("bleib stehen", external_key="ext-1")

    assert second.ok is True and second.value["duplicate"] is False
    assert again.ok is True and again.value["duplicate"] is True
    assert again.value["entry"]["id"] == original["id"]
    entries = store.list_whiteboard(thread_id)
    assert entries[0].to_dict() == original
    assert [entry.content for entry in entries] == ["bleib stehen", "danach"]
    assert store.get_thread(thread_id).context.notes == "alte notiz"
    if isinstance(store, JsonStore):
        assert path.read_bytes() == before
        assert len(list(path.parent.glob("*.json"))) == 2
    else:
        payload = store.connection.execute(
            "SELECT payload FROM whiteboard_entries WHERE id = ?",
            (original["id"],),
        ).fetchone()[0]
        assert payload == before


def test_secret_content_is_rejected_and_not_stored(store) -> None:
    gate = runtime(store)
    result = gate.run(
        "board-probe",
        "whiteboard:append",
        lambda context: context.append_whiteboard(
            store._thread.id,
            actor="Mensch",
            actor_type="human",
            entry_type="note",
            content="api_key=abcdefghijklmnopqrstuvwxyz",
        ),
    )

    assert result.ok is False
    assert "api_key" not in (result.error or "")
    assert store.list_whiteboard(store._thread.id) == []


def test_append_without_the_write_action_is_denied(store) -> None:
    gate = runtime(store, write_actions=("board:note",))
    result = gate.run(
        "board-probe",
        "board:note",
        lambda context: context.append_whiteboard(
            store._thread.id,
            actor="Mensch",
            actor_type="human",
            entry_type="note",
            content="nein",
        ),
    )

    assert result.ok is False and result.error == "module_write_action"
    assert store.list_whiteboard(store._thread.id) == []
