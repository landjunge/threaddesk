"""Compatibility registrations reuse existing MCP domain adapters and schemas."""
from __future__ import annotations

import copy

from threaddesk.services.commands.model import CommandSpec

# Effect declarations are deliberately explicit. An unreviewed future legacy
# tool must not silently become a read, bypass revision checks or be executed.
_DATA = {"switch_thread", "add_note", "save_snapshot", "restore_snapshot", "generate_prompt"}
_NATIVE = {"thread_manage", "knowledge_manage", "issue_handoff", "bind_handoff_run",
           "record_handoff_question", "answer_handoff_question", "library_manage", "library_receive"}
_READ = {"library_receive_status", "library_search", "library_file_info", "get_reentry",
         "get_issued_handoff", "thread_operation_status", "list_threads", "get_thread",
         "current_thread", "list_snapshots", "list_gnom_jobs", "check_gate", "list_returns",
         "get_return", "library_query"}
_EXTERNAL = {"export_handoff", "import_return", "export_grok", "export_gnom",
             "bind_gnom_job", "receive_gnom_callback", "dashboard", "review_return"}
_TARGETS = {"switch_thread": "id", "add_note": "id", "save_snapshot": "id", "restore_snapshot": "snapshot",
            "generate_prompt": "id", "export_handoff": "id", "export_grok": "id", "export_gnom": "id"}


def specifications():
    from threaddesk.services.mcp import TOOLS, McpBridge
    for tool in TOOLS:
        name = tool["name"]
        if name in {"command_catalog", "command_invoke", "command_query"}:
            continue
        if name not in _DATA | _NATIVE | _READ | _EXTERNAL:
            raise RuntimeError("Legacy command needs an effect review: " + name)
        schema = copy.deepcopy(tool["inputSchema"])
        # Composed contracts (the receiver's action-specific oneOf) already
        # close each branch. Closing their property-less parent would reject
        # every valid action, including the very first upload request.
        if not any(key in schema for key in ("oneOf", "anyOf", "allOf", "$ref")):
            schema.setdefault("additionalProperties", False)
        effect = "read" if name in _READ else "data" if name in _DATA else "domain" if name in _NATIVE else "external"
        def handle(svc, args, selected=name):
            return McpBridge(svc)._dispatch(selected, args)
        yield CommandSpec(name, _module(name), tool["description"], schema, handle,
                          effect=effect, scope="workspace.read" if effect == "read" else "workspace.write",
                          revision_target=_TARGETS.get(name), native_contract=name in _NATIVE,
                          affects_index=name in {"thread_manage", "add_note", "save_snapshot", "restore_snapshot", "generate_prompt", "review_return"})


def _module(name):
    for needle, domain in (("library", "library"), ("handoff", "handoffs"), ("return", "returns"),
                           ("gnom", "handoffs"), ("grok", "handoffs"), ("snapshot", "snapshots"),
                           ("knowledge", "knowledge"), ("gate", "gate")):
        if needle in name:
            return domain
    return "threads"
