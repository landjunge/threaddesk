"""Library copies, receipts and pending bytes survive real backup restoration."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import zipfile

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.services.library_import import LibraryImporter
from threaddesk.services.mcp import McpBridge
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.storage.portable_backup import download_backup, restore_backup
from threaddesk.storage.workspace_backup import BackupError, WorkspaceBackup


def receive(bridge, action, transfer_id="pending", **fields):
    result = bridge.call("library_receive", {"action": action, "transfer_id": transfer_id, **fields})
    assert result["ok"], result
    return result["result"]


def prepare(store, tmp_path):
    svc = ThreadService(store)
    tid = svc.create("Library project").id
    source = tmp_path / "originals"
    source.mkdir()
    original = source / "note.md"
    original.write_bytes(b"Library roundtrip text\n")
    imported = LibraryImporter(store).import_tree(source)
    assert imported["stored"] == 1
    bridge = McpBridge(svc)
    payload = b"received bytes\n"
    for transfer_id in ("done", "pending"):
        receive(bridge, "begin", transfer_id, filename=transfer_id + ".txt", thread_id=tid,
                size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        data = payload if transfer_id == "done" else payload[:5]
        receive(bridge, "append", transfer_id, offset=0, data_base64=base64.b64encode(data).decode())
    receipt = receive(bridge, "commit", "done")["receipt"]
    return svc, original, receipt, payload


def check_restored(store, original, receipt, payload):
    svc = ThreadService(store)
    importer = LibraryImporter(store)
    records = importer.catalog()["records"]
    assert len(records) == 2
    note = next(r for r in records if r["filename"] == "note.md")
    assert importer.open_record(note["id"])[0].read_bytes() == original.read_bytes()
    bridge = McpBridge(svc)
    assert receive(bridge, "status", "done")["receipt"] == receipt
    assert receive(bridge, "status")["next_offset"] == 5
    receive(bridge, "append", offset=5, data_base64=base64.b64encode(payload[5:]).decode())
    completed = receive(bridge, "commit")["receipt"]
    assert importer.open_record(completed["record_id"])[0].read_bytes() == payload
    assert len(importer.catalog()["records"]) == 3


@pytest.mark.parametrize("backend", [JsonStore, SQLiteStore])
def test_portable_library_roundtrip_preserves_originals_receipts_and_resume(tmp_path, backend):
    store = backend(tmp_path / "source")
    svc, original, receipt, payload = prepare(store, tmp_path)
    before = (original.read_bytes(), original.stat().st_mtime_ns)
    body = download_backup(store)
    restored = restore_backup(body, tmp_path / "target")
    target = backend(restored)
    try:
        check_restored(target, original, receipt, payload)
        assert (original.read_bytes(), original.stat().st_mtime_ns) == before
        assert receive(McpBridge(svc), "status")["next_offset"] == 5
    finally:
        for item in (store, target):
            if isinstance(item, SQLiteStore):
                item.connection.close()


def test_workspace_library_roundtrip(tmp_path):
    store = SQLiteStore(tmp_path / "source")
    _, original, receipt, payload = prepare(store, tmp_path)
    manager = WorkspaceBackup(tmp_path / "backups")
    backup = manager.create(store)
    restored = manager.restore_verified(backup, tmp_path / "restored")
    target = SQLiteStore(restored)
    try:
        check_restored(target, original, receipt, payload)
    finally:
        target.connection.close()
        store.connection.close()


@pytest.mark.parametrize("backend", [JsonStore, SQLiteStore])
def test_receiver_wal_snapshot_is_self_contained_and_leaves_source_unchanged(tmp_path, backend):
    store = backend(tmp_path / "source")
    svc, original, receipt, payload = prepare(store, tmp_path)
    script = '''
import os
from threaddesk.api.service import ThreadService
from threaddesk.services.mcp import McpBridge
result = McpBridge(ThreadService()).call("library_receive", {"action":"append", "transfer_id":"pending", "offset":5, "data_base64":"dg=="})
assert result["ok"], result
os._exit(75)
'''
    # Hold a reader open so the writer's committed frame remains in the WAL.
    root = Path(store.workspace_path) / "library-files"
    pinned = sqlite3.connect(root / "receive.sqlite3")
    pinned.execute("BEGIN")
    pinned.execute("SELECT count(*) FROM transfers").fetchone()
    env = {**os.environ, "THREADDESK_HOME": str(store.workspace_path),
           "THREADDESK_STORAGE": "sqlite" if backend is SQLiteStore else "json"}
    process = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=20)
    assert process.returncode == 75, process.stderr
    wal = root / "receive.sqlite3-wal"
    assert wal.is_file() and wal.stat().st_size > 0
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / "receive.sqlite3", wal)}
    try:
        body = download_backup(store)
        assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before} == before
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            assert not any(name.endswith(("-wal", "-shm", "-journal")) for name in archive.namelist())
        restored = backend(restore_backup(body, tmp_path / "target"))
        try:
            bridge = McpBridge(ThreadService(restored))
            assert receive(bridge, "status")["next_offset"] == 6
            receive(bridge, "append", offset=6, data_base64=base64.b64encode(payload[6:]).decode())
            completed = receive(bridge, "commit")["receipt"]
            assert LibraryImporter(restored).open_record(completed["record_id"])[0].read_bytes() == payload
        finally:
            if backend is SQLiteStore:
                restored.connection.close()
    finally:
        pinned.close()
        if backend is SQLiteStore:
            store.connection.close()


@pytest.mark.parametrize("backend", [JsonStore, SQLiteStore])
def test_library_change_during_capture_refuses_backup(tmp_path, backend, monkeypatch):
    from threaddesk.storage import library_backup
    store = backend(tmp_path / "source")
    svc, _, _, _ = prepare(store, tmp_path)
    normalize = library_backup._normalize_receiver

    def change_after_copy(root):
        normalize(root)
        receive(McpBridge(svc), "append", offset=5, data_base64="dg==")

    monkeypatch.setattr(library_backup, "_normalize_receiver", change_after_copy)
    try:
        with pytest.raises(BackupError, match="changed"):
            download_backup(store)
        assert receive(McpBridge(svc), "status")["next_offset"] == 6
    finally:
        if backend is SQLiteStore:
            store.connection.close()


@pytest.mark.parametrize("damage", ["blob", "receipt", "missing_blob", "missing_import", "sidecar"])
def test_recomputed_archive_hashes_cannot_hide_invalid_library(tmp_path, damage):
    store = JsonStore(tmp_path / "source")
    _, _, receipt, _ = prepare(store, tmp_path)
    with zipfile.ZipFile(io.BytesIO(download_backup(store))) as archive:
        bodies = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(bodies["manifest.json"])
    blob = "library-files/blobs/" + receipt["sha256"]
    if damage == "receipt":
        database = tmp_path / "tampered.sqlite3"
        name = "library-files/receive.sqlite3"
        database.write_bytes(bodies["workspace/" + name])
        with sqlite3.connect(database) as conn:
            row = conn.execute("SELECT receipt FROM transfers WHERE id='done'").fetchone()
            value = json.loads(row[0])
            value["sha256"] = "0" * 64
            conn.execute("UPDATE transfers SET receipt=? WHERE id='done'", (json.dumps(value),))
        bodies["workspace/" + name] = database.read_bytes()
    elif damage == "missing_blob":
        del bodies["workspace/" + blob]
        del manifest["files"][blob]
    elif damage == "missing_import":
        for name in list(manifest["files"]):
            if name.startswith("library-files/records/"):
                record = json.loads(bodies["workspace/" + name])
                if record["filename"] == "note.md":
                    missing = "library-files/blobs/" + record["sha256"]
                    for dropped in (name, missing):
                        del bodies["workspace/" + dropped]
                        del manifest["files"][dropped]
    elif damage == "sidecar":
        bodies["workspace/library-files/receive.sqlite3-wal"] = b"foreign WAL"
    else:
        bodies["workspace/" + blob] = b"forged"
    for name, value in bodies.items():
        if name.startswith("workspace/"):
            manifest["files"][name[len("workspace/"):]] = {"size": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    bodies["manifest.json"] = json.dumps(manifest).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, value in bodies.items():
            archive.writestr(name, value)
    target = tmp_path / "target"
    with pytest.raises(BackupError):
        restore_backup(output.getvalue(), target)
    assert not (target / "active-profile.json").exists()
    assert not list((target / "profiles").iterdir())


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory_file"])
def test_library_links_and_invalid_directory_never_publish(tmp_path, kind):
    store = JsonStore(tmp_path / "source")
    _, original, _, _ = prepare(store, tmp_path)
    outside = tmp_path / "outside"
    outside.write_bytes(b"preserve outside")
    root = Path(store.workspace_path) / "library-files"
    if kind == "directory_file":
        (root / "extra").mkdir()
        # A reserved directory must never silently disappear from a backup.
        import shutil
        shutil.rmtree(root / "records")
        (root / "records").write_bytes(b"not a directory")
    else:
        blob = next((root / "blobs").iterdir())
        blob.unlink()
        blob.symlink_to(outside) if kind == "symlink" else os.link(outside, blob)
    with pytest.raises(BackupError):
        download_backup(store)
    assert outside.read_bytes() == b"preserve outside"
    assert original.read_bytes() == b"Library roundtrip text\n"


@pytest.mark.parametrize("backend", [JsonStore, SQLiteStore])
def test_library_limit_refuses_whole_backup_instead_of_omitting_copies(tmp_path, backend, monkeypatch):
    from threaddesk.storage import portable_backup
    store = backend(tmp_path / "source")
    _, original, _, _ = prepare(store, tmp_path)
    large = original.parent / "large.pdf"
    large.write_bytes(b"%PDF" + b"x" * (600 * 1024))
    LibraryImporter(store).import_tree(original.parent)
    monkeypatch.setattr(portable_backup, "LIMIT", 512 * 1024)
    try:
        with pytest.raises(BackupError, match="size limit"):
            download_backup(store)
        assert large.stat().st_size == 600 * 1024 + 4
    finally:
        if backend is SQLiteStore:
            store.connection.close()


@pytest.mark.parametrize("backend", [JsonStore, SQLiteStore])
def test_version_one_portable_backup_remains_readable(tmp_path, backend):
    store = backend(tmp_path / "source")
    thread = ThreadService(store).create("Legacy without library")
    try:
        with zipfile.ZipFile(io.BytesIO(download_backup(store))) as archive:
            bodies = {name: archive.read(name) for name in archive.namelist()}
        manifest = json.loads(bodies["manifest.json"])
        manifest["version"] = 1
        # Real legacy archives predate all v3-only metadata fields.
        for field in ("directories", "symlinks", "consistency"):
            manifest.pop(field, None)
        bodies["manifest.json"] = json.dumps(manifest).encode()
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            for name, value in bodies.items():
                archive.writestr(name, value)
        target = backend(restore_backup(output.getvalue(), tmp_path / "target"))
        try:
            assert target.get_thread(thread.id).title == thread.title
            assert not (target.workspace_path / "library-files").exists()
        finally:
            if backend is SQLiteStore:
                target.connection.close()
    finally:
        if backend is SQLiteStore:
            store.connection.close()


def test_manifest_overhead_is_included_in_download_limit(tmp_path, monkeypatch):
    from threaddesk.storage import portable_backup
    store = JsonStore(tmp_path / "source")
    ThreadService(store).create("Complete backup must fit its restore limit")
    with zipfile.ZipFile(io.BytesIO(download_backup(store))) as archive:
        payload_bytes = sum(item.file_size for item in archive.infolist() if item.filename != "manifest.json")
    monkeypatch.setattr(portable_backup, "LIMIT", payload_bytes + 1)
    with pytest.raises(BackupError, match="size limit"):
        download_backup(store)


@pytest.mark.parametrize("backend", [JsonStore, SQLiteStore])
def test_hot_rollback_journal_is_recovered_only_in_private_backup_copy(tmp_path, backend):
    store = backend(tmp_path / "source")
    svc, _, _, _ = prepare(store, tmp_path)
    bridge = McpBridge(svc)
    payload = b"x" * (4 * 1024 * 1024)
    tid = svc.current().id
    receive(bridge, "begin", "interrupted", filename="interrupted.txt", thread_id=tid,
            size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    for offset in range(0, len(payload), 256 * 1024):
        receive(bridge, "append", "interrupted", offset=offset,
                data_base64=base64.b64encode(payload[offset:offset + 256 * 1024]).decode())
    root = Path(store.workspace_path) / "library-files"
    script = '''
import os, sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
conn.execute("PRAGMA journal_mode=DELETE")
conn.execute("PRAGMA cache_size=32")
conn.execute("PRAGMA secure_delete=ON")
conn.execute("BEGIN IMMEDIATE")
conn.execute("UPDATE transfers SET state='aborted' WHERE id='interrupted'")
conn.execute("DELETE FROM chunks WHERE transfer_id='interrupted'")
os._exit(76)
'''
    process = subprocess.run([sys.executable, "-c", script, str(root / "receive.sqlite3")],
                             capture_output=True, text=True, timeout=20)
    assert process.returncode == 76, process.stderr
    journal = root / "receive.sqlite3-journal"
    assert journal.is_file() and journal.stat().st_size > 2 * 1024 * 1024
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / "receive.sqlite3", journal)}
    try:
        body = download_backup(store)
        assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before} == before
        target = backend(restore_backup(body, tmp_path / "target"))
        try:
            restored = McpBridge(ThreadService(target))
            state = receive(restored, "status", "interrupted")
            assert state["state"] == "receiving" and state["next_offset"] == len(payload)
            receipt = receive(restored, "commit", "interrupted")["receipt"]
            assert LibraryImporter(target).open_record(receipt["record_id"])[0].read_bytes() == payload
        finally:
            if backend is SQLiteStore:
                target.connection.close()
    finally:
        if backend is SQLiteStore:
            store.connection.close()


@pytest.mark.parametrize("backend", [JsonStore, SQLiteStore])
def test_corrupt_receiver_database_returns_controlled_backup_error(tmp_path, backend):
    store = backend(tmp_path / "source")
    _, original, _, _ = prepare(store, tmp_path)
    (Path(store.workspace_path) / "library-files/receive.sqlite3").write_bytes(b"not a SQLite database")
    try:
        with pytest.raises(BackupError):
            download_backup(store)
        assert original.read_bytes() == b"Library roundtrip text\n"
    finally:
        if backend is SQLiteStore:
            store.connection.close()


@pytest.mark.parametrize("backend", [JsonStore, SQLiteStore])
def test_replaced_workspace_cannot_rebind_library_capture(tmp_path, backend, monkeypatch):
    from threaddesk.storage import library_backup
    store = backend(tmp_path / "source")
    _, original, _, _ = prepare(store, tmp_path)
    capture = library_backup.capture
    normalized = []
    moved = tmp_path / "moved-source"

    def exchange_root(workspace, destination, **kwargs):
        # Native Windows may prevent this rename through its retained handles;
        # otherwise the original bound source must reject the replacement.
        Path(workspace).rename(moved)
        Path(workspace).mkdir()
        (Path(workspace) / "library-files").mkdir()
        return capture(workspace, destination, **kwargs)

    monkeypatch.setattr(library_backup, "capture", exchange_root)
    monkeypatch.setattr(library_backup, "_normalize_receiver", lambda root: normalized.append(root))
    try:
        with pytest.raises(BackupError):
            download_backup(store)
        assert not normalized
        assert original.read_bytes() == b"Library roundtrip text\n"
        if moved.exists():
            assert (moved / "library-files/receive.sqlite3").is_file()
    finally:
        if backend is SQLiteStore:
            store.connection.close()


def test_concurrent_core_edit_during_library_snapshot_is_not_published(tmp_path):
    store = SQLiteStore(tmp_path / "source")
    svc, original, _, _ = prepare(store, tmp_path)
    tid = svc.current().id

    def concurrent_write(stage):
        if stage == "after_database":
            other = SQLiteStore(store.workspace_path)
            try:
                ThreadService(other).set_note("Concurrent edit retained", tid)
            finally:
                other.connection.close()

    manager = WorkspaceBackup(tmp_path / "backups", fault=concurrent_write)
    try:
        with pytest.raises(BackupError, match="changed"):
            manager.create(store)
        assert svc.get(tid).context.notes == "Concurrent edit retained"
        assert not list((tmp_path / "backups").iterdir())
        assert original.read_bytes() == b"Library roundtrip text\n"
    finally:
        store.connection.close()


@pytest.mark.parametrize("backend", [JsonStore, SQLiteStore])
def test_library_root_case_alias_is_refused_instead_of_silently_omitted(tmp_path, backend):
    store = backend(tmp_path / "source")
    _, original, _, _ = prepare(store, tmp_path)
    root = Path(store.workspace_path)
    (root / "library-files").rename(root / "renaming-library")
    (root / "renaming-library").rename(root / "Library-Files")
    try:
        with pytest.raises(BackupError):
            download_backup(store)
        assert len(list((root / "Library-Files/records").glob("*.json"))) == 2
        assert original.read_bytes() == b"Library roundtrip text\n"
    finally:
        if backend is SQLiteStore:
            store.connection.close()


def test_external_super_journal_is_refused_before_sqlite_opens_the_capture(tmp_path, monkeypatch):
    from threaddesk.storage import library_backup
    store = JsonStore(tmp_path / "source")
    prepare(store, tmp_path)
    outside = tmp_path / "external-super-journal"
    outside.write_bytes(b"must remain untouched")
    name = os.fsencode(outside)
    trailer = len(name).to_bytes(4, "big") + (sum(name) & 0xffffffff).to_bytes(4, "big") + library_backup.JOURNAL_MAGIC
    journal = Path(store.workspace_path) / "library-files/receive.sqlite3-journal"
    journal.write_bytes(b"\0" * 512 + name + trailer)

    def refuse_sqlite(*args, **kwargs):
        raise AssertionError("SQLite must not open a capture with an external super-journal")

    monkeypatch.setattr(library_backup.sqlite3, "connect", refuse_sqlite)
    with pytest.raises(BackupError, match="Multi-database"):
        download_backup(store)
    assert outside.read_bytes() == b"must remain untouched"
    assert journal.read_bytes().endswith(trailer)


def test_receiver_commit_uses_flushable_handles_without_changing_bytes(tmp_path, monkeypatch):
    original_fsync = os.fsync
    checked = []

    def write_access_required(fd):
        # Model FlushFileBuffers' GENERIC_WRITE requirement on POSIX too.
        # A zero-byte write checks access without altering data or offset.
        if stat.S_ISREG(os.fstat(fd).st_mode):
            os.write(fd, b"")
            checked.append(fd)
        return original_fsync(fd)

    monkeypatch.setattr(os, "fsync", write_access_required)
    store = JsonStore(tmp_path / "source")
    svc, original, receipt, payload = prepare(store, tmp_path)
    path, _ = LibraryImporter(store).open_record(receipt["record_id"])
    assert checked and path.read_bytes() == payload
    assert original.read_bytes() == b"Library roundtrip text\n"
