"""Shared library commands and transports must agree on real canonical state."""
import json
import subprocess
import sys

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.core.models import KnowledgeNode
from threaddesk.services.library_api import LibraryApplication
from threaddesk.services.library_files import LibraryFileService
from threaddesk.services.mcp import McpBridge
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.storage.portable_backup import download_backup, restore_backup


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def library(tmp_path, request, monkeypatch):
    root = tmp_path / "desk"
    monkeypatch.setenv("THREADDESK_HOME", str(root))
    monkeypatch.setenv("THREADDESK_STORAGE", "sqlite" if request.param is SQLiteStore else "json")
    store = request.param(root)
    svc = ThreadService(store)
    thread = svc.create("Current library")
    node = KnowledgeNode(id="aaaaaaaaaaaa", kind="project", title="Library project",
                         metadata={"thread_id": thread.id})
    store.save_node(node)
    source = tmp_path / "source"
    source.mkdir()
    original = source / "lookup.txt"
    original.write_text("Original indexed content: Hafenbrücke DeltaAnchor", encoding="utf-8")
    app = LibraryApplication(store)
    result = app.call({"action": "import", "operation_id": "fixture-import",
                       "data": {"source": str(source), "thread_id": thread.id}})
    assert result["complete"], result
    record_id = result["files"][0]["record_id"]
    yield app, svc, record_id, node, original, root
    if hasattr(store, "connection"):
        store.connection.close()


def test_shared_commands_keep_graph_search_and_trash_consistent(library):
    app, svc, identity, node, original, root = library
    assert app.call({"action": "list", "node_id": node.id})["records"][0]["id"] == identity
    graph = svc.graph()
    assert identity in {item["id"] for item in graph["nodes"]}
    assert any(item["source_id"] == node.id and item["target_id"] == identity for item in graph["relations"])
    assert app.call({"action": "search", "query": "hafenbruecke"})["hits"][0]["record_id"] == identity
    assert app.call({"action": "search", "query": "DeltaAnchor", "project_id": node.id})["hits"]
    info = app.call({"action": "info", "id": identity})
    moved = app.call({"action": "move", "id": identity, "operation_id": "move-file",
                      "expected_revision": info["revision"], "data": {"folder": "Reviewed"}})
    assert moved["record"]["logical_path"] == "Reviewed/lookup.txt"
    trash = app.call({"action": "trash", "id": identity, "operation_id": "trash-file",
                      "expected_revision": moved["record"]["revision"], "data": {}})
    assert identity not in {item["id"] for item in svc.graph()["nodes"]}
    assert not app.call({"action": "search", "query": "DeltaAnchor"})["hits"]
    preview = app.call({"action": "preview", "id": identity})
    assert preview["kind"] == "metadata" and not preview["can_open"]
    restored = app.call({"action": "restore", "id": identity, "operation_id": "restore-file",
                         "expected_revision": trash["record"]["revision"],
                         "data": {"trash_generation": trash["record"]["trash_generation"]}})
    assert restored["record"]["id"] == identity
    assert app.call({"action": "search", "query": "DeltaAnchor"})["hits"]
    assert original.read_text() == "Original indexed content: Hafenbrücke DeltaAnchor"


def test_real_cli_mcp_http_share_receipts_and_preview(library, monkeypatch):
    app, svc, identity, node, original, root = library
    bridge = McpBridge(svc)
    response = bridge.call("library_query", {"action": "preview", "id": identity})
    assert response["ok"] and "DeltaAnchor" in response["result"]["text"]
    assert not bridge.call("library_query", {"action": "trash", "id": identity})["ok"]
    cli = subprocess.run([sys.executable, "-m", "threaddesk.ui.cli", "library", "--request",
                          json.dumps({"action": "info", "id": identity})], text=True, capture_output=True, check=False)
    assert cli.returncode == 0, cli.stderr
    assert json.loads(cli.stdout)["result"]["sha256"] == response["result"]["record"]["sha256"]
    from http_ui_client import UIClient
    from threaddesk.ui.server import create_app
    with UIClient(create_app()) as client:
        result = client.get("/api/library/query", params={"action": "preview", "id": identity})
        assert result.status_code == 200
        assert result.json()["result"]["record"]["id"] == identity
        assert client.get("/api/library/query", params={"action": "rename", "id": identity}).status_code == 400
        assert client.post("/api/library/command", json={"action": "info", "id": []}).status_code == 400
    assert app.call({"action": "operation", "operation_id": "fixture-import"})["found"]


def test_canonical_writes_stale_then_refresh_index(library):
    app, svc, identity, node, original, root = library
    svc.set_note("UniqueCurrentThreadNeedle", svc.current().id)
    assert app.index.status()["status"] == "stale"
    with pytest.raises(ManagementError, match="index_stale"):
        app.call({"action": "search", "query": "UniqueCurrentThreadNeedle"})
    from threaddesk.services.library_refresh import refresh_existing
    assert refresh_existing(svc.store)["status"] == "ready"
    assert app.call({"action": "search", "query": "UniqueCurrentThreadNeedle"})["hits"]
    request = {"action": "reindex", "operation_id": "reindex-receipt"}
    assert app.call(request)["index"]["status"] == "ready"
    assert app.call(request)["duplicate"]
    assert app.call({"action": "operation", "operation_id": "reindex-receipt"})["found"]


def test_portable_backup_keeps_file_lifecycle(library, tmp_path, monkeypatch):
    app, svc, identity, node, original, root = library
    record = app.call({"action": "info", "id": identity})
    app.call({"action": "trash", "id": identity, "operation_id": "backup-trash",
              "expected_revision": record["revision"], "data": {}})
    packed = download_backup(svc.store)
    restored = tmp_path / "restored"
    restored = restore_backup(packed, restored)
    destination = SQLiteStore(restored) if isinstance(svc.store, SQLiteStore) else JsonStore(restored)
    try:
        files = LibraryFileService(destination)
        assert files.preview(identity)["record"]["trashed"]
        assert files.operation_status("backup-trash")["found"]
    finally:
        if hasattr(destination, "connection"):
            destination.connection.close()


def test_operation_ids_cannot_cross_domains(library):
    app, svc, identity, node, original, root = library
    record = app.call({"action": "info", "id": identity})
    with pytest.raises(ManagementError, match="import"):
        app.call({"action": "copy", "id": identity, "expected_revision": record["revision"],
                  "operation_id": "fixture-import", "data": {"filename": "UnsafeDuplicate.txt"}})
    request = {"action": "copy", "id": identity, "expected_revision": record["revision"],
               "operation_id": "bound-copy", "data": {"filename": "SafeCopy.txt"}}
    copied = app.call(request)
    assert app.call(request)["record"]["id"] == copied["record"]["id"]
    with pytest.raises(ManagementError, match="different"):
        app.call({"action": "reindex", "operation_id": "bound-copy"})


def test_legacy_batch_replay_cannot_poison_public_binding(library, tmp_path):
    from threaddesk.services.library_batch import LibraryBatchImporter
    from threaddesk.services.library_operation import LibraryOperationBinding
    app, svc, identity, node, original, root = library
    batch = LibraryBatchImporter(svc.store)
    manifest = batch.manifest_for_folder(original.parent)
    receipt = batch.run(manifest, operation_id="legacy-batch")
    assert receipt["complete"]
    wrong = tmp_path / "different-source"
    wrong.mkdir()
    (wrong / "other.txt").write_text("Other bytes")
    with pytest.raises(ManagementError, match="different import"):
        app.call({"action": "import", "operation_id": "legacy-batch",
                  "data": {"source": str(wrong)}})
    assert LibraryOperationBinding(svc.store).read("legacy-batch") is None
    replay = app.call({"action": "import", "operation_id": "legacy-batch",
                       "data": {"manifest": manifest}})
    assert replay["complete"]
    assert app.call({"action": "resume", "operation_id": "legacy-batch"})["complete"]
    assert replay["files"][0]["record_id"] == receipt["files"][0]["record_id"]


def test_source_refresh_has_definite_replay_and_readback(library, monkeypatch):
    from threaddesk.services.library_watch import LibrarySourceWatch
    app, svc, identity, node, original, root = library
    calls = []
    def poll(watch):
        calls.append(True)
        return {"watches": [], "outcomes": []}
    monkeypatch.setattr(LibrarySourceWatch, "poll_once", poll)
    request = {"action": "refresh_sources", "operation_id": "source-refresh-receipt"}
    result = app.call(request)
    assert result["status"] == "complete"
    assert app.call({"action": "operation", "operation_id": request["operation_id"]})["result"] == result
    assert app.call(request) == {**result, "duplicate": True}
    assert len(calls) == 1


def test_format_capabilities_do_not_hide_import_guards(library):
    app, *_ = library
    formats = {row["suffix"]: row for row in app.call({"action": "formats"})}
    assert not formats[".key"]["import_allowed"]
    assert formats[".key"]["import_error"] == "secret_name"
    assert not formats[".exe"]["import_allowed"]
    assert formats[".pdf"]["import_allowed"]
    assert formats[".py"]["import_allowed"] and not formats[".py"]["external_open"]
