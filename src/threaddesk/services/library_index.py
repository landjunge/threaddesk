"""Existing library search facade backed by a disposable SQLite FTS index.

Canonical bytes/records remain authoritative. JSON is retained as a small
compatibility/status manifest, not as the content-search implementation.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import date
from pathlib import Path
from uuid import uuid4
from urllib.parse import quote

from threaddesk.services.library_search.database import SearchDatabase
from threaddesk.services.library_search.normalize import folded, terms
from threaddesk.services.library_search.projections import (
    file_document,
    workspace_documents,
)

MAX_EXCERPT = 32 * 1024


class LibrarySearchError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class _KeepPrevious(Exception):
    pass


class LibraryIndex:
    def __init__(self, library_root: Path) -> None:
        root = Path(library_root)
        self.root = root.parent.resolve() / root.name
        self.path = self.root / "index.json"
        self.database = SearchDatabase(self.root)

    def _source_state(self):
        path = self.root.parent / "library-file-state.json"
        if path.is_symlink():
            raise OSError("state_unsafe")
        state = json.loads(path.read_text()) if path.exists() else {}
        generation = state.get("generation", 0)
        if type(generation) is not int or generation < 0:
            raise ValueError("state_invalid")
        records = self.root / "records"
        signature = []
        if records.is_symlink():
            raise OSError("records_unsafe")
        if records.is_dir():
            for record in sorted(records.glob("*.json")):
                stat = record.lstat()
                signature.append((record.name, stat.st_mtime_ns, stat.st_size))
        from threaddesk.storage.library_search_state import canonical_state
        signature.append(("canonical", canonical_state(self.root.parent)))
        receipts = self.root.parent / "library-batch-sources.json"
        if receipts.is_symlink():
            raise OSError("unsafe_source_receipts")
        if receipts.exists():
            info = receipts.stat()
            signature.append(("source_receipts", info.st_mtime_ns, info.st_size))
        return generation, hashlib.sha256(json.dumps(signature).encode()).hexdigest()

    def status(self) -> dict:
        document = self._read()
        if document is None:
            return {
                "status": "missing",
                "documents": 0,
                "failed": 0,
                "error": "",
                "mode": "missing",
            }
        result = {
            key: document.get(key, default)
            for key, default in (
                ("status", "ready"),
                ("failed", 0),
                ("error", ""),
                ("mode", "legacy_json"),
                ("generation", ""),
                ("state_generation", 0),
                ("entity_documents", 0),
                ("errors", []),
                ("projection_errors", []),
            )
        }
        result["documents"] = len(document.get("documents") or [])
        if document.get("backend") == "sqlite":
            try:
                state, signature = self._source_state()
                if state != document.get(
                    "state_generation"
                ) or signature != document.get("source_signature"):
                    result.update(status="stale", error="source_changed")
                elif not self.database.path.is_file():
                    result.update(status="failed", error="index_missing")
                else:
                    with self.database.connect() as db:
                        current = db.execute(
                            "SELECT value FROM metadata WHERE key='generation'"
                        ).fetchone()
                    if not current or current[0] != document.get("generation"):
                        result.update(status="stale", error="generation_changed")
            except (OSError, ValueError, TypeError, sqlite3.Error):
                result.update(status="failed", error="source_state_unreadable")
        return result

    def rebuild(self, records: list[dict], blobs: Path, *, store=None) -> dict:
        documents, errors, stored = (
            [],
            [],
            sum(record.get("status") == "stored" for record in records),
        )
        had_previous = self._has_ready_index()
        generation, signature = self._source_state()
        from threaddesk.services.library_search.projects import project_records
        records = project_records(store, records)
        token = uuid4().hex
        try:
            with self.database.connect(write=True) as db:
                mode = self.database.initialize(db)

                def source_documents():
                    for record in records:
                        if record.get("status") != "stored":
                            continue
                        try:
                            previous = db.execute(
                                "SELECT payload FROM documents WHERE key=?",
                                ("file:" + record["id"],),
                            ).fetchone()
                            doc = file_document(
                                record,
                                blobs,
                                json.loads(previous[0]) if previous else None,
                            )
                            if doc["extraction_status"] in {
                                "failed",
                                "unsupported",
                                "limited",
                            }:
                                errors.append(
                                    {
                                        "id": record.get("id", ""),
                                        "error": doc["extraction_error"]
                                        or doc["extraction_status"],
                                    }
                                )
                            documents.append(
                                {
                                    key: value
                                    for key, value in doc.items()
                                    if key
                                    not in {"normalized", "fingerprint", "excerpt"}
                                }
                            )
                            yield doc
                        except (OSError, ValueError, TypeError, KeyError) as exc:
                            errors.append(
                                {
                                    "id": record.get("id", ""),
                                    "error": type(exc).__name__,
                                }
                            )
                    if stored and not documents and had_previous:
                        raise _KeepPrevious()

                self.database.replace(db, source_documents(), ("file",))
                if store is not None:
                    self.database.replace(
                        db, workspace_documents(store, errors), ("thread", "node")
                    )
                db.execute(
                    "INSERT OR REPLACE INTO metadata VALUES('generation',?)", (token,)
                )
                entity_count = db.execute(
                    "SELECT count(*) FROM documents WHERE entity_type!='file'"
                ).fetchone()[0]
        except _KeepPrevious:
            return {
                **self.status(),
                "status": "failed",
                "failed": len(errors),
                "error": "index_kept",
            }
        manifest = {
            "version": 2,
            "backend": "sqlite",
            "mode": mode,
            "generation": token,
            "state_generation": generation,
            "source_signature": signature,
            "status": "partial"
            if errors and documents
            else "failed"
            if stored and not documents
            else "ready",
            "failed": len(errors),
            "errors": errors[:100],
            "error": "",
            "entity_documents": entity_count,
            "documents": documents,
        }
        self._replace(manifest)
        return self.status()

    def sync_workspace(self, store) -> dict:
        """Refresh existing thread projections/graph documents after a source write."""
        from threaddesk.services.library_import import LibraryImporter
        importer = LibraryImporter(store)
        return self.rebuild(importer._read_records(), importer.blobs, store=store)

    def search(
        self,
        text: str,
        *,
        limit: int = 20,
        thread_id=None,
        project_id=None,
        kind=None,
        date_from=None,
        date_to=None,
        assignment=None,
        include_trashed=False,
        offset=0,
        entity_type="file",
    ) -> list[dict]:
        query = terms(text)
        if not query:
            return []
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or type(offset) is not int
            or not 0 <= offset <= 10000
        ):
            raise LibrarySearchError("invalid_search_limit")
        if type(include_trashed) is not bool:
            raise LibrarySearchError("invalid_search_filter")
        document = self._read()
        if not document:
            return []
        state = self.status()
        if state["status"] in {"failed", "stale"}:
            raise LibrarySearchError("index_" + state["status"])
        filters = {"include_trashed": include_trashed}
        for key, value in (
            ("thread_id", thread_id),
            ("project_id", project_id),
            ("kind", kind),
            ("date_from", date_from),
            ("date_to", date_to),
            ("assignment", assignment),
        ):
            if value is not None:
                if not isinstance(value, str) or len(value) > 256:
                    raise LibrarySearchError("invalid_search_filter")
                filters[key] = value
        for value in (date_from, date_to):
            if value is not None:
                try:
                    date.fromisoformat(value[:10])
                except ValueError as exc:
                    raise LibrarySearchError("invalid_search_filter") from exc
        if entity_type != "all":
            if entity_type not in {"file", "thread", "node"}:
                raise LibrarySearchError("invalid_search_filter")
            filters["entity_type"] = entity_type
        if document.get("backend") != "sqlite":
            found = [
                item
                for item in document.get("documents", [])
                if all(
                    word in folded(" ".join(str(value) for value in item.values()))
                    for word in query
                )
                and all(
                    item.get(key) == value
                    for key, value in filters.items()
                    if key in {"thread_id", "project_id", "assignment"}
                )
            ]
            return found[offset : offset + limit]
        try:
            found = self.database.query(query, filters, limit, offset)
        except (sqlite3.Error, OSError, ValueError) as exc:
            raise LibrarySearchError("index_unavailable") from exc
        for item in found:
            item.pop("normalized", None)
            item.pop("fingerprint", None)
            content = item.pop("excerpt", "")
            matched = [
                content.casefold().find(word.casefold()) for word in text.split()
            ]
            begin = max(
                0, min((index for index in matched if index >= 0), default=0) - 60
            )
            item["snippet"] = content[begin : begin + 240]
            item["index_status"] = state["status"]
            item["open_path"] = (
                "/library/files/" + item["record_id"] if item.get("record_id") else ""
            )
            graph_id = item.get("file_node_id") or item.get("record_id") or item.get("node_id")
            item["graph_path"] = "/map?node=" + quote(str(graph_id), safe="") if graph_id else ""
            item["thread_path"] = (
                "/?thread=" + quote(str(item["thread_id"]), safe="") if item.get("thread_id") else ""
            )
        return found

    def _has_ready_index(self):
        value = self._read()
        return bool(
            value
            and value.get("status") in {"ready", "partial"}
            and value.get("documents")
        )

    def _read(self):
        if not self.path.is_file():
            return None
        try:
            if self.root.is_symlink() or self.path.is_symlink():
                raise OSError("index_unsafe_path")
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(
                data.get("documents"), list
            ):
                raise TypeError("index_invalid")
            return data
        except (OSError, ValueError, TypeError):
            return {
                "status": "failed",
                "failed": 0,
                "error": "index_unreadable",
                "documents": [],
            }

    def _replace(self, payload):
        if payload.get("backend") == "sqlite" and self.database.path.is_file():
            # Rebuilds release their data transaction before publishing JSON.
            # A newer worker may already have committed another generation.
            # Bind this publication to the current token while holding the same
            # SQLite writer reservation used by all index rebuilds/processes.
            with self.database.connect(write=True) as db:
                try:
                    current = db.execute(
                        "SELECT value FROM metadata WHERE key='generation'"
                    ).fetchone()
                except sqlite3.OperationalError:
                    # A failed/legacy projection may not have metadata yet.
                    # Preserve its failure marker so runtime repair can rebuild
                    # it, but never publish unverified ready results.
                    if payload.get("status") in {"ready", "partial"}:
                        raise
                    current = None
                if current is not None and current[0] != payload.get("generation"):
                    return
                if current is None and payload.get("status") in {"ready", "partial"}:
                    return
                self._write_manifest(payload)
            return
        self._write_manifest(payload)

    def _write_manifest(self, payload):
        if self.root.is_symlink() or self.path.is_symlink():
            raise OSError("index_unsafe_path")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(prefix=".index-", dir=self.root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False)
                stream.write("\n")
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
