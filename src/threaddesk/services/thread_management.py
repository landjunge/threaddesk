"""Revision-bound local thread administration. Never dispatches agent work."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from threaddesk.core.errors import InvalidState, ManagementError, NotFound
from threaddesk.core.models import now_iso
from threaddesk.core.secrets import reject_secrets

FIELDS = {
    "create": {"title", "description", "project_id", "parent_thread_id"},
    "update": {"title", "description", "status"},
    "set_note": {"text", "append"},
    "add_file": {"path"}, "remove_file": {"path"},
    "organize": {"project_id", "parent_thread_id", "related_thread_ids"},
    "archive": set(), "unarchive": set(), "delete": set(), "switch": set(),
}
REQUIRED = {"create": {"title"}, "set_note": {"text"}, "add_file": {"path"}, "remove_file": {"path"}}
ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def organization(thread) -> dict:
    saved = thread.context.extra.get("organization") or {}
    return {"project_id": saved.get("project_id"), "parent_thread_id": saved.get("parent_thread_id"), "related_thread_ids": list(saved.get("related_thread_ids") or [])}


def _invalid(message="Ungültige Verwaltungsanfrage."):
    raise ManagementError("validation_error", message)


def validate(arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict) or set(arguments) - {"operation_id", "action", "id", "expected_revision", "data"}:
        _invalid()
    args = dict(arguments)
    if not isinstance(args.get("operation_id"), str) or not ID.fullmatch(args["operation_id"]):
        _invalid("operation_id muss 1–128 Buchstaben, Zahlen, Unterstriche oder Bindestriche enthalten.")
    action = args.get("action")
    if action not in FIELDS:
        _invalid("Unbekannte Verwaltungsaktion.")
    revision = args.get("expected_revision")
    if type(revision) is not int or revision < 0:
        _invalid("expected_revision muss eine nichtnegative ganze Zahl sein.")
    if action == "create":
        if revision != 0 or "id" in args:
            _invalid("create benötigt expected_revision=0 und keine id.")
    elif not isinstance(args.get("id"), str) or not ID.fullmatch(args["id"]):
        _invalid("Eine exakte Thread-ID ist erforderlich.")
    data = args.setdefault("data", {})
    if not isinstance(data, dict) or set(data) - FIELDS[action] or REQUIRED.get(action, set()) - set(data):
        _invalid("data enthält fehlende oder unbekannte Aktionsfelder.")
    if action in {"update", "organize"} and not data:
        _invalid("Mindestens ein Änderungsfeld ist erforderlich.")
    for key, value in data.items():
        if key == "append":
            if type(value) is not bool:
                _invalid("append muss ein boolescher Wert sein.")
        elif key == "related_thread_ids":
            if not isinstance(value, list) or len(value) > 100 or any(not isinstance(item, str) or not ID.fullmatch(item) for item in value) or len(set(value)) != len(value):
                _invalid("related_thread_ids benötigt höchstens 100 unterschiedliche exakte IDs.")
        elif key in {"project_id", "parent_thread_id"}:
            if value is not None and (not isinstance(value, str) or not ID.fullmatch(value)):
                _invalid("Zuordnung benötigt eine exakte ID oder null.")
        elif not isinstance(value, str) or len(value) > (100000 if key == "text" else 10000):
            _invalid("Textfeld fehlt, hat den falschen Typ oder ist zu lang.")
    reject_secrets(json.dumps(data, ensure_ascii=False))
    return args


def _organize(svc, thread_id, fields):
    thread = svc.store.get_thread(thread_id)
    current = organization(thread)
    current.update(fields)
    project = current["project_id"]
    if project is not None and svc.store.get_node(project).kind != "project":
        _invalid("project_id muss auf einen Projektknoten verweisen.")
    for linked in current["related_thread_ids"]:
        if linked == thread_id:
            _invalid("Ein Thread kann nicht mit sich selbst verknüpft werden.")
        svc.store.get_thread(linked)
    visited = {thread_id}
    parent = current["parent_thread_id"]
    while parent:
        if parent in visited:
            _invalid("Zyklische Elternzuordnung ist nicht erlaubt.")
        visited.add(parent)
        parent = organization(svc.store.get_thread(parent))["parent_thread_id"]
    thread.context.extra["organization"] = current
    thread.updated_at = now_iso()
    svc.store.save_thread(thread)
    svc.bus.emit("thread.organized", {"id": thread.id, "revision": thread.revision})
    return thread


def manage(svc, arguments: dict[str, Any]) -> dict[str, Any]:
    args = validate(arguments)
    digest = hashlib.sha256(json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    store = svc.store
    try:
        with store.transaction():
            saved = store.get_management_operation(args["operation_id"])
            if saved:
                if saved["request_hash"] != digest:
                    raise ManagementError("operation_conflict", "Operationskennung wurde bereits mit anderem Inhalt verwendet.")
                return {**saved["result"], "duplicate": True}
            action, data = args["action"], args["data"]
            thread = None
            if action != "create":
                thread = store.get_thread(args["id"])
                if thread.revision != args["expected_revision"]:
                    raise ManagementError("revision_conflict", "Thread wurde zwischenzeitlich geändert.", expected_revision=args["expected_revision"], actual_revision=thread.revision)
            if action == "create":
                thread = svc.create(data["title"], data.get("description", ""))
                if set(data) & {"project_id", "parent_thread_id"}:
                    thread = _organize(svc, thread.id, {key: data[key] for key in ("project_id", "parent_thread_id") if key in data})
            elif action == "update":
                if "title" in data:
                    thread = svc.rename(thread.id, data["title"])
                if "description" in data:
                    thread = svc.set_description(data["description"], thread.id)
                if "status" in data:
                    thread = svc.set_status(data["status"], thread.id)
            elif action == "set_note":
                thread = svc.set_note(data["text"], thread.id, append=data.get("append", False))
            elif action == "add_file":
                thread = svc.add_file(data["path"], thread.id)
            elif action == "remove_file":
                thread = svc.remove_file(data["path"], thread.id)
            elif action == "organize":
                thread = _organize(svc, thread.id, data)
            elif action in {"archive", "unarchive", "switch"}:
                thread = getattr(svc, action)(thread.id)
            elif action == "delete":
                svc.delete(thread.id)
            result = {"operation_id": args["operation_id"], "action": action, "duplicate": False, "thread_id": thread.id, "revision": thread.revision, "deleted": action == "delete", "thread": None if action == "delete" else thread.to_dict()}
            store.save_management_operation(args["operation_id"], {"request_hash": digest, "recorded_at": now_iso(), "result": result})
            return result
    except ManagementError:
        raise
    except NotFound as exc:
        raise ManagementError("not_found", "Thread oder Zuordnungsziel wurde nicht gefunden.") from exc
    except InvalidState as exc:
        raise ManagementError("invalid_state", str(exc)) from exc
