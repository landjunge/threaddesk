"""Machine-readable ThreadDesk capability modules for connected clients."""

from __future__ import annotations

from typing import Any


MODULES: tuple[dict[str, Any], ...] = (
    {
        "id": "threads",
        "name": "Threads und Projekte",
        "purpose": "Threads finden, lesen, organisieren und verwalten.",
        "operations": [
            {"tool": "list_threads", "mode": "read"},
            {"tool": "get_thread", "mode": "read"},
            {
                "tool": "thread_manage",
                "mode": "write",
                "actions": [
                    "create",
                    "update",
                    "set_note",
                    "organize",
                    "archive",
                    "unarchive",
                    "delete",
                ],
            },
        ],
    },
    {
        "id": "knowledge",
        "name": "Brainstormings und Pläne",
        "purpose": "Wissenseinträge suchen, prüfen, anlegen und überarbeiten.",
        "operations": [
            {"tool": "search_knowledge", "mode": "read"},
            {"tool": "get_knowledge", "mode": "read"},
            {"tool": "get_reentry", "mode": "read"},
            {
                "tool": "knowledge_manage",
                "mode": "write",
                "actions": [
                    "record",
                    "update",
                    "transition",
                    "supersede",
                    "merge",
                    "resolve_question",
                    "save_reentry",
                ],
            },
        ],
    },
    {
        "id": "tasks",
        "name": "Aufgaben",
        "purpose": "Aufgaben nach Status und Thread finden und ihren Stand verwalten.",
        "operations": [
            {"tool": "list_tasks", "mode": "read"},
            {
                "tool": "knowledge_manage",
                "mode": "write",
                "actions": ["record", "update", "transition", "archive", "unarchive"],
            },
        ],
        "scope": "Tasks are stored in the knowledge graph and belong to a thread.",
    },
    {
        "id": "graph",
        "name": "Wissensgraph",
        "purpose": "Verknüpfungen zwischen Wissenseinträgen lesen und erstellen.",
        "operations": [
            {"tool": "get_knowledge", "mode": "read", "includes": ["relations"]},
            {"tool": "knowledge_manage", "mode": "write", "actions": ["link", "merge"]},
        ],
    },
    {
        "id": "trash",
        "name": "Papierkorb",
        "purpose": "Archivierte Einträge finden und wiederherstellen.",
        "operations": [
            {"tool": "list_trash", "mode": "read"},
            {
                "tool": "knowledge_manage",
                "mode": "write",
                "actions": ["archive", "unarchive"],
            },
        ],
    },
    {
        "id": "snapshots",
        "name": "Snapshots",
        "purpose": "Thread-Kontext und Wissensgraph vor Änderungen sichern, Verlauf lesen und wiederherstellen.",
        "operations": [
            {"tool": "list_snapshots", "mode": "read"},
            {
                "tool": "thread_manage",
                "mode": "write",
                "actions": ["snapshot", "restore_snapshot"],
            },
        ],
        "snapshot_scope": "thread_context_and_knowledge_graph",
    },
)


def catalog(
    available_tools: set[str], tool_schemas: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Return discoverable module operations and their live invocation schemas."""
    tool_schemas = tool_schemas or {}
    modules = []
    for module in MODULES:
        operations = [
            {
                **operation,
                "available": operation["tool"] in available_tools,
                **(
                    {"schema_ref": operation["tool"]}
                    if operation["tool"] in tool_schemas
                    else {}
                ),
            }
            for operation in module["operations"]
        ]
        modules.append(
            {
                **module,
                "available": all(operation["available"] for operation in operations),
                "operations": operations,
            }
        )
    referenced_tools = {
        operation["tool"]
        for module in MODULES
        for operation in module["operations"]
        if operation["tool"] in tool_schemas
    }
    return {
        "modules": modules,
        "input_schemas": {
            tool: tool_schemas[tool] for tool in sorted(referenced_tools)
        },
    }
