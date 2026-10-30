"""Workspace-bound dispatch, durable operation lookup and bounded readback."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from threaddesk.core.errors import ManagementError, NotFound, ThreadDeskError
from threaddesk.core.models import now_iso
from threaddesk.services.commands.registry import CommandRegistry
from threaddesk.services.commands.model import workspace_identity
from threaddesk.services.commands.validation import command_request_digest, encode, envelope, invalid, validate

RESULT_BUDGET = 24000


@dataclass(frozen=True)
class _Replay:
    result: Any


class CommandApplication:
    def __init__(self, service, *, allowed_scopes=None, registry=None, result_budget=RESULT_BUDGET, transport="local"):
        self.service, self.store = service, service.store
        self.scopes = None if allowed_scopes is None else frozenset(allowed_scopes)
        self.registry = registry or CommandRegistry(self.store)
        self.result_budget = result_budget
        self.transport = transport

    @property
    def workspace_id(self):
        return workspace_identity(self.store)

    def catalog(self, *, limit=10, offset=0):
        if type(limit) is not int or not 1 <= limit <= 25 or type(offset) is not int or not 0 <= offset <= 100000:
            invalid("Invalid catalogue page")
        rows = self.registry.records(self.scopes, self.transport)
        selected, size = [], 0
        for row in rows[offset:offset + limit]:
            count = len(encode(row).encode())
            if selected and size + count > RESULT_BUDGET:
                break
            selected.append(row)
            size += count
        following = offset + len(selected)
        return {"schema": "threaddesk.command-catalog.v1", "version": 1,
                "workspace_id": self.workspace_id, "revision": self.registry.revision(self.scopes, self.transport),
                "commands": selected, "total": len(rows), "offset": offset,
                "next_offset": following if following < len(rows) else None,
                "transport_note": "KiraBridge native contracts remain external; authorized visible CLI uses the same commands."}

    @staticmethod
    def _operation_key(identity):
        return "command-" + hashlib.sha256(identity.encode()).hexdigest()

    def operation(self, identity):
        from threaddesk.services.commands.validation import ID
        if not isinstance(identity, str) or not ID.fullmatch(identity):
            invalid("Invalid operation identity")
        saved = self._receipt(self._operation_key(identity))
        return {"operation_id": identity, "found": saved is not None,
                "state": saved.get("state") if saved else None,
                "result": saved.get("result") if saved else None,
                "error": saved.get("error") if saved else None,
                "safe_to_retry": not saved or saved.get("state") == "rejected"}

    def call(self, request, *, read_only=False):
        from threaddesk.services.commands.errors import normalized
        try:
            return self._call(request, read_only=read_only)
        except Exception as exc:
            error = normalized(exc)
            if error is exc:
                raise
            raise error from exc

    def _prepare(self, request, *, read_only=False, check_catalog=True):
        req = envelope(request)
        if req["workspace_id"] != self.workspace_id:
            raise ManagementError("workspace_mismatch", "Command belongs to another workspace")
        spec = self.registry.get(req["command"])
        availability = self.registry.availability(spec, self.scopes, self.transport)
        if availability != "available":
            raise ManagementError(availability, "Command is not currently available")
        current_revision = self.registry.revision(self.scopes, self.transport)
        if check_catalog and "catalog_revision" in req and req["catalog_revision"] != current_revision:
            raise ManagementError("catalog_conflict", "Refresh the command catalogue before invoking")
        if read_only and spec.effect != "read":
            raise ManagementError("read_only_required", "This adapter only accepts read commands")
        args = dict(req.get("arguments", {}))
        if spec.effect == "read" and "as_of" in spec.schema.get("properties", {}):
            from datetime import datetime, timezone
            stamp = args.get("as_of", req.get("snapshot_at", now_iso()))
            try:
                parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("timezone required")
            except (TypeError, ValueError, AttributeError):
                invalid("An offset-qualified read snapshot timestamp is required")
            args["as_of"] = parsed.astimezone(timezone.utc).isoformat()
            req["snapshot_at"] = args["as_of"]
        if spec.effect != "read":
            if not req.get("operation_id"):
                invalid("Mutations require an operation_id")
            if spec.native_contract:
                for field in ("operation_id", "expected_revision"):
                    if field not in spec.schema.get("properties", {}):
                        continue
                    if field in req:
                        if field in args and args[field] != req[field]:
                            invalid("Envelope and domain operation bindings differ", field=field)
                        args[field] = req[field]
        validate(spec.schema, args)
        return req, spec, args, current_revision

    def _call(self, request, *, read_only=False):
        req, spec, args, current_revision = self._prepare(request, read_only=read_only)
        if spec.effect == "read":
            result = (self.catalog(**args) if spec.id == "command.catalog"
                      else self.operation(args["operation_id"]) if spec.id == "command.operation"
                      else self._execute(spec, args))
            return self._response(result, req, current_revision)
        digest = self._digest(req, spec, args)
        key = self._operation_key(req["operation_id"])
        if spec.effect == "data" and not spec.native_contract:
            with self.service.bus.defer_until_commit(), self.store.transaction():
                previous = self._previous(key, digest)
                if previous is not None:
                    return self._response(previous, req, current_revision, duplicate=True)
                self._check_revision(spec, args, req)
                result = self._execute(spec, args)
                self._save(key, digest, "complete", result=result)
        else:
            # A committed reservation precedes network/filesystem/OS effects.
            # Uncertain delivery is never automatically repeated.
            with self.store.transaction():
                previous = self._previous(key, digest)
                if previous is not None:
                    return self._response(previous, req, current_revision, duplicate=True)
                self._check_revision(spec, args, req)
                self._save(key, digest, "pending")
            try:
                if spec.id == "backup.create":
                    result = self._execute(spec, args, backup_reservation={
                        "operation_id": req["operation_id"], "expected_revision": req.get("expected_revision")})
                else:
                    result = self._execute(spec, args)
            except Exception as exc:
                from threaddesk.services.commands.errors import normalized
                translated = normalized(exc)
                error = {"code": translated.code, "error_type": type(exc).__name__}
                with self.store.transaction():
                    self._save(key, digest, "failed", error=error)
                raise
            with self.store.transaction():
                self._save(key, digest, "complete", result=result)
        response = self._response(result, req, current_revision, duplicate=False)
        if spec.affects_index:
            from threaddesk.services.library_refresh import refresh_existing
            projection = refresh_existing(self.store)
            response["projections"] = {"index": {key: projection[key] for key in ("status", "error") if key in projection}}
        return response

    def _execute(self, spec, args, *, backup_reservation=None):
        if spec.id == "command.reconcile":
            return self.reconcile(args["request"])
        if spec.id == "backup.create":
            return spec.handler(self.service, args, command_reservation=backup_reservation)
        return spec.handler(self.service, args)

    def _digest(self, req, spec, args):
        return command_request_digest(self.workspace_id, spec.id, args, req["operation_id"],
                                      req.get("expected_revision"))

    def reconcile(self, original_request):
        """Adopt a proven owner receipt without ever repeating its effect."""
        req, spec, args, _revision = self._prepare(original_request, check_catalog=False)
        if spec.effect == "read" or spec.id == "command.reconcile":
            invalid("Only an original domain mutation can be reconciled")
        key, digest = self._operation_key(req["operation_id"]), self._digest(req, spec, args)
        saved = self._receipt(key)
        if saved is None:
            raise ManagementError("operation_not_found", "No command reservation exists for this request")
        if saved["request_hash"] != digest:
            raise ManagementError("operation_conflict", "Original command request does not match its reservation")
        if saved["state"] == "complete":
            return {"operation_id": req["operation_id"], "state": "complete", "adopted": False,
                    "external_effect_repeated": False, "result": saved["result"]}
        from threaddesk.services.commands.reconciliation import verify_owner_result
        result = verify_owner_result(self.service, spec.id, args)
        with self.store.transaction():
            current = self._receipt(key)
            if current["request_hash"] != digest:
                raise ManagementError("operation_conflict", "Command reservation changed")
            if current["state"] != "complete":
                self._save(key, digest, "complete", result=result)
            else:
                result = current["result"]
        return {"operation_id": req["operation_id"], "state": "complete", "adopted": True,
                "external_effect_repeated": False, "result": result}

    def _save(self, key, digest, state, *, result=None, error=None):
        # Store receipts are append-only on SQLite. Each transition is a new
        # immutable record; a crash cannot erase the prior reservation.
        storage_key = key + "-" + state
        self.store.save_management_operation(storage_key, {"request_hash": digest, "recorded_at": now_iso(),
            "state": state, "result": result, "error": error, "kind": "command",
            "storage_operation_id": storage_key})

    def _receipt(self, key):
        for state in ("complete", "failed", "pending"):
            saved = self.store.get_management_operation(key + "-" + state)
            if saved is not None:
                return saved
        return None

    def _previous(self, key, digest):
        previous = self._receipt(key)
        if previous is None:
            return None
        if previous["request_hash"] != digest:
            raise ManagementError("operation_conflict", "Operation identity already has a different request")
        if previous.get("state") != "complete":
            raise ManagementError("operation_unconfirmed", "Read the durable operation status before continuing",
                                  state=previous.get("state", "unknown"))
        # Null is a valid successful domain result, so use an explicit wrapper.
        return _Replay(previous["result"])

    def _check_revision(self, spec, args, req):
        target = spec.revision_target
        if not target:
            return
        expected = req.get("expected_revision")
        if type(expected) is not int:
            invalid("An expected_revision is required for this command")
        if target == "create":
            if expected != 0:
                raise ManagementError("revision_conflict", "Creation requires revision 0")
            return
        if target.startswith("node:"):
            node = self.store.get_node(args[target.split(":", 1)[1]])
            if expected != node.revision:
                raise ManagementError("revision_conflict", "Graph node changed since it was read",
                                      actual_revision=node.revision, expected_revision=expected)
            return
        if target.startswith("thread_in_trash:"):
            field = target.split(":", 1)[1]
            thread = self.store.get_thread(args[field], include_trashed=True)
            if expected != thread.revision:
                raise ManagementError("revision_conflict", "Thread changed since lifecycle review",
                                      actual_revision=thread.revision, expected_revision=expected)
            return
        if target == "snapshot":
            identity = self.store.get_snapshot(args["snap_id"]).thread_id
        else:
            identity = args.get(target)
            if not identity:
                invalid("An exact thread identity is required", field=target)
        thread = self.store.get_thread(identity)
        if expected != thread.revision:
            raise ManagementError("revision_conflict", "Thread changed since it was read",
                                  actual_revision=thread.revision, expected_revision=expected)

    def _response(self, result, req, revision, *, duplicate=None):
        if isinstance(result, _Replay):
            result = result.result
        body = encode(result)
        digest = hashlib.sha256(body.encode()).hexdigest()
        if req.get("result_digest") and req["result_digest"] != digest:
            raise ManagementError("result_changed", "Readback changed; restart from result_offset 0")
        response = {"schema": "threaddesk.command-result.v1", "workspace_id": self.workspace_id,
                    "catalog_revision": revision, "command": req["command"], "result_digest": digest}
        if "snapshot_at" in req:
            response["snapshot_at"] = req["snapshot_at"]
        if duplicate is not None:
            response.update(duplicate=duplicate, operation_id=req["operation_id"])
        offset = req.get("result_offset", 0)
        if offset == 0 and len(body.encode()) <= self.result_budget:
            return {**response, "result": result, "next_offset": None}
        page = body[offset:offset + self.result_budget // 4]
        following = offset + len(page)
        return {**response, "result_page": page, "encoding": "json-text-codepoint-pages",
                "offset": offset, "total": len(body),
                "next_offset": following if following < len(body) else None}
