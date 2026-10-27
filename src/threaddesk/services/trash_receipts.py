"""Inventory and minimize exact object copies in durable operation results.

The public plan contains IDs, hashes and JSON paths, never old result bodies.
Unknown attributable content and unresolved commands block the purge. Audit
requests/statuses are retained; a replay explicitly returns reduced content.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from threaddesk.storage.purge_receipts import SCHEMA, digest


MARKER = "threaddesk.purged-payload.v1"
ENTRY_FIELDS = {"version", "trash_id", "kind", "object_id", "workspace_id", "generation", "revision",
                "state", "deleted_at", "actor_evidence", "object_revision", "object_digest",
                "reference_digest", "restored_at", "purged_at", "content_purged"}
ENTRY_REMOVED = {"references", "title", "actor", "original_status"}
CONTROL_FIELDS = {"operation_id", "action", "duplicate", "thread_id", "revision", "deleted", "thread",
                  "snapshot", "node", "relation", "entry", "unresolved_references", "external_originals_preserved",
                  "content_purged", "purged_payloads"}
TEXT_FIELDS = {"text", "prompt", "content", "summary", "details", "description", "notes", "excerpt",
               "body", "html", "markdown", "output", "message", "answer", "reply", "transcript", "result"}


def _has_text(value):
    if isinstance(value, str):
        return bool(value)
    if isinstance(value, dict):
        return any(_has_text(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_text(item) for item in value)
    return False


def _identified_owner(value):
    if isinstance(value.get("thread_id"), str):
        return True
    return isinstance(value.get("id"), str) and (
        isinstance(value.get("context"), dict)
        or {"notes", "description", "organization", "revision"} <= set(value)
        or {"kind", "metadata", "title"} <= set(value)
        or {"source_id", "target_id", "kind"} <= set(value))


def minimal_entry(entry):
    return {**{key: deepcopy(value) for key, value in entry.items() if key in ENTRY_FIELDS},
            "content_purged": True}


def _payload(kind, object_id, revision=None):
    value = {"schema": MARKER, "kind": kind, "object_id": object_id, "content_purged": True}
    if type(revision) is int:
        value["revision"] = revision
    return value


class _Reducer:
    def __init__(self, kind, object_id):
        self.kind, self.object_id = kind, object_id
        self.paths, self.blockers, self.nodes = [], [], 0

    def walk(self, value, path="$", depth=0, owned=False, owns_target=False):
        self.nodes += 1
        if depth > 40 or self.nodes > 100000:
            raise ValueError("receipt_structure_limit")
        if isinstance(value, list):
            return [self.walk(item, f"{path}[{i}]", depth + 1, owned, owns_target) for i, item in enumerate(value)]
        if not isinstance(value, dict):
            return deepcopy(value)
        if value.get("schema") == MARKER:
            return deepcopy(value)
        # Historical lifecycle generations and move/restore receipts retain
        # their execution state, but no longer retain titles/paths/actors.
        if (value.get("kind") == self.kind and value.get("object_id") == self.object_id
                and isinstance(value.get("trash_id"), str)):
            if set(value) - ENTRY_FIELDS - ENTRY_REMOVED:
                self.blockers.append({"path": path, "reason": "unknown_lifecycle_result_field"})
            reduced = minimal_entry(value)
            if reduced != value:
                self.paths.append(path)
            return reduced
        shape = None
        if self.kind == "thread":
            if value.get("id") == self.object_id and (
                    isinstance(value.get("context"), dict)
                    or {"notes", "description", "organization", "revision"} <= set(value)):
                shape = "thread"
            elif value.get("thread_id") == self.object_id and "id" in value and (
                    "context" in value or {"id", "label"} <= set(value)
                    and set(value) <= {"id", "label", "thread_id", "created_at"}):
                shape = "snapshot"
            elif value.get("thread_id") == self.object_id and {"id", "content", "entry_type"} <= set(value):
                shape = "whiteboard"
        elif self.kind == "node" and value.get("id") == self.object_id and {"kind", "metadata", "title"} <= set(value):
            shape = "node"
        elif self.kind == "relation" and value.get("id") == self.object_id and {"source_id", "target_id", "kind"} <= set(value):
            shape = "relation"
        if shape:
            self.paths.append(path)
            return {**_payload(shape, value["id"], value.get("revision")), "id": value["id"],
                    **({"thread_id": self.object_id} if shape in {"snapshot", "whiteboard"} else {})}
        if value.get("id") == self.object_id and value.get("schema") != MARKER:
            self.blockers.append({"path": path, "reason": "unknown_target_result_shape"})
        owned = owned or _identified_owner(value)
        result = {}
        targeted = self.kind == "thread" and value.get("thread_id") == self.object_id
        owns_target = owns_target or targeted
        controls = CONTROL_FIELDS
        if targeted and value.get("action") in {"record", "supersede", "resolve_question", "save_reentry"}:
            from threaddesk.services.knowledge_memory import INSTRUCTION
            if value.get("instruction") == INSTRUCTION:
                controls = CONTROL_FIELDS | {"instruction", "node_id"}
        for key, child in value.items():
            # A result wrapper can contain identified payloads; a string in
            # that same position still has no inspectable ownership contract.
            textual = key in TEXT_FIELDS and not (key == "result" and isinstance(child, dict))
            if (not owned or owns_target) and textual and _has_text(child):
                self.blockers.append({"path": path + "." + key, "reason": "unattributed_text_result"})
            if targeted and key not in controls:
                self.blockers.append({"path": path + "." + key, "reason": "unknown_owned_result_field"})
            reduced = self.walk(child, path + "." + key, depth + 1, owned, owns_target)
            # Legacy thread administration and MCP adapters require this key
            # to be either a complete live thread or null. IDs remain beside it.
            if key == "thread" and isinstance(reduced, dict) and reduced.get("schema") == MARKER:
                result[key] = None
                result.setdefault("purged_payloads", []).append(reduced)
            else:
                result[key] = reduced
        return result


@dataclass
class ReceiptPlan:
    public: dict
    changes: list

    def apply(self, store, entry, *, operation_id, purged_at):
        for item in self.changes:
            evidence = {"schema": SCHEMA, "kind": entry["kind"], "object_id": entry["object_id"],
                        "trash_id": entry["trash_id"], "generation": entry["generation"],
                        "purge_operation_id": operation_id, "purged_at": purged_at,
                        "original_record_digest": item["record_digest"],
                        "original_result_digest": item["original_result_digest"],
                        "result_digest": item["result_digest"], "paths": item["paths"]}
            store.reduce_management_operation_for_purge(item["storage_operation_id"],
                expected_record_digest=item["record_digest"], reduced_result=item["result"], evidence=evidence)


def receipt_plan(store, kind, object_id, *, exempt_pending=None):
    records = store.list_management_operation_records()
    by_id = {item["storage_operation_id"]: item["record"] for item in records}
    changes, blockers, total = [], [], 0
    if len(records) > 20000:
        public = {"version": 1, "records": [], "blockers": [{"reason": "receipt_inventory_limit"}]}
        public["digest"] = digest(public)
        return ReceiptPlan(public, [])
    for item in records:
        identity, record = item["storage_operation_id"], item["record"]
        if not isinstance(record, dict):
            blockers.append({"storage_operation_id": identity, "reason": "receipt_invalid_record"})
            continue
        if ((record.get("kind") == "command" and record.get("state") == "pending")
                or identity.startswith("command-") and identity.endswith("-pending")):
            prefix = identity.removesuffix("-pending")
            valid = (record.get("kind") == "command" and record.get("state") == "pending"
                     and isinstance(record.get("request_hash"), str) and len(record["request_hash"]) == 64)
            finished = valid and any(isinstance(by_id.get(prefix + "-" + state), dict)
                and by_id[prefix + "-" + state].get("kind") == "command"
                and by_id[prefix + "-" + state].get("state") == state
                and by_id[prefix + "-" + state].get("request_hash") == record["request_hash"]
                for state in ("complete", "failed"))
            exempt = (valid and exempt_pending and identity == exempt_pending[0]
                      and record["request_hash"] in exempt_pending[1])
            if not finished and not exempt:
                blockers.append({"storage_operation_id": identity, "reason": "unconfirmed_command_requires_review"})
        try:
            total += len(str(record))
            if total > 32 * 1024 * 1024:
                raise ValueError("receipt_inventory_limit")
            reducer = _Reducer(kind, object_id)
            result = reducer.walk(record.get("result"))
            for problem in reducer.blockers:
                blockers.append({"storage_operation_id": identity, **problem})
            if isinstance(record.get("result"), str) and record["result"]:
                blockers.append({"storage_operation_id": identity, "path": "$", "reason": "unattributed_text_result"})
            if reducer.paths:
                changes.append({"storage_operation_id": identity, "record_digest": digest(record),
                                "original_result_digest": digest(record.get("result")),
                                "result_digest": digest(result), "paths": reducer.paths, "result": result})
        except (ValueError, TypeError, RecursionError) as exc:
            blockers.append({"storage_operation_id": identity, "reason": str(exc)[:80]})
            if total > 32 * 1024 * 1024:
                break
    public = {"version": 1, "records": [{key: value for key, value in item.items() if key != "result"}
                                          for item in changes], "blockers": blockers}
    public["digest"] = digest(public)
    return ReceiptPlan(public, changes)
