"""One bounded library command boundary shared by CLI, browser and MCP."""
from __future__ import annotations

import re
import sqlite3

from threaddesk.core.errors import ManagementError, ThreadDeskError
from threaddesk.core.models import now_iso
from threaddesk.services.library_import import LibraryImporter
from threaddesk.services.library_index import LibraryIndex, LibrarySearchError

READ_ACTIONS = frozenset({"status", "search", "list", "info", "preview", "formats", "operation", "import_status", "sources"})
WRITE_ACTIONS = frozenset({"import", "resume", "reindex", "rename", "copy", "move", "assign", "trash", "restore", "open", "refresh_sources"})
_FIELDS = {"action", "id", "query", "limit", "offset", "thread_id", "node_id", "folder", "sort",
           "entity_type", "project_id", "kind", "date_from", "date_to", "assignment", "include_trashed",
           "operation_id", "expected_revision", "data"}
_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _invalid(message="Invalid library command"):
    raise ManagementError("validation_error", message)


class LibraryApplication:
    def __init__(self, store):
        self.store = store
        self.importer = LibraryImporter(store)
        self.index = LibraryIndex(self.importer.root)

    def call(self, arguments, *, read_only=False):
        try:
            return self._call(arguments, read_only=read_only)
        except (ManagementError, LibrarySearchError, ThreadDeskError, OSError, ValueError, TypeError, sqlite3.Error) as exc:
            if isinstance(exc, ManagementError):
                error = exc
            elif isinstance(exc, (LibrarySearchError, ThreadDeskError)):
                error = ManagementError(getattr(exc, "code", "invalid_state"), str(exc))
            else:
                error = ManagementError("library_unavailable", "Library operation could not be confirmed.",
                                        error_type=type(exc).__name__)
            from threaddesk.services.library_operation import LibraryOperationBinding
            try:
                LibraryOperationBinding(self.store).rejected(arguments, error)
            except (OSError, ValueError, sqlite3.Error):
                pass  # Retain the original error if the optional diagnostic cannot be saved.
            if error is exc:
                raise
            raise error from exc

    def _call(self, arguments, *, read_only=False):
        if not isinstance(arguments, dict) or set(arguments) - _FIELDS:
            _invalid()
        args = dict(arguments)
        action = args.pop("action", None)
        if not isinstance(action, str) or action not in READ_ACTIONS | WRITE_ACTIONS or (read_only and action not in READ_ACTIONS):
            _invalid("Unknown or non-read library action")
        allowed = {
            "status": set(), "formats": set(), "sources": set(),
            "refresh_sources": {"operation_id"}, "info": {"id"}, "preview": {"id"},
            "operation": {"operation_id"}, "import_status": {"operation_id", "offset", "limit"},
            "import": {"operation_id", "data"}, "resume": {"operation_id"},
            "reindex": {"operation_id"}, "open": {"id", "operation_id", "expected_revision"},
            "list": {"thread_id", "node_id", "folder", "sort", "include_trashed", "limit", "offset"},
            "search": {"query", "entity_type", "limit", "offset", "thread_id", "project_id", "kind", "date_from", "date_to", "assignment", "include_trashed"},
        }.get(action, {"id", "operation_id", "expected_revision", "data"})
        if set(args) - allowed:
            _invalid("Unexpected fields for library action")
        for key in ("query", "entity_type", "folder", "sort", "kind", "date_from", "date_to", "assignment"):
            if key in args and (not isinstance(args[key], str) or len(args[key].encode()) > 2000):
                _invalid()
        if "data" in args and (not isinstance(args["data"], dict) or len(str(args["data"])) > 131072):
            _invalid()
        for key in ("limit", "offset", "expected_revision"):
            if key in args and (type(args[key]) is not int or args[key] < 0):
                _invalid()
        if not 1 <= args.get("limit", 50) <= 100 or args.get("offset", 0) > 100000:
            _invalid("Invalid page size")
        if "include_trashed" in args and type(args["include_trashed"]) is not bool:
            _invalid()
        for key in ("id", "thread_id", "node_id", "project_id", "operation_id"):
            if key in args and (not isinstance(args[key], str) or not _ID.fullmatch(args[key])):
                _invalid("Invalid identifier")
        if action in WRITE_ACTIONS and not args.get("operation_id"):
            _invalid("An operation_id is required")
        prepared_manifest = None
        prior_command = None
        if action in WRITE_ACTIONS:
            from threaddesk.services.library_operation import LibraryOperationBinding
            # Older direct domain receipts predate the public command binding.
            from threaddesk.services.library_files import LibraryFileService
            files = LibraryFileService(self.store)
            legacy = files.operation_status(args["operation_id"])
            if legacy["found"]:
                if legacy["result"].get("action") != action:
                    raise ManagementError("operation_conflict", "Operation ID already has a different result.")
                files.verify_recorded_request({"action": action, **args})
            if action not in {"import", "resume"} and len(args["operation_id"]) <= 100:
                from threaddesk.services.library_batch import LibraryBatchImporter
                from threaddesk.services.library_import import LibraryImportError
                try:
                    LibraryBatchImporter(self.store).status(args["operation_id"])
                except LibraryImportError as exc:
                    if exc.code != "batch_not_found":
                        raise
                else:
                    raise ManagementError("operation_conflict", "Operation ID belongs to an existing import.")
            if action != "reindex" and self.store.get_management_operation(self._index_operation(args["operation_id"])):
                raise ManagementError("operation_conflict", "Operation ID belongs to an existing index refresh.")
            binding_request = {"action": action, **args}
            if action in {"import", "resume"}:
                prepared_manifest, digest = self._prepare_import(action, args)
                binding_request = {"action": "import", "operation_id": args["operation_id"],
                                   "data": {"manifest_hash": digest}}
            binding = LibraryOperationBinding(self.store)
            prior_command = binding.read(args["operation_id"])
            binding.bind(binding_request)
        if action == "status":
            result = self.importer.catalog()
            # File details are independently paginated by list/import_status.
            for collection in ("records", "failures", "pending", "outstanding", "formats"):
                result.pop(collection, None)
            from threaddesk.services.library_batch.public_status import projection_status
            result["index"] = projection_status(result["index"])
            result["historical_inventory_verified"] = False
            from threaddesk import __version__
            from threaddesk.build_info import SOURCE_COMMIT, BUILD_ID
            result["build"] = {"version": __version__, "source_commit": SOURCE_COMMIT, "build_id": BUILD_ID}
            return result
        if action in {"sources", "refresh_sources"}:
            from threaddesk.services.library_watch import LibrarySourceWatch
            watch = LibrarySourceWatch(self.store)
            if action == "sources":
                return watch.status()
            previous = binding.result(args["operation_id"])
            if previous:
                return {**previous, "duplicate": True}
            if prior_command:
                return {"operation_id": args["operation_id"], "status": "unknown"}
            result = {**watch.poll_once(), "operation_id": args["operation_id"], "status": "complete"}
            return binding.completed(args["operation_id"], result)
        if action == "formats":
            from threaddesk.services.file_formats import describe
            from threaddesk.services.library_import import supported_formats
            return [describe("file" + row["suffix"]) for row in supported_formats()]
        if action == "search":
            query = args.pop("query", "")
            if not isinstance(query, str) or not query.strip() or len(query.encode()) > 1000:
                _invalid("A bounded search query is required")
            allowed = {"limit", "offset", "thread_id", "entity_type", "project_id", "kind", "date_from", "date_to", "assignment", "include_trashed"}
            if set(args) - allowed:
                _invalid()
            args.setdefault("entity_type", "all")
            return {"hits": self.index.search(query, **args), "index": self.index.status()}
        from threaddesk.services.library_files import LibraryFileService
        files = LibraryFileService(self.store)
        if action == "list":
            allowed = {"thread_id", "node_id", "folder", "include_trashed", "sort", "limit", "offset"}
            if set(args) - allowed:
                _invalid()
            return files.list(**args)
        if action in {"info", "preview"}:
            if set(args) != {"id"}:
                _invalid()
            return getattr(files, action)(args["id"])
        if action == "operation":
            if set(args) != {"operation_id"}:
                _invalid()
            result = files.operation_status(args["operation_id"])
            if result["found"]:
                return result
            from threaddesk.services.library_batch import LibraryBatchImporter
            from threaddesk.services.library_import import LibraryImportError
            if len(args["operation_id"]) <= 100:
                try:
                    job = LibraryBatchImporter(self.store).status(args["operation_id"])
                    from threaddesk.services.library_batch.public_status import public_status
                    return {"operation_id": args["operation_id"], "found": True, "result": public_status(job)}
                except LibraryImportError as exc:
                    if exc.code != "batch_not_found":
                        raise
            saved = self.store.get_management_operation(self._index_operation(args["operation_id"]))
            if saved:
                return {"operation_id": args["operation_id"], "found": True, "result": saved["result"]}
            from threaddesk.services.library_operation import LibraryOperationBinding
            binding = LibraryOperationBinding(self.store)
            completed = binding.result(args["operation_id"])
            if completed:
                return {"operation_id": args["operation_id"], "found": True, "result": completed}
            rejection = binding.rejection(args["operation_id"])
            claimed = binding.read(args["operation_id"])
            return {"operation_id": args["operation_id"], "found": bool(rejection or claimed),
                    "result": ({"status": "failed", **rejection} if rejection else
                               {"status": "unknown", "action": claimed["action"]} if claimed else None)}
        if action == "import_status":
            from threaddesk.services.library_batch import LibraryBatchImporter
            from threaddesk.services.library_batch.public_status import public_status
            if "operation_id" not in args:
                _invalid("An operation_id is required")
            return public_status(LibraryBatchImporter(self.store).status(args["operation_id"]),
                                 offset=args.get("offset", 0), limit=min(args.get("limit", 20), 50))
        if action in {"import", "resume"}:
            from threaddesk.services.library_batch import LibraryBatchImporter
            batch = LibraryBatchImporter(self.store)
            data = args.get("data", {})
            if action == "import" and "source" in data:
                from threaddesk.services.library_watch import LibrarySourceWatch
                LibrarySourceWatch(self.store).register(data["source"], data.get("thread_id"), data.get("node_id"))
            from threaddesk.services.library_batch.public_status import public_status
            return public_status(batch.run(prepared_manifest, operation_id=args["operation_id"]))
        if action == "reindex":
            from threaddesk.services.library_links import sync_file_nodes
            identity = self._index_operation(args["operation_id"])
            previous = self.store.get_management_operation(identity)
            if previous:
                return {**previous["result"], "duplicate": True}
            projection = sync_file_nodes(self.store)
            result = {"operation_id": args["operation_id"], "projection": projection,
                      "index": self.index.rebuild(self.importer._read_records(), self.importer.blobs, store=self.store)}
            if result["index"].get("status") == "ready":
                with self.store.transaction():
                    prior = self.store.get_management_operation(identity)
                    if prior:
                        return {**prior["result"], "duplicate": True}
                    self.store.save_management_operation(identity, {"result": result, "recorded_at": now_iso(), "request_hash": self._index_operation(args["operation_id"])})
            return result
        if action == "open":
            if set(args) != {"id", "operation_id", "expected_revision"}:
                _invalid()
            return files.open(args["id"], operation_id=args["operation_id"], expected_revision=args["expected_revision"])
        if set(args) - {"id", "operation_id", "expected_revision", "data"}:
            _invalid()
        result = files.manage({"action": action, **args})
        from threaddesk.services.library_links import sync_file_nodes
        try:
            result["graph_projection"] = sync_file_nodes(self.store)
        except (OSError, ValueError, ThreadDeskError) as exc:
            result["graph_projection"] = {"status": "pending", "error": type(exc).__name__}
        result["index"] = self.index.status()
        result["index_pending"] = result["index"].get("status") != "ready"
        return result

    @staticmethod
    def _index_operation(operation_id):
        import hashlib
        return "library-index-" + hashlib.sha256(operation_id.encode()).hexdigest()

    def _prepare_import(self, action, args):
        """Validate owner identity before adopting an older unbound receipt."""
        from pathlib import Path
        from threaddesk.services.library_batch import LibraryBatchImporter
        from threaddesk.services.library_batch.manifest import validate
        from threaddesk.services.library_import import LibraryImportError
        batch = LibraryBatchImporter(self.store)
        try:
            previous = batch.status(args["operation_id"])
        except LibraryImportError as exc:
            if exc.code != "batch_not_found":
                raise
            previous = None
        if action == "resume":
            if previous is None:
                raise LibraryImportError("batch_not_found")
            manifest = previous["manifest"]
        else:
            data = args.get("data", {})
            if set(data) == {"manifest"}:
                manifest = data["manifest"]
            elif "source" in data and not set(data) - {"source", "thread_id", "node_id"}:
                if not isinstance(data["source"], str) or not data["source"] or len(data["source"]) > 4096:
                    _invalid("Invalid source folder")
                manifest = batch.manifest_for_folder(Path(data["source"]), thread_id=data.get("thread_id"),
                                                     node_id=data.get("node_id"))
            else:
                _invalid("data.manifest or an explicit data.source is required")
        _, digest = validate(manifest)
        if previous and previous["manifest_hash"] != digest:
            raise ManagementError("operation_conflict", "Operation ID belongs to a different import manifest.")
        return manifest, digest
