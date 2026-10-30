"""Real concurrent index publishers must not replace a newer generation."""
import json
import multiprocessing
import sqlite3
import threading
from copy import deepcopy
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.services.library_import import LibraryImporter
from threaddesk.services.library_index import LibraryIndex, LibrarySearchError
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def example(request, tmp_path):
    store = request.param(tmp_path / "workspace")
    ThreadService(store).create("Index race fixture")
    source = tmp_path / "originals"
    source.mkdir()
    original = source / "fixture.txt"
    original.write_bytes(b"Unique library-owl marker")
    importer = LibraryImporter(store)
    assert importer.import_tree(source)["stored"] == 1
    index = LibraryIndex(importer.root)
    records = importer._read_records()
    assert index.rebuild(records, importer.blobs, store=store)["status"] == "ready"
    yield store, importer, index, records, original
    if isinstance(store, SQLiteStore):
        store.connection.close()


def held_publisher(root, backend, ready, release, result):
    """Usable in both a separate thread and a spawned interpreter process."""
    store = (SQLiteStore if backend == "sqlite" else JsonStore)(Path(root))
    importer = LibraryImporter(store)
    index = LibraryIndex(importer.root)
    publish = index._replace

    def pause(payload):
        ready.set()  # Its database transaction already committed.
        if not release.wait(15):
            raise AssertionError("newer publisher did not complete")
        publish(payload)

    index._replace = pause
    try:
        state = index.rebuild(importer._read_records(), importer.blobs, store=store)
        result.put({"state": state})
    except Exception as exc:  # noqa: BLE001 -- the parent asserts this worker failure
        result.put({"error": repr(exc)})
    finally:
        if isinstance(store, SQLiteStore):
            store.connection.close()


@pytest.mark.parametrize("separate_process", [False, True], ids=["threads", "processes"])
def test_late_publisher_cannot_overwrite_newer_complete_generation(example, separate_process):
    from queue import Queue

    store, importer, index, records, original = example
    source_before = index._source_state()
    context = multiprocessing.get_context("spawn") if separate_process else None
    ready = context.Event() if context else threading.Event()
    release = context.Event() if context else threading.Event()
    result = context.Queue() if context else Queue()
    arguments = (str(store.root), "sqlite" if isinstance(store, SQLiteStore) else "json", ready, release, result)
    worker = context.Process(target=held_publisher, args=arguments) if context else threading.Thread(target=held_publisher, args=arguments)
    worker.start()
    try:
        assert ready.wait(15), "older publisher did not reach the publication boundary"
        latest = index.rebuild(records, importer.blobs, store=store)
        assert latest["status"] == "ready"
        latest_manifest = index.path.read_bytes()
    finally:
        release.set()
        worker.join(15)
        if separate_process and worker.is_alive():
            worker.terminate()
            worker.join(5)
    assert not worker.is_alive()
    older = result.get(timeout=5)
    assert "error" not in older, older
    assert older["state"]["status"] == "ready"
    assert index.path.read_bytes() == latest_manifest
    assert index.status()["generation"] == latest["generation"]
    assert index.status()["status"] == "ready"
    assert index._source_state() == source_before
    assert index.search("library-owl")[0]["record_id"] == records[0]["id"]
    assert original.read_bytes() == b"Unique library-owl marker"
    if context:
        result.close()
        result.join_thread()


def test_old_refresh_stale_marker_cannot_replace_a_newer_generation(example):
    store, importer, index, records, _ = example
    old = deepcopy(index._read())
    latest = index.rebuild(records, importer.blobs, store=store)
    before = index.path.read_bytes()
    index._replace({**old, "status": "stale", "error": "canonical_change"})
    assert index.path.read_bytes() == before
    assert index.status()["generation"] == latest["generation"]
    assert index.status()["status"] == "ready"


def test_real_canonical_change_remains_stale_and_never_serves_old_results(example):
    store, _importer, index, _records, _ = example
    thread = store.list_threads(include_archived=True)[0]
    ThreadService(store).set_note("A real canonical change", thread.id)
    state = index.status()
    assert state["status"] == "stale" and state["error"] == "source_changed"
    with pytest.raises(LibrarySearchError, match="index_stale"):
        index.search("library-owl")


def test_status_and_search_do_not_write_canonical_files_or_index(example):
    store, _importer, index, _records, _ = example

    def inventory():
        return {str(path.relative_to(store.root)): (path.stat().st_size, path.stat().st_mtime_ns, path.read_bytes())
                for path in store.root.rglob("*") if path.is_file()}

    before = inventory()
    assert index.status()["status"] == "ready"
    assert index.search("library-owl")
    assert inventory() == before


def test_missing_index_reads_remain_inert(tmp_path):
    root = tmp_path / "missing-library"
    index = LibraryIndex(root)
    assert index.status()["status"] == "missing" and index.search("needle") == []
    assert not root.exists()


def test_legacy_json_manifest_needs_no_database(tmp_path):
    index = LibraryIndex(tmp_path / "library")
    index._replace({"version": 1, "status": "ready", "documents": [
        {"id": "legacy", "record_id": "legacy", "filename": "legacyneedle.txt"}]})
    assert index.status()["status"] == "ready"
    assert index.search("legacyneedle")[0]["record_id"] == "legacy"
    assert not index.database.path.exists()


def test_failed_schema_marker_remains_publishable_then_repairable(example):
    store, importer, index, records, _ = example
    old = index._read()
    with sqlite3.connect(index.database.path) as db:
        db.execute("DROP TABLE metadata")
    assert index.status()["status"] == "failed"
    index._replace({**old, "status": "stale", "error": "canonical_change"})
    assert json.loads(index.path.read_text())["status"] == "stale"
    assert index.rebuild(records, importer.blobs, store=store)["status"] == "ready"
    assert index.search("library-owl")
