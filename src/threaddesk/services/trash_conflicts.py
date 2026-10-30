"""Explicit review of durable room lifecycle conflicts, never implicit deletion."""
from __future__ import annotations

from copy import deepcopy

from threaddesk.core.errors import ManagementError, NotFound
from threaddesk.services.trash import _hash, _id
from threaddesk.storage.operation_results import result_object


class TrashConflictReview:
    def __init__(self, service):
        self.service = service
        self.store = service.store

    def list(self):
        records = self.store.list_management_operations()
        resolved = {result_object(item).get("resolved_conflict") for item in records}
        result = []
        for record in records:
            if record.get("kind") != "lifecycle_conflict" or record["result"]["operation_id"] in resolved:
                continue
            item = deepcopy(record["result"])
            item["expected_object_digest"] = self._conflict_object_digest(item["thread_id"])
            result.append(item)
        return result

    def _conflict_object_digest(self, thread_id):
        try:
            obj = self.service._object("thread", thread_id)
        except NotFound:
            return _hash(self.store.get_object_lifecycle("thread", thread_id))
        contributions = sorted((entry.to_dict() for entry in self.store.list_whiteboard(
            thread_id, include_trashed=True)), key=lambda entry: entry["id"])
        return _hash({"thread": obj, "whiteboard": contributions})

    def resolve(self, *, conflict_id, expected_object_digest, choice, operation_id):
        _id(conflict_id)
        if choice not in {"keep_local", "adopt_incoming"}:
            raise ManagementError("validation_error", "Lokalen Stand behalten oder konkrete Generation übernehmen.")
        request = {"action": "resolve_sync_conflict", "conflict_id": conflict_id,
                   "expected_object_digest": expected_object_digest, "choice": choice}

        def apply():
            record = self.store.get_management_operation(conflict_id)
            if record is None or record.get("kind") != "lifecycle_conflict":
                raise NotFound("Lebenszykluskonflikt wurde nicht gefunden.")
            conflict = record["result"]
            thread_id = conflict["thread_id"]
            if expected_object_digest != self._conflict_object_digest(thread_id):
                raise ManagementError("revision_conflict", "Objekt wurde seit der Konfliktansicht geändert.")
            if any(result_object(item).get("resolved_conflict") == conflict_id
                   for item in self.store.list_management_operations()):
                raise ManagementError("lifecycle_conflict", "Konflikt wurde bereits aufgelöst.")
            if choice == "adopt_incoming":
                incoming = conflict["incoming"]
                if incoming.get("state") not in {"trashed", "restored"}:
                    raise ManagementError("lifecycle_conflict", "Keine übernehmbare Lösch- oder Restoregeneration.")
                latest = self.store.get_object_lifecycle("thread", thread_id)
                generation = latest["generation"] if latest else 0
                if incoming["state"] == "trashed":
                    if incoming["generation"] != generation + 1:
                        raise ManagementError("generation_conflict", "Löschgeneration ist nicht aktuell.")
                    obj = self.service._object("thread", thread_id)
                    self.service._move_in_transaction(kind="thread", object_id=thread_id,
                        expected_revision=obj["revision"], actor="room_conflict_resolution")
                else:
                    if latest is None or latest["state"] == "restored":
                        if incoming["generation"] != generation + 1:
                            raise ManagementError("generation_conflict", "Restoregeneration fehlt oder ist veraltet.")
                        obj = self.service._object("thread", thread_id)
                        latest = self.service._move_in_transaction(kind="thread", object_id=thread_id,
                            expected_revision=obj["revision"], actor="room_conflict_resolution")["entry"]
                    if incoming["generation"] != latest["generation"]:
                        raise ManagementError("generation_conflict", "Restoregeneration ist veraltet.")
                    self.service._restore_in_transaction(trash_id=latest["trash_id"], generation=latest["generation"],
                                                 expected_revision=latest["revision"])
            return {"resolved_conflict": conflict_id, "choice": choice, "state": "resolved"}

        return self.service._operation(operation_id, request, apply)
