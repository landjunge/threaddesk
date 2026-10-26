"""Change-triggered import orchestration; no broad scanner or second importer."""

from __future__ import annotations

import hashlib
from pathlib import Path
from time import time

from threaddesk.core.errors import NotFound
from threaddesk.core.models import now_iso
from threaddesk.services.library_batch import LibraryBatchImporter
from threaddesk.services.library_import import LibraryImporter, LibraryImportError
from threaddesk.services.library_watch.registry import MAX_WATCHES, WatchRegistry
from threaddesk.services.library_watch.scan import snapshot

RETRY_SECONDS = 30


class LibrarySourceWatch:
    def __init__(self, store):
        self.store = store
        self.registry = WatchRegistry(store)

    def _source(self, source):
        supplied = Path(source).absolute()
        if any(part.is_symlink() for part in (supplied, *supplied.parents)):
            raise LibraryImportError("source_symlink")
        return LibraryImporter(self.store)._accept_source(supplied)

    def register(self, source, thread_id=None, node_id=None):
        root = self._source(source)
        if thread_id is not None:
            self.store.get_thread(thread_id)
        if node_id is not None:
            self.store.get_node(node_id)
        identity = hashlib.sha256(str(root).encode()).hexdigest()[:24]
        with self.registry.locked():
            state = self.registry.read()
            old = state["watches"].get(identity)
            if old:
                if (old.get("thread_id"), old.get("node_id")) != (thread_id, node_id):
                    raise LibraryImportError("watch_assignment_conflict")
                return dict(old)
            if len(state["watches"]) >= MAX_WATCHES:
                raise LibraryImportError("watch_limit")
            info = root.stat()
            value = {
                "id": identity,
                "source": str(root),
                "thread_id": thread_id,
                "node_id": node_id,
                "source_identity": [info.st_dev, info.st_ino],
                "registered_at": now_iso(),
                "status": "pending",
                "sequence": 0,
                "fingerprint": "",
                "files": [],
                "last_attempt": None,
                "last_success": None,
                "last_error": "",
                "retry_after": 0,
                "last_attempt_fingerprint": "",
                "operation_id": None,
                "missing_sources": [],
            }
            state["watches"][identity] = value
            self.registry.write(state)
            return dict(value)

    def status(self):
        state = self.registry.read()
        return {
            "schema_version": 1,
            "max_watches": MAX_WATCHES,
            "watches": [
                self._public(state["watches"][key]) for key in sorted(state["watches"])
            ],
        }

    @staticmethod
    def _public(watch):
        value = {
            key: item
            for key, item in watch.items()
            if key not in {"files", "stored_sources"}
        }
        value["files_count"] = len(watch.get("files", []))
        for key in ("missing_sources", "scan_warnings"):
            rows = watch.get(key, [])
            value[key] = rows[:25]
            value[key + "_count"] = len(rows)
            value[key + "_truncated"] = len(rows) > 25
        return value

    def _observe(self, watch):
        root = self._source(watch["source"])
        info = root.stat()
        if [info.st_dev, info.st_ino] != watch["source_identity"]:
            raise LibraryImportError("source_replaced")
        return root, snapshot(root)

    def poll_once(self):
        """Process one changed source; unchanged polls do not hash or write."""
        with self.registry.locked():
            state = self.registry.read()
            outcomes = []
            watches = list(state["watches"].values())
            previous = state.get("last_processed")
            if previous in state["watches"]:
                start = (
                    next(
                        index
                        for index, value in enumerate(watches)
                        if value["id"] == previous
                    )
                    + 1
                )
                watches = watches[start:] + watches[:start]
            for watch in watches:
                try:
                    root, observed = self._observe(watch)
                except (OSError, LibraryImportError) as exc:
                    error = getattr(exc, "code", "source_unavailable")
                    if watch.get("last_error") != error or time() >= watch.get(
                        "retry_after", 0
                    ):
                        watch.update(
                            status="unavailable",
                            last_error=error,
                            last_attempt=now_iso(),
                            retry_after=time() + RETRY_SECONDS,
                        )
                        self.registry.write(state)
                    outcomes.append(
                        {"id": watch["id"], "status": "unavailable", "error": error}
                    )
                    continue
                fingerprint = observed["fingerprint"]
                if fingerprint == watch["fingerprint"] and not watch["last_error"]:
                    outcomes.append({"id": watch["id"], "status": "unchanged"})
                    continue
                same_attempt = fingerprint == watch.get("last_attempt_fingerprint")
                if (
                    same_attempt
                    and watch.get("last_error")
                    and time() < watch.get("retry_after", 0)
                ):
                    outcomes.append(
                        {
                            "id": watch["id"],
                            "status": "backoff",
                            "error": watch["last_error"],
                        }
                    )
                    continue
                state["last_processed"] = watch["id"]
                self._refresh(state, watch, root, observed, same_attempt)
                outcomes.append(
                    {
                        "id": watch["id"],
                        "status": watch["status"],
                        "operation_id": watch["operation_id"],
                    }
                )
                break
            return {**self.status(), "outcomes": outcomes}

    def _refresh(self, state, watch, root, observed, same_attempt):
        fingerprint = observed["fingerprint"]
        if not same_attempt or not watch.get("operation_id"):
            watch["sequence"] += 1
            watch["operation_id"] = (
                f"watch-{watch['id']}-{watch['sequence']}-{fingerprint[:16]}"
            )
        watch.update(
            last_attempt=now_iso(),
            last_attempt_fingerprint=fingerprint,
            status="running",
            last_error="",
        )
        self.registry.write(state)  # Durable identity precedes any import side effect.
        batch = LibraryBatchImporter(self.store)
        try:
            try:
                batch.status(watch["operation_id"])
            except LibraryImportError as exc:
                if exc.code != "batch_not_found":
                    raise
                manifest = batch.manifest_for_folder(
                    root, thread_id=watch["thread_id"], node_id=watch["node_id"]
                )
                job = batch.run(manifest, operation_id=watch["operation_id"])
            else:
                job = batch.resume(watch["operation_id"])
            _, after = self._observe(watch)
            current = after["fingerprint"] == fingerprint
            complete = (
                bool(job.get("complete")) and current and not observed["warnings"]
            )
            stored = dict(watch.get("stored_sources", {}))
            stored.update(
                {
                    row["original_path"]: row["record_id"]
                    for row in job.get("files", [])
                    if row.get("status") in {"stored", "duplicate"}
                    and row.get("record_id")
                }
            )
            missing = {row["path"]: row for row in watch.get("missing_sources", [])}
            for name in set(watch["files"]) - set(observed["files"]):
                missing[name] = {
                    "path": name,
                    "status": "source_missing",
                    "record_id": stored.get(name),
                    "stored_copy_not_deleted_by_watch": True,
                }
            for name in observed["files"]:
                missing.pop(name, None)
            watch["missing_sources"] = [missing[name] for name in sorted(missing)]
            watch["stored_sources"] = stored
            watch.update(
                files=observed["files"],
                receipt={
                    "operation_id": job["operation_id"],
                    "complete": job.get("complete", False),
                    "counts": job.get("counts", {}),
                    "source_current": current,
                },
                scan_warnings=observed["warnings"],
            )
            if complete:
                watch.update(
                    fingerprint=fingerprint,
                    status="ready",
                    last_error="",
                    last_success=now_iso(),
                    retry_after=0,
                )
            else:
                error = (
                    "source_changed_during_import" if not current else "partial_import"
                )
                watch.update(
                    status="partial",
                    last_error=error,
                    retry_after=time() + RETRY_SECONDS,
                )
        except (OSError, ValueError, LibraryImportError, NotFound) as exc:
            watch.update(
                status="failed",
                last_error=getattr(exc, "code", type(exc).__name__),
                retry_after=time() + RETRY_SECONDS,
            )
        self.registry.write(state)
