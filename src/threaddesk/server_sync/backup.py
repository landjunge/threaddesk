"""Cold, complete server snapshots with verified restore into a new directory.

The CLI server and account provisioning must hold server_lock for their lifetime.
No filesystem snapshot promise is made for arbitrary external writers.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tarfile
import tempfile
import unicodedata

FORMAT = "threaddesk.server.backup.v1"
MAX_BYTES = 4 * 1024**3
MAX_FILES = 100000
MAX_MANIFEST = 16 * 1024**2
LOCK = ".server.lock"


class BackupError(ValueError):
    pass


def _plain_path(path):
    path = Path(os.path.abspath(path))
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise BackupError("Symlink paths are not allowed")
    return path


@contextmanager
def server_lock(data_dir):
    """Fail instead of backing up a running server or starting a second server."""
    import fcntl
    root = _plain_path(data_dir)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not root.is_dir():
        raise BackupError("Private server directory required")
    root.chmod(0o700)
    descriptor = os.open(root / LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise BackupError("Unsafe server lock")
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BackupError("Stop the server before backup; data directory is in use") from exc
        yield root
    finally:
        os.close(descriptor)


def _relative(value):
    if (not isinstance(value, str) or not value or len(value.encode("utf-8")) > 4096
            or "\\" in value or ":" in value or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise BackupError("Unsafe archive path")
    if any(p in {"", ".", ".."} or len(p.encode("utf-8")) > 255 for p in value.split("/")):
        raise BackupError("Unsafe archive path")
    if value == LOCK:
        raise BackupError("Lifecycle lock is not snapshot content")
    return value


def _regular_open(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(descriptor)
        raise BackupError("Snapshot accepts regular files without hardlinks only")
    return os.fdopen(descriptor, "rb"), info


def _hash_file(path):
    digest = hashlib.sha256()
    with _regular_open(path)[0] as source:
        for part in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def _inventory(root, max_bytes, max_files):
    files, directories, total = [], [], 0
    def visit(directory):
        nonlocal total
        with os.scandir(directory) as items:
            for item in sorted(items, key=lambda item: item.name):
                relative = Path(item.path).relative_to(root).as_posix()
                if relative == LOCK:
                    continue
                _relative(relative)
                if len(files) + len(directories) >= max_files:
                    raise BackupError("Snapshot file count exceeds limit")
                info = item.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    directories.append(relative)
                    visit(Path(item.path))
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    total += info.st_size
                    if total > max_bytes:
                        raise BackupError("Snapshot exceeds byte limit")
                    digest = _hash_file(item.path)
                    files.append({"path": relative, "size": info.st_size, "sha256": digest})
                else:
                    raise BackupError("Snapshot refuses symlinks, hardlinks and special files")
    visit(root)
    return {"format": FORMAT, "files": files, "directories": directories, "total_bytes": total}


def _fsync_dir(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _check_content(root, manifest):
    # Credentials must remain usable; fail before publishing a broken restore.
    from threaddesk.server_sync.auth import Credentials
    credentials = Credentials(root)
    if len(credentials.key) != 32 or any(not isinstance(h, str) or len(h) != 64
                                         or any(c not in "0123456789abcdef" for c in h)
                                         for h in credentials.users.values()):
        raise BackupError("Invalid snapshot credentials")
    for item in manifest["files"]:
        path = root / item["path"]
        if path.name == "sync.sqlite3":
            try:
                connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
                try:
                    if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                        raise BackupError("Snapshot database integrity check failed")
                    invalid = connection.execute("SELECT count(*) FROM versions WHERE typeof(body) != 'blob' OR typeof(size) != 'integer' OR size < 0 OR size > 67108864 OR length(body) != size").fetchone()[0]
                    if invalid:
                        raise BackupError("Snapshot contains a corrupt file version")
                    invalid = connection.execute("SELECT count(*) FROM chunks WHERE typeof(body) != 'blob' OR length(body) NOT BETWEEN 1 AND 262144 OR typeof(offset) != 'integer' OR offset < 0").fetchone()[0]
                    if invalid:
                        raise BackupError("Snapshot contains a corrupt transfer journal")
                    for digest, size, content in connection.execute("SELECT sha256,size,body FROM versions"):
                        if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
                            raise BackupError("Snapshot contains a corrupt file version")
                    for project, transfer, offset in connection.execute("SELECT project,transfer,offset FROM uploads WHERE state='receiving'"):
                        actual = 0
                        for start, content in connection.execute("SELECT offset,body FROM chunks WHERE project=? AND transfer=? ORDER BY offset", (project, transfer)):
                            if start != actual:
                                raise BackupError("Snapshot contains a corrupt transfer journal")
                            actual += len(content)
                        if actual != offset:
                            raise BackupError("Snapshot contains a corrupt transfer journal")
                finally:
                    connection.close()
            except sqlite3.Error as exc:
                raise BackupError("Database needs recovery; restart and cleanly stop server first") from exc


def backup(data_dir, output, *, max_bytes=MAX_BYTES, max_files=MAX_FILES):
    """Write a new uncompressed private tar; never replace an older artifact."""
    root, destination = _plain_path(data_dir), _plain_path(output)
    if not root.is_dir() or not destination.parent.is_dir():
        raise BackupError("Existing source and output parent directories required")
    if destination == root or root in destination.parents:
        raise BackupError("Backup output must be outside server data")
    if destination.exists():
        raise BackupError("Backup output already exists; choose a new filename")
    with server_lock(root):
        manifest = _inventory(root, max_bytes, max_files)
        _check_content(root, manifest)
        raw_manifest = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        if len(raw_manifest) > MAX_MANIFEST:
            raise BackupError("Snapshot manifest exceeds limit")
        required_space = 2 * manifest["total_bytes"] + len(raw_manifest) + 2048 * (len(manifest["files"]) + 1) + 1024**2
        if shutil.disk_usage(destination.parent).free < required_space:
            raise BackupError("Insufficient free space for archive and verification staging")
        descriptor, stage_name = tempfile.mkstemp(prefix=".td-backup-", dir=destination.parent)
        stage = Path(stage_name)
        try:
            with os.fdopen(descriptor, "wb") as output_file:
                with tarfile.open(fileobj=output_file, mode="w|", format=tarfile.USTAR_FORMAT) as archive:
                    info = tarfile.TarInfo("manifest.json")
                    info.size, info.mode = len(raw_manifest), 0o600
                    archive.addfile(info, io.BytesIO(raw_manifest))
                    for item in manifest["files"]:
                        info = tarfile.TarInfo("data/" + item["path"])
                        info.size, info.mode = item["size"], 0o600
                        with _regular_open(root / item["path"])[0] as source:
                            archive.addfile(info, source)
                        if _hash_file(root / item["path"]) != item["sha256"]:
                            raise BackupError("Source changed during cold backup")
                output_file.flush()
                os.fsync(output_file.fileno())
            # Validate actual archived bytes too, not only a second source read.
            with tempfile.TemporaryDirectory(prefix=".td-backup-check-", dir=destination.parent) as check:
                _extract(stage, Path(check), max_bytes=max_bytes, max_files=max_files)
            os.link(stage, destination)  # exclusive atomic publication
            _fsync_dir(destination.parent)
        finally:
            stage.unlink(missing_ok=True)
    return manifest


def _validate_manifest(value, max_bytes, max_files):
    if not isinstance(value, dict) or set(value) != {"format", "files", "directories", "total_bytes"} or value["format"] != FORMAT:
        raise BackupError("Unknown backup format")
    if not isinstance(value["files"], list) or not isinstance(value["directories"], list):
        raise BackupError("Invalid snapshot manifest")
    if len(value["files"]) + len(value["directories"]) > max_files:
        raise BackupError("Snapshot file count exceeds limit")
    paths, portable, total = {}, set(), 0
    for item in value["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
            raise BackupError("Invalid file manifest")
        path = _relative(item["path"])
        if type(item["size"]) is not int or item["size"] < 0:
            raise BackupError("Invalid file size")
        digest = item["sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise BackupError("Invalid content hash")
        if path in paths:
            raise BackupError("Duplicate snapshot path")
        paths[path] = item
        total += item["size"]
        if total > max_bytes:
            raise BackupError("Snapshot exceeds byte limit")
    all_paths = list(paths) + [_relative(item) for item in value["directories"]]
    for path in all_paths:
        alias = unicodedata.normalize("NFC", path).casefold()
        if alias in portable:
            raise BackupError("Duplicate or aliased snapshot path")
        portable.add(alias)
        parts = path.split("/")
        if any("/".join(parts[:i]) in paths for i in range(1, len(parts))):
            raise BackupError("File and directory paths overlap")
    if type(value["total_bytes"]) is not int or total != value["total_bytes"]:
        raise BackupError("Snapshot total does not match")
    return paths


def _extract(source, stage, *, max_bytes, max_files):
    if source.stat().st_size > max_bytes + MAX_MANIFEST + 4096 * (max_files + 1):
        raise BackupError("Archive exceeds bounded size")
    def header(stream):
        raw = stream.read(512)
        if len(raw) != 512:
            raise BackupError("Truncated archive header")
        if raw == bytes(512):
            if stream.read(512) != bytes(512):
                raise BackupError("Invalid archive terminator")
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                if any(block):
                    raise BackupError("Trailing archive content")
            return None
        item = tarfile.TarInfo.frombuf(raw, "utf-8", "strict")
        # Parse plain USTAR headers only; never let tarfile interpret PAX/longname
        # metadata or decompress arbitrary payloads before enforcing limits.
        if item.type not in {tarfile.REGTYPE, tarfile.AREGTYPE}:
            raise BackupError("Only regular archive members are allowed")
        return item

    def padding(stream, size):
        amount = (-size) % 512
        if len(stream.read(amount)) != amount:
            raise BackupError("Truncated archive padding")

    try:
        with _regular_open(source)[0] as archive_file:
            first = header(archive_file)
            if first is None or first.name != "manifest.json" or not 0 <= first.size <= MAX_MANIFEST:
                raise BackupError("Manifest must be first regular archive member")
            raw_manifest = archive_file.read(first.size)
            if len(raw_manifest) != first.size:
                raise BackupError("Truncated manifest")
            padding(archive_file, first.size)
            manifest = json.loads(raw_manifest)
            expected = _validate_manifest(manifest, max_bytes, max_files)
            if shutil.disk_usage(stage).free < manifest["total_bytes"] + 1024**2:
                raise BackupError("Insufficient free space for restore staging")
            for directory in manifest["directories"]:
                (stage / directory).mkdir(parents=True, exist_ok=True, mode=0o700)
            seen = set()
            while True:
                item = header(archive_file)
                if item is None:
                    break
                if not item.name.startswith("data/"):
                    raise BackupError("Only manifested files may be restored")
                relative = _relative(item.name[5:])
                wanted = expected.get(relative)
                if wanted is None or relative in seen or item.size != wanted["size"]:
                    raise BackupError("Archive membership or size mismatch")
                seen.add(relative)
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                digest = hashlib.sha256()
                with target.open("xb") as out:
                    target.chmod(0o600)
                    remaining = item.size
                    while remaining:
                        block = archive_file.read(min(remaining, 1024 * 1024))
                        if not block:
                            raise BackupError("Truncated archive content")
                        remaining -= len(block)
                        digest.update(block)
                        out.write(block)
                    out.flush()
                    os.fsync(out.fileno())
                padding(archive_file, item.size)
                if digest.hexdigest() != wanted["sha256"]:
                    raise BackupError("Snapshot content hash mismatch")
            if seen != set(expected):
                raise BackupError("Snapshot is incomplete")
            _check_content(stage, manifest)
            for parent, directories, files in os.walk(stage, topdown=False):
                os.chmod(parent, 0o700)
                _fsync_dir(parent)
            return manifest
    except (tarfile.TarError, EOFError, json.JSONDecodeError, UnicodeError, KeyError, TypeError, RecursionError) as exc:
        raise BackupError("Malformed snapshot archive") from exc



def restore(archive, data_dir, *, max_bytes=MAX_BYTES, max_files=MAX_FILES):
    """Validate in a private staging directory, then publish to a NEW path only."""
    source, destination = _plain_path(archive), _plain_path(data_dir)
    if destination.exists() or not destination.parent.is_dir():
        raise BackupError("Restore requires a NEW directory beneath an existing parent")
    if not source.is_file():
        raise BackupError("Backup archive not found")
    stage = Path(tempfile.mkdtemp(prefix=".td-restore-", dir=destination.parent))
    try:
        manifest = _extract(source, stage, max_bytes=max_bytes, max_files=max_files)
        # Reserve final name without overwriting a directory created concurrently.
        destination.mkdir(mode=0o700)
        try:
            # POSIX rename replaces only our empty reserved directory.
            os.rename(stage, destination)
        except BaseException:
            destination.rmdir()
            raise
        _fsync_dir(destination.parent)
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)
