"""Private atomic job receipts, separate from the existing CAS file store."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import tempfile

from threaddesk.services.library_import import LibraryImportError
from threaddesk.services.library_batch.manifest import operation_id


class JobStore:
    def __init__(self, store):
        self.root = Path(store.workspace_path)

    def _path(self, name):
        path = self.root / name
        if self.root.is_symlink() or path.is_symlink():
            raise LibraryImportError("batch_store_path")
        return path

    @contextmanager
    def locked(self):
        """Serialize batch writers without locking the whole application database."""
        import fcntl
        path = self._path(".library-batch.lock")
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1:
                raise LibraryImportError("batch_store_path")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def read(self, name, default=None):
        path = self._path(name)
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            return default
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 16 * 1024 * 1024 or info.st_nlink != 1:
                raise LibraryImportError("batch_store_path")
            try:
                result = json.load(handle)
            except (UnicodeError, ValueError) as exc:
                raise LibraryImportError("batch_receipt_damaged") from exc
        if not isinstance(result, dict):
            raise LibraryImportError("batch_receipt_damaged")
        return result

    def write(self, name, payload):
        target = self._path(name)
        fd, temporary = tempfile.mkstemp(prefix=".library-batch-", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)

    @staticmethod
    def job_name(identity):
        return "library-batch-" + operation_id(identity) + ".json"
