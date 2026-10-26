"""Checkpointed orchestration; CAS, graph and index are reconciled, not one transaction."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

from threaddesk.core.errors import InvalidState, NotFound
from threaddesk.core.models import new_thread, now_iso
from threaddesk.services.library_batch.jobs import JobStore
from threaddesk.services.library_batch.manifest import source_key, validate
from threaddesk.services.library_import import (
    LibraryImportError, LibraryImporter, MAX_BATCH_BYTES, UNASSIGNED_TITLE, _hash_file,
)
from threaddesk.services.library_index import LibraryIndex


class _ExpectedImporter(LibraryImporter):
    """Keep the caller's checksum binding through the existing publication path."""
    expected_source = None

    def _check_expected(self, digest, size):
        if self.expected_source is not None and self.expected_source != (digest, size):
            raise LibraryImportError("source_changed_during_import")

    def _stored_match(self, relative, digest, size):
        self._check_expected(digest, size)
        return super()._stored_match(relative, digest, size)

    def _publish_blob(self, source, digest, size):
        self._check_expected(digest, size)
        return super()._publish_blob(source, digest, size)


class LibraryBatchImporter:
    def __init__(self, store):
        self.store, self.importer, self.jobs = store, _ExpectedImporter(store), JobStore(store)

    def manifest_for_folder(self, source, *, thread_id=None, node_id=None):
        """Snapshot the current supplied folder; old inventories are comparison only."""
        supplied = Path(source)
        if any(parent.is_symlink() for parent in (supplied, *supplied.parents)):
            raise LibraryImportError("source_symlink")
        root = self.importer._accept_source(supplied)
        files = []
        for path, relative in self.importer._discover(root):
            ref = hashlib.sha256((str(root) + "\0" + relative).encode()).hexdigest()
            entry = {"path": str(path), "original_path": relative, "source_ref": "local-tree-" + ref,
                     "historical_identity": "current_local_snapshot"}
            if thread_id is not None:
                entry["thread_id"] = thread_id
            if node_id is not None:
                entry["node_id"] = node_id
            try:
                if not any(parent.is_symlink() for parent in (path, *path.parents)):
                    entry["sha256"], entry["size"] = _hash_file(path)
            except (OSError, LibraryImportError):
                pass  # The job reports this file independently, without losing others.
            files.append(entry)
        return {"files": files, "expected_count": len(files)}

    def status(self, operation_id):
        result = self.jobs.read(self.jobs.job_name(operation_id))
        if result is None:
            raise LibraryImportError("batch_not_found")
        return result

    def resume(self, operation_id):
        return self.run(self.status(operation_id)["manifest"], operation_id=operation_id)

    def run(self, manifest, *, operation_id):
        normalized, digest = validate(manifest)
        name = self.jobs.job_name(operation_id)
        with self.jobs.locked():
            job = self.jobs.read(name)
            if job is not None and job["manifest_hash"] != digest:
                raise LibraryImportError("operation_conflict")
            if job is None:
                job = {"version": 1, "operation_id": operation_id, "manifest_hash": digest,
                       "manifest": json.loads(json.dumps(manifest)), "created_at": now_iso(),
                       "state": "running", "complete": False, "files": [],
                       "projection": {"status": "pending"}, "index": {"status": "pending"}}
                self.jobs.write(name, job)
            if job["complete"]:
                return job
            previous = {item["source_key"]: item for item in job["files"]}
            sources = self.jobs.read("library-batch-sources.json", {"version": 1, "sources": {}})
            if not isinstance(sources.get("sources"), dict):
                raise LibraryImportError("batch_receipt_damaged")
            self.importer.recover_blob_publications(cleanup=True)
            results, total = [], 0
            for row in normalized["files"]:
                key = source_key(row)
                old = previous.get(key)
                if old and old["status"] in {"stored", "duplicate"}:
                    try:
                        _, record = self.importer.open_record(old["record_id"])
                        results.append(old)
                        total += record["size"]
                        continue
                    except (OSError, LibraryImportError, NotFound):
                        pass
                pending = {"source_key": key, "source_ref": row["source_ref"],
                           "original_path": row["original_path"], "status": "processing"}
                job["files"] = results + [pending]
                self.jobs.write(name, job)
                result = self._one(row, normalized["protected_exclusions"], sources, total)
                results.append(result)
                total += result.get("size", 0) if result["status"] in {"stored", "duplicate"} else 0
                # Source receipts and CAS may predate this checkpoint after a crash.
                self.jobs.write("library-batch-sources.json", sources)
                job["files"] = results
                self.jobs.write(name, job)
            job["projection"] = self._project()
            job["index"] = self._index()
            counts = Counter(item["status"] for item in results)
            counts["unavailable"] = normalized["expected_count"] - len(results)
            job["counts"] = dict(counts)
            derived_ready = job["projection"].get("status") == "ready" and job["index"].get("status") == "ready"
            job["complete"] = derived_ready and not counts["unavailable"] and all(
                item["status"] in {"stored", "duplicate"} for item in results)
            job["state"] = "complete" if job["complete"] else "partial"
            job["updated_at"] = now_iso()
            self.jobs.write(name, job)
            return job

    def _one(self, row, protected, sources, total):
        result = {"source_key": source_key(row), "source_ref": row["source_ref"],
                  "original_path": row["original_path"]}
        if row["source_ref"] in protected:
            return dict(result, status="blocked", error="protected_source")
        try:
            path = Path(row["path"])
            if any(parent.is_symlink() for parent in (path, *path.parents)):
                raise LibraryImportError("source_symlink")
            if not path.is_file():
                return dict(result, status="missing", error="source_missing")
            root = self.importer.workspace.resolve()
            resolved = path.resolve(strict=True)
            if resolved == root or root in resolved.parents:
                raise LibraryImportError("source_is_store")
            digest, size = _hash_file(path)
            if total + size > MAX_BATCH_BYTES:
                raise LibraryImportError("batch_too_large")
            if row.get("sha256") is not None and row["sha256"] != digest:
                return dict(result, status="conflict", error="source_checksum", actual_sha256=digest)
            if row.get("size") is not None and row["size"] != size:
                return dict(result, status="conflict", error="source_size", actual_size=size)
            if row.get("node_id"):
                self.store.get_node(row["node_id"])
            key = source_key(row)
            receipt = sources["sources"].get(key)
            unchanged = receipt and (receipt["sha256"], receipt["size"]) == (digest, size)
            if receipt and not unchanged and row.get("source_version") is not None:
                return dict(result, status="conflict", error="source_ref_conflict")
            predecessor = (receipt["record_id"] if receipt and not unchanged else
                           receipt.get("predecessor_record_id") if receipt else None)
            history = list(receipt.get("history", [])) if receipt else []
            if predecessor and predecessor not in history:
                history.append(predecessor)
            if unchanged:
                _, record = self.importer.open_record(receipt["record_id"])
                item_status = "duplicate"
                preserve = receipt.get("state") == "complete"
                new_record = bool(receipt.get("new_record")) and not preserve
            else:
                journal = self.importer._read_journal()
                self.importer.expected_source = (digest, size)
                imported, _created = self.importer._import_one(path, row["relative_path"], journal)
                if imported.status not in {"stored", "duplicate"}:
                    return dict(result, status="blocked" if imported.error.startswith("secret_") else "failed", error=imported.error)
                _, record = self.importer.open_record(imported.record_id)
                if (record["sha256"], record["size"]) != (digest, size):
                    raise LibraryImportError("source_changed_during_import")
                item_status = imported.status
                preserve = item_status == "duplicate"
                new_record = item_status == "stored"
            # Persist this stage before metadata/link writes, so interrupted mapping
            # is distinguishable from an already completed duplicate import.
            sources["sources"][key] = {"record_id": record["id"], "sha256": digest, "size": size,
                                       "state": "record_published", "history": history, "new_record": new_record,
                                       "predecessor_record_id": predecessor,
                                       "recorded_at": now_iso()}
            self.jobs.write("library-batch-sources.json", sources)
            if predecessor and new_record and not record.get("predecessor_record_id") and record["id"] != predecessor:
                record["predecessor_record_id"] = predecessor
            metadata_row = dict(row)
            if predecessor:
                previous_record = self._previous_record(predecessor)
                for field in ("thread_id", "node_id"):
                    if metadata_row.get(field) is None and previous_record.get(field):
                        metadata_row[field] = previous_record[field]
                if row.get("node_id") is None and previous_record.get("node_ids"):
                    record["node_ids"] = list(previous_record["node_ids"])
                if new_record and record["id"] != predecessor:
                    # A source refresh is a new byte version, never a restore.
                    for field in ("trashed", "trash_generation", "deleted_at", "restored_at"):
                        if field in previous_record:
                            record[field] = previous_record[field]
            record, assignment = self._metadata(record, metadata_row, preserve_assignment=preserve)
            sources["sources"][key]["state"] = "complete"
            source_error = self._post_copy_check(path, digest, size)
            return dict(result, status="conflict" if source_error else item_status,
                        **({"error": source_error} if source_error else {}),
                        record_id=record["id"], sha256=digest,
                        size=size, thread_id=record["thread_id"], node_id=record.get("node_id"),
                        assignment=assignment, predecessor_record_id=record.get("predecessor_record_id"),
                        historical_identity=row.get("historical_identity") or "unverified")
        except NotFound:
            return dict(result, status="conflict", error="attachment_node_missing")
        except LibraryImportError as exc:
            return dict(result, status="failed", error=exc.code)
        except (OSError, ValueError, InvalidState) as exc:
            return dict(result, status="failed", error=type(exc).__name__)

    @staticmethod
    def _post_copy_check(path, digest, size):
        try:
            if any(parent.is_symlink() for parent in (path, *path.parents)):
                return "source_changed_after_copy"
            if _hash_file(path) != (digest, size):
                return "source_changed_after_copy"
        except (OSError, LibraryImportError):
            return "source_unavailable_after_copy"
        return None

    def _previous_record(self, record_id):
        record = self.importer._record_by_id(record_id) or {}
        try:
            from threaddesk.services.library_files.state import apply_overlay
        except ModuleNotFoundError as exc:
            if exc.name not in {"threaddesk.services.library_files", "threaddesk.services.library_files.state"}:
                raise
            return record
        return apply_overlay(record, self.importer.root)

    def _metadata(self, record, row, *, preserve_assignment):
        assignment = "unassigned"
        try:
            thread_id = record.get("thread_id") if preserve_assignment else row.get("thread_id")
            thread = self.store.get_thread(thread_id) if thread_id else None
        except NotFound:
            thread = None
        if thread is not None:
            assignment = "explicit"
        else:
            thread = next((t for t in self.store.list_threads(include_archived=True)
                           if t.title == UNASSIGNED_TITLE), None)
            if thread is None:
                thread = new_thread(UNASSIGNED_TITLE, "Dateien ohne bestätigte Projektzuordnung.")
                self.store.save_thread(thread)
        if record.get("thread_id") != thread.id:
            self.importer._unlink_thread(record.get("thread_id"), record["id"])
            record.update(thread_id=thread.id, thread_title=thread.title, assignment=assignment)
        refs = list(record.get("source_refs") or [])
        if row["source_ref"] not in refs:
            refs.append(row["source_ref"])
        metadata = dict(record.get("source_metadata") or {})
        metadata[row["source_ref"]] = {"original_path": row["original_path"], "local_origin": row["path"],
                                      "source_version": row.get("source_version"),
                                      "historical_identity": row.get("historical_identity") or "unverified",
                                      "requested_thread_id": row.get("thread_id"), "requested_node_id": row.get("node_id")}
        record.update(source_refs=refs, source_metadata=metadata)
        if preserve_assignment:
            assignment = record.get("assignment") or assignment
        else:
            record["assignment"] = assignment
        if row.get("node_id") and not record.get("node_id"):
            record["node_id"] = row["node_id"]
        self.importer._write_json(self.importer.records / (record["id"] + ".json"), record)
        if record["id"] not in thread.context.extra.get("library_files", []):
            self.importer._link_thread(thread, record["id"])
        return record, assignment

    def _project(self):
        try:
            from threaddesk.services.library_links import sync_file_nodes
            return {"status": "ready", **sync_file_nodes(self.store)}
        except (ImportError, OSError, ValueError, NotFound, InvalidState) as exc:
            return {"status": "failed", "error": type(exc).__name__}

    def _index(self):
        try:
            from inspect import signature
            records = self.importer._read_records()
            rebuild = LibraryIndex(self.importer.root).rebuild
            if "store" in signature(rebuild).parameters:
                return rebuild(records, self.importer.blobs, store=self.store)
            return rebuild(records, self.importer.blobs)
        except (ImportError, OSError, ValueError, TypeError, InvalidState) as exc:
            return {"status": "failed", "error": type(exc).__name__}
