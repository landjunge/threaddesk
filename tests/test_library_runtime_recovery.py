"""Recover derived library projections without touching original source files."""

import hashlib
import io
import zipfile

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import NotFound
from threaddesk.services.library_import import LibraryImporter
from threaddesk.services.library_index import LibraryIndex
from threaddesk.services.library_runtime import LibraryRuntime
from threaddesk.services.mcp import McpBridge
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.portable_backup import download_backup, restore_backup
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def existing_library(tmp_path, request, monkeypatch):
    backend = request.param
    store = backend(tmp_path / "workspace")
    source = tmp_path / "originals"
    source.mkdir()
    original = source / "note.md"
    original.write_text(
        "prefix " * 6000 + "RecoveryAnchor deep content", encoding="utf-8"
    )
    # Reproduce an older valid CAS library predating graph/index enrichment.
    with monkeypatch.context() as patch:
        patch.setattr(
            LibraryImporter, "rebuild_index", lambda self: {"status": "not_initialized"}
        )
        importer = LibraryImporter(store)
        assert importer.import_tree(source)["stored"] == 1
    record = importer._read_records()[0]
    yield backend, store, original, record
    if backend is SQLiteStore:
        store.connection.close()


def _files(root):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def _recovered(backend, root, record):
    store = backend(root)
    try:
        index = LibraryIndex(root / "library-files")
        assert index.status()["status"] == "ready"
        assert index.search("RecoveryAnchor")[0]["record_id"] == record["id"]
        node = store.get_node(record["id"])
        assert node.metadata["library_record_id"] == record["id"]
        assert LibraryImporter(store).open_record(record["id"])[0].read_bytes()
    finally:
        if backend is SQLiteStore:
            store.connection.close()


def test_missing_database_with_current_manifest_recovers(existing_library):
    backend, store, original, record = existing_library
    index = LibraryIndex(store.workspace_path / "library-files")
    index.rebuild([record], index.root / "blobs", store=store)
    index.database.path.unlink()
    assert index.status()["error"] == "index_missing"
    before = original.read_bytes(), original.stat().st_mtime_ns
    runtime = LibraryRuntime(lambda: backend(store.workspace_path))
    runtime.tick()
    _recovered(backend, store.workspace_path, record)
    assert runtime.last_error == ""
    assert (original.read_bytes(), original.stat().st_mtime_ns) == before


def test_real_portable_restore_reconstructs_graph_and_content_index(
    existing_library, tmp_path
):
    backend, store, original, record = existing_library
    index = LibraryIndex(store.workspace_path / "library-files")
    index.rebuild([record], index.root / "blobs", store=store)
    body = download_backup(store)
    with zipfile.ZipFile(io.BytesIO(body)) as package:
        assert not any("content-search.sqlite3" in name for name in package.namelist())
        assert any(
            name.endswith("library-files/index.json") for name in package.namelist()
        )
    restored = restore_backup(body, tmp_path / "restored")
    assert not (restored / "library-files/content-search.sqlite3").exists()
    before = original.read_bytes(), original.stat().st_mtime_ns
    LibraryRuntime(lambda: backend(restored)).tick()
    _recovered(backend, restored, record)
    assert (original.read_bytes(), original.stat().st_mtime_ns) == before


def test_legacy_manifest_upgrades_without_source_registration(existing_library):
    backend, store, _original, record = existing_library
    index = LibraryIndex(store.workspace_path / "library-files")
    index._replace(
        {
            "version": 1,
            "status": "ready",
            "failed": 0,
            "documents": [
                {"id": record["id"], "filename": "note.md", "excerpt": "prefix only"}
            ],
        }
    )
    assert index.status()["mode"] == "legacy_json"
    LibraryRuntime(lambda: backend(store.workspace_path)).tick()
    _recovered(backend, store.workspace_path, record)
    assert not (store.workspace_path / "library-watch.json").exists()


def test_records_without_manifest_initialize_only_in_runtime(existing_library):
    backend, store, _original, record = existing_library
    root = store.workspace_path
    assert not (root / "library-files/index.json").exists()
    bridge = McpBridge(ThreadService(store))
    before = _files(root)
    read = bridge.call("library_query", {"action": "search", "query": "RecoveryAnchor"})
    assert read["ok"]
    assert _files(root) == before  # No read-triggered initialization or graph writes.
    LibraryRuntime(lambda: backend(root)).tick()
    _recovered(backend, root, record)


@pytest.mark.parametrize("backend", [JsonStore, SQLiteStore], ids=["json", "sqlite"])
def test_empty_profile_tick_creates_no_library_artifacts(tmp_path, backend):
    root = tmp_path / "empty"
    store = backend(root)
    if backend is SQLiteStore:
        store.connection.close()
    before = _files(root)
    runtime = LibraryRuntime(lambda: backend(root))
    runtime.tick()
    assert runtime.last_error == ""
    assert _files(root) == before
    assert not (root / "library-files").exists()
    assert not (root / "library-watch.json").exists()


def test_runtime_does_not_follow_linked_records_directory(existing_library):
    backend, store, _original, record = existing_library
    records = store.workspace_path / "library-files/records"
    preserved = store.workspace_path / "preserved-records"
    records.rename(preserved)
    records.symlink_to(preserved, target_is_directory=True)
    before = {path.name: path.read_bytes() for path in preserved.iterdir()}
    runtime = LibraryRuntime(lambda: backend(store.workspace_path))
    runtime.tick()
    assert runtime.last_error
    assert not (store.workspace_path / "library-files/index.json").exists()
    assert {path.name: path.read_bytes() for path in preserved.iterdir()} == before
    with pytest.raises(NotFound):
        store.get_node(record["id"])
