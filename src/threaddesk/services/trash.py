"""Reversible object lifecycle, shared by all application transports.

Payloads and their IDs stay in their original stores. The only destructive
method requires an exact, freshly calculated preview and explicit confirmation.
No method touches external files or shared library blobs.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from uuid import uuid4

from threaddesk.core.errors import ManagementError, NotFound
from threaddesk.core.models import now_iso

KINDS = {"thread", "node", "relation"}


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _id(value, *, maximum=128):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,%s}" % maximum, value):
        raise ManagementError("validation_error", "Exakte Kennung ist erforderlich.")
    return value


def _revision(value):
    if type(value) is not int or value < 1:
        raise ManagementError("validation_error", "Eine positive Revision ist erforderlich.")
    return value


class TrashService:
    def __init__(self, store):
        self.store = store

    def _object(self, kind, object_id):
        if not isinstance(kind, str) or kind not in KINDS:
            raise ManagementError("validation_error", "Unbekannte Papierkorb-Objektart.")
        _id(object_id)
        if kind == "thread":
            return self.store.get_thread(object_id, include_trashed=True).to_dict()
        if kind == "node":
            return self.store.get_node(object_id, include_trashed=True).to_dict()
        relation = next((r for r in self.store.list_relations(include_trashed=True)
                         if r.id == object_id), None)
        if relation is None:
            raise NotFound("Beziehung wurde nicht gefunden.")
        return relation.to_dict()

    def _workspace(self):
        key = "lifecycle_workspace_v1"
        saved = self.store.get_management_operation(key)
        if saved:
            return saved["result"]["workspace_id"]
        identity = uuid4().hex
        self.store.save_management_operation(key, {
            "request_hash": _hash({"version": 1}), "recorded_at": now_iso(),
            "kind": "lifecycle_identity", "result": {"operation_id": key, "workspace_id": identity}})
        return identity

    def _operation(self, operation_id, request, apply):
        _id(operation_id)
        key = "trash_" + _hash(operation_id)
        digest = _hash(request)
        with self.store.transaction():
            saved = self.store.get_management_operation(key)
            if saved is not None:
                if saved["request_hash"] != digest:
                    raise ManagementError("operation_conflict", "Operationskennung hat einen anderen Inhalt.")
                return {**deepcopy(saved["result"]), "duplicate": True}
            result = {**apply(), "operation_id": operation_id, "duplicate": False}
            # Internal key remains explicit and migratable; public ID is unchanged.
            self.store.save_management_operation(key, {
                "request_hash": digest, "recorded_at": now_iso(), "kind": "lifecycle",
                "storage_operation_id": key, "result": deepcopy(result)})
        from threaddesk.services.library_refresh import refresh_existing
        refresh_existing(self.store)
        return result

    def operation_status(self, operation_id):
        _id(operation_id)
        saved = self.store.get_management_operation("trash_" + _hash(operation_id))
        return {"operation_id": operation_id, "found": saved is not None,
                "result": deepcopy(saved["result"]) if saved else None}

    def verify_recorded_request(self, arguments):
        """Read an exact owner result for global receipt reconciliation only."""
        fields = {
            "move": {"kind", "object_id", "expected_revision", "actor"},
            "restore": {"trash_id", "generation", "expected_revision"},
            "purge": {"trash_id", "generation", "expected_revision", "reference_digest", "confirmation"},
            "resolve_sync_conflict": {"conflict_id", "expected_object_digest", "choice"},
        }
        if (not isinstance(arguments, dict) or not isinstance(arguments.get("action"), str)
                or arguments["action"] not in fields):
            raise ManagementError("validation_error", "Unbekannte Papierkorboperation.")
        action = arguments["action"]
        if set(arguments) - fields[action] - {"action", "operation_id"}:
            raise ManagementError("validation_error", "Unbekannte Papierkorbfelder.")
        required = fields[action] - ({"actor"} if action == "move" else set())
        if required - set(arguments):
            raise ManagementError("validation_error", "Papierkorbbeleg benötigt den vollständigen Request.")
        identity = _id(arguments.get("operation_id"))
        request = {key: value for key, value in arguments.items() if key != "operation_id"}
        if action == "move":
            request.setdefault("actor", "local")
        saved = self.store.get_management_operation("trash_" + _hash(identity))
        if saved is None:
            return {"found": False, "result": None}
        if saved["request_hash"] != _hash(request):
            raise ManagementError("operation_conflict", "Papierkorbbeleg gehört zu einem anderen Request.")
        return {"found": True, "result": deepcopy(saved["result"])}

    def sync_conflicts(self):
        from threaddesk.services.trash_conflicts import TrashConflictReview
        return TrashConflictReview(self).list()

    def resolve_sync_conflict(self, *, conflict_id, expected_object_digest, choice, operation_id):
        from threaddesk.services.trash_conflicts import TrashConflictReview
        return TrashConflictReview(self).resolve(conflict_id=conflict_id,
            expected_object_digest=expected_object_digest, choice=choice, operation_id=operation_id)

    def list(self, *, state="trashed", kind=None, offset=0, limit=50):
        if (not isinstance(state, str) or state not in {"trashed", "restored", "purged", "all"}
                or (kind is not None and (not isinstance(kind, str) or kind not in KINDS))):
            raise ManagementError("validation_error", "Ungültiger Papierkorbfilter.")
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ManagementError("validation_error", "Ungültige Seitengrenzen.")
        items = [item for item in self.store.list_trash_entries()
                 if (state == "all" or item["state"] == state) and (kind is None or item["kind"] == kind)]
        items.sort(key=lambda item: (item["deleted_at"], item["trash_id"]), reverse=True)
        end = offset + limit
        return {"items": items[offset:end], "total": len(items), "offset": offset,
                "next_offset": end if end < len(items) else None, "version": 1}

    def get(self, trash_id):
        _id(trash_id, maximum=180)
        entry = self.store.get_trash_entry(trash_id)
        if entry is None:
            raise NotFound("Papierkorbeintrag wurde nicht gefunden.")
        return deepcopy(entry)

    def preview(self, *, kind, object_id):
        obj = self._object(kind, object_id)
        references = {"snapshots": [], "whiteboard": [], "nodes": [], "relations": [],
                      "threads": [], "sources": [], "library_records_preserved": [], "external_files_preserved": []}
        if kind == "thread":
            references["snapshots"] = [s.id for s in self.store.list_snapshots(object_id, include_trashed=True)]
            references["whiteboard"] = [s.id for s in self.store.list_whiteboard(object_id, include_trashed=True)]
            references["nodes"] = [n.id for n in self.store.list_nodes(include_trashed=True)
                                    if n.metadata.get("thread_id") == object_id]
            references["external_files_preserved"] = list(obj["context"]["files"])
            for thread in self.store.list_threads(include_archived=True, include_trashed=True):
                org = thread.context.extra.get("organization") or {}
                if object_id in [org.get("parent_thread_id"), *(org.get("related_thread_ids") or [])]:
                    references["threads"].append(thread.id)
        elif kind == "node":
            references["relations"] = [r.id for r in self.store.list_relations(include_trashed=True)
                                        if object_id in (r.source_id, r.target_id)]
            for thread in self.store.list_threads(include_archived=True, include_trashed=True):
                if (thread.context.extra.get("organization") or {}).get("project_id") == object_id:
                    references["threads"].append(thread.id)
        references["sources"] = [r.source_id for r in self.store.list_source_records()
                                 if r.target_id == object_id]
        from threaddesk.services.library_import import LibraryImporter
        for record in LibraryImporter(self.store)._read_records():
            if ((kind == "thread" and record.get("thread_id") == object_id)
                    or (kind == "node" and (object_id in record.get("node_ids", [])
                        or record.get("node_id") == object_id or record.get("id") == object_id))):
                references["library_records_preserved"].append(record["id"])
        for value in references.values():
            value.sort()
        blockers = []
        if (references["nodes"] or references["relations"] or references["threads"]
                or references["sources"] or references["library_records_preserved"]):
            blockers.append("referenced_object")
        if kind == "thread":
            # A stored handoff is never cancelled by a data lifecycle action.
            if any(h.get("handoff", {}).get("thread_id") == object_id
                   for h in self.store.list_issued_handoffs()):
                blockers.append("issued_handoff_requires_review")
            if (self.store.workspace_path / "server-sync-private" / (object_id + ".json")).exists():
                blockers.append("sync_binding_requires_review")
        return {"object": obj, "references": references, "reference_digest": _hash(references),
                "blockers": blockers, "external_originals_preserved": True, "version": 1}

    def move(self, *, kind, object_id, expected_revision, operation_id, actor="local"):
        if type(expected_revision) is not int or expected_revision < 0:
            raise ManagementError("validation_error", "Eine nichtnegative Objektrevision ist erforderlich.")
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 200:
            raise ManagementError("validation_error", "Ungültige Akteurbezeichnung.")
        request = {"action": "move", "kind": kind, "object_id": object_id,
                   "expected_revision": expected_revision, "actor": actor}

        return self._operation(operation_id, request, lambda: self._move_in_transaction(
            kind=kind, object_id=object_id, expected_revision=expected_revision, actor=actor))

    def _move_in_transaction(self, *, kind, object_id, expected_revision, actor):
        """Shared mutation body for the already-transactional sync adapters."""
        preview = self.preview(kind=kind, object_id=object_id)
        obj = preview["object"]
        latest = self.store.get_object_lifecycle(kind, object_id)
        if latest and latest["state"] in {"trashed", "purged"}:
            raise ManagementError("object_in_trash", "Objekt befindet sich bereits im Papierkorb.")
        if obj["revision"] != expected_revision:
            raise ManagementError("revision_conflict", "Objekt wurde geändert.",
                                  actual_revision=obj["revision"], expected_revision=expected_revision)
        generation = (latest["generation"] if latest else 0) + 1
        entry = {"version": 1, "trash_id": f"{kind}-{object_id}-g{generation}",
                 "kind": kind, "object_id": object_id, "workspace_id": self._workspace(),
                 "generation": generation, "revision": 1, "state": "trashed",
                 "title": obj.get("title", obj.get("kind", object_id)), "deleted_at": now_iso(),
                 "actor": actor, "actor_evidence": "caller_label", "object_revision": expected_revision,
                 "original_status": obj.get("status"), "object_digest": _hash(obj),
                 "reference_digest": preview["reference_digest"], "references": preview["references"]}
        self.store.save_trash_entry(entry)
        if kind == "thread" and self.store.get_current_id() == object_id:
            self.store.set_current_id(None)
        return {"entry": entry}

    def _exact_entry(self, trash_id, generation, expected_revision):
        _revision(generation)
        _revision(expected_revision)
        entry = self.get(trash_id)
        latest = self.store.get_object_lifecycle(entry["kind"], entry["object_id"])
        if generation != entry["generation"] or latest["trash_id"] != trash_id:
            raise ManagementError("generation_conflict", "Die Löschgeneration ist nicht mehr aktuell.")
        if expected_revision != entry["revision"]:
            raise ManagementError("revision_conflict", "Papierkorbeintrag wurde geändert.",
                                  actual_revision=entry["revision"])
        if entry["state"] != "trashed":
            raise ManagementError("lifecycle_conflict", "Eintrag befindet sich nicht mehr im Papierkorb.")
        obj = self._object(entry["kind"], entry["object_id"])
        if _hash(obj) != entry["object_digest"]:
            raise ManagementError("object_changed_in_trash", "Objekt wurde außerhalb des Papierkorbvertrags verändert.",
                                  actual_revision=obj.get("revision"), object_id=entry["object_id"])
        return entry

    def restore(self, *, trash_id, generation, expected_revision, operation_id):
        request = {"action": "restore", "trash_id": trash_id, "generation": generation,
                   "expected_revision": expected_revision}

        return self._operation(operation_id, request, lambda: self._restore_in_transaction(
            trash_id=trash_id, generation=generation, expected_revision=expected_revision))

    def _restore_in_transaction(self, *, trash_id, generation, expected_revision):
        """Preserve one lifecycle implementation inside the sync unit of work."""
        entry = self._exact_entry(trash_id, generation, expected_revision)
        self._object(entry["kind"], entry["object_id"])
        entry.update(state="restored", revision=entry["revision"] + 1, restored_at=now_iso())
        self.store.save_trash_entry(entry)
        unresolved = []
        if entry["kind"] == "thread":
            obj = self._object("thread", entry["object_id"])
            parent = (obj["context"]["extra"].get("organization") or {}).get("parent_thread_id")
            if parent:
                try:
                    self.store.get_thread(parent)
                except (NotFound, ManagementError):
                    unresolved.append({"kind": "parent_thread", "object_id": parent})
        elif entry["kind"] == "node":
            owner = self._object("node", entry["object_id"])["metadata"].get("thread_id")
            if owner:
                try:
                    self.store.get_thread(owner)
                except (NotFound, ManagementError):
                    unresolved.append({"kind": "owning_thread", "object_id": owner})
        elif entry["kind"] == "relation":
            obj = self._object("relation", entry["object_id"])
            for node_id in (obj["source_id"], obj["target_id"]):
                try:
                    self.store.get_node(node_id)
                except (NotFound, ManagementError):
                    unresolved.append({"kind": "relation_endpoint", "object_id": node_id})
        return {"entry": entry, "unresolved_references": unresolved}

    def purge_preview(self, trash_id):
        return self._purge_preview(trash_id)[0]

    def _purge_preview(self, trash_id, *, exempt_pending=None):
        from threaddesk.services.trash_receipts import ENTRY_FIELDS, ENTRY_REMOVED, minimal_entry, receipt_plan
        entry = self.get(trash_id)
        if entry["state"] != "trashed":
            raise ManagementError("lifecycle_conflict", "Nur Papierkorbeinträge sind endgültig löschbar.")
        preview = self.preview(kind=entry["kind"], object_id=entry["object_id"])
        receipts = receipt_plan(self.store, entry["kind"], entry["object_id"], exempt_pending=exempt_pending)
        histories = []
        history_blockers = []
        for historical in self.store.list_trash_entries():
            if historical["kind"] == entry["kind"] and historical["object_id"] == entry["object_id"]:
                unknown = set(historical) - ENTRY_FIELDS - ENTRY_REMOVED
                if unknown:
                    history_blockers.append({"trash_id": historical["trash_id"], "fields": sorted(unknown),
                                             "reason": "unknown_lifecycle_result_field"})
                histories.append({"trash_id": historical["trash_id"], "record_digest": _hash(historical),
                                  "result_digest": _hash(minimal_entry(historical)),
                                  "removed_fields": sorted(set(historical) & ENTRY_REMOVED)})
        histories.sort(key=lambda value: value["trash_id"])
        binding = {"version": 2, "references": preview["references"],
                   "receipt_reduction_digest": receipts.public["digest"], "trash_entries": histories,
                   "history_blockers": history_blockers}
        digest = _hash(binding)
        blockers = [*preview["blockers"]]
        if receipts.public["blockers"]:
            blockers.append("receipt_reduction_requires_review")
        if history_blockers:
            blockers.append("trash_history_requires_review")
        return {**preview, "version": 2, "entry": entry, "reference_digest": digest,
                "receipt_reduction": receipts.public, "trash_entry_reduction": histories,
                "trash_entry_reduction_blockers": history_blockers,
                "blockers": blockers, "confirmation": "DELETE " + entry["trash_id"] + " " + digest}, receipts

    def purge(self, *, trash_id, generation, expected_revision, reference_digest,
              confirmation, operation_id):
        request = {"action": "purge", "trash_id": trash_id, "generation": generation,
                   "expected_revision": expected_revision, "reference_digest": reference_digest,
                   "confirmation": confirmation}

        def apply():
            from threaddesk.services.trash_receipts import minimal_entry
            from threaddesk.services.commands.model import workspace_identity
            from threaddesk.services.commands.validation import command_request_digest
            entry = self._exact_entry(trash_id, generation, expected_revision)
            arguments = {key: value for key, value in request.items() if key != "action"}
            arguments["operation_id"] = operation_id
            # Native commands accept the revision in the envelope, or solely
            # in domain arguments. Only these exact canonical reservations may
            # remain pending while this particular owner call is executing.
            digests = {command_request_digest(workspace_identity(self.store), "trash.purge", arguments,
                                              operation_id, revision)
                       for revision in (None, expected_revision)}
            pending_key = "command-" + hashlib.sha256(operation_id.encode()).hexdigest() + "-pending"
            preview, receipts = self._purge_preview(trash_id, exempt_pending=(pending_key, digests))
            if preview["reference_digest"] != reference_digest:
                raise ManagementError("reference_conflict", "Referenzen haben sich seit der Vorschau geändert.")
            if confirmation != preview["confirmation"]:
                raise ManagementError("explicit_confirmation_required", "Exakte endgültige Löschbestätigung fehlt.")
            if preview["blockers"]:
                raise ManagementError("purge_blocked", "Referenzen oder offene Übergaben verhindern die Löschung.",
                                      blockers=preview["blockers"])
            stamp = now_iso()
            receipts.apply(self.store, entry, operation_id=operation_id, purged_at=stamp)
            for historical in self.store.list_trash_entries():
                if historical["kind"] == entry["kind"] and historical["object_id"] == entry["object_id"]:
                    self.store.save_trash_entry(minimal_entry(historical))
            self.store.purge_trash_object(entry["kind"], entry["object_id"])
            entry = minimal_entry(entry)
            entry.update(state="purged", revision=entry["revision"] + 1, purged_at=stamp)
            self.store.save_trash_entry(entry)
            return {"entry": entry, "external_originals_preserved": True,
                    "receipt_reduction": {"version": 1, "digest": receipts.public["digest"],
                                          "records": len(receipts.changes)}}

        return self._operation(operation_id, request, apply)
