"""Complete, verified workspace backups, separate from thread snapshots."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Callable
from uuid import uuid4

from threaddesk import __version__
from threaddesk.storage.sqlite_store import SQLiteStore


class BackupError(RuntimeError):
    pass


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

    def create(self, store: SQLiteStore) -> Path:
        self.backup_root.mkdir(parents=True, exist_ok=True)
        name = f"workspace-{uuid4().hex[:12]}"
        partial = self.backup_root / f"{name}.partial"
        complete = self.backup_root / f"{name}.complete"
        try:
            partial.mkdir(mode=0o700)
            database = partial / "threaddesk.sqlite3"
            destination = sqlite3.connect(database)
            try:
                store.connection.backup(destination)
            finally:
                destination.close()
            database.chmod(0o600)
            self._fault("after_database")

            artifacts = partial / "artifacts"
            for source in sorted(store.root.iterdir()):
                if not source.is_file() or source.name in self.ARTIFACT_EXCLUDES or source.name.startswith("."):
                    continue
                artifacts.mkdir(mode=0o700, exist_ok=True)
                target = artifacts / source.name
                self.copy_file(source, target)
                target.chmod(0o600)

            directory_backup = partial / "directories"
            for name in ("artifacts", "imports"):
                source_root = store.root / name
                if not source_root.is_dir():
                    continue
                for source in sorted(source_root.rglob("*")):
                    if not source.is_file():
                        continue
                    relative = source.relative_to(store.root)
                    target = directory_backup / relative
                    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                    self.copy_file(source, target)
                    target.chmod(0o600)

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
            partial.rename(complete)
            return complete
        except Exception as exc:
            if partial.exists():
                shutil.rmtree(partial)
            raise BackupError(f"Workspace-Backup fehlgeschlagen: {type(exc).__name__}") from exc

    def _verify(self, backup: Path) -> dict:
        try:
            manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("kind") != "threaddesk.workspace-backup":
                raise BackupError("Unbekanntes Backup-Format.")
            for relative, expected in manifest["files"].items():
                path = backup / relative
                if not path.is_file() or self._hash(path) != expected["sha256"]:
                    raise BackupError(f"Prüfsumme stimmt nicht: {relative}")
            database = backup / "threaddesk.sqlite3"
            connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
            try:
                if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise BackupError("SQLite-Prüfung fehlgeschlagen.")
                version = connection.execute("SELECT version FROM schema_info").fetchone()[0]
                if version != manifest["schema_version"]:
                    raise BackupError("Schema-Version stimmt nicht.")
            finally:
                connection.close()
            return manifest
        except BackupError:
            raise
        except Exception as exc:
            raise BackupError(f"Backup kann nicht geprüft werden: {type(exc).__name__}") from exc

    def restore_verified(self, backup: Path, target: Path) -> Path:
        backup = Path(backup)
        target = Path(target)
        self._verify(backup)
        if target.exists():
            raise BackupError("Wiederherstellungsziel existiert bereits.")
        temporary = target.with_name(target.name + f".partial-{uuid4().hex[:8]}")
        try:
            temporary.mkdir(parents=True, mode=0o700)
            shutil.copy2(backup / "threaddesk.sqlite3", temporary / "threaddesk.sqlite3")
            artifact_root = backup / "artifacts"
            if artifact_root.exists():
                for source in artifact_root.iterdir():
                    shutil.copy2(source, temporary / source.name)
            directory_root = backup / "directories"
            if directory_root.exists():
                for source in sorted(directory_root.rglob("*")):
                    if not source.is_file():
                        continue
                    target_path = temporary / source.relative_to(directory_root)
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target_path)
            validation = SQLiteStore(temporary)
            try:
                if validation.connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise BackupError("Wiederhergestelltes Profil ist beschädigt.")
            finally:
                validation.connection.close()
            (temporary / ".backup-verified").write_text("verified\n", encoding="utf-8")
            temporary.rename(target)
            return target
        except Exception as exc:
            if temporary.exists():
                shutil.rmtree(temporary)
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
