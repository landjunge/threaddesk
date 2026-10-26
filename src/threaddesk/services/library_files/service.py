"""File metadata operations over the existing library CAS, never source files."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path, PurePosixPath

from threaddesk.core.errors import ManagementError, NotFound, ThreadDeskError
from threaddesk.core.models import new_id, now_iso
from threaddesk.services.library_files import state, validation


class LibraryFileService:
    def __init__(self, store, *, opener=None, handler_resolver=None):
        # The importer reads state overlays; defer construction to avoid a module
        # initialization cycle when index code imports the independent state API.
        from threaddesk.services.library_import import LibraryImporter
        self.store = store
        self.importer = LibraryImporter(store)
        self.root = self.importer.root
        self.opener = opener
        self.handler_resolver = handler_resolver

    def info(self, record_id: str, *, include_trashed: bool = False) -> dict:
        validation.record_id(record_id)
        record = self.importer._record_by_id(record_id)
        if record is None or record.get("status") != "stored":
            state.fail("not_found", "Datei wurde nicht gefunden.")
        if record.get("trashed") and not include_trashed:
            state.fail("object_in_trash", "Datei liegt im Papierkorb.")
        from threaddesk.services.library_files.versions import annotate_versions
        return state.normalize(annotate_versions([record], self.root)[0])

    def list(self, *, thread_id=None, node_id=None, folder=None,
             include_trashed=False, sort="name", limit=100, offset=0) -> dict:
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
            state.fail("validation_error", "Ungültige Seitengrenze.")
        if type(include_trashed) is not bool or sort not in {"name", "date", "size", "type"}:
            state.fail("validation_error", "Ungültiger Listenfilter.")
        if thread_id is not None:
            validation.record_id(thread_id)
        if node_id is not None:
            validation.record_id(node_id)
        if folder is not None:
            validation.folder(folder)
        linked_thread = None
        if node_id is not None:
            try:
                node = self.store.get_node(node_id)
            except NotFound:
                node = None
            if node is not None and not node.metadata.get("library_record_id"):
                linked_thread = node.metadata.get("thread_id")
        rows = [state.normalize(row) for row in self.importer._read_records()
                if row.get("status") == "stored"]
        rows = [row for row in rows if (include_trashed or not row["trashed"])
                and (thread_id is None or row.get("thread_id") == thread_id)
                and (node_id is None or node_id == row["id"] or node_id in row.get("node_ids", [])
                     or (linked_thread is not None and row.get("thread_id") == linked_thread))]
        folders = set()
        if folder is not None:
            prefix = folder + "/" if folder else ""
            for row in rows:
                logical = row["logical_path"]
                if logical.startswith(prefix) and "/" in logical[len(prefix):]:
                    folders.add(prefix + logical[len(prefix):].split("/", 1)[0])
            rows = [row for row in rows if str(PurePosixPath(row["logical_path"]).parent) == "."] if folder == "" else [
                        row for row in rows if str(PurePosixPath(row["logical_path"]).parent) == folder]
        keys = {"name": lambda row: row["filename"].casefold(),
                "date": lambda row: row.get("modified_at", ""),
                "size": lambda row: row.get("size", 0),
                "type": lambda row: row.get("format", "")}
        rows.sort(key=lambda row: (keys[sort](row), row["id"]))
        end = offset + limit
        return {"records": rows[offset:end], "folders": sorted(folders), "total": len(rows),
                "next_offset": end if end < len(rows) else None,
                "generation": state.state_generation(self.root)}

    def operation_status(self, operation_id: str) -> dict:
        validation.operation_id(operation_id)
        saved = state.read_state(self.root)["operations"].get(operation_id)
        return {"operation_id": operation_id, "found": saved is not None,
                "result": copy.deepcopy(saved["result"]) if saved else None}

    def verify_recorded_request(self, arguments: dict) -> dict:
        """Read-only owner validation before adopting a legacy public receipt.

        A wrong replay must not reserve a new command binding. Validate exactly
        as the original owner does; historical receipts do not depend on today's
        object revision, visibility, standard application, or index availability.
        """
        if isinstance(arguments, dict) and arguments.get("action") == "open":
            from threaddesk.services.library_files.opening import validate_open_request
            args = validate_open_request(arguments)
        else:
            args = validation.request(arguments)
        saved = state.read_state(self.root)["operations"].get(args["operation_id"])
        return {"operation_id": args["operation_id"], "found": saved is not None,
                "result": self._replay(saved, self._request_hash(args)) if saved else None}

    def manage(self, arguments: dict) -> dict:
        args = validation.request(arguments)
        digest = self._request_hash(args)
        with self.store.transaction():
            document = state.read_state(self.root)
            saved = document["operations"].get(args["operation_id"])
            if saved:
                return self._replay(saved, digest)
            record = self.info(args["id"], include_trashed=True)
            self._check_revision(record, args["expected_revision"])
            action = args["action"]
            if record["trashed"] and action != "restore":
                state.fail("object_in_trash", "Datei liegt im Papierkorb.")
            result_record = self._mutate(record, action, args["data"])
            if action == "copy":
                result_record["id"] = new_id()
                result_record["file_node_id"] = result_record["id"]
                result_record["revision"] = 1
                result_record["copied_from"] = record["id"]
                result_record["node_ids"] = list(args["data"].get("node_ids", []))
                if result_record["node_ids"]:
                    result_record["node_id"] = result_record["node_ids"][0]
                else:
                    result_record.pop("node_id", None)
            else:
                result_record["revision"] += 1
            result_record["modified_at"] = now_iso()
            self._check_destination(result_record, action)
            document["records"][result_record["id"]] = result_record
            document["generation"] += 1
            result = {"operation_id": args["operation_id"], "action": action,
                      "duplicate": False, "record": result_record,
                      "generation": document["generation"], "index_pending": True}
            document["operations"][args["operation_id"]] = {
                "request_hash": digest, "result": result, "recorded_at": now_iso()}
            state.write_state(self.root, document)
        self._refresh_index()
        return copy.deepcopy(result)

    @staticmethod
    def _request_hash(args):
        return hashlib.sha256(json.dumps(args, sort_keys=True, ensure_ascii=False,
                                         separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _replay(saved, digest):
        if saved["request_hash"] != digest:
            state.fail("operation_conflict", "Operationskennung hat bereits einen anderen Inhalt.")
        return {**copy.deepcopy(saved["result"]), "duplicate": True}

    @staticmethod
    def _check_revision(record, revision):
        if record["revision"] != revision:
            state.fail("revision_conflict", "Datei wurde zwischenzeitlich geändert.",
                       expected_revision=revision, actual_revision=record["revision"])

    def _mutate(self, record, action, data):
        value = copy.deepcopy(record)
        if action in {"rename", "copy"}:
            if "filename" in data:
                value["filename"] = data["filename"]
            elif action == "copy":
                value["filename"] = self._copy_name(record)
        if action in {"rename", "copy", "move"}:
            previous = str(PurePosixPath(record["logical_path"]).parent)
            current_folder = "" if previous == "." else previous
            current_folder = data.get("folder", current_folder)
            value["logical_path"] = str(PurePosixPath(current_folder) / value["filename"])
        if "thread_id" in data:
            if data["thread_id"] is None:
                state.fail("validation_error", "Eine bestehende Zielthread-ID ist erforderlich.")
            try:
                target = self.store.get_thread(data["thread_id"])
            except NotFound as exc:
                raise ManagementError("not_found", "Zielthread fehlt.") from exc
            value.update(thread_id=target.id, thread_title=target.title, assignment="matched")
        if "node_ids" in data:
            for node_id in data["node_ids"]:
                try:
                    self.store.get_node(node_id)
                except NotFound as exc:
                    raise ManagementError("not_found", "Zielknoten fehlt.") from exc
            value["node_ids"] = list(data["node_ids"])
            if value["node_ids"]:
                value["node_id"] = value["node_ids"][0]
            else:
                value.pop("node_id", None)
        if action == "trash":
            value.update(trashed=True, trash_generation=record["trash_generation"] + 1,
                         deleted_at=now_iso())
        if action == "restore":
            if not record["trashed"]:
                state.fail("invalid_state", "Datei liegt nicht im Papierkorb.")
            if data["trash_generation"] != record["trash_generation"]:
                state.fail("trash_generation_conflict", "Papierkorbgeneration wurde geändert.")
            value.update(trashed=False, restored_at=now_iso())
        return value

    def _copy_name(self, record):
        path = Path(record["filename"])
        used = {row["filename"].casefold() for row in self.importer._read_records()
                if not row.get("trashed") and str(PurePosixPath(row.get("logical_path", row.get("origin_path", ""))).parent)
                == str(PurePosixPath(record["logical_path"]).parent)}
        for number in range(1, 10001):
            candidate = f"{path.stem} Kopie {number}{path.suffix}"
            validation.filename(candidate)
            if candidate.casefold() not in used:
                return candidate
        state.fail("name_conflict", "Kein freier Kopiename verfügbar.")

    def _check_destination(self, record, action):
        if action not in {"rename", "copy", "move", "restore"}:
            return
        from threaddesk.services.library_files.versions import confirmed_predecessors
        previous_versions = confirmed_predecessors(record, self.root)
        for other in self.importer._read_records():
            if other["id"] in previous_versions and not other.get("copied_from"):
                continue
            if (other["id"] != record["id"] and not other.get("trashed")
                    and other.get("logical_path", other.get("origin_path", "")).casefold()
                    == record["logical_path"].casefold()):
                state.fail("name_conflict", "Im Zielordner existiert bereits eine Datei dieses Namens.")

    def _refresh_index(self):
        # Metadata committed independently; an index failure cannot undo/replay it.
        try:
            from threaddesk.services.library_index import LibraryIndex
            from threaddesk.services.library_links import sync_file_nodes
            sync_file_nodes(self.store)
            index = LibraryIndex(self.root)
            import inspect
            options = {"store": self.store} if "store" in inspect.signature(index.rebuild).parameters else {}
            return index.rebuild(self.importer._read_records(), self.importer.blobs, **options)
        except (OSError, ValueError, ThreadDeskError):
            return {"status": "stale", "error": "index_refresh_failed"}

    def preview(self, record_id: str) -> dict:
        from threaddesk.services.library_files.preview import preview
        return preview(self, record_id)

    def open(self, record_id: str, *, operation_id: str, expected_revision: int) -> dict:
        from threaddesk.services.library_files.opening import open_file
        return open_file(self, record_id, operation_id=operation_id,
                         expected_revision=expected_revision)
