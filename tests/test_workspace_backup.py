from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.storage.workspace_backup import BackupError, WorkspaceBackup
from threaddesk.storage import workspace_backup


def native_before_open(monkeypatch, callback):
    """Windows injects at its handle adapter; POSIX tests inject at openat."""
    from threaddesk.storage.windows_backup_source import WindowsSourceTree
    original = WindowsSourceTree.open

    @contextmanager
    def observed(self, relative, expected):
        callback(relative)
        with original(self, relative, expected) as handle:
            yield handle

    monkeypatch.setattr(WindowsSourceTree, "open", observed)


def workspace(root: Path) -> SQLiteStore:
    store = SQLiteStore(root)
    service = ThreadService(store)
    thread = service.create("Vor dem Import")
    service.set_note("Darf nicht verloren gehen", thread.id)
    service.snapshot("Sicherer Stand", thread.id)
    service.create_node("project", "ThreadDesk", status="active")
    service.append_whiteboard(
        thread.id,
        actor="Mensch",
        actor_type="human",
        entry_type="note",
        content="Verlauf bleibt im Backup",
    )
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
        "whiteboard": [
            item.to_dict()
            for thread in threads
            for item in store.list_whiteboard(thread.id)
        ],
        "current_id": store.get_current_id(),
    }


def test_backup_manifest_and_verified_restore_match_exactly(tmp_path: Path) -> None:
    source = workspace(tmp_path / "source")
    expected = logical(source)
    backup = WorkspaceBackup(tmp_path / "backups").create(source)
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["kind"] == "threaddesk.workspace-backup"
    from threaddesk import __version__
    assert manifest["app_version"] == __version__
    from threaddesk.storage.schema import SCHEMA_VERSION
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["design_reference"] == "desk-r2"
    assert set(manifest["files"]) == {
        "threaddesk.sqlite3",
        "artifacts/handoff.json",
        "artifacts/actors.json",
    }

    restored_path = WorkspaceBackup(tmp_path / "backups").restore_verified(backup, tmp_path / "restored")
    restored = SQLiteStore(restored_path)
    assert logical(restored) == expected
    assert (restored_path / "threaddesk.sqlite3").read_bytes() == (backup / "threaddesk.sqlite3").read_bytes()
    assert (restored_path / "handoff.json").read_bytes() == (source.root / "handoff.json").read_bytes()
    assert (restored_path / ".backup-verified").is_file()


def test_backup_preserves_content_artifacts_and_import_evidence_directories(tmp_path: Path) -> None:
    source = workspace(tmp_path / "source")
    content = source.root / "artifacts" / ("a" * 64)
    content.parent.mkdir()
    content.write_text("content\n", encoding="utf-8")
    imported = source.root / "imports" / "bundle.tdbundle"
    imported.parent.mkdir()
    imported.write_bytes(b"bundle")
    manager = WorkspaceBackup(tmp_path / "backups")

    backup = manager.create(source)
    restored = manager.restore_verified(backup, tmp_path / "restored")

    assert (restored / "artifacts" / content.name).read_bytes() == content.read_bytes()
    assert (restored / "imports" / imported.name).read_bytes() == imported.read_bytes()


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


@pytest.mark.parametrize("location", ["root", "content", "directory"])
def test_workspace_backup_rejects_external_links_before_reading(tmp_path, monkeypatch, location):
    source = workspace(tmp_path / "source")
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "private.json"
    secret.write_bytes(b"EXTERNAL-CONTENT-MUST-NOT-BE-READ")
    if location == "root":
        (source.root / "linked.json").symlink_to(secret)
    elif location == "content":
        (source.root / "artifacts").mkdir()
        (source.root / "artifacts" / "linked").symlink_to(secret)
    else:
        (source.root / "imports").symlink_to(outside, target_is_directory=True)
    original = os.open
    external = secret.stat().st_ino
    opened_external = []

    def observed(*args, **kwargs):
        fd = original(*args, **kwargs)
        if os.fstat(fd).st_ino == external:
            opened_external.append(fd)
        return fd

    monkeypatch.setattr(os, "open", observed)
    manager = WorkspaceBackup(tmp_path / "backups")
    with pytest.raises(BackupError):
        manager.create(source)
    assert not opened_external
    assert not list(manager.backup_root.glob("*.complete"))
    assert not list(manager.backup_root.glob("*.partial"))


@pytest.mark.parametrize("replacement", ["symlink", "regular"])
def test_workspace_source_swap_at_first_open_is_rejected(tmp_path, monkeypatch, replacement):
    source = workspace(tmp_path / "source")
    selected = source.root / "handoff.json"
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"EXTERNAL-CONTENT")
    original = os.open
    root_inode = source.root.stat().st_ino
    switched = False
    outside_opened = []

    def swap(name, flags, *args, **kwargs):
        nonlocal switched
        directory = kwargs.get("dir_fd")
        if name == "handoff.json" and directory is not None and os.fstat(directory).st_ino == root_inode and not switched:
            switched = True
            selected.rename(source.root / "old-handoff")
            if replacement == "symlink":
                selected.symlink_to(outside)
            else:
                selected.write_text('{"new":"regular inode"}')
        fd = original(name, flags, *args, **kwargs)
        if os.fstat(fd).st_ino == outside.stat().st_ino:
            outside_opened.append(fd)
        return fd

    if workspace_backup._WINDOWS_SOURCE:
        def native_swap(relative):
            nonlocal switched
            if relative == "handoff.json" and not switched:
                switched = True
                selected.rename(source.root / "old-handoff")
                if replacement == "symlink":
                    selected.symlink_to(outside)
                else:
                    selected.write_text('{"new":"regular inode"}')
        native_before_open(monkeypatch, native_swap)
    else:
        monkeypatch.setattr(os, "open", swap)
    with pytest.raises(BackupError):
        WorkspaceBackup(tmp_path / "backups").create(source)
    assert switched and not outside_opened
    assert not list((tmp_path / "backups").glob("*.complete"))


def test_root_directory_exchange_before_first_file_read_is_rejected(tmp_path, monkeypatch):
    source = workspace(tmp_path / "source")
    original = os.open
    root_inode = source.root.stat().st_ino
    switched = False

    def swap(name, flags, *args, **kwargs):
        nonlocal switched
        directory = kwargs.get("dir_fd")
        if name == "handoff.json" and directory is not None and os.fstat(directory).st_ino == root_inode and not switched:
            switched = True
            source.root.rename(tmp_path / "original-source")
            source.root.mkdir()
            (source.root / "handoff.json").write_bytes(b"unrelated source")
        return original(name, flags, *args, **kwargs)

    if workspace_backup._WINDOWS_SOURCE:
        def native_swap(relative):
            nonlocal switched
            if relative == "handoff.json" and not switched:
                switched = True
                source.root.rename(tmp_path / "original-source")
                source.root.mkdir()
                (source.root / "handoff.json").write_bytes(b"unrelated source")
        native_before_open(monkeypatch, native_swap)
    else:
        monkeypatch.setattr(os, "open", swap)
    with pytest.raises(BackupError):
        WorkspaceBackup(tmp_path / "backups").create(source)
    assert switched and not list((tmp_path / "backups").glob("*.complete"))


@pytest.mark.parametrize("extra", ["artifacts/unlisted.json", "directories/imports/unlisted.bin", "unlisted.txt"])
def test_restore_rejects_every_manifest_foreign_file(tmp_path, extra):
    source = workspace(tmp_path / "source")
    manager = WorkspaceBackup(tmp_path / "backups")
    backup = manager.create(source)
    unexpected = backup / extra
    unexpected.parent.mkdir(parents=True, exist_ok=True)
    unexpected.write_bytes(b"not verified by the manifest")
    with pytest.raises(BackupError, match="Manifest"):
        manager.restore_verified(backup, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
    assert not list(tmp_path.glob("restored.partial-*"))


@pytest.mark.parametrize("member", ["manifest.json", "artifacts/handoff.json", "threaddesk.sqlite3"])
def test_restore_rejects_manifest_member_symlinks(tmp_path, member):
    source = workspace(tmp_path / "source")
    manager = WorkspaceBackup(tmp_path / "backups")
    backup = manager.create(source)
    selected = backup / member
    external = tmp_path / "external-copy"
    external.write_bytes(selected.read_bytes())
    selected.unlink()
    selected.symlink_to(external)
    with pytest.raises(BackupError):
        manager.restore_verified(backup, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_restore_rejects_same_content_different_inode_between_inventory_and_open(tmp_path, monkeypatch):
    source = workspace(tmp_path / "source")
    manager = WorkspaceBackup(tmp_path / "backups")
    backup = manager.create(source)
    selected = backup / "artifacts" / "handoff.json"
    directory_inode = selected.parent.stat().st_ino
    original = os.open
    switched = False

    def swap(name, flags, *args, **kwargs):
        nonlocal switched
        directory = kwargs.get("dir_fd")
        if name == "handoff.json" and directory is not None and os.fstat(directory).st_ino == directory_inode and not switched:
            switched = True
            body = selected.read_bytes()
            selected.rename(selected.with_name("old"))
            selected.write_bytes(body)
        return original(name, flags, *args, **kwargs)

    if workspace_backup._WINDOWS_SOURCE:
        def native_swap(relative):
            nonlocal switched
            if relative == "artifacts/handoff.json" and not switched:
                switched = True
                body = selected.read_bytes()
                selected.rename(selected.with_name("old"))
                selected.write_bytes(body)
        native_before_open(monkeypatch, native_swap)
    else:
        monkeypatch.setattr(os, "open", swap)
    with pytest.raises(BackupError):
        manager.restore_verified(backup, tmp_path / "restored")
    assert switched and not (tmp_path / "restored").exists()


def test_restore_rejects_new_unlisted_file_after_checksum_verification(tmp_path):
    source = workspace(tmp_path / "source")
    manager = WorkspaceBackup(tmp_path / "backups")
    backup = manager.create(source)

    def change(stage):
        if stage == "after_restore_verification":
            (backup / "artifacts" / "late.json").write_bytes(b"late arrival")

    with pytest.raises(BackupError):
        WorkspaceBackup(tmp_path / "backups", fault=change).restore_verified(backup, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_restore_opens_sqlite_only_from_the_private_verified_copy(tmp_path, monkeypatch):
    source = workspace(tmp_path / "source")
    manager = WorkspaceBackup(tmp_path / "backups")
    backup = manager.create(source)
    original = workspace_backup.sqlite3.connect
    paths = []

    def observed(path, *args, **kwargs):
        paths.append(str(path))
        assert str(backup) not in str(path), "Never reopen the untrusted source by SQLite pathname"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(workspace_backup.sqlite3, "connect", observed)
    assert manager.restore_verified(backup, tmp_path / "restored").is_dir()
    assert paths


def test_restore_does_not_replace_a_target_created_during_verification(tmp_path):
    source = workspace(tmp_path / "source")
    backup = WorkspaceBackup(tmp_path / "backups").create(source)
    target = tmp_path / "restored"

    def reserve(stage):
        if stage == "after_restore_verification":
            target.mkdir()
            (target / "existing.txt").write_text("preserve")

    with pytest.raises(BackupError, match="existiert"):
        WorkspaceBackup(tmp_path / "backups", fault=reserve).restore_verified(backup, target)
    assert (target / "existing.txt").read_text() == "preserve"
    assert not list(tmp_path.glob("restored.partial-*"))


def test_missing_descriptor_primitives_fail_closed_explicitly(tmp_path, monkeypatch):
    source = workspace(tmp_path / "source")
    monkeypatch.setattr(workspace_backup, "_WINDOWS_SOURCE", False)
    monkeypatch.setattr(workspace_backup, "_DESCRIPTOR_READS", False)
    with pytest.raises(BackupError, match="nicht unterstützt"):
        WorkspaceBackup(tmp_path / "backups").create(source)
    assert not list((tmp_path / "backups").glob("*.complete"))


def test_fifo_artifact_is_rejected_without_opening_or_hanging(tmp_path):
    source = workspace(tmp_path / "source")
    if not hasattr(os, "mkfifo"):
        # Windows has no filesystem FIFO primitive. Its pipe namespace must
        # still never be accepted as a workspace-relative backup file.
        with workspace_backup._SourceTree(source.root) as tree:
            with pytest.raises(BackupError):
                tree.info(r"\\.\pipe\not-a-workspace-file")
        return
    os.mkfifo(source.root / "not-a-file.json")
    with pytest.raises(BackupError):
        WorkspaceBackup(tmp_path / "backups").create(source)


def test_publish_refuses_even_an_empty_target_created_at_the_last_moment(tmp_path, monkeypatch):
    source = workspace(tmp_path / "source")
    manager = WorkspaceBackup(tmp_path / "backups")
    backup = manager.create(source)
    target = tmp_path / "restored"
    original = workspace_backup._publish_new
    identity = None

    def late_target(temporary, destination):
        nonlocal identity
        destination.mkdir()
        identity = destination.stat().st_ino
        return original(temporary, destination)

    monkeypatch.setattr(workspace_backup, "_publish_new", late_target)
    with pytest.raises(BackupError):
        manager.restore_verified(backup, target)
    assert target.is_dir() and target.stat().st_ino == identity
    assert not list(target.iterdir())
    assert not list(tmp_path.glob("restored.partial-*"))


@pytest.mark.parametrize("name", ["NUL", "con.json", "COM1.txt", "lpt9.log", "AUX.md",
                                 "COM¹.bin", "name.", "name ", "C:outside.json", "safe:stream"])
def test_manifest_cannot_write_windows_devices_drive_paths_or_aliases(tmp_path, name):
    source = workspace(tmp_path / "source")
    manager = WorkspaceBackup(tmp_path / "backups")
    backup = manager.create(source)
    selected = backup / "artifacts" / "handoff.json"
    body = selected.read_bytes()
    with pytest.raises(BackupError, match="portable"):
        manager._restore_name("artifacts/" + name, portable=True)
    manifest_path = backup / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["artifacts/" + name] = manifest["files"].pop("artifacts/handoff.json")
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(BackupError):
        manager.restore_verified(backup, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
    assert selected.read_bytes() == body


def test_windows_source_dispatch_never_uses_posix_descriptor_fallback(tmp_path, monkeypatch):
    from threaddesk.storage import windows_backup_source

    called = []

    class Native:
        def __init__(self, root, *, error_type):
            called.append((root, error_type))

    monkeypatch.setattr(workspace_backup, "_WINDOWS_SOURCE", True)
    monkeypatch.setattr(workspace_backup, "_DESCRIPTOR_READS", False)
    monkeypatch.setattr(windows_backup_source, "WindowsSourceTree", Native)
    assert isinstance(workspace_backup._SourceTree(tmp_path), Native)
    assert called == [(tmp_path, BackupError)]


def test_relative_backup_and_restore_paths_keep_working(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = workspace(Path("source"))
    manager = WorkspaceBackup(Path("backups"))
    backup = manager.create(source)
    restored = manager.restore_verified(backup, Path("restored"))
    assert restored == Path("restored") and restored.is_dir()
    with (restored / "handoff.json").open() as handle:
        assert json.load(handle) == {"kind": "threaddesk.handoff"}


def test_create_does_not_clean_a_preexisting_partial_directory(tmp_path, monkeypatch):
    from types import SimpleNamespace

    source = workspace(tmp_path / "source")
    manager = WorkspaceBackup(tmp_path / "backups")
    manager.backup_root.mkdir()
    fixed = SimpleNamespace(hex="deadbeef123456789012345678901234")
    existing = manager.backup_root / f"workspace-{fixed.hex[:12]}.partial"
    existing.mkdir()
    (existing / "keep").write_bytes(b"foreign existing stage")
    monkeypatch.setattr(workspace_backup, "uuid4", lambda: fixed)
    with pytest.raises(BackupError):
        manager.create(source)
    assert (existing / "keep").read_bytes() == b"foreign existing stage"


def test_restore_does_not_clean_a_preexisting_partial_directory(tmp_path, monkeypatch):
    from types import SimpleNamespace

    source = workspace(tmp_path / "source")
    manager = WorkspaceBackup(tmp_path / "backups")
    backup = manager.create(source)
    fixed = SimpleNamespace(hex="deadbeef123456789012345678901234")
    target = tmp_path / "restored"
    existing = target.with_name(target.name + f".partial-{fixed.hex[:8]}")
    existing.mkdir()
    (existing / "keep").write_bytes(b"foreign existing stage")
    monkeypatch.setattr(workspace_backup, "uuid4", lambda: fixed)
    with pytest.raises(BackupError):
        manager.restore_verified(backup, target)
    assert (existing / "keep").read_bytes() == b"foreign existing stage"


@pytest.mark.parametrize("operation", ["create", "restore"])
def test_exchanged_stage_is_never_recursively_cleaned(tmp_path, operation):
    source = workspace(tmp_path / "source")
    manager = WorkspaceBackup(tmp_path / "backups")
    backup = manager.create(source)
    target = tmp_path / "restored"
    moved = tmp_path / "our-moved-stage"
    exchanged = None

    def exchange(stage):
        nonlocal exchanged
        if (operation, stage) not in {
            ("create", "after_database"), ("restore", "after_restore_verification")
        }:
            return
        partial = (next(manager.backup_root.glob("*.partial")) if operation == "create"
                   else next(tmp_path.glob("restored.partial-*")))
        partial.rename(moved)
        partial.mkdir()
        (partial / "keep").write_bytes(b"foreign replacement stage")
        exchanged = partial
        raise RuntimeError("source operation stopped after the namespace exchange")

    failing = WorkspaceBackup(manager.backup_root, fault=exchange)
    with pytest.raises(BackupError):
        failing.create(source) if operation == "create" else failing.restore_verified(backup, target)
    assert exchanged is not None
    assert (exchanged / "keep").read_bytes() == b"foreign replacement stage"
    assert (moved / "threaddesk.sqlite3").is_file()


def test_local_workspace_name_rules_do_not_add_windows_restrictions_on_posix(tmp_path):
    from threaddesk.storage import portable_backup

    assert WorkspaceBackup._restore_name("artifacts/note:daily.json", portable=False) == "note:daily.json"
    assert not portable_backup._allowed("note:daily.json", "json")
    if workspace_backup._WINDOWS_SOURCE:
        with pytest.raises(BackupError):
            WorkspaceBackup._restore_name("artifacts/note:daily.json")
    else:
        source = workspace(tmp_path / "source")
        (source.root / "note:daily.json").write_bytes(b'{"local":true}')
        manager = WorkspaceBackup(tmp_path / "backups")
        backup = manager.create(source)
        restored = manager.restore_verified(backup, tmp_path / "restored")
        assert (restored / "note:daily.json").read_bytes() == b'{"local":true}'
