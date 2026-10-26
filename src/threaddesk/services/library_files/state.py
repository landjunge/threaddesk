"""Atomic metadata overlay for existing content-addressed library records.

A single owner document contains effective records and operation receipts. The
original imported records and blob bytes are retained unchanged. Database/store
transactions serialize writers; this document is the file-domain commit point.
"""
from __future__ import annotations

import copy
import json
import os
import stat
import tempfile
from pathlib import Path

from threaddesk.core.errors import ManagementError

STATE_NAME = "library-file-state.json"
MAX_STATE_BYTES = 32 * 1024 * 1024


def fail(code: str, message: str, **details):
    raise ManagementError(code, message, **details)


def state_path(library_root: Path) -> Path:
    return Path(library_root).parent / STATE_NAME


def check_path(path: Path, *, directory: bool = False) -> None:
    """Reject a changed storage root or link before reading/writing local state."""
    for part in (path, *path.parents):
        if part.is_symlink():
            fail("file_integrity", "Verknüpfte Speicherpfade sind nicht erlaubt.")
    if path.exists():
        info = path.lstat()
        if directory and not stat.S_ISDIR(info.st_mode):
            fail("file_integrity", "Speicherverzeichnis ist ungültig.")
        if not directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            fail("file_integrity", "Speicherdatei ist ungültig.")


def read_state(library_root: Path) -> dict:
    path = state_path(library_root)
    check_path(path)
    if not path.exists():
        return {"schema_version": 1, "generation": 0, "records": {}, "operations": {}}
    try:
        if path.stat().st_size > MAX_STATE_BYTES:
            raise ValueError("state size")
        data = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or data.get("schema_version") != 1
                or type(data.get("generation")) is not int or data["generation"] < 0
                or not isinstance(data.get("records"), dict)
                or not isinstance(data.get("operations"), dict)):
            raise ValueError("state shape")
        return data
    except (OSError, ValueError, TypeError) as exc:
        raise ManagementError("file_state_unavailable", "Dateiverwaltungsstand ist nicht lesbar.") from exc


def write_state(library_root: Path, state: dict) -> None:
    path = state_path(library_root)
    check_path(path)
    payload = (json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n").encode()
    if len(payload) > MAX_STATE_BYTES:
        fail("file_state_limit", "Dateiverwaltungsstand überschreitet das Größenlimit.")
    fd, temporary = tempfile.mkstemp(prefix=".library-file-state-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as outgoing:
            os.fchmod(outgoing.fileno(), 0o600)
            outgoing.write(payload)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        check_path(path)
        os.replace(temporary, path)
        if hasattr(os, "O_DIRECTORY"):
            parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def state_generation(library_root: Path) -> int:
    return read_state(library_root)["generation"]


def apply_overlay(record: dict, library_root: Path) -> dict:
    state = read_state(library_root)
    return normalize(state["records"].get(record.get("id"), record))


def normalize(record: dict) -> dict:
    value = copy.deepcopy(record)
    value.setdefault("revision", 1)
    value["file_node_id"] = value.get("id")
    value.setdefault("logical_path", value.get("origin_path", value.get("filename", "")))
    value.setdefault("trashed", False)
    value.setdefault("trash_generation", 0)
    # Older batch metadata added node_id after node_ids had become [].
    # Explicit unassignment removes both fields; retain real legacy links.
    targets = list(value.get("node_ids") or [])
    if value.get("node_id") and value["node_id"] not in targets:
        targets.insert(0, value["node_id"])
    value["node_ids"] = targets
    return value


def effective_records(records: list[dict], library_root: Path) -> list[dict]:
    state = read_state(library_root)
    rows = {record["id"]: normalize(record) for record in records}
    rows.update({key: normalize(value) for key, value in state["records"].items()})
    from threaddesk.services.library_files.versions import annotate_versions
    return annotate_versions([rows[key] for key in sorted(rows)], library_root)
