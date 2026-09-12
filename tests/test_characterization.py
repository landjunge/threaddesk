"""Public contracts that the storage refactor and migration must preserve."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.services.mcp import McpBridge
from threaddesk.storage.json_store import JsonStore
from threaddesk.ui import cli


FIXTURES = Path(__file__).parent / "fixtures" / "json_store"


def fixture_store(tmp_path: Path, name: str) -> JsonStore:
    root = tmp_path / name
    shutil.copytree(FIXTURES / name, root)
    return JsonStore(root)


def test_empty_small_and_legacy_json_stores_keep_their_public_shape(tmp_path: Path) -> None:
    assert fixture_store(tmp_path, "empty").list_threads() == []

    small = fixture_store(tmp_path, "small").list_threads()[0]
    assert small.to_dict() == {
        "id": "thread-small",
        "title": "Beispielprojekt",
        "description": "Anonymisierter Bestand",
        "status": "active",
        "created_at": "2026-01-01T10:00:00+00:00",
        "updated_at": "2026-01-02T10:00:00+00:00",
        "context": {
            "notes": "Nächsten Schritt prüfen.",
            "files": ["docs/plan.md"],
            "prompts": [],
            "agent_state": {},
            "extra": {},
        },
        "current_snapshot_id": None,
    }

    legacy = fixture_store(tmp_path, "legacy").list_threads()[0]
    assert legacy.to_dict() == {
        "id": "thread-legacy",
        "title": "Älterer Bestand",
        "description": "",
        "status": "idea",
        "created_at": "",
        "updated_at": "",
        "context": {
            "notes": "",
            "files": [],
            "prompts": [],
            "agent_state": {},
            "extra": {},
        },
        "current_snapshot_id": None,
    }


def test_corrupt_json_fails_loudly_instead_of_being_silently_dropped(tmp_path: Path) -> None:
    store = fixture_store(tmp_path, "corrupt")
    with pytest.raises(json.JSONDecodeError):
        store.list_threads()


def test_service_snapshot_and_graph_survive_reopening_the_store(tmp_path: Path) -> None:
    service = ThreadService(JsonStore(tmp_path))
    thread = service.create("Charakterisierung", "öffentliches Verhalten")
    service.set_note("gesicherter Stand")
    snapshot = service.snapshot("vor Umbau")
    project = service.create_node("project", "ThreadDesk", status="active")
    task = service.create_node("task", "Speicher trennen", status="ready")
    relation = service.connect(project.id, task.id, "contains")

    reopened = ThreadService(JsonStore(tmp_path))
    assert reopened.current().id == thread.id
    assert reopened.snapshots(thread.id)[0].to_dict() == snapshot.to_dict()
    assert reopened.graph()["counts"] == {"nodes": 2, "relations": 1}
    assert reopened.list_relations()[0].to_dict() == relation.to_dict()


def test_cli_and_mcp_publish_the_current_command_and_tool_contracts(tmp_path: Path) -> None:
    parser = cli.build_parser()
    commands = next(
        action.choices
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert tuple(commands) == (
        "new", "list", "switch", "current", "note", "describe", "status",
        "files", "rename", "archive", "unarchive", "delete", "snap", "prompt",
        "handoff", "mcp", "grok", "gnom", "gate", "dash", "graph", "serve", "ui",
    )

    bridge = McpBridge(ThreadService(JsonStore(tmp_path)))
    assert [tool["name"] for tool in bridge.list_tools()] == [
        "list_threads", "get_thread", "current_thread", "switch_thread", "add_note",
        "save_snapshot", "list_snapshots", "restore_snapshot", "generate_prompt",
        "export_handoff", "export_grok", "export_gnom", "check_gate", "dashboard",
    ]
    assert all("delete" not in tool["name"] for tool in bridge.list_tools())


def test_ui_route_contract_is_stable() -> None:
    pytest.importorskip("fastapi")
    from threaddesk.ui.server import create_app

    routes = {
        (method, route.path)
        for route in create_app().routes
        for method in getattr(route, "methods", set())
        if route.path != "/openapi.json" and method != "HEAD"
    }
    assert ("GET", "/") in routes
    assert ("GET", "/api/graph") in routes
    assert ("POST", "/threads/{thread_id}/snapshot") in routes
    assert ("POST", "/snapshots/{snap_id}/restore") in routes
    assert ("POST", "/gate/freeze") in routes
    assert not any("notion" in path.lower() or "import" in path.lower() for _, path in routes)


@pytest.mark.parametrize("exporter", ["gnom", "grok"])
def test_agent_packages_are_local_artifacts_and_never_execute(tmp_path: Path, exporter: str) -> None:
    service = ThreadService(JsonStore(tmp_path))
    service.create("Paketvertrag")

    packet = getattr(service, exporter)()

    assert packet["kind"] == f"threaddesk.{exporter}"
    assert packet["ran"] is False
    assert Path(packet["path"]).is_file()


def test_gate_check_is_read_only(tmp_path: Path) -> None:
    service = ThreadService(JsonStore(tmp_path))
    thread = service.create("Schrankenvertrag")
    before = service.gate()

    result = service.gate_check("execute", thread.id)

    assert result["allow"] is True
    assert service.gate() == before
