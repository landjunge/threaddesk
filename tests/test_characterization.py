"""Public contracts that the storage refactor and migration must preserve."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry

from threaddesk.api.service import ThreadService
from threaddesk.services.commands.model import workspace_identity
from threaddesk.services.commands.registry import CommandRegistry
from threaddesk.services.mcp import McpBridge
from threaddesk.services.mcp_commands import tool_name
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
        "revision": 0,
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
        "revision": 0,
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
        "handoff", "inbox", "mcp", "grok", "gnom", "gnom-job", "module", "workshop", "gate", "dash", "graph", "authority", "serve", "ui", "search", "library", "command",
    )

    bridge = McpBridge(ThreadService(JsonStore(tmp_path)))
    legacy_names = [
        "library_receive_status", "library_search", "library_file_info", "library_receive",
        "knowledge_manage", "get_reentry",
        "record_handoff_question", "answer_handoff_question",
        "issue_handoff", "get_issued_handoff", "bind_handoff_run",
        "thread_operation_status", "thread_manage", "list_threads", "get_thread", "current_thread", "switch_thread", "add_note",
        "save_snapshot", "list_snapshots", "restore_snapshot", "generate_prompt",
        "export_handoff", "import_return", "get_return", "list_returns", "review_return",
        "export_grok", "export_gnom", "bind_gnom_job", "receive_gnom_callback",
        "list_gnom_jobs", "check_gate", "dashboard", "library_query", "library_manage",
        "command_catalog", "command_query", "command_invoke",
    ]
    tools = bridge.list_tools()
    legacy, dynamic = tools[:len(legacy_names)], tools[len(legacy_names):]
    assert [tool["name"] for tool in legacy] == legacy_names
    assert all("delete" not in tool["name"] for tool in legacy)
    assert all(tool["name"].startswith("td_") for tool in dynamic)
    assert len({tool["name"] for tool in tools}) == len(tools)

    records = {row["id"]: row for row in CommandRegistry(bridge.svc.store).records(transport="mcp")
               if row["availability"] == "available"}
    by_id = {tool["_meta"]["threaddesk"]["id"]: tool for tool in dynamic}
    assert len(by_id) == len(dynamic) and set(by_id) == set(records)
    workspace_id = workspace_identity(bridge.svc.store)
    for identity, record in records.items():
        tool = by_id[identity]
        assert tool["name"] == tool_name(identity)
        assert tool["_meta"]["threaddesk"] == {**record, "workspace_id": workspace_id}
        assert tool["annotations"]["readOnlyHint"] == (record["effect"] == "read")
        published = tool["inputSchema"]
        Draft202012Validator.check_schema(published)
        domain = published["properties"]["arguments"]
        # Concrete source constraints survive the envelope; native bindings may
        # move their requirement to the envelope, preserving the domain schema.
        assert all(domain[key] == value for key, value in record["input_schema"].items()
                   if key not in {"$id", "required"})
        assert set(record["input_schema"].get("required", [])) <= (
            set(domain.get("required", [])) | set(published["required"]))

    # Explicit lifecycle tools replace the former blanket ban on "delete".
    # Discovery must retain the concrete consent and preview bindings.
    for identity, arguments in (
        ("whiteboard.delete", {"id": "fixture-thread", "confirm_thread_move": True}),
        ("trash.purge", {"trash_id": "fixture-trash", "generation": 1,
                         "reference_digest": "0" * 64,
                         "confirmation": "DELETE fixture-trash " + "0" * 64}),
    ):
        tool = by_id[identity]
        schema = tool["inputSchema"]
        assert tool["_meta"]["threaddesk"]["scope"] == "workspace.write"
        assert tool["annotations"]["readOnlyHint"] is False
        assert {"operation_id", "expected_revision"} <= set(schema["required"])
        assert set(arguments) <= set(schema["properties"]["arguments"]["required"])
        payload = {"workspace_id": workspace_id, "operation_id": "contract-consent",
                   "expected_revision": 0, "arguments": arguments}
        validator = Draft202012Validator(schema, registry=Registry())
        validator.validate(payload)
        for field in ("operation_id", "expected_revision"):
            assert not validator.is_valid({key: value for key, value in payload.items() if key != field})
        consent = "confirm_thread_move" if identity == "whiteboard.delete" else "confirmation"
        assert not validator.is_valid({**payload, "arguments": {
            key: value for key, value in arguments.items() if key != consent}})
        if identity == "whiteboard.delete":
            assert not validator.is_valid({**payload, "arguments": {**arguments, consent: False}})


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
