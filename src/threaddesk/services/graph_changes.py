"""Cheap, inert graph invalidation; never read imported contents or add activity.

JSON's canonical writers publish atomic replacements, so fixed directory
metadata observes object commits without opening every document. SQLite uses
the existing canonical revision signature within one read-only snapshot. Root
directory times, control heartbeats, command receipts and indexes are excluded.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import stat
import time

from threaddesk.core.errors import ThreadDeskError
from threaddesk.core.models import now_iso
from threaddesk.services.activity import utc
from threaddesk.services.library_files.state import check_path
from threaddesk.storage.library_search_state import canonical_state
from threaddesk.storage.owner_documents import KEY as MIGRATED_OWNER_KEY

DIRECTORIES = ("threads", "nodes", "relations", "trash", "library-files", "library-files/records")
OWNER_FILES = ("library-file-state.json", "file-activity.json")


def _metadata(path, *, directory=False, identity_only=False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    valid = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    if not valid:
        raise OSError("unsafe_graph_state")
    identity = (info.st_dev, info.st_ino)
    return identity if identity_only else (*identity, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class GraphChangeService:
    def __init__(self, store):
        self.store = store
        self.root = Path(store.workspace_path)

    def _files(self):
        # Only the directory identity is relevant at root: its timestamps also
        # change for every view-control heartbeat and unrelated receipt.
        result = [["workspace", _metadata(self.root, directory=True, identity_only=True)]]
        for name in DIRECTORIES:
            result.append([name, _metadata(self.root / name, directory=True, identity_only=name == "library-files")])
        for name in OWNER_FILES:
            result.append([name, _metadata(self.root / name)])
        return result

    def _sqlite(self):
        path = self.store.database_path
        check_path(path)
        identity = _metadata(path, identity_only=True)
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
            deadline = time.monotonic() + 0.5
            db.set_progress_handler(lambda: time.monotonic() > deadline, 10000)
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("BEGIN")
            state = canonical_state(self.root, connection=db)
            relations = hashlib.sha256()
            for row in db.execute("SELECT id,source_id,target_id,kind,created_at,json_extract(payload,'$.revision') FROM relations ORDER BY id"):
                relations.update(json.dumps(tuple(row), separators=(",", ":")).encode())
                relations.update(b"\n")
            # Migration can retain the initial activity only in SQLite until
            # the owner publishes its first file. A revision is sufficient.
            migrated = None
            if not (self.root / "file-activity.json").exists():
                migrated = db.execute("SELECT json_extract(value,'$.\"file-activity.json\".revision') FROM app_state WHERE key=?",
                                      (MIGRATED_OWNER_KEY,)).fetchone()
            return [identity, state, relations.hexdigest(), tuple(migrated) if migrated else None]

    def status(self, *, workspace_id):
        as_of = utc(now_iso()).isoformat()
        result = {"schema": "threaddesk.graph.change-status.v1", "workspace_id": workspace_id,
                  "as_of": as_of, "minute": as_of[:16], "status": "unavailable", "fingerprint": None}
        try:
            check_path(self.root, directory=True)
            for _ in range(2):
                # The management journal marks a multi-document JSON commit;
                # wait for its canonical result instead of showing a partial graph.
                if not hasattr(self.store, "database_path") and (self.root / ".management-commit.json").exists():
                    continue
                before = self._files()
                database = self._sqlite() if hasattr(self.store, "database_path") else None
                after = self._files()
                if before == after and (hasattr(self.store, "database_path") or not (self.root / ".management-commit.json").exists()):
                    body = json.dumps([after, database], separators=(",", ":"), allow_nan=False).encode()
                    return {**result, "status": "ready", "fingerprint": hashlib.sha256(body).hexdigest()}
            return {**result, "error": "graph_state_changing"}
        except (OSError, ValueError, TypeError, sqlite3.Error, ThreadDeskError):
            return {**result, "error": "graph_change_status_unavailable"}
