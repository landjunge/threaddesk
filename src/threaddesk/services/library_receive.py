"""Resumable local MCP receiver. The upstream bridge owns authentication.

Only bytes, a filename and an existing thread ID cross this boundary. No URL,
source path, principal claim, command or destination path is accepted.
SQLite commits chunks/offsets together and keeps receipts across MCP restarts.
"""
from __future__ import annotations

import base64
import binascii
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile

from threaddesk.core.errors import ManagementError
from threaddesk.core.models import new_id
from threaddesk.services.library_import import (
    LibraryImporter, MAX_FILE_BYTES, validate_received_filename,
)

MAX_CHUNK_BYTES = 256 * 1024
MAX_ACTIVE = 32
MAX_RESERVED = 512 * 1024 * 1024
ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
FIELDS = {
    "begin": {"transfer_id", "filename", "thread_id", "size", "sha256"},
    "append": {"transfer_id", "offset", "data_base64"},
    "status": {"transfer_id"},
    "commit": {"transfer_id"},
    "abort": {"transfer_id"},
}


def fail(code: str):
    raise ManagementError(code, f"Library receiver: {code}")


def validate(args: dict) -> str:
    if not isinstance(args, dict):
        fail("validation_error")
    action = args.get("action")
    if not isinstance(action, str) or action not in FIELDS:
        fail("validation_error")
    if set(args) != FIELDS[action] | {"action"}:
        fail("validation_error")
    if not isinstance(args["transfer_id"], str) or not ID.fullmatch(args["transfer_id"]):
        fail("validation_error")
    if action == "begin":
        validate_received_filename(args["filename"])
        if not isinstance(args["thread_id"], str) or not ID.fullmatch(args["thread_id"]):
            fail("validation_error")
        if type(args["size"]) is not int or not 0 <= args["size"] <= MAX_FILE_BYTES:
            fail("validation_error")
        if not isinstance(args["sha256"], str) or not DIGEST.fullmatch(args["sha256"]):
            fail("validation_error")
    if action == "append":
        if type(args["offset"]) is not int or not 0 <= args["offset"] <= MAX_FILE_BYTES:
            fail("validation_error")
        data = args["data_base64"]
        if not isinstance(data, str) or not 1 <= len(data) <= 4 * ((MAX_CHUNK_BYTES + 2) // 3):
            fail("chunk_size")
    return action


def schema() -> dict:
    props = {
        "action": {"type": "string", "enum": list(FIELDS)},
        "transfer_id": {"type": "string", "pattern": ID.pattern},
        "filename": {"type": "string", "minLength": 1, "maxLength": 240},
        "thread_id": {"type": "string", "pattern": ID.pattern},
        "size": {"type": "integer", "minimum": 0, "maximum": MAX_FILE_BYTES},
        "sha256": {"type": "string", "pattern": DIGEST.pattern},
        "offset": {"type": "integer", "minimum": 0, "maximum": MAX_FILE_BYTES},
        "data_base64": {"type": "string", "minLength": 1,
                        "maxLength": 4 * ((MAX_CHUNK_BYTES + 2) // 3)},
    }
    return {"type": "object", "oneOf": [
        {"type": "object", "additionalProperties": False,
         "required": ["action", *sorted(fields)],
         "properties": {"action": {"const": action}, **{k: props[k] for k in fields}}}
        for action, fields in FIELDS.items()
    ]}


class LibraryReceiver:
    def __init__(self, store):
        self.store = store
        self.importer = LibraryImporter(store)
        self.root = self.importer.root
        self.db = self.root / "receive.sqlite3"

    def _guard(self, *, recover=False):
        # This is an owner-local workspace, not a sandbox against hostile
        # concurrent filesystem replacement. Refuse existing links/special files.
        for path in (self.importer.workspace, self.root, self.importer.records, self.importer.blobs):
            for parent in (path, *path.parents):
                if parent.is_symlink():
                    fail("unsafe_store")
            if path.exists() and not path.is_dir():
                fail("unsafe_store")
        for path in (self.root / "index.json", self.root / "index.json.tmp",
                     self.db, self.db.with_name(self.db.name + "-journal"),
                     self.db.with_name(self.db.name + "-wal"), self.db.with_name(self.db.name + "-shm")):
            if path.is_symlink():
                fail("unsafe_store")
            if path.exists():
                info = path.stat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    fail("unsafe_store")
        internal_links = self.importer.recover_blob_publications(cleanup=False)
        for folder in (self.importer.records, self.importer.blobs):
            if folder.is_dir():
                for path in folder.iterdir():
                    info = path.lstat()
                    if (not stat.S_ISREG(info.st_mode)
                            or info.st_nlink != 1 and path not in internal_links):
                        fail("unsafe_store")
        if recover and internal_links:
            self.importer.recover_blob_publications(cleanup=True)

    @contextmanager
    def _connect(self, *, readonly=False):
        self._guard(recover=not readonly)
        if readonly:
            conn = sqlite3.connect(self.db.absolute().as_uri() + "?mode=ro", uri=True, timeout=10)
        else:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                fd = os.open(self.db, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(fd)
            conn = sqlite3.connect(self.db, timeout=10)
            conn.execute("PRAGMA synchronous=FULL")
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS transfers (
                    id TEXT PRIMARY KEY, manifest TEXT NOT NULL,
                    record_id TEXT NOT NULL, state TEXT NOT NULL,
                    next_offset INTEGER NOT NULL, receipt TEXT);
                CREATE TABLE IF NOT EXISTS chunks (
                    transfer_id TEXT NOT NULL, offset INTEGER NOT NULL,
                    data BLOB NOT NULL, PRIMARY KEY (transfer_id, offset));
            ''')
            conn.execute("BEGIN IMMEDIATE")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            if not readonly:
                conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _public(row):
        return {"found": True, "transfer_id": row["id"], "state": row["state"],
                "next_offset": row["next_offset"], "manifest": json.loads(row["manifest"]),
                "receipt": json.loads(row["receipt"]) if row["receipt"] else None,
                "max_chunk_bytes": MAX_CHUNK_BYTES}

    def call(self, args: dict) -> dict:
        action = validate(args)
        transfer_id = args["transfer_id"]
        if action == "status" and not self.db.exists():
            self._guard()
            return {"found": False, "transfer_id": transfer_id}
        with self._connect(readonly=action == "status") as conn:
            row = conn.execute("SELECT * FROM transfers WHERE id=?", (transfer_id,)).fetchone()
            if action == "begin":
                manifest = {k: args[k] for k in ("filename", "thread_id", "size", "sha256")}
                encoded = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
                if row:
                    if row["manifest"] != encoded:
                        fail("transfer_conflict")
                    return self._public(row)
                self.store.get_thread(manifest["thread_id"])
                active = conn.execute("SELECT manifest FROM transfers WHERE state='receiving'").fetchall()
                if len(active) >= MAX_ACTIVE or sum(json.loads(r[0])["size"] for r in active) + manifest["size"] > MAX_RESERVED:
                    fail("receive_quota")
                conn.execute("INSERT INTO transfers VALUES (?,?,?,'receiving',0,NULL)",
                             (transfer_id, encoded, new_id()))
            elif not row:
                if action == "status":
                    return {"found": False, "transfer_id": transfer_id}
                fail("transfer_missing")
            elif action == "append":
                if row["state"] != "receiving":
                    fail("transfer_closed")
                try:
                    data = base64.b64decode(args["data_base64"], validate=True)
                except (binascii.Error, ValueError):
                    fail("invalid_base64")
                if not 1 <= len(data) <= MAX_CHUNK_BYTES:
                    fail("chunk_size")
                offset = args["offset"]
                old = conn.execute("SELECT data FROM chunks WHERE transfer_id=? AND offset=?", (transfer_id, offset)).fetchone()
                if old:
                    if old[0] != data:
                        fail("chunk_conflict")
                else:
                    manifest = json.loads(row["manifest"])
                    if offset != row["next_offset"]:
                        fail("offset_conflict")
                    if offset + len(data) > manifest["size"]:
                        fail("size_mismatch")
                    conn.execute("INSERT INTO chunks VALUES (?,?,?)", (transfer_id, offset, data))
                    conn.execute("UPDATE transfers SET next_offset=? WHERE id=?", (offset + len(data), transfer_id))
            elif action == "commit":
                if row["state"] == "aborted":
                    fail("transfer_closed")
                if row["state"] != "committed":
                    receipt = self._commit(conn, row)
                    conn.execute("UPDATE transfers SET state='committed',receipt=? WHERE id=?",
                                 (json.dumps(receipt, ensure_ascii=False), transfer_id))
                    conn.execute("DELETE FROM chunks WHERE transfer_id=?", (transfer_id,))
            elif action == "abort":
                if row["state"] == "committed":
                    fail("transfer_closed")
                conn.execute("UPDATE transfers SET state='aborted' WHERE id=?", (transfer_id,))
                conn.execute("DELETE FROM chunks WHERE transfer_id=?", (transfer_id,))
            return self._public(conn.execute("SELECT * FROM transfers WHERE id=?", (transfer_id,)).fetchone())

    def _commit(self, conn, row):
        manifest = json.loads(row["manifest"])
        if row["next_offset"] != manifest["size"]:
            fail("transfer_incomplete")
        # Unique private staging is never exposed as a tool argument or result.
        with tempfile.TemporaryDirectory(prefix="receive-", dir=self.root) as folder:
            path = Path(folder) / "payload"
            digest = hashlib.sha256()
            with path.open("xb") as output:
                for chunk in conn.execute("SELECT data FROM chunks WHERE transfer_id=? ORDER BY offset", (row["id"],)):
                    output.write(chunk[0])
                    digest.update(chunk[0])
                output.flush()
                os.fsync(output.fileno())
            if digest.hexdigest() != manifest["sha256"]:
                fail("checksum_mismatch")
            receipt = self.importer.receive_verified(path, filename=manifest["filename"],
                thread_id=manifest["thread_id"], record_id=row["record_id"],
                sha256=manifest["sha256"], size=manifest["size"])
            # Flush published bytes/record before a durable success receipt.
            for saved in (self.importer.blobs / manifest["sha256"],
                          self.importer.records / f"{row['record_id']}.json"):
                with saved.open("rb") as handle:
                    os.fsync(handle.fileno())
            if os.name != "nt":
                for directory in (self.importer.blobs, self.importer.records, self.root):
                    fd = os.open(directory, os.O_RDONLY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
        return {"format": "threaddesk.library.receipt.v1", "transfer_id": row["id"], **receipt}
