"""Small lifecycle persistence adapters; callers own the existing unit of work.

The object payloads stay in place. Entries retain every deletion generation so
an old restore receipt cannot restore a later deletion of the same object.
"""
from __future__ import annotations

import json
import re

from threaddesk.core.errors import ManagementError, NotFound


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,180}", value):
        raise ManagementError("validation_error", "Ungültige Lebenszykluskennung.")
    return value


class LifecycleStore:
    def get_object_lifecycle(self, kind: str, object_id: str) -> dict | None:
        items = [item for item in self.list_trash_entries()
                 if item["kind"] == kind and item["object_id"] == object_id]
        return max(items, key=lambda item: item["generation"], default=None)

    def object_in_trash(self, kind: str, object_id: str) -> bool:
        entry = self.get_object_lifecycle(kind, object_id)
        return entry is not None and entry["state"] in {"trashed", "purged"}

    def require_live_object(self, kind: str, object_id: str) -> None:
        if self.object_in_trash(kind, object_id):
            raise ManagementError("object_in_trash", "Objekt befindet sich im Papierkorb.",
                                  kind=kind, object_id=object_id)

    def hidden_node_ids(self, nodes) -> set[str]:
        states = self.list_trash_entries()
        newest = {}
        for item in states:
            key = item["kind"], item["object_id"]
            if key not in newest or newest[key]["generation"] < item["generation"]:
                newest[key] = item
        hidden = {key for key, item in newest.items() if item["state"] in {"trashed", "purged"}}
        return {node.id for node in nodes if ("node", node.id) in hidden
                or (isinstance(node.metadata.get("thread_id"), str)
                    and ("thread", node.metadata["thread_id"]) in hidden)}

    def require_live_node_reference(self, node_id: str) -> None:
        self.require_live_object("node", node_id)
        try:
            node = self.get_node(node_id, include_trashed=True)
        except NotFound:
            return  # Preserve the backend's existing dangling-reference rules.
        if node.metadata.get("thread_id"):
            self.require_live_object("thread", node.metadata["thread_id"])


class JsonLifecycleStore(LifecycleStore):
    def list_management_operation_records(self):
        with self._locked():
            folder = self.root / "management-operations"
            names = {path.name for path in folder.glob("*.json")}
            if self.in_transaction:
                names.update(path.split("/")[1] for path in self._pending
                             if path.startswith("management-operations/") and len(path.split("/")) == 2)
            return [{"storage_operation_id": name[:-5], "record": self._read_json(folder / name)}
                    for name in sorted(names) if self._staged_exists(folder / name)]

    def reduce_management_operation_for_purge(self, operation_id, *, expected_record_digest, reduced_result, evidence):
        from threaddesk.storage.purge_receipts import reduced_record
        path = self.root / "management-operations" / (identifier(operation_id) + ".json")
        record = self._read_json(path) if self._staged_exists(path) else None
        value = reduced_record(self, record, expected_record_digest=expected_record_digest,
                               reduced_result=reduced_result, evidence=evidence)
        self._write_json(path, value)

    def purge_trash_object(self, kind: str, object_id: str) -> None:
        identifier(object_id)
        if not self.object_in_trash(kind, object_id):
            raise ManagementError("lifecycle_conflict", "Objekt muss zuerst in den Papierkorb.")
        if kind == "thread":
            self.delete_thread(object_id)
            self._delete_path(self.root / "thread-revisions" / (object_id + ".json"))
        elif kind in {"node", "relation"}:
            folder = self.nodes_dir if kind == "node" else self.relations_dir
            self._delete_path(folder / (object_id + ".json"))
        else:
            raise ManagementError("validation_error", "Unbekannte Objektart.")

    def get_trash_entry(self, trash_id: str) -> dict | None:
        path = self.root / "trash" / (identifier(trash_id) + ".json")
        return self._read_json(path) if self._staged_exists(path) else None

    def save_trash_entry(self, entry: dict) -> None:
        self._write_json(self.root / "trash" / (identifier(entry["trash_id"]) + ".json"), entry)

    def list_trash_entries(self) -> list[dict]:
        paths = {path.name for path in (self.root / "trash").glob("*.json")}
        # Include staged creates and excludes staged deletes, just like get.
        if self._pending is not None:
            paths.update(path.split("/")[1] for path in self._pending
                         if path.startswith("trash/") and len(path.split("/")) == 2)
        return [self._read_json(self.root / "trash" / name) for name in sorted(paths)
                if self._staged_exists(self.root / "trash" / name)]


class SQLiteLifecycleStore(LifecycleStore):
    def list_management_operation_records(self):
        return [{"storage_operation_id": row["id"], "record": self._load(row)} for row in
                self.connection.execute("SELECT id,payload FROM management_operations ORDER BY id")]

    def reduce_management_operation_for_purge(self, operation_id, *, expected_record_digest, reduced_result, evidence):
        from threaddesk.storage.purge_receipts import reduced_record
        identity = identifier(operation_id)
        record = self.get_management_operation(identity)
        value = reduced_record(self, record, expected_record_digest=expected_record_digest,
                               reduced_result=reduced_result, evidence=evidence)
        self.connection.execute("UPDATE management_operations SET payload=? WHERE id=?", (self._dump(value), identity))

    def purge_trash_object(self, kind: str, object_id: str) -> None:
        if not self.object_in_trash(kind, object_id):
            raise ManagementError("lifecycle_conflict", "Objekt muss zuerst in den Papierkorb.")
        if kind == "thread":
            self.delete_thread(object_id)
        elif kind in {"node", "relation"}:
            table = "nodes" if kind == "node" else "relations"
            self.connection.execute("DELETE FROM " + table + " WHERE id=?", (object_id,))
        else:
            raise ManagementError("validation_error", "Unbekannte Objektart.")

    def get_trash_entry(self, trash_id: str) -> dict | None:
        row = self.connection.execute("SELECT payload FROM trash_entries WHERE id=?",
                                      (identifier(trash_id),)).fetchone()
        return self._load(row) if row else None

    def get_object_lifecycle(self, kind: str, object_id: str) -> dict | None:
        row = self.connection.execute(
            "SELECT payload FROM trash_entries WHERE kind=? AND object_id=? "
            "ORDER BY generation DESC LIMIT 1", (kind, object_id)).fetchone()
        return self._load(row) if row else None

    def save_trash_entry(self, entry: dict) -> None:
        self.connection.execute(
            "INSERT INTO trash_entries(id,kind,object_id,generation,state,payload) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET state=excluded.state,payload=excluded.payload",
            (identifier(entry["trash_id"]), entry["kind"], entry["object_id"], entry["generation"],
             entry["state"], self._dump(entry)))
        self._commit()

    def list_trash_entries(self) -> list[dict]:
        return [self._load(row) for row in self.connection.execute(
            "SELECT payload FROM trash_entries ORDER BY id")]
