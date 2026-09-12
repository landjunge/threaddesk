from __future__ import annotations

import json
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.storage.workspace_backup import BackupError, WorkspaceBackup


def workspace(root: Path) -> SQLiteStore:
    store = SQLiteStore(root)
    service = ThreadService(store)
    thread = service.create("Vor dem Import")
    service.set_note("Darf nicht verloren gehen", thread.id)
    service.snapshot("Sicherer Stand", thread.id)
    service.create_node("project", "ThreadDesk", status="active")
    store.write_text_artifact("handoff.json", '{"kind":"threaddesk.handoff"}\n')
    return store


def logical(store: SQLiteStore) -> dict:
    threads = store.list_threads(True)
    return {
        "threads": [item.to_dict() for item in threads],
        "snapshots": [item.to_dict() for thread in threads for item in store.list_snapshots(thread.id)],
        "nodes": [item.to_dict() for item in store.list_nodes()],
        "relations": [item.to_dict() for item in store.list_relations()],
        "events": [item.to_dict() for item in store.list_graph_events()],
        "current_id": store.get_current_id(),
    }


def test_backup_manifest_and_verified_restore_match_exactly(tmp_path: Path) -> None:
    source = workspace(tmp_path / "source")
    expected = logical(source)
    backup = WorkspaceBackup(tmp_path / "backups").create(source)
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["kind"] == "threaddesk.workspace-backup"
    assert manifest["app_version"] == "0.1.0"
    assert manifest["schema_version"] == 1
    assert manifest["design_reference"] == "desk-r2"
    assert set(manifest["files"]) == {"threaddesk.sqlite3", "artifacts/handoff.json"}

    restored_path = WorkspaceBackup(tmp_path / "backups").restore_verified(backup, tmp_path / "restored")
    restored = SQLiteStore(restored_path)
    assert logical(restored) == expected
    assert (restored_path / "threaddesk.sqlite3").read_bytes() == (backup / "threaddesk.sqlite3").read_bytes()
    assert (restored_path / "handoff.json").read_bytes() == (source.root / "handoff.json").read_bytes()
    assert (restored_path / ".backup-verified").is_file()


def test_corrupt_backup_is_rejected_without_target(tmp_path: Path) -> None:
    source = workspace(tmp_path / "source")
    manager = WorkspaceBackup(tmp_path / "backups")
    backup = manager.create(source)
    (backup / "threaddesk.sqlite3").write_bytes(b"broken")

    with pytest.raises(BackupError, match="Prüfsumme"):
        manager.restore_verified(backup, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


@pytest.mark.parametrize("stage", ["after_database", "before_manifest"])
def test_interrupted_backup_is_never_marked_complete(tmp_path: Path, stage: str) -> None:
    source = workspace(tmp_path / "source")

    def interrupt(current: str) -> None:
        if current == stage:
            raise RuntimeError("power loss")

    with pytest.raises(BackupError):
        WorkspaceBackup(tmp_path / "backups", fault=interrupt).create(source)
    assert not list((tmp_path / "backups").glob("*.complete"))


def test_disk_full_cleans_up_incomplete_backup(tmp_path: Path) -> None:
    source = workspace(tmp_path / "source")

    def no_space(_source: Path, _target: Path) -> None:
        raise OSError(28, "No space left on device")

    with pytest.raises(BackupError, match="OSError"):
        WorkspaceBackup(tmp_path / "backups", copy_file=no_space).create(source)
    assert not list((tmp_path / "backups").glob("*.partial"))


@pytest.mark.parametrize("status", ["committing", "recovery_required"])
def test_restart_prepares_verified_recovery_profile(tmp_path: Path, status: str) -> None:
    store = workspace(tmp_path / "source")
    manager = WorkspaceBackup(tmp_path / "backups")
    backup = manager.create(store)
    store.save_import_batch("batch-1", {"id": "batch-1", "status": status, "backup_path": str(backup)})

    recovered = manager.recover_on_start(store, tmp_path / "recovery")

    assert recovered[0]["status"] == "recovery_ready"
    assert Path(recovered[0]["recovered_profile"]).joinpath(".backup-verified").is_file()
    assert store.get_import_batch("batch-1")["status"] == "recovery_ready"
