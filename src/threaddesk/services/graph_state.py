"""Bounded, private owner documents shared by activity and saved graph views.

The document is its own commit point for both JSON and SQLite profiles. Reads
never create a document or lock. Writers use a stable lock inode and publish an
fsynced replacement, so an interrupted write leaves either complete version.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import tempfile

from threaddesk.core.errors import ManagementError
from threaddesk.services.library_files.state import check_path

MAX_BYTES = 16 * 1024 * 1024


class GraphDocument:
    def __init__(self, store, name, initial):
        if name not in {"file-activity.json", "graph-views.json", "graph-view-control.json"}:
            raise ValueError("Unknown graph owner document")
        self.store = store
        self.root = Path(store.workspace_path)
        self.path = self.root / name
        self.initial = initial

    def read(self):
        check_path(self.path)
        try:
            descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            migrated = (getattr(self.store, "get_migrated_owner_document", None)
                        if self.path.name in {"file-activity.json", "graph-views.json"} else None)
            data = migrated(self.path.name) if migrated else None
            return data if data is not None else self.initial()
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES:
                raise ValueError("Owner document size or type")
            with os.fdopen(descriptor, "r", encoding="utf-8") as incoming:
                descriptor = None
                data = json.load(incoming)
            if not isinstance(data, dict) or data.get("schema_version") != 1:
                raise ValueError("Owner document schema")
            return data
        except (OSError, ValueError, TypeError) as exc:
            raise ManagementError("graph_state_unavailable", "Graph state cannot be read.") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)

    @contextmanager
    def locked(self):
        import fcntl
        path = self.path.with_name("." + self.path.stem + ".lock")
        check_path(path)
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ManagementError("graph_state_unavailable", "Graph lock is invalid.")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    def write(self, data):
        payload = (json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode()
        if len(payload) > MAX_BYTES:
            raise ManagementError("graph_state_limit", "Graph state exceeds its storage budget.")
        check_path(self.path)
        descriptor, temporary = tempfile.mkstemp(prefix="." + self.path.stem + "-", dir=self.root)
        try:
            with os.fdopen(descriptor, "wb") as outgoing:
                os.fchmod(outgoing.fileno(), 0o600)
                outgoing.write(payload)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            check_path(self.path)
            os.replace(temporary, self.path)
            if hasattr(os, "O_DIRECTORY"):
                directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)
