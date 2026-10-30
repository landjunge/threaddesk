"""Read-only proof of an already committed domain result.

The caller must first verify its original command envelope, workspace, scopes,
operation identity and request hash. These helpers never invoke a mutation,
open an application, refresh an index or retry a network/filesystem effect.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from threaddesk.core.errors import ManagementError
from threaddesk.core.models import Thread

FILE_ACTIONS = frozenset({"rename", "copy", "move", "assign", "trash", "restore", "open"})
TRASH_ACTIONS = {"trash.move": "move", "trash.restore": "restore", "trash.purge": "purge",
                 "trash.resolve_sync_conflict": "resolve_sync_conflict"}


def _unverifiable(command, *, status=None):
    raise ManagementError("owner_receipt_unverifiable", "No confirmed matching owner result is available",
                          command=command, **({"owner_status": status} if status is not None else {}))


def _hash(arguments):
    return hashlib.sha256(json.dumps(arguments, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _confirmed(command, result):
    if not isinstance(result, dict):
        _unverifiable(command)
    status = result.get("status")
    if status is not None and (not isinstance(status, str) or status in {"unknown", "pending", "failed", "queued", "running"}):
        _unverifiable(command, status=status if isinstance(status, str) else "invalid")
    return {**deepcopy(result), "duplicate": True}


def _management(svc, command, arguments):
    from threaddesk.services.thread_management import validate as thread_request
    from threaddesk.services.knowledge_memory import validate as knowledge_request
    from threaddesk.services.mcp import _public
    args = (thread_request if command == "thread_manage" else knowledge_request)(arguments)
    saved = svc.store.get_management_operation(args["operation_id"])
    if not saved:
        _unverifiable(command)
    if saved.get("request_hash") != _hash(args):
        raise ManagementError("operation_conflict", "Owner receipt belongs to a different request")
    result = _confirmed(command, saved.get("result"))
    if result.get("operation_id") != args["operation_id"] or result.get("action") != args["action"]:
        _unverifiable(command)
    if result.get("thread") is not None:
        result["thread"] = _public(Thread.from_dict(result["thread"]))
    return result


def _library(svc, command, arguments):
    from threaddesk.services.library_files import LibraryFileService
    if (not isinstance(arguments, dict) or not isinstance(arguments.get("action"), str)
            or arguments["action"] not in FILE_ACTIONS):
        _unverifiable(command)
    files = LibraryFileService(svc.store)
    # Both are inert owner lookups. The first validates the exact original
    # request, even if the live object has since changed or been removed.
    verified = files.verify_recorded_request(arguments)
    if not verified.get("found"):
        _unverifiable(command)
    readback = files.operation_status(arguments["operation_id"])
    if not readback.get("found"):
        _unverifiable(command)
    result = _confirmed(command, readback.get("result"))
    if result.get("action") != arguments["action"] or result.get("operation_id") != arguments["operation_id"]:
        _unverifiable(command)
    if arguments["action"] == "open":
        if result.get("status") != "launch_requested" or result.get("record_id") != arguments["id"]:
            _unverifiable(command, status=result.get("status"))
    elif not isinstance(result.get("record"), dict):
        _unverifiable(command)
    return result


def _handoff(svc, arguments):
    from threaddesk.services.thread_management import ID
    command = "issue_handoff"
    if (not isinstance(arguments, dict)
            or set(arguments) - {"operation_id", "id", "expected_revision", "target"}
            or not {"operation_id", "id", "expected_revision"} <= set(arguments)
            or any(not isinstance(arguments[key], str) or not ID.fullmatch(arguments[key]) for key in ("operation_id", "id"))
            or type(arguments["expected_revision"]) is not int or arguments["expected_revision"] < 0):
        raise ManagementError("validation_error", "Invalid issued-handoff receipt request")
    target = arguments.get("target", "generic")
    if not isinstance(target, str) or target not in {"generic", "grok", "codex", "claude", "gnom-hub-v1"}:
        raise ManagementError("validation_error", "Invalid issued-handoff target")
    expected = _hash({**arguments, "target": target})
    # Do not construct IssuedHandoffs: source_roots() and current originals are
    # irrelevant to proof of an already issued immutable handoff.
    records = [row for row in svc.store.list_issued_handoffs()
               if row.get("operation_id") == arguments["operation_id"]]
    if len(records) != 1:
        _unverifiable(command)
    record = records[0]
    if record.get("request_hash") != expected:
        raise ManagementError("operation_conflict", "Issued handoff belongs to a different request")
    handoff = record.get("handoff")
    if not isinstance(handoff, dict) or record.get("content_hash") != _hash(handoff):
        _unverifiable(command)
    return _confirmed(command, {**handoff, "content_hash": record["content_hash"]})


def verify_owner_result(svc, command_id, arguments):
    """Return a confirmed matching owner result, or reject without a write.

    Module own-record writes currently have no separately operation-bound owner
    receipt. Their current data/revision is not proof of which request wrote it.
    Unlisted effects intentionally remain unverifiable instead of being replayed.
    """
    if not isinstance(command_id, str):
        raise ManagementError("validation_error", "An exact command identity is required")
    if command_id in {"thread_manage", "knowledge_manage"}:
        return _management(svc, command_id, arguments)
    if command_id == "library_manage":
        return _library(svc, command_id, arguments)
    if command_id == "graph_view.manage":
        from threaddesk.services.graph_views import GraphViewService
        verified = GraphViewService(svc.store).verify_recorded_request(arguments)
    elif command_id in TRASH_ACTIONS:
        from threaddesk.services.trash import TrashService
        if not isinstance(arguments, dict) or "action" in arguments:
            raise ManagementError("validation_error", "Trash command supplies its own action binding")
        verified = TrashService(svc.store).verify_recorded_request(
            {"action": TRASH_ACTIONS[command_id], **arguments})
    elif command_id == "issue_handoff":
        return _handoff(svc, arguments)
    else:
        _unverifiable(command_id)
    if not verified.get("found"):
        _unverifiable(command_id)
    return _confirmed(command_id, verified.get("result"))
