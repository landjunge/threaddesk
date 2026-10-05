"""Downloadable, checked backups. Restore opens a separate profile."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4

from threaddesk.storage.json_store import DEFAULT_ROOT, JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.storage.workspace_backup import BackupError, WorkspaceBackup

LIMIT = 134_217_728
DATA_DIRS = frozenset({
    "imports",
    "threads",
    "source-records",
    "graph-events",
    "relations",
    "artifacts",
    "snapshots",
    "nodes",
    "whiteboard",
})
# Written while the desk is open. They must not abort a backup.
RUNTIME_FILES = frozenset({
    "desktop.lock",
    "desktop-port.json",
    "active-profile.json",
    "hausmeister-activity.json",
})
_TEXT = frozenset({".json", ".md", ".txt"})


def base_root() -> Path:
    home = os.environ.get("THREADDESK_HOME")
    return Path(home) if home else DEFAULT_ROOT


def selected_profile() -> tuple[Path, str | None]:
    root = base_root()
    pointer = root / "active-profile.json"
    if not pointer.exists():
        return root, None
    try:
        data = json.loads(pointer.read_text(encoding="utf-8"))
        name = data.get("name")
        backend = data.get("backend")
        if (
            not isinstance(name, str)
            or len(name) != 32
            or any(char not in "0123456789abcdef" for char in name)
            or backend not in {"json", "sqlite"}
        ):
            raise BackupError("The selected workspace cannot be opened.")
        profile = (root / "profiles" / name).resolve()
        if profile.is_symlink() or profile.parent != (root / "profiles").resolve() or not profile.is_dir():
            raise BackupError("The selected workspace cannot be opened.")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise BackupError("The selected workspace cannot be opened.") from exc
    return profile, backend


def _allowed(name: str, backend: str) -> bool:
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or path.is_absolute()
        or name != str(path)
        or any(part in {"", ".", ".."} or part.startswith(".") for part in path.parts)
    ):
        return False
    if len(path.parts) == 1:
        if name == "threaddesk.sqlite3" and backend == "sqlite":
            return True
        if name in RUNTIME_FILES:
            return False
        return path.suffix in _TEXT
    return path.parts[0] in DATA_DIRS


def download_backup(store) -> bytes:
    backend = "sqlite" if isinstance(store, SQLiteStore) else "json"
    with tempfile.TemporaryDirectory(prefix="threaddesk-backup-") as temp:
        source = Path(store.root)
        if backend == "sqlite":
            backup = WorkspaceBackup(Path(temp)).create(store)
            source = Path(temp) / "profile"
            WorkspaceBackup(Path(temp)).restore_verified(backup, source)
        files: dict[str, dict[str, object]] = {}
        bodies: dict[str, bytes] = {}
        for path in sorted(source.rglob("*")):
            name = path.relative_to(source).as_posix()
            if not _allowed(name, backend):
                continue
            if path.is_symlink() or any(parent != source and parent.is_symlink() for parent in path.parents):
                raise BackupError("Symbolic links cannot be backed up.")
            if not path.is_file():
                continue
            body = path.read_bytes()
            if sum(len(item) for item in bodies.values()) + len(body) > LIMIT:
                raise BackupError("Workspace exceeds the backup size limit.")
            bodies[name] = body
            files[name] = {"size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        if backend == "json":
            current = {
                path.relative_to(source).as_posix()
                for path in source.rglob("*")
                if path.is_file() and _allowed(path.relative_to(source).as_posix(), backend)
            }
            if current != set(bodies) or any(
                (source / name).read_bytes() != body for name, body in bodies.items()
            ):
                raise BackupError("Workspace changed during backup. Please try again.")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "kind": "threaddesk.portable-backup",
                        "version": 1,
                        "backend": backend,
                        "files": files,
                    },
                    sort_keys=True,
                ),
            )
            for name, body in bodies.items():
                archive.writestr("workspace/" + name, body)
        return output.getvalue()


def restore_backup(body: bytes, root: Path) -> Path:
    if len(body) > LIMIT:
        raise BackupError("Backup exceeds the size limit.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile as exc:
        raise BackupError("Backup could not be opened.") from exc
    with archive:
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, json.JSONDecodeError) as exc:
            raise BackupError("Invalid backup manifest.") from exc
        if (
            not isinstance(manifest, dict)
            or manifest.get("kind") != "threaddesk.portable-backup"
            or manifest.get("version") != 1
            or manifest.get("backend") not in {"json", "sqlite"}
            or not isinstance(manifest.get("files"), dict)
        ):
            raise BackupError("Unknown backup format.")
        backend = manifest["backend"]
        names = set(archive.namelist())
        expected = {"manifest.json"} | {f"workspace/{name}" for name in manifest["files"]}
        if names != expected:
            raise BackupError("Unexpected backup files.")
        for name, meta in manifest["files"].items():
            if not isinstance(name, str) or not _allowed(name, backend):
                raise BackupError("Invalid backup path.")
            if not isinstance(meta, dict):
                raise BackupError("Backup checksum does not match.")
            payload = archive.read("workspace/" + name)
            if len(payload) != meta.get("size") or hashlib.sha256(payload).hexdigest() != meta.get("sha256"):
                raise BackupError("Backup checksum does not match.")
        if backend == "sqlite" and "threaddesk.sqlite3" not in manifest["files"]:
            raise BackupError("Missing workspace database.")
        profile_name = uuid4().hex
        profiles = root / "profiles"
        profiles.mkdir(parents=True, exist_ok=True)
        target = profiles / profile_name
        temporary = profiles / f"{profile_name}.tmp"
        if temporary.exists():
            raise BackupError("Invalid profile directory.")
        temporary.mkdir(mode=0o700)
        try:
            for name in manifest["files"]:
                destination = temporary / name
                if destination.is_symlink():
                    raise BackupError("Symbolic links are not allowed.")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read("workspace/" + name))
            for volatile in ("desktop-port.json", "desktop.lock"):
                path = temporary / volatile
                if path.exists():
                    path.unlink()
            _disable_caretaker(temporary)
            info = {
                "name": profile_name,
                "backend": backend,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            (temporary / ".profile-info.json").write_text(
                json.dumps(info, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.rename(target)
        except Exception:
            if temporary.exists():
                import shutil
                shutil.rmtree(temporary, ignore_errors=True)
            raise
        (root / "active-profile.json").write_text(
            json.dumps({"name": profile_name, "backend": backend}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return target


def profiles(root: Path) -> list[dict]:
    folder = root / "profiles"
    if not folder.is_dir():
        return []
    found = []
    for info_path in sorted(folder.glob("*/.profile-info.json")):
        profile = info_path.parent
        name = profile.name
        if (
            len(name) != 32
            or any(char not in "0123456789abcdef" for char in name)
            or profile.is_symlink()
        ):
            continue
        try:
            data = json.loads(info_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("name") == name and data.get("backend") in {"json", "sqlite"}:
            found.append(data)
    return found


def _disable_caretaker(profile: Path) -> None:
    settings = profile / "hausmeister.json"
    if settings.is_file():
        try:
            data = json.loads(settings.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            data["enabled"] = False
            settings.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
    modules = profile / "modules.json"
    if not modules.is_file():
        return
    try:
        data = json.loads(modules.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    assistant = (data.get("modules") or {}).get("local-assistant") if isinstance(data, dict) else None
    if isinstance(assistant, dict):
        assistant["enabled"] = False
        modules.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
