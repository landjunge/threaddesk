"""Complete, verified workspace backups, separate from thread snapshots."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import sys
import tempfile
from typing import Callable
from uuid import uuid4

from threaddesk import __version__
from threaddesk.storage.sqlite_store import SQLiteStore


class BackupError(RuntimeError):
    pass


_DESCRIPTOR_READS = os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd
_WINDOWS_SOURCE = os.name == "nt"


def _publish_new(source: Path, target: Path) -> None:
    """Publish a new directory without replacing even an existing empty target."""
    if os.name == "nt":
        os.rename(source, target)  # Windows rename refuses an existing destination.
        return
    import ctypes

    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = getattr(library, "renamex_np", None)
        if rename is None:
            raise BackupError("Atomare Wiederherstellung ohne Überschreiben wird nicht unterstützt.")
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(os.fsencode(source), os.fsencode(target), 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        rename = getattr(library, "renameat2", None)
        if rename is None:
            raise BackupError("Atomare Wiederherstellung ohne Überschreiben wird nicht unterstützt.")
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(-100, os.fsencode(source), -100, os.fsencode(target), 1)  # RENAME_NOREPLACE
    else:
        raise BackupError("Atomare Wiederherstellung ohne Überschreiben wird nicht unterstützt.")
    if result:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _stamp(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _relative(name: str, *, portable: bool = False) -> tuple[str, ...]:
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise BackupError("Ungültiger Backup-Pfad.")
    path = PurePosixPath(name)
    if (not path.parts or path.is_absolute() or str(path) != name
            or any(p in {".", ".."} for p in path.parts)):
        raise BackupError("Ungültiger Backup-Pfad.")
    if portable:
        reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
        reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT")
                        for number in "123456789¹²³")
        if any(
            part.endswith((".", " ")) or part.split(".")[0].rstrip(" ").upper() in reserved
            or any(c in '<>:"|?*' or ord(c) < 32 for c in part)
            for part in path.parts
        ):
            raise BackupError("Backup-Pfad enthält nicht portable Geräte- oder Aliasnamen.")
    return path.parts


class _SourceTree:
    """No-follow, descriptor-relative reads within one explicitly selected root.

    Parent aliases such as macOS /var are resolved before binding the root. Root
    and descendant links are refused, and changed names/inodes fail the read.
    Windows dispatches to a separate handle-relative native adapter. Platforms
    without either safe primitive fail closed rather than following source links.
    """

    def __new__(cls, root):
        if _WINDOWS_SOURCE:
            from threaddesk.storage.windows_backup_source import WindowsSourceTree
            return WindowsSourceTree(root, error_type=BackupError)
        return super().__new__(cls)

    def __init__(self, root: Path):
        if not hasattr(os, "O_NOFOLLOW") or not _DESCRIPTOR_READS:
            raise BackupError("Sicherer Backup-Dateizugriff wird hier nicht unterstützt.")
        self.path = Path(root).absolute()
        self.canonical = self.path.parent.resolve(strict=True) / self.path.name
        self.flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        self._root_fds = []
        self._root_guards = []
        try:
            parent = os.open(self.canonical.anchor, self.flags | os.O_DIRECTORY)
            self._root_fds.append(parent)
            for name in self.canonical.parts[1:]:
                before = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if not stat.S_ISDIR(before.st_mode):
                    raise BackupError("Backup-Quellverzeichnis ist kein reguläres Verzeichnis.")
                child = os.open(name, self.flags | os.O_DIRECTORY, dir_fd=parent)
                self._root_fds.append(child)
                identity = _stamp(before)[:2]
                if _stamp(os.fstat(child))[:2] != identity:
                    raise BackupError("Backup-Quellverzeichnis wurde ausgetauscht.")
                self._root_guards.append((parent, name, identity))
                parent = child
            self.fd = parent
            self.identity = _stamp(os.fstat(self.fd))[:2]
        except BaseException:
            for fd in reversed(self._root_fds):
                os.close(fd)
            raise
        self.directories = {}

    def __enter__(self):
        try:
            self._check_root()
            return self
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *args):
        for fd in reversed(self._root_fds):
            os.close(fd)

    def _check_root(self):
        if self.path.parent.resolve(strict=True) / self.path.name != self.canonical:
            raise BackupError("Backup-Quelle wurde ausgetauscht.")
        for parent, name, identity in self._root_guards:
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(current.st_mode) or _stamp(current)[:2] != identity:
                raise BackupError("Backup-Quelle wurde ausgetauscht.")

    @contextmanager
    def _parent(self, parts):
        self._check_root()
        parent = self.fd
        opened = []
        guards = []
        try:
            for i, name in enumerate(parts):
                before = os.stat(name, dir_fd=parent, follow_symlinks=False)
                identity = _stamp(before)[:2]
                expected = self.directories.get("/".join(parts[:i + 1]), identity)
                if not stat.S_ISDIR(before.st_mode) or identity != expected:
                    raise BackupError("Backup-Quellverzeichnis wurde ausgetauscht.")
                child = os.open(name, self.flags | os.O_DIRECTORY, dir_fd=parent)
                opened.append(child)
                if _stamp(os.fstat(child))[:2] != identity:
                    raise BackupError("Backup-Quellverzeichnis wurde ausgetauscht.")
                guards.append((parent, name, identity))
                parent = child
            self._check_root()
            yield parent
            for directory, name, identity in guards:
                if _stamp(os.stat(name, dir_fd=directory, follow_symlinks=False))[:2] != identity:
                    raise BackupError("Backup-Quellverzeichnis wurde ausgetauscht.")
            self._check_root()
        finally:
            for fd in reversed(opened):
                os.close(fd)

    def scan(self, allowed, descend) -> dict[str, tuple]:
        files = {}

        def walk(parts):
            with self._parent(parts) as directory:
                for name in sorted(os.listdir(directory)):
                    relative = "/".join((*parts, name))
                    if not allowed(relative) and not descend(relative):
                        continue
                    info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        raise BackupError("Symbolische Links sind in Backup-Quellen nicht erlaubt.")
                    if stat.S_ISDIR(info.st_mode):
                        if descend(relative):
                            identity = _stamp(info)[:2]
                            if self.directories.setdefault(relative, identity) != identity:
                                raise BackupError("Backup-Quellverzeichnis wurde ausgetauscht.")
                            walk((*parts, name))
                    elif allowed(relative):
                        if not stat.S_ISREG(info.st_mode):
                            raise BackupError("Backup-Quelle enthält keine reguläre Datei.")
                        files[relative] = _stamp(info)
        walk(())
        return files

    @contextmanager
    def open(self, relative: str, expected: tuple):
        parts = _relative(relative)
        with self._parent(parts[:-1]) as directory:
            before = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
            if _stamp(before) != expected or not stat.S_ISREG(before.st_mode):
                raise BackupError("Backup-Quelldatei wurde ausgetauscht oder verändert.")
            fd = os.open(parts[-1], self.flags, dir_fd=directory)
            with os.fdopen(fd, "rb") as handle:
                if _stamp(os.fstat(handle.fileno())) != expected:
                    raise BackupError("Backup-Quelldatei wurde ausgetauscht oder verändert.")
                self._check_root()
                yield handle
                if (
                    _stamp(os.fstat(handle.fileno())) != expected
                    or _stamp(os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)) != expected
                ):
                    raise BackupError("Backup-Quelldatei wurde ausgetauscht oder verändert.")

    def info(self, relative: str) -> tuple:
        parts = _relative(relative)
        with self._parent(parts[:-1]) as directory:
            info = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                raise BackupError("Backup-Quelle enthält keine reguläre Datei.")
            return _stamp(info)

    def read(self, relative: str, expected: tuple, *, limit: int | None = None) -> bytes:
        with self.open(relative, expected) as handle:
            if limit is not None and expected[3] > limit:
                raise BackupError("Workspace exceeds the backup size limit.")
            body = handle.read() if limit is None else handle.read(limit + 1)
            if limit is not None and len(body) > limit:
                raise BackupError("Workspace exceeds the backup size limit.")
            return body


def _verify_captured(root: Path, files: dict) -> None:
    """Compare actual directory entries and bytes, not normalized pathname guesses."""
    with _SourceTree(root) as source:
        inventory = source.scan(lambda _: True, lambda _: True)
        if set(inventory) != set(files):
            raise BackupError("Backup-Ziel enthält abweichende oder kollidierende Dateinamen.")
        for name, expected in files.items():
            fingerprint, count = hashlib.sha256(), 0
            with source.open(name, inventory[name]) as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    count += len(chunk)
                    fingerprint.update(chunk)
            if count != expected["size"] or fingerprint.hexdigest() != expected["sha256"]:
                raise BackupError("Geprüfte Backup-Zieldatei wurde verändert.")
        if source.scan(lambda _: True, lambda _: True) != inventory:
            raise BackupError("Backup-Ziel wurde während der Rückprüfung verändert.")


def _cleanup_owned(root: Path, identity: tuple | None) -> None:
    """Clean only a stage we created; never recursively reopen a substituted root."""
    if identity is None:
        return
    try:
        info = root.lstat()
        if not stat.S_ISDIR(info.st_mode) or _stamp(info)[:2] != identity:
            return
        with _SourceTree(root) as source:
            # Windows pins this root against rename; POSIX deletion uses its
            # verified descriptor even if its old pathname is exchanged later.
            if _stamp(root.lstat())[:2] != identity:
                return
            if _WINDOWS_SOURCE:
                for child in root.iterdir():
                    if child.is_dir() and not child.is_symlink():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
            else:
                if _stamp(os.fstat(source.fd))[:2] != identity:
                    return
                for name in os.listdir(source.fd):
                    child = os.stat(name, dir_fd=source.fd, follow_symlinks=False)
                    if stat.S_ISDIR(child.st_mode):
                        shutil.rmtree(name, dir_fd=source.fd)
                    else:
                        os.unlink(name, dir_fd=source.fd)
            source._check_root()
        if _stamp(root.lstat())[:2] == identity:
            root.rmdir()  # Never recursively delete through this pathname.
    except (OSError, BackupError):
        pass  # Preserve an unavailable/exchanged stage; never mask the original failure.


class WorkspaceBackup:
    ARTIFACT_EXCLUDES = {"threaddesk.sqlite3", "threaddesk.sqlite3-wal", "threaddesk.sqlite3-shm"}

    def __init__(
        self,
        backup_root: Path,
        *,
        copy_file: Callable[[Path, Path], None] = shutil.copy2,
        fault: Callable[[str], None] | None = None,
    ) -> None:
        self.backup_root = Path(backup_root)
        self.copy_file = copy_file
        self.fault = fault

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _fault(self, stage: str) -> None:
        if self.fault:
            self.fault(stage)

    @classmethod
    def _artifact_allowed(cls, name: str) -> bool:
        parts = _relative(name)
        if len(parts) == 1:
            return name not in cls.ARTIFACT_EXCLUDES and not name.startswith(".")
        return parts[0] in {"artifacts", "imports"}

    @staticmethod
    def _artifact_descend(name: str) -> bool:
        return _relative(name)[0] in {"artifacts", "imports"}

    def _copy_source(self, source: _SourceTree, relative: str, expected: tuple, target: Path):
        with source.open(relative, expected) as handle:
            if self.copy_file is shutil.copy2:
                with target.open("xb") as output:
                    target.chmod(0o600)
                    shutil.copyfileobj(handle, output)
            else:
                # Preserve the internal copy-fault injection hook, but give it a
                # private captured file, never an untrusted source pathname.
                with tempfile.TemporaryDirectory(prefix=".copy-", dir=target.parent) as folder:
                    captured = Path(folder) / "source"
                    with captured.open("xb") as output:
                        captured.chmod(0o600)
                        shutil.copyfileobj(handle, output)
                    self.copy_file(captured, target)
            target.chmod(0o600)

    def create(self, store: SQLiteStore) -> Path:
        self.backup_root.mkdir(parents=True, exist_ok=True)
        name = f"workspace-{uuid4().hex[:12]}"
        partial = self.backup_root / f"{name}.partial"
        complete = self.backup_root / f"{name}.complete"
        owned = None
        try:
            partial.mkdir(mode=0o700)
            owned = _stamp(partial.lstat())[:2]
            database = partial / "threaddesk.sqlite3"
            with _SourceTree(store.root) as source:
                inventory = source.scan(self._artifact_allowed, self._artifact_descend)
                # SQLite reads its existing connection; this guard also refuses
                # a linked/replaced pathname around the snapshot operation.
                with source.open("threaddesk.sqlite3", source.info("threaddesk.sqlite3")):
                    destination = sqlite3.connect(database)
                    try:
                        store.connection.backup(destination)
                    finally:
                        destination.close()
                database.chmod(0o600)
                self._fault("after_database")

                for relative, expected in inventory.items():
                    target = partial / (
                        "artifacts" if len(_relative(relative)) == 1 else "directories"
                    ) / relative
                    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                    self._copy_source(source, relative, expected, target)
                if source.scan(self._artifact_allowed, self._artifact_descend) != inventory:
                    raise BackupError("Workspace changed during backup. Please try again.")

            schema_version = store.connection.execute("SELECT version FROM schema_info").fetchone()[0]
            files = {
                str(path.relative_to(partial)): {
                    "sha256": self._hash(path),
                    "size": path.stat().st_size,
                }
                for path in sorted(partial.rglob("*"))
                if path.is_file()
            }
            manifest = {
                "kind": "threaddesk.workspace-backup",
                "version": 2,
                "app_version": __version__,
                "schema_version": schema_version,
                "design_reference": "desk-r2",
                "files": files,
            }
            self._fault("before_manifest")
            manifest_path = partial / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest_path.chmod(0o600)
            _publish_new(partial, complete)
            return complete
        except Exception as exc:
            _cleanup_owned(partial, owned)
            if isinstance(exc, BackupError):
                raise
            raise BackupError(f"Workspace-Backup fehlgeschlagen: {type(exc).__name__}") from exc

    @classmethod
    def _restore_name(cls, relative: str, *, portable: bool | None = None) -> str:
        parts = _relative(relative, portable=_WINDOWS_SOURCE if portable is None else portable)
        if relative == "threaddesk.sqlite3":
            return relative
        if (len(parts) == 2 and parts[0] == "artifacts"
                and parts[1] not in cls.ARTIFACT_EXCLUDES and not parts[1].startswith(".")):
            return parts[1]
        if len(parts) >= 3 and parts[0] == "directories" and parts[1] in {"artifacts", "imports"}:
            return "/".join(parts[1:])
        raise BackupError("Ungültiger Backup-Pfad.")

    def _verified_copy(self, backup: Path, temporary: Path) -> dict:
        with _SourceTree(backup) as source:
            inventory = source.scan(lambda _: True, lambda _: True)
            if "manifest.json" not in inventory:
                raise BackupError("Backup-Manifest fehlt.")
            manifest = json.loads(source.read("manifest.json", inventory["manifest.json"]))
            if (not isinstance(manifest, dict)
                    or manifest.get("kind") != "threaddesk.workspace-backup"
                    or manifest.get("version") not in {1, 2}
                    or not isinstance(manifest.get("files"), dict)):
                raise BackupError("Unbekanntes Backup-Format.")
            files = manifest["files"]
            if "threaddesk.sqlite3" not in files:
                raise BackupError("Workspace-Datenbank fehlt im Manifest.")
            if set(inventory) != {"manifest.json", *files}:
                raise BackupError("Backup enthält nicht im Manifest geprüfte Dateien.")
            names = {relative: self._restore_name(relative) for relative in files}
            destinations = set(names.values())
            if len(destinations) != len(names) or any(
                str(parent) in destinations
                for name in destinations for parent in PurePosixPath(name).parents
                if str(parent) != "."
            ):
                raise BackupError("Backup-Zielpfade überschneiden sich.")
            for relative, expected in files.items():
                if (not isinstance(expected, dict) or type(expected.get("size")) is not int
                        or expected["size"] < 0 or not isinstance(expected.get("sha256"), str)
                        or len(expected["sha256"]) != 64
                        or any(c not in "0123456789abcdef" for c in expected["sha256"])):
                    raise BackupError("Ungültiger Backup-Prüfnachweis.")
                target = temporary / names[relative]
                target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                fingerprint = hashlib.sha256()
                count = 0
                with source.open(relative, inventory[relative]) as handle, target.open("xb") as output:
                    target.chmod(0o600)
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        fingerprint.update(chunk)
                        count += len(chunk)
                        output.write(chunk)
                if count != expected["size"] or fingerprint.hexdigest() != expected["sha256"]:
                    raise BackupError(f"Prüfsumme stimmt nicht: {relative}")
            _verify_captured(temporary, {names[name]: expected for name, expected in files.items()})
            # SQLite opens the private captured copy, never the untrusted source
            # pathname that was checked earlier. No source WAL/sidecar is read.
            database = temporary / "threaddesk.sqlite3"
            connection = sqlite3.connect(database.absolute().as_uri() + "?mode=ro&immutable=1", uri=True)
            try:
                if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise BackupError("SQLite-Prüfung fehlgeschlagen.")
                version = connection.execute("SELECT version FROM schema_info").fetchone()[0]
                if version != manifest["schema_version"]:
                    raise BackupError("Schema-Version stimmt nicht.")
            finally:
                connection.close()
            self._fault("after_restore_verification")
            if source.scan(lambda _: True, lambda _: True) != inventory:
                raise BackupError("Backup-Quelle wurde während der Prüfung verändert.")
            return manifest

    def _verify(self, backup: Path) -> dict:
        try:
            with tempfile.TemporaryDirectory(prefix="threaddesk-verify-") as folder:
                return self._verified_copy(Path(backup), Path(folder))
        except BackupError:
            raise
        except Exception as exc:
            raise BackupError(f"Backup kann nicht geprüft werden: {type(exc).__name__}") from exc

    def restore_verified(self, backup: Path, target: Path) -> Path:
        backup = Path(backup)
        target = Path(target)
        if target.exists() or target.is_symlink():
            raise BackupError("Wiederherstellungsziel existiert bereits.")
        temporary = target.with_name(target.name + f".partial-{uuid4().hex[:8]}")
        owned = None
        try:
            temporary.mkdir(parents=True, mode=0o700)
            owned = _stamp(temporary.lstat())[:2]
            self._verified_copy(backup, temporary)
            validation = SQLiteStore(temporary)
            try:
                if validation.connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise BackupError("Wiederhergestelltes Profil ist beschädigt.")
            finally:
                validation.connection.close()
            (temporary / ".backup-verified").write_text("verified\n", encoding="utf-8")
            if target.exists() or target.is_symlink():
                raise BackupError("Wiederherstellungsziel existiert bereits.")
            _publish_new(temporary, target)
            return target
        except Exception as exc:
            _cleanup_owned(temporary, owned)
            if isinstance(exc, BackupError):
                raise
            raise BackupError(f"Wiederherstellung fehlgeschlagen: {type(exc).__name__}") from exc

    def recover_on_start(self, store: SQLiteStore, recovery_root: Path) -> list[dict]:
        recovered = []
        for batch in store.list_import_batches():
            if batch.get("status") not in {"committing", "recovery_required"}:
                continue
            target = Path(recovery_root) / str(batch["id"])
            self.restore_verified(Path(batch["backup_path"]), target)
            updated = dict(batch)
            updated.update(status="recovery_ready", recovered_profile=str(target))
            store.save_import_batch(str(batch["id"]), updated)
            recovered.append(updated)
        return recovered
