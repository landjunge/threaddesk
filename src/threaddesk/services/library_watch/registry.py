"""Persistent owner-only watch declarations, separate from batch receipts."""

from __future__ import annotations

import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path

from threaddesk.services.library_batch.jobs import JobStore
from threaddesk.services.library_import import LibraryImportError

NAME = "library-watch.json"
MAX_WATCHES = 8


class WatchRegistry:
    def __init__(self, store):
        self.jobs = JobStore(store)

    @contextmanager
    def locked(self):
        import fcntl

        path = self.jobs._path(".library-watch.lock")
        descriptor = os.open(
            path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise LibraryImportError("watch_store_path")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LibraryImportError("watch_busy") from exc
            yield
        finally:
            os.close(descriptor)

    def read(self):
        value = self.jobs.read(NAME, {"schema_version": 1, "watches": {}})
        if (
            value.get("schema_version") != 1
            or not isinstance(value.get("watches"), dict)
            or len(value["watches"]) > MAX_WATCHES
        ):
            raise LibraryImportError("watch_registry_invalid")
        for identity, watch in value["watches"].items():
            if (
                not isinstance(identity, str)
                or not isinstance(watch, dict)
                or watch.get("id") != identity
                or not isinstance(watch.get("source"), str)
                or not Path(watch["source"]).is_absolute()
                or type(watch.get("sequence")) is not int
                or not isinstance(watch.get("files"), list)
                or not isinstance(watch.get("source_identity"), list)
                or len(watch["source_identity"]) != 2
            ):
                raise LibraryImportError("watch_registry_invalid")
        return value

    def write(self, value):
        if len(json.dumps(value, ensure_ascii=False).encode()) > 8 * 1024 * 1024:
            raise LibraryImportError("watch_registry_limit")
        self.jobs.write(NAME, value)
