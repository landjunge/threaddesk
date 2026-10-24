"""Verified library capture, including a self-contained receiver DB snapshot.

Only descriptor-bound copies are opened as SQLite databases. Original database
paths/WALs are never reopened by SQLite, recovered, checkpointed or modified.
An observed source change refuses publication; callers can retry the backup.
"""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import nullcontext
from pathlib import Path, PurePosixPath
import re
import sqlite3

from threaddesk.storage.workspace_backup import BackupError, _SourceTree

DIGEST = re.compile(r"^[0-9a-f]{64}$")
RECORD = re.compile(r"^[0-9a-f]{12}\.json$")
METADATA = {"journal.json", "index.json", "receive.sqlite3"}
SIDECARS = {"receive.sqlite3-wal", "receive.sqlite3-journal"}
JOURNAL_MAGIC = bytes.fromhex("d9d505f920a163d7")


def _reject_super_journal(root: Path) -> None:
    # A receiver uses one DB and never ATTACHes another. SQLite's rollback
    # trailer may name an external super-journal; reject it before SQLite can
    # perform recovery I/O. Format: sqlite.org/src/doc/trunk/src/pager.c,
    # readSuperJournal (length/checksum/magic in the final 16 bytes).
    journal = root / "receive.sqlite3-journal"
    if not journal.exists() or journal.stat().st_size < 16:
        return
    with journal.open("rb") as incoming:
        incoming.seek(-16, os.SEEK_END)
        trailer = incoming.read(16)
    if trailer[8:] == JOURNAL_MAGIC and int.from_bytes(trailer[:4], "big"):
        raise BackupError("Multi-database library journals are not supported.")


def allowed(name: str, *, capture=False) -> bool:
    parts = PurePosixPath(name).parts
    if len(parts) == 2 and parts[0] == "library-files":
        return parts[1] in METADATA or capture and parts[1] in SIDECARS
    if len(parts) == 3 and parts[0] == "library-files":
        return bool((parts[1] == "blobs" and DIGEST.fullmatch(parts[2]))
                    or (parts[1] == "records" and RECORD.fullmatch(parts[2])))
    return False


def descend(name: str) -> bool:
    return name in {"library-files", "library-files/blobs", "library-files/records"}


def _normalize_receiver(root: Path) -> None:
    database = root / "receive.sqlite3"
    if not database.exists():
        if any((root / name).exists() for name in SIDECARS):
            raise BackupError("Library receiver database is missing.")
        return
    normalized = root / "normalized.sqlite3"
    _reject_super_journal(root)
    source = None
    destination = None
    try:
        source = sqlite3.connect(database.absolute().as_uri() + "?mode=rw", uri=True)
        source.execute("PRAGMA trusted_schema=OFF")
        if source.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise BackupError("Library receiver integrity check failed.")
        destination = sqlite3.connect(normalized)
        source.backup(destination)
        destination.execute("PRAGMA journal_mode=DELETE")
    except sqlite3.Error as exc:
        raise BackupError("Library receiver snapshot cannot be captured safely.") from exc
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
    normalized.chmod(0o600)
    normalized.replace(database)
    # These names belong exclusively to the private capture directory.
    for name in (*SIDECARS, "receive.sqlite3-shm"):
        (root / name).unlink(missing_ok=True)


def capture(workspace: Path, destination: Path, *, limit: int | None = None, source_tree=None) -> bool:
    """Copy only the persistent library, rejecting races/links and partial data.

    destination is a newly owned private staging directory. Excludes disposable
    upload staging, blob partials and shared-memory sidecars. The DB plus WAL or
    rollback journal are copied together before SQLite opens that private copy.
    """
    workspace, destination = Path(workspace), Path(destination)
    total = 0
    with (_SourceTree(workspace) if source_tree is None else nullcontext(source_tree)) as source:
        def select(name):
            canonical = name.casefold()
            if name != canonical and (descend(canonical) or allowed(canonical, capture=True)):
                raise BackupError("Library path has a noncanonical case alias.")
            return descend(name) or allowed(name, capture=True)

        inventory = source.scan(select, descend)
        if any(descend(name) for name in inventory):
            raise BackupError("Library storage directory is not a directory.")
        if not inventory:
            return False
        for name, expected in inventory.items():
            if limit is not None and total + expected[3] > limit:
                raise BackupError("Library exceeds the backup size limit.")
            target = destination.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            with source.open(name, expected) as incoming, target.open("xb") as output:
                # Use the existing handle-based link check on native Windows.
                if hasattr(source, "check_control_journal_links"):
                    source.check_control_journal_links(incoming)
                elif os.fstat(incoming.fileno()).st_nlink != 1:
                    raise BackupError("Hardlinked library files are not allowed.")
                target.chmod(0o600)
                copied = 0
                while chunk := incoming.read(1024 * 1024):
                    copied += len(chunk)
                    if limit is not None and total + copied > limit:
                        raise BackupError("Library exceeds the backup size limit.")
                    output.write(chunk)
                if copied != expected[3]:
                    raise BackupError("Library changed during backup. Please try again.")
                total += copied
        _normalize_receiver(destination / "library-files")
        validate(destination / "library-files")
        if source.scan(select, descend) != inventory:
            raise BackupError("Library changed during backup. Please try again.")
    return True


def _hash(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as incoming:
        while chunk := incoming.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def validate(root: Path) -> None:
    """Check private restored/captured files before selecting or publishing them."""
    root = Path(root)
    if not root.exists():
        return
    try:
        records = {}
        checked = {}
        for path in (root / "records").glob("*.json"):
            item = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(item, dict) or item.get("id") != path.stem
                    or item.get("status") != "stored" or not isinstance(item.get("sha256"), str)
                    or not DIGEST.fullmatch(item["sha256"]) or type(item.get("size")) is not int
                    or item["size"] < 0):
                raise BackupError("Invalid library record.")
            blob = root / "blobs" / item["sha256"]
            if item["sha256"] not in checked:
                checked[item["sha256"]] = _hash(blob)
            if checked[item["sha256"]] != (item["sha256"], item["size"]):
                raise BackupError("Library blob checksum does not match its record.")
            records[item["id"]] = item
        # Unreferenced complete blobs are preserved too (publication can have
        # been interrupted before its record). Never accept corrupt copies.
        for blob in (root / "blobs").glob("*"):
            if not DIGEST.fullmatch(blob.name) or (blob.name not in checked and _hash(blob)[0] != blob.name):
                raise BackupError("Invalid library blob.")
        journal = root / "journal.json"
        if journal.exists():
            value = json.loads(journal.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not isinstance(value.get("items"), dict):
                raise BackupError("Invalid library import journal.")
            for item in value["items"].values():
                if not isinstance(item, dict):
                    raise BackupError("Invalid library import state.")
                if item.get("status") == "stored":
                    record = records.get(item.get("record_id"))
                    if (record is None or (item.get("sha256"), item.get("size"))
                            != (record["sha256"], record["size"])):
                        raise BackupError("Library import journal is missing its verified copy.")
        database = root / "receive.sqlite3"
        if database.exists():
            connection = sqlite3.connect(database.absolute().as_uri() + "?mode=ro&immutable=1", uri=True)
            try:
                connection.execute("PRAGMA trusted_schema=OFF")
                if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise BackupError("Invalid library receiver database.")
                if connection.execute("SELECT count(*) FROM chunks WHERE transfer_id NOT IN (SELECT id FROM transfers)").fetchone()[0]:
                    raise BackupError("Library chunks have no transfer.")
                for transfer_id, manifest, record_id, state, offset, receipt in connection.execute(
                        "SELECT id,manifest,record_id,state,next_offset,receipt FROM transfers"):
                    info = json.loads(manifest)
                    if (not isinstance(info, dict) or type(info.get("size")) is not int
                            or not 0 <= info["size"] <= 256 * 1024 * 1024
                            or not isinstance(info.get("sha256"), str) or not DIGEST.fullmatch(info["sha256"])
                            or type(offset) is not int or not 0 <= offset <= info["size"]
                            or state not in {"receiving", "committed", "aborted"}):
                        raise BackupError("Invalid library transfer state.")
                    if state == "committed":
                        acknowledgement = json.loads(receipt)
                        record = records.get(record_id)
                        if (record is None or acknowledgement["transfer_id"] != transfer_id
                                or acknowledgement["record_id"] != record_id
                                or acknowledgement["format"] != "threaddesk.library.receipt.v1"
                                or acknowledgement["thread_id"] != info["thread_id"]
                                or (acknowledgement["sha256"], acknowledgement["size"]) != (info["sha256"], info["size"])
                                or (record["sha256"], record["size"]) != (info["sha256"], info["size"])):
                            raise BackupError("Library receipt is missing its verified copy.")
                    chunks = connection.execute("SELECT offset,length(data) FROM chunks WHERE transfer_id=? ORDER BY offset", (transfer_id,))
                    end = 0
                    for start, length in chunks:
                        if start != end or not 1 <= length <= 256 * 1024 or state != "receiving":
                            raise BackupError("Invalid library transfer chunks.")
                        end += length
                    if state == "receiving" and end != offset:
                        raise BackupError("Library transfer bytes are incomplete.")
            finally:
                connection.close()
    except BackupError:
        raise
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        raise BackupError("Library backup cannot be verified.") from exc
