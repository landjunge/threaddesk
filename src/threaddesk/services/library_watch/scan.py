"""Bounded metadata-only change detection for explicitly authorized folders."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from time import monotonic

from threaddesk.services.library_import import _SKIP_DIRS, MAX_FILES, LibraryImportError

MAX_SCAN_ENTRIES = 8192
MAX_SCAN_DIRECTORIES = 256
MAX_SCAN_SECONDS = 0.25


def snapshot(root: Path) -> dict:
    deadline = monotonic() + MAX_SCAN_SECONDS
    pending = [root]
    rows, warnings = [], []
    entries = directories = 0
    while pending:
        if monotonic() > deadline or directories >= MAX_SCAN_DIRECTORIES:
            raise LibraryImportError("watch_scan_budget")
        directory = pending.pop()
        if directory.is_symlink():
            warnings.append(
                {
                    "path": directory.relative_to(root).as_posix(),
                    "error": "source_symlink",
                }
            )
            continue
        directories += 1
        with os.scandir(directory) as children:
            for entry in children:
                entries += 1
                if entries > MAX_SCAN_ENTRIES or monotonic() > deadline:
                    raise LibraryImportError("watch_scan_budget")
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    if (
                        not entry.name.startswith(".")
                        and entry.name.casefold() not in _SKIP_DIRS
                    ):
                        pending.append(path)
                    continue
                if len(rows) >= MAX_FILES or len(relative.encode()) > 4096:
                    raise LibraryImportError("watch_scan_budget")
                if stat.S_ISLNK(info.st_mode):
                    warnings.append({"path": relative, "error": "source_symlink"})
                rows.append(
                    [
                        relative,
                        info.st_size,
                        info.st_mtime_ns,
                        info.st_ctime_ns,
                        info.st_ino,
                        stat.S_IFMT(info.st_mode),
                    ]
                )
    rows.sort()
    fingerprint = hashlib.sha256(
        json.dumps(rows, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "fingerprint": fingerprint,
        "files": [row[0] for row in rows],
        "warnings": warnings,
        "entries": entries,
        "directories": directories,
    }
