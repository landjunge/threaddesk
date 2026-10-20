"""Bounded pure projections owned by storage; never call legacy get_thread."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from threaddesk.core.models import Thread
from threaddesk.core.search import RECORD_BYTES, SearchDocument, SearchError


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise SearchError("invalid_identifier")
    return value


def source_tree(root):
    # Reuse the existing bound, no-follow storage reader, including Windows.
    if os.name == "nt":
        from threaddesk.storage.windows_backup_source import WindowsSourceTree
        return WindowsSourceTree(root, error_type=SearchError)
    else:
        from threaddesk.storage.workspace_backup import _SourceTree
        return _SourceTree(root)


def read_json(root: Path, relative: str, limit=RECORD_BYTES, *, reader=None):
    try:
        if reader is None:
            with source_tree(root) as source:
                return read_json(root, relative, limit, reader=source)
        else:
            source = reader
            expected = source.info(relative)
            raw = source.read(relative, expected, limit=limit)
        return json.loads(raw), len(raw)
    except Exception as exc:
        raise SearchError("source_unreadable_or_over_limit") from exc


def document(data, size):
    try:
        context = data.get("context") or {}
        org = (context.get("extra") or {}).get("organization") or {}
        values = [data.get("title", ""), data.get("description", ""), context.get("notes", "")]
        if any(not isinstance(v, str) for v in values):
            raise ValueError("invalid content")
        revision = data.get("revision", 0)
        if type(revision) is not int or revision < 0:
            raise ValueError("invalid revision")
        return SearchDocument(identifier(data["id"]), revision, *values,
                              org.get("project_id"), data.get("status", "idea"), size)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise SearchError("source_invalid") from exc


class JsonSearchAdapter:
    """No JSON index: bounded current-source scan, never a global snapshot."""
    mode = "bounded_scan"
    managed_generation = False

    def __init__(self, store):
        self.store = store
        self.root = store.workspace_path
        self._source = None

    def close(self):
        if self._source is not None:
            self._source.__exit__(None, None, None)
            self._source = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def state(self):
        if self.store._pending is not None:
            return {"enabled": False, "status": "unavailable", "generation": "",
                    "reason": "write_transaction_active"}
        path = self.root / "local-search.json"
        if not path.exists():
            return {"enabled": False, "status": "disabled", "generation": ""}
        try:
            data, _ = read_json(self.root, path.name, 16384)
            enabled = data["enabled"]
            if (type(data.get("format")) is not int or data["format"] != 1 or type(enabled) is not bool
                    or not isinstance(data["incarnation"], str) or len(data["incarnation"]) > 128):
                raise ValueError("invalid search state")
            info = self.store.threads_dir.stat()
            return {**data, "status": "scan_only" if enabled else "disabled",
                    "generation": "%s:%s:%s:%s" % (data["incarnation"], info.st_ino,
                                                     info.st_mtime_ns, info.st_ctime_ns)}
        except Exception:
            return {"enabled": False, "status": "unavailable", "generation": "",
                    "reason": "search_state_invalid"}

    def configure(self, enabled):
        from uuid import uuid4
        import tempfile
        self.close()
        path = self.root / "local-search.json"
        if path.is_symlink():
            raise SearchError("search_state_invalid")
        # Optional configuration is outside the canonical journal. A random
        # owner-only temporary file avoids following a predictable .tmp link.
        descriptor, temporary = tempfile.mkstemp(prefix=".search-", dir=self.root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"format": 1, "enabled": enabled, "incarnation": uuid4().hex}, stream)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return self.state()

    def rebuild(self):
        # Reconciliation of a scan-only source starts a new observation/cursor
        # generation; it does not falsely claim to have indexed every JSON file.
        if not self.state()["enabled"]:
            raise SearchError("search_disabled")
        return self.configure(True)

    def candidates(self, terms, project_id, include_archived, *, indexed=False):
        if self.store.threads_dir.is_symlink():
            raise SearchError("source_unreadable_or_over_limit")
        with os.scandir(self.store.threads_dir) as entries:
            for entry in entries:
                # Even unrelated/invalid entries consume one candidate budget.
                name = entry.name[:-5] if entry.name.endswith(".json") else ""
                yield name, None

    def read(self, exact_id):
        identifier(exact_id)
        if self._source is None:
            self._source = source_tree(self.root).__enter__()
        data, size = read_json(self.root, "threads/%s.json" % exact_id, reader=self._source)
        if data.get("id") != exact_id:
            raise SearchError("source_identity_mismatch")
        result = document(data, size)
        anchor_path = self.root / "thread-revisions" / (exact_id + ".json")
        if anchor_path.exists():
            anchor, anchor_size = read_json(self.root, "thread-revisions/%s.json" % exact_id, 16384, reader=self._source)
            if type(anchor.get("revision")) is not int or anchor["revision"] < 0:
                raise SearchError("source_invalid")
            # Calculate the same effective revision without writing an anchor.
            thread = Thread.from_dict(data)
            changed = self.store._thread_digest(thread) != anchor["content_hash"]
            from dataclasses import replace
            result = replace(result, revision=max(result.revision, anchor["revision"] + int(changed)),
                             source_bytes=size + anchor_size)
        return result


def projection_digest(doc):
    return hashlib.sha256(json.dumps([doc.thread_id, doc.revision, doc.title,
        doc.description, doc.notes, doc.project_id, doc.status], ensure_ascii=False).encode()).hexdigest()
