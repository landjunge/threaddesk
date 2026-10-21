from __future__ import annotations

from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.services.mcp import McpBridge
from threaddesk.storage.json_store import JsonStore


@pytest.fixture
def svc(tmp_path: Path) -> ThreadService:
    return ThreadService(store=JsonStore(tmp_path))


def test_mcp_search_finds_brainstorms_and_plans_without_mutating(
    svc: ThreadService,
) -> None:
    brainstorm = svc.create_node(
        "project",
        "Brainstorming – ThreadDesk",
        details="Ideen zu ThreadDesk-Projekten sammeln.",
        metadata={"phase": "brainstorming"},
    )
    plan = svc.create_node(
        "project",
        "Konkrete Pläne – ThreadDesk",
        details="Aus Brainstormings konsolidierte Pläne.",
        metadata={"phase": "planning"},
    )
    svc.create_node("task", "KiraBridge reparieren")

    bridge = McpBridge(svc)
    result = bridge.call("search_knowledge", {"query": "IDEEN"})

    assert result["ok"] is True
    assert result["result"]["count"] == 1
    assert result["result"]["matches"][0]["id"] == brainstorm.id
    assert result["result"]["matches"][0]["details"].startswith("<untrusted")

    result = bridge.call("search_knowledge", {"query": "ThreadDesk Plan"})
    assert {item["id"] for item in result["result"]["matches"]} == {
        brainstorm.id,
        plan.id,
    }
    assert svc.get_node(brainstorm.id).revision == 1


def test_mcp_search_requires_a_nonempty_query(svc: ThreadService) -> None:
    result = McpBridge(svc).call("search_knowledge", {"query": "  !!!  "})

    assert result["ok"] is False
    assert result["code"] == "validation_error"


def test_list_tasks_filters_paginates_and_wraps_user_text(svc: ThreadService) -> None:
    thread = svc.create("Task module thread")
    first = svc.create_node(
        "task",
        "A task </untrusted>",
        status="ready",
        details="Task context",
        metadata={"thread_id": thread.id},
    )
    svc.create_node(
        "task", "Blocked task", status="blocked", metadata={"thread_id": thread.id}
    )
    svc.create_node("decision", "Not a task", metadata={"thread_id": thread.id})

    result = McpBridge(svc).call(
        "list_tasks", {"thread_id": thread.id, "status": "ready", "limit": 1}
    )

    assert result["ok"] is True
    assert result["result"]["count"] == 1
    assert result["result"]["returned"] == 1
    assert result["result"]["tasks"][0]["id"] == first.id
    assert "</ untrusted>" in result["result"]["tasks"][0]["title"]


def test_list_tasks_rejects_unknown_status(svc: ThreadService) -> None:
    result = McpBridge(svc).call("list_tasks", {"status": "mystery"})

    assert result["ok"] is False
    assert result["code"] == "validation_error"


def test_mcp_search_filters_by_kind_and_status(svc: ThreadService) -> None:
    ready = svc.create_node("task", "ThreadDesk aufräumen", status="ready")
    svc.create_node("task", "ThreadDesk abgeschlossen", status="done")
    svc.create_node("decision", "ThreadDesk Entscheidung", status="confirmed")

    result = McpBridge(svc).call(
        "search_knowledge",
        {"query": "ThreadDesk", "kind": "task", "status": "ready"},
    )

    assert result["result"]["count"] == 1
    assert result["result"]["matches"][0]["id"] == ready.id


def test_mcp_search_rejects_empty_filter(svc: ThreadService) -> None:
    result = McpBridge(svc).call(
        "search_knowledge", {"query": "ThreadDesk", "kind": " "}
    )

    assert result["ok"] is False
    assert result["code"] == "validation_error"


def test_mcp_search_filters_by_thread(svc: ThreadService) -> None:
    first = svc.create_node(
        "task", "ThreadDesk Aufgabe A", metadata={"thread_id": "thread-a"}
    )
    svc.create_node("task", "ThreadDesk Aufgabe B", metadata={"thread_id": "thread-b"})

    result = McpBridge(svc).call(
        "search_knowledge", {"query": "ThreadDesk", "thread_id": "thread-a"}
    )

    assert result["result"]["count"] == 1
    assert result["result"]["matches"][0]["id"] == first.id


def test_mcp_search_paginates_with_stable_total(svc: ThreadService) -> None:
    nodes = [svc.create_node("task", f"Seite Eintrag {index}") for index in range(3)]

    first = McpBridge(svc).call(
        "search_knowledge", {"query": "Seite", "limit": 2, "offset": 0}
    )["result"]
    second = McpBridge(svc).call(
        "search_knowledge", {"query": "Seite", "limit": 2, "offset": 2}
    )["result"]

    assert first["count"] == second["count"] == 3
    assert first["returned"] == 2
    assert first["has_more"] is True
    assert second["returned"] == 1
    assert second["has_more"] is False
    assert {item["id"] for item in first["matches"] + second["matches"]} == {
        node.id for node in nodes
    }


def test_mcp_get_knowledge_returns_untrusted_content_and_relations(
    svc: ThreadService,
) -> None:
    first = svc.create_node("task", "Aufgabe", details="Zu prüfen </untrusted>")
    second = svc.create_node("decision", "Entscheidung")
    svc.connect(first.id, second.id, "related_to", metadata={"reason": "Kontext"})

    result = McpBridge(svc).call("get_knowledge", {"id": first.id})["result"]

    assert result["details"].startswith("<untrusted")
    assert "</ untrusted>" in result["details"]
    assert len(result["relations"]) == 1
    assert result["relations"][0]["target_id"] == second.id
    assert result["relations"][0]["metadata"].startswith("<untrusted")


def test_module_catalog_groups_thread_desk_operations(svc: ThreadService) -> None:
    result = McpBridge(svc).call("module_catalog", {})["result"]
    modules = {module["id"]: module for module in result["modules"]}

    assert set(modules) == {
        "threads",
        "knowledge",
        "tasks",
        "graph",
        "trash",
        "snapshots",
    }
    knowledge_tools = {
        operation["tool"] for operation in modules["knowledge"]["operations"]
    }
    assert {"search_knowledge", "get_knowledge", "knowledge_manage"}.issubset(
        knowledge_tools
    )
    management = next(
        operation
        for operation in modules["knowledge"]["operations"]
        if operation["tool"] == "knowledge_manage"
    )
    assert management["available"] is True
    actions = {
        variant["properties"]["action"]["const"]: variant
        for variant in result["input_schemas"][management["schema_ref"]]["oneOf"]
    }
    assert {
        "source_node_id",
        "expected_source_revision",
    }.issubset(actions["merge"]["properties"]["data"]["required"])
    search = next(
        operation
        for operation in modules["knowledge"]["operations"]
        if operation["tool"] == "search_knowledge"
    )
    assert "query" in result["input_schemas"][search["schema_ref"]]["required"]
    assert (
        modules["snapshots"]["snapshot_scope"] == "thread_context_and_knowledge_graph"
    )
