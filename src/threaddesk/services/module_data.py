"""One owned module-data artifact, with a shared writer lock and CAS revision."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
import stat

from threaddesk.core.errors import InvalidState, ManagementError
from threaddesk.core.secrets import reject_secrets

MAX_DATA_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 10000


@contextmanager
def locked_artifact(store, name):
    """Cross-process lock for writers of this existing artifact family."""
    path = store.artifact_path(name)
    if path.is_symlink():
        raise InvalidState("module_control_path")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "a+b") as stream:
            identity = os.fstat(stream.fileno())
            current = path.lstat()
            if (not stat.S_ISREG(identity.st_mode) or identity.st_nlink != 1
                    or (identity.st_dev, identity.st_ino) != (current.st_dev, current.st_ino)):
                raise InvalidState("module_control_path")
            if os.name == "nt":
                import msvcrt
                if os.fstat(stream.fileno()).st_size == 0:
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        raise InvalidState("module_control_path") from exc


def load(store, module_id):
    path = store.artifact_path(f"module-{module_id}-data.json")
    if path.is_symlink():
        raise InvalidState("module_data")
    if not path.exists():
        return {"schema_version": 1, "records": {}}
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DATA_BYTES:
        raise InvalidState("module_data")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise InvalidState("module_data") from exc
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or not isinstance(value.get("records"), dict)
            or type(value.get("revision", 0)) is not int or value.get("revision", 0) < 0):
        raise InvalidState("module_data")
    return value


def write_record(store, module_id, record_id, value, *, expected_revision=None):
    """The only writer used by both legacy ModuleContext and new commands."""
    with locked_artifact(store, f"module-{module_id}-data.lock"):
        state = load(store, module_id)
        revision = state.get("revision", 0)
        if expected_revision is not None:
            if type(expected_revision) is not int or expected_revision < 0:
                raise ManagementError("validation_error", "Invalid module-data revision")
            if revision != expected_revision:
                raise ManagementError("revision_conflict", "Module data changed since it was read",
                                      actual_revision=revision, expected_revision=expected_revision)
        if record_id not in state["records"] and len(state["records"]) >= MAX_RECORDS:
            raise ManagementError("module_data_limit", "Module record budget reached")
        state["records"][record_id] = dict(value)
        state["revision"] = revision + 1
        try:
            encoded = json.dumps(state, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ManagementError("validation_error", "Module records require JSON values") from exc
        reject_secrets(encoded)
        if len(encoded.encode("utf-8")) > MAX_DATA_BYTES:
            raise ManagementError("module_data_limit", "Module data exceeds its byte budget")
        store.write_json_artifact(f"module-{module_id}-data.json", state)
        return {"record_id": record_id, "revision": state["revision"]}
