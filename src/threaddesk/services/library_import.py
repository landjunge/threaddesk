"""Copy provided library files into ThreadDesk. Originals are only read.

ChatGPT does not expose a library API to this program. The operator supplies
a folder, selected files, or a zip export. Bytes land in a content-addressed
store after a second SHA-256 check. An existing blob is never overwritten.
"""
from __future__ import annotations

from threaddesk.services.file_formats.registry import FORMATS as FORMAT_REGISTRY

from datetime import datetime, timezone
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import zipfile

from threaddesk.core.errors import InvalidState, NotFound, SecretRejected, ThreadDeskError
from threaddesk.core.models import new_id, new_thread
from threaddesk.core.secrets import reject_secrets
from threaddesk.services.library_index import LibraryIndex

MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_BATCH_BYTES = 2 * 1024 * 1024 * 1024
MAX_FILES = 2000
MAX_ZIP_ENTRIES = 500
MAX_ZIP_UNCOMPRESSED = 256 * 1024 * 1024
MAX_TEXT_SCAN = 2 * 1024 * 1024
UNASSIGNED_TITLE = "Nicht zugeordnet"
_RECORD_ID = re.compile(r"^[0-9a-f]{12}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_PUBLICATION_PARTIAL = re.compile(r"^\.([0-9a-f]{64})\.[a-z0-9_]{8}$")
_SKIP_DIRS = {
    ".git", ".ssh", ".aws", ".gnupg", ".threaddesk", "node_modules",
    "__pycache__", "keychains",
}
_SECRET_NAME = re.compile(
    r"(?i)(^|[._-])(env|id_rsa|id_ed25519|credentials|cookies|secrets?)($|[._-])"
    r"|\.(pem|key|p12|pfx|kdbx)$"
)
_FORMATS = {suffix: (entry[0], entry[1]) for suffix, entry in FORMAT_REGISTRY.items()}


def _format_for(suffix):
    return _FORMATS.get(suffix, ("unknown", "application/octet-stream"))


_EXECUTABLE_SUFFIXES = {".exe", ".com", ".command", ".msi", ".app", ".pkg", ".dmg"}
_TEXT_SUFFIXES = {suffix for suffix, entry in FORMAT_REGISTRY.items()
                  if entry[2] in {"text", "html", "rtf"}}


class LibraryImportError(InvalidState):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ImportItem:
    relative_path: str
    status: str
    sha256: str = ""
    size: int = 0
    record_id: str = ""
    error: str = ""
    thread_id: str = ""
    thread_title: str = ""
    filename: str = ""
    format: str = ""


def supported_formats() -> list[dict[str, str]]:
    rows = []
    for suffix, (kind, media) in sorted(_FORMATS.items()):
        rows.append({"suffix": suffix, "format": kind, "media_type": media})
    return rows


def _size_label(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size / (1024 * 1024):.1f} MiB"


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())


def _safe_relative(name: str) -> str:
    text = name.replace("\\", "/").strip()
    if not text or "\x00" in text or text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise LibraryImportError("unsafe_path")
    pure = PurePosixPath(text)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise LibraryImportError("unsafe_path")
    return pure.as_posix()


def _hash_file(path: Path, limit: int = MAX_FILE_BYTES) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise LibraryImportError("file_too_large")
            digest.update(chunk)
    return digest.hexdigest(), size


def _looks_secret_name(relative: str) -> bool:
    name = PurePosixPath(relative).name
    return bool(_SECRET_NAME.search(name))


def _scan_text(path: Path, suffix: str) -> None:
    if suffix not in _TEXT_SUFFIXES:
        return
    with path.open("rb") as handle:
        sample = handle.read(MAX_TEXT_SCAN + 1)
    if len(sample) > MAX_TEXT_SCAN:
        sample = sample[:MAX_TEXT_SCAN]
    try:
        text = sample.decode("utf-8")
    except UnicodeError:
        return
    reject_secrets(text)


def _zip_members(package: Path) -> list[tuple[str, bytes]]:
    if not zipfile.is_zipfile(package):
        raise LibraryImportError("zip_invalid")
    members: list[tuple[str, bytes]] = []
    total = 0
    with zipfile.ZipFile(package) as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if len(infos) > MAX_ZIP_ENTRIES:
            raise LibraryImportError("zip_too_many")
        for info in infos:
            if info.flag_bits & 0x1:
                raise LibraryImportError("zip_encrypted")
            relative = _safe_relative(info.filename)
            if info.file_size > MAX_FILE_BYTES or info.compress_size > MAX_FILE_BYTES:
                raise LibraryImportError("file_too_large")
            total += info.file_size
            if total > MAX_ZIP_UNCOMPRESSED:
                raise LibraryImportError("zip_too_large")
            payload = archive.read(info)
            if len(payload) != info.file_size or len(payload) > MAX_FILE_BYTES:
                raise LibraryImportError("zip_size_mismatch")
            members.append((relative, payload))
    return members


class LibraryImporter:
    def __init__(self, store) -> None:
        self.store = store
        self.workspace = Path(store.workspace_path)
        self.root = self.workspace / "library-files"
        self.blobs = self.root / "blobs"
        self.records = self.root / "records"
        self.journal_path = self.root / "journal.json"

    def catalog(self) -> dict:
        journal = self._read_journal()
        records = [self._public_record(item) for item in self._read_records()]
        stored = [item for item in records if item["integrity"] == "verified" and not item.get("trashed")]
        failed = [item for item in journal["items"].values() if item.get("status") == "failed"]
        pending = [item for item in journal["items"].values() if item.get("status") == "pending"]
        outstanding = self._outstanding(journal)
        return {
            "records": stored,
            "failures": failed,
            "pending": pending,
            "outstanding": outstanding,
            "counts": {
                "stored": len(stored),
                "failed": len(failed),
                "pending": len(pending),
                "outstanding": len(outstanding),
                "records": len(records),
            },
            "source": journal.get("source") or "",
            "complete": not failed and not pending and not outstanding,
            "formats": supported_formats(),
            "limits": {
                "file_bytes": MAX_FILE_BYTES,
                "batch_bytes": MAX_BATCH_BYTES,
                "files": MAX_FILES,
            },
            "index": LibraryIndex(self.root).status(),
        }

    def for_thread(self, thread_id: str) -> list[dict]:
        try:
            records = self._read_records()
        except (OSError, json.JSONDecodeError):
            return []
        return [
            self._public_record(item) for item in records
            if item.get("thread_id") == thread_id and item.get("status") == "stored" and not item.get("trashed")
        ]

    def import_tree(self, source: Path) -> dict:
        root = self._accept_source(source)
        discovered = self._discover(root)
        journal = self._read_journal()
        journal["source"] = str(root)
        batch = 0
        results: list[ImportItem] = []
        for path, relative in discovered:
            if batch > MAX_BATCH_BYTES:
                results.append(ImportItem(relative, "failed", error="batch_too_large"))
                self._remember(journal, relative, status="failed", error="batch_too_large")
                continue
            item, added = self._import_one(path, relative, journal)
            results.append(item)
            if item.status == "stored":
                batch += item.size
            elif added:
                batch += item.size
        self._write_json(self.journal_path, journal)
        summary = self._summary(results)
        summary["verified"] = self._verify_stored()
        summary["index"] = self.rebuild_index()
        return summary

    def import_files(self, named: list[tuple[str, Path]]) -> dict:
        with tempfile.TemporaryDirectory(prefix="threaddesk-library-") as folder:
            root = Path(folder)
            for raw_name, payload in named:
                relative = _safe_relative(raw_name)
                target = root.joinpath(*PurePosixPath(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(payload, target)
            return self.import_tree(root)

    def import_zip_package(self, package: Path) -> dict:
        members = _zip_members(package)
        with tempfile.TemporaryDirectory(prefix="threaddesk-library-zip-") as folder:
            root = Path(folder)
            for relative, payload in members:
                target = root.joinpath(*PurePosixPath(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
            return self.import_tree(root)

    def rebuild_index(self) -> dict:
        try:
            from threaddesk.services.library_links import sync_file_nodes
            sync_file_nodes(self.store)
            return LibraryIndex(self.root).rebuild(self._read_records(), self.blobs, store=self.store)
        except (OSError, ValueError, ThreadDeskError):
            return {"status": "failed", "documents": 0, "failed": 0, "error": "index_store"}

    def reassign(self, record_id: str, thread_title: str) -> dict:
        """Legacy name-based facade; effective membership belongs to file manager."""
        from threaddesk.services.library_files import LibraryFileService
        service = LibraryFileService(self.store)
        record = service.info(record_id)
        matches = [thread for thread in self.store.list_threads(include_archived=True)
                   if _norm(thread.title) == _norm(thread_title)]
        if not matches:
            raise LookupError(thread_title)
        if len(matches) != 1:
            from threaddesk.core.errors import ManagementError
            raise ManagementError("assignment_conflict", "Threadtitel ist nicht eindeutig.")
        result = service.manage({"operation_id": "legacy-reassign-" + new_id(),
                                 "action": "assign", "id": record_id,
                                 "expected_revision": record["revision"],
                                 "data": {"thread_id": matches[0].id}})
        return self._public_record(result["record"])

    def _unlink_thread(self, thread_id: str | None, record_id: str) -> None:
        if not thread_id:
            return
        try:
            current = self.store.get_thread(thread_id)
        except NotFound:
            return
        ids = [item for item in list(current.context.extra.get("library_files") or []) if item != record_id]
        current.context.extra["library_files"] = ids
        self.store.save_thread(current)

    def resume(self) -> dict:
        source = self._read_journal().get("source") or ""
        if not source:
            raise LibraryImportError("no_source")
        return self.import_tree(Path(source))

    def open_record(self, record_id: str, *, include_trashed: bool = False) -> tuple[Path, dict]:
        if not _RECORD_ID.fullmatch(record_id or ""):
            raise NotFound(record_id)
        path = self.records / f"{record_id}.json"
        record = self._record_by_id(record_id)
        if record is None or (record.get("trashed") and include_trashed is not True):
            raise NotFound(record_id)
        try:
            if self.records.is_symlink() or path.is_symlink():
                raise LibraryImportError("integrity")
            expected = record.get("sha256", "")
            if (not isinstance(expected, str) or not _DIGEST.fullmatch(expected)
                    or record.get("id") != record_id or type(record.get("size")) is not int):
                raise LibraryImportError("integrity")
            blob = self.blobs / expected
            if (self.root.is_symlink() or self.blobs.is_symlink() or blob.is_symlink()
                    or not blob.is_file() or blob.stat().st_nlink != 1):
                raise LibraryImportError("integrity")
            digest, size = _hash_file(blob)
            if digest != expected or size != record["size"] or record.get("status") != "stored":
                raise LibraryImportError("integrity")
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise LibraryImportError("integrity") from exc
        return blob, record

    def receive_verified(self, path: Path, *, filename: str, thread_id: str,
                         record_id: str, sha256: str, size: int) -> dict:
        """Publish a receiver-owned staging file, repairing interrupted retries.

        The receiver persists record_id before this call. Never auto-assign a
        remote upload by a folder title or accept a caller-selected local path.
        """
        thread = self.store.get_thread(thread_id)
        validate_received_filename(filename)
        if not _RECORD_ID.fullmatch(record_id) or not _DIGEST.fullmatch(sha256):
            raise LibraryImportError("integrity")
        _scan_text(path, Path(filename).suffix.casefold())
        if _hash_file(path) != (sha256, size):
            raise LibraryImportError("integrity")
        target = self.records / f"{record_id}.json"
        if target.exists():
            _, record = self.open_record(record_id)
            if (record["sha256"], record["size"], record["thread_id"], record["filename"]) != (sha256, size, thread_id, filename):
                raise LibraryImportError("receipt_conflict")
        else:
            self._publish_blob(path, sha256, size)
            kind, media = _format_for(Path(filename).suffix.casefold())
            record = self._write_record(relative=filename, digest=sha256, size=size,
                                        kind=kind, media=media, thread=thread,
                                        version=self._next_version(filename), record_id=record_id)
        self._link_thread(thread, record_id)
        return {"record_id": record_id, "sha256": sha256, "size": size,
                "thread_id": thread_id, "open_path": f"/library/files/{record_id}",
                "index": self.rebuild_index()}

    def _accept_source(self, source: Path) -> Path:
        try:
            root = source.resolve(strict=True)
        except OSError as exc:
            raise LibraryImportError("source_missing") from exc
        if not root.is_dir() or root.is_symlink():
            raise LibraryImportError("source_not_directory")
        home = Path.home().resolve()
        if root == home or root == Path(root.anchor).resolve():
            raise LibraryImportError("source_too_broad")
        if any(part.casefold() in _SKIP_DIRS for part in root.parts):
            raise LibraryImportError("source_blocked")
        workspace = self.workspace.resolve()
        if root == workspace or workspace in root.parents or root in workspace.parents:
            raise LibraryImportError("source_is_store")
        return root

    def _discover(self, root: Path) -> list[tuple[Path, str]]:
        found: list[tuple[Path, str]] = []
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [
                name for name in dirnames
                if not name.startswith(".") and name.casefold() not in _SKIP_DIRS
            ]
            for name in sorted(filenames):
                path = Path(dirpath) / name
                relative = path.relative_to(root).as_posix()
                if path.is_symlink():
                    found.append((path, relative))
                    continue
                try:
                    resolved = path.resolve(strict=True)
                except OSError:
                    found.append((path, relative))
                    continue
                if self.workspace.resolve() in resolved.parents or resolved == self.workspace.resolve():
                    continue
                found.append((path, relative))
                if len(found) > MAX_FILES:
                    raise LibraryImportError("too_many_files")
        return found

    def _import_one(self, path: Path, relative: str, journal: dict) -> tuple[ImportItem, bool]:
        try:
            relative = _safe_relative(relative)
        except LibraryImportError as exc:
            self._remember(journal, relative, status="failed", error=exc.code)
            return ImportItem(relative, "failed", error=exc.code), False
        if path.is_symlink() or not path.is_file():
            self._remember(journal, relative, status="failed", error="not_a_file")
            return ImportItem(relative, "failed", error="not_a_file"), False
        suffix = PurePosixPath(relative).suffix.casefold()
        if suffix in _EXECUTABLE_SUFFIXES:
            self._remember(journal, relative, status="failed", error="unsupported")
            return ImportItem(relative, "failed", error="unsupported"), False
        if _looks_secret_name(relative):
            self._remember(journal, relative, status="failed", error="secret_name")
            return ImportItem(relative, "failed", error="secret_name"), False
        try:
            _scan_text(path, suffix)
            digest, size = _hash_file(path)
        except SecretRejected:
            self._remember(journal, relative, status="failed", error="secret_content")
            return ImportItem(relative, "failed", error="secret_content"), False
        except LibraryImportError as exc:
            self._remember(journal, relative, status="failed", error=exc.code)
            return ImportItem(relative, "failed", error=exc.code), False
        existing = self._stored_match(relative, digest, size)
        if existing is not None:
            self._remember(
                journal, relative, status="stored", sha256=digest, size=size,
                record_id=existing["id"], error="",
            )
            return ImportItem(
                relative, "duplicate", sha256=digest, size=size, record_id=existing["id"],
                thread_id=existing.get("thread_id", ""), thread_title=existing.get("thread_title", ""),
                filename=existing.get("filename", ""), format=existing.get("format", ""),
            ), False
        self._remember(journal, relative, status="pending", sha256=digest, size=size)
        try:
            created = self._publish_blob(path, digest, size)
            kind, media = _format_for(suffix)
            thread = self._assign(relative)
            record = self._write_record(
                relative=relative, digest=digest, size=size, kind=kind, media=media,
                thread=thread, version=self._next_version(relative),
            )
            self._link_thread(thread, record["id"])
        except (LibraryImportError, OSError) as exc:
            code = exc.code if isinstance(exc, LibraryImportError) else "store_failed"
            self._remember(journal, relative, status="failed", sha256=digest, size=size, error=code)
            return ImportItem(relative, "failed", sha256=digest, size=size, error=code), False
        self._remember(
            journal, relative, status="stored", sha256=digest, size=size,
            record_id=record["id"], error="",
        )
        return ImportItem(
            relative, "stored", sha256=digest, size=size, record_id=record["id"],
            thread_id=thread.id, thread_title=thread.title,
            filename=PurePosixPath(relative).name, format=kind,
        ), created

    def recover_blob_publications(self, *, cleanup: bool = False) -> set[Path]:
        """Recognize a completed internal link pair after a process crash.

        Read callers only validate the pair. Explicit writes may unlink its
        private temporary name, preserving the published blob. Any unknown or
        external hardlink still fails the receiver's normal guard.
        """
        recognized: set[Path] = set()
        pairs: list[tuple[Path, Path]] = []
        if not self.blobs.is_dir():
            return recognized
        for partial in self.blobs.iterdir():
            match = _PUBLICATION_PARTIAL.fullmatch(partial.name)
            if not match:
                continue
            target = self.blobs / match[1]
            try:
                left, right = partial.lstat(), target.lstat()
            except FileNotFoundError:
                continue
            if (not stat.S_ISREG(left.st_mode) or not stat.S_ISREG(right.st_mode)
                    or left.st_nlink != 2 or right.st_nlink != 2
                    or (left.st_dev, left.st_ino) != (right.st_dev, right.st_ino)):
                continue
            if _hash_file(target)[0] != match[1]:
                continue
            recognized.update((partial, target))
            pairs.append((partial, target))
        if cleanup:
            for partial, target in pairs:
                # Recheck identities before removing only the internal name.
                left, right = partial.lstat(), target.lstat()
                if (left.st_dev, left.st_ino, left.st_nlink) != (right.st_dev, right.st_ino, 2):
                    raise LibraryImportError("integrity")
                partial.unlink()
        return recognized

    def _publish_blob(self, source: Path, digest: str, size: int) -> bool:
        self.blobs.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = self.blobs / digest
        if target.exists():
            if not self._blob_matches(digest, size):
                raise LibraryImportError("existing_checksum")
            return False
        digest_copy = hashlib.sha256()
        copied = 0
        fd, name = tempfile.mkstemp(prefix=f".{digest}.", dir=self.blobs)
        partial = Path(name)
        try:
            with os.fdopen(fd, "wb") as outgoing, source.open("rb") as incoming:
                while True:
                    chunk = incoming.read(1024 * 1024)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > size:
                        raise LibraryImportError("copy_checksum")
                    outgoing.write(chunk)
                    digest_copy.update(chunk)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if digest_copy.hexdigest() != digest or copied != size:
                raise LibraryImportError("copy_checksum")
            try:
                os.link(partial, target)  # Exclusive publication; never replace an existing blob.
            except FileExistsError:
                if not self._blob_matches(digest, size):
                    raise LibraryImportError("existing_checksum")
                return False
        finally:
            partial.unlink(missing_ok=True)
        if not self._blob_matches(digest, size):
            raise LibraryImportError("copy_checksum")
        return True

    def _blob_matches(self, digest: str, size: int) -> bool:
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            return False
        target = self.blobs / digest
        if self.root.is_symlink() or self.blobs.is_symlink() or target.is_symlink() or not target.is_file():
            return False
        actual, actual_size = _hash_file(target)
        return actual == digest and actual_size == size

    def _stored_match(self, relative: str, digest: str, size: int) -> dict | None:
        if not self._blob_matches(digest, size):
            return None
        for record in self._read_records():
            if (record.get("origin_path") == relative and record.get("sha256") == digest
                    and record.get("status") == "stored"):
                return record
        return None

    def _assign(self, relative: str):
        from threaddesk.api.service import ThreadService
        threads = ThreadService(store=self.store).list(include_archived=True)
        by_title = {}
        for thread in threads:
            by_title.setdefault(_norm(thread.title), thread)
        folders = PurePosixPath(relative).parts[:-1]
        for part in reversed(folders):
            match = by_title.get(_norm(part))
            if match is not None:
                return match
        existing = by_title.get(_norm(UNASSIGNED_TITLE))
        if existing is not None:
            return existing
        thread = new_thread(UNASSIGNED_TITLE, "Dateien ohne eindeutige Projektzuordnung.")
        self.store.save_thread(thread)
        return thread

    def _link_thread(self, thread, record_id: str) -> None:
        current = self.store.get_thread(thread.id)
        ids = list(current.context.extra.get("library_files") or [])
        if record_id not in ids:
            ids.append(record_id)
        current.context.extra["library_files"] = ids
        self.store.save_thread(current)

    def _write_record(self, *, relative, digest, size, kind, media, thread, version: int, record_id=None) -> dict:
        record = {
            "id": record_id or new_id(),
            "sha256": digest,
            "size": size,
            "filename": PurePosixPath(relative).name,
            "format": kind,
            "media_type": media,
            "origin_path": relative,
            "thread_id": thread.id,
            "thread_title": thread.title,
            "assignment": "unassigned" if _norm(thread.title) == _norm(UNASSIGNED_TITLE) else "matched",
            "status": "stored",
            "version": version,
            "integrity": "verified",
            "imported_at": datetime.now(timezone.utc).isoformat(),
        }
        self.records.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._write_json(self.records / f"{record['id']}.json", record)
        return record

    def _next_version(self, relative: str) -> int:
        versions = [
            int(item.get("version") or 0)
            for item in self._read_records()
            if item.get("origin_path") == relative
        ]
        return max(versions, default=0) + 1

    def _record_by_id(self, record_id: str) -> dict | None:
        if not isinstance(record_id, str) or not _RECORD_ID.fullmatch(record_id):
            return None
        from threaddesk.services.library_files.state import normalize, read_state
        overlay = read_state(self.root)["records"].get(record_id)
        if overlay is not None:
            return normalize(overlay)
        path = self.records / f"{record_id}.json"
        if not path.is_file():
            return None
        if self.root.is_symlink() or self.records.is_symlink() or path.is_symlink():
            raise LibraryImportError("integrity")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise LibraryImportError("integrity")
            return normalize(record)
        except (OSError, ValueError) as exc:
            raise LibraryImportError("integrity") from exc

    def _read_records(self) -> list[dict]:
        from threaddesk.services.library_files.state import effective_records
        rows = []
        if self.records.is_dir():
            if self.root.is_symlink() or self.records.is_symlink():
                raise LibraryImportError("integrity")
            for path in sorted(self.records.glob("*.json")):
                if not _RECORD_ID.fullmatch(path.stem):
                    continue
                if path.is_symlink():
                    raise LibraryImportError("integrity")
                rows.append(json.loads(path.read_text(encoding="utf-8")))
        return effective_records(rows, self.root)

    def _public_record(self, record: dict) -> dict:
        item = dict(record)
        item["integrity"] = record.get("integrity") or "unchecked"
        item["size_label"] = _size_label(int(record.get("size") or 0))
        return item

    def _verify_stored(self) -> bool:
        records = self._read_records()
        return all(
            item.get("status") == "stored" and self._blob_matches(item.get("sha256", ""), int(item.get("size") or 0))
            for item in records
        )

    def _outstanding(self, journal: dict) -> list[dict]:
        source = journal.get("source") or ""
        if not source:
            return [
                item for item in journal["items"].values()
                if item.get("status") != "stored"
            ]
        root = Path(source)
        try:
            root = self._accept_source(root)
        except LibraryImportError:
            return [
                item for item in journal["items"].values()
                if item.get("status") != "stored"
            ]
        missing = []
        try:
            discovered = self._discover(root)
        except LibraryImportError:
            return [{"relative_path": key, **value} for key, value in journal["items"].items() if value.get("status") != "stored"]
        for _path, relative in discovered:
            current = journal["items"].get(relative)
            if not current or current.get("status") != "stored":
                missing.append({"relative_path": relative, "status": (current or {}).get("status") or "outstanding"})
        return missing

    def _read_journal(self) -> dict:
        if not self.journal_path.is_file():
            return {"version": 1, "source": "", "items": {}}
        data = json.loads(self.journal_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
            raise LibraryImportError("journal_damaged")
        data.setdefault("version", 1)
        data.setdefault("source", "")
        return data

    def _remember(self, journal: dict, relative: str, **fields) -> None:
        current = dict(journal["items"].get(relative) or {})
        current["relative_path"] = relative
        current.update(fields)
        journal["items"][relative] = current
        self._write_json(self.journal_path, journal)

    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(path)

    @staticmethod
    def _summary(results: list[ImportItem]) -> dict:
        def count(status: str) -> int:
            return sum(1 for item in results if item.status == status)
        return {
            "stored": count("stored"),
            "duplicate": count("duplicate"),
            "failed": count("failed"),
            "results": [item.__dict__ for item in results],
        }


def validate_received_filename(filename: str) -> None:
    if (not isinstance(filename, str) or not filename or len(filename.encode("utf-8")) > 240
            or filename in {".", ".."} or any(ord(c) < 32 or c in '/\\:' for c in filename)):
        raise LibraryImportError("unsafe_path")
    if _looks_secret_name(filename):
        raise LibraryImportError("secret_name")
    if Path(filename).suffix.casefold() in _EXECUTABLE_SUFFIXES:
        raise LibraryImportError("unsupported")
