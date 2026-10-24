"""Receiver protocol/security and real MCP to stored-download integration."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.services.library_import import LibraryImporter, LibraryImportError
from threaddesk.services.library_receive import LibraryReceiver, MAX_CHUNK_BYTES
from threaddesk.services.mcp import McpBridge
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.ui.mcp_stdio import handle


@pytest.fixture(params=[JsonStore, SQLiteStore])
def desk(tmp_path, request):
    store = request.param(tmp_path / "desk")
    svc = ThreadService(store=store)
    thread = svc.create("Receiver test")
    yield svc, thread.id
    if isinstance(store, SQLiteStore):
        store.connection.close()


def begin(thread_id, data=b"Hallo Bruecke\n", **extra):
    return {"action": "begin", "transfer_id": "test-upload-1", "filename": "Plan.md",
            "thread_id": thread_id, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), **extra}


def append(data=b"Hallo Bruecke\n", offset=0):
    return {"action": "append", "transfer_id": "test-upload-1", "offset": offset,
            "data_base64": base64.b64encode(data).decode()}


def call(svc, **args):
    return McpBridge(svc).call("library_receive", args)


def test_restart_retry_receipt_search_and_download(desk, monkeypatch):
    svc, tid = desk
    data = b"Hallo Bruecke\n"
    assert call(svc, **begin(tid))["result"]["next_offset"] == 0
    assert call(svc, **append(data[:5]))["result"]["next_offset"] == 5
    # A freshly constructed MCP bridge resumes exactly the saved byte offset.
    state = McpBridge(svc).call("library_receive_status", {"transfer_id": "test-upload-1"})["result"]
    assert state["next_offset"] == 5 and state["receipt"] is None
    assert call(svc, **append(data[:5]))["result"]["next_offset"] == 5
    assert call(svc, **append(data[5:], 5))["result"]["next_offset"] == len(data)
    receipt = call(svc, action="commit", transfer_id="test-upload-1")["result"]["receipt"]
    assert receipt["sha256"] == hashlib.sha256(data).hexdigest()
    assert receipt["index"]["status"] == "ready"
    assert call(svc, action="commit", transfer_id="test-upload-1")["result"]["receipt"] == receipt
    assert len(list((Path(svc.store.root) / "library-files/records").glob("*.json"))) == 1
    bridge = McpBridge(svc)
    rpc = handle(bridge, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "library_search", "arguments": {"thread_id": tid, "query": "Bruecke"}}})
    hits = json.loads(rpc["result"]["content"][0]["text"])["hits"]
    assert hits[0]["id"] == receipt["record_id"]
    info = bridge.call("library_file_info", {"thread_id": tid, "record_id": receipt["record_id"]})
    assert info["result"]["open_path"] == receipt["open_path"]
    other = svc.create("Other")
    assert not bridge.call("library_file_info", {"thread_id": other.id, "record_id": receipt["record_id"]})["ok"]
    assert bridge.call("library_search", {"thread_id": other.id, "query": "Bruecke"})["result"]["hits"] == []
    from http_ui_client import UIClient
    from threaddesk.ui.server import create_app
    monkeypatch.setenv("THREADDESK_HOME", str(svc.store.root))
    client = UIClient(create_app())
    response = client.get(receipt["open_path"])
    assert response.status_code == 200 and response.content == data
    assert response.headers["content-disposition"].startswith("attachment")


def test_conflicts_incomplete_checksum_and_abort(desk):
    svc, tid = desk
    call(svc, **begin(tid))
    assert call(svc, **begin(tid, filename="other.md"))["code"] == "transfer_conflict"
    assert call(svc, **append(b"X", 1))["code"] == "offset_conflict"
    assert call(svc, action="commit", transfer_id="test-upload-1")["code"] == "transfer_incomplete"
    call(svc, **append(b"X"))
    assert call(svc, **append(b"Y"))["code"] == "chunk_conflict"
    call(svc, **append(b"X" * 13, 1))
    assert call(svc, action="commit", transfer_id="test-upload-1")["code"] == "checksum_mismatch"
    assert not (Path(svc.store.root) / "library-files/records").exists()
    assert call(svc, action="abort", transfer_id="test-upload-1")["result"]["state"] == "aborted"
    assert call(svc, action="abort", transfer_id="test-upload-1")["ok"]
    assert call(svc, action="commit", transfer_id="test-upload-1")["code"] == "transfer_closed"


@pytest.mark.parametrize("changes", [
    {"filename": "../bad.md"}, {"filename": "a\\b.md"}, {"filename": "a\nb.md"},
    {"filename": "credentials.json"}, {"filename": "run.command"},
    {"transfer_id": "../escape"}, {"thread_id": "../escape"}, {"size": True},
    {"size": -1}, {"size": 256 * 1024 * 1024 + 1}, {"sha256": "a" * 63},
    {"source_path": "/etc/passwd"}, {"principal": "admin"},
])
def test_remote_input_rejected_without_receiver_writes(desk, changes):
    svc, tid = desk
    assert not call(svc, **{**begin(tid), **changes})["ok"]
    assert not (Path(svc.store.root) / "library-files").exists()


def test_invalid_chunks_and_no_side_effect_status(desk):
    svc, tid = desk
    result = McpBridge(svc).call("library_receive_status", {"transfer_id": "missing"})
    assert result["result"]["found"] is False
    assert not (Path(svc.store.root) / "library-files").exists()
    call(svc, **begin(tid))
    assert call(svc, **{**append(), "data_base64": "***"})["code"] == "invalid_base64"
    assert call(svc, **append(b"x" * (MAX_CHUNK_BYTES + 1)))["code"] == "chunk_size"
    assert call(svc, **{**append(), "offset": False})["code"] == "validation_error"
    assert call(svc, **append(b"x" * 15))["code"] == "size_mismatch"


def test_interrupted_publish_repairs_without_duplicate(desk, monkeypatch):
    svc, tid = desk
    call(svc, **begin(tid))
    call(svc, **append())
    with monkeypatch.context() as patch:
        patch.setattr(LibraryImporter, "_link_thread", lambda *a: (_ for _ in ()).throw(OSError("test interruption")))
        assert not call(svc, action="commit", transfer_id="test-upload-1")["ok"]
    result = call(svc, action="commit", transfer_id="test-upload-1")
    assert result["ok"] and result["result"]["state"] == "committed"
    rid = result["result"]["receipt"]["record_id"]
    assert svc.store.get_thread(tid).context.extra["library_files"] == [rid]
    assert len(list((Path(svc.store.root) / "library-files/records").glob("*.json"))) == 1


def test_symlink_store_refused(desk, tmp_path):
    svc, tid = desk
    outside = tmp_path / "outside"
    outside.mkdir()
    (Path(svc.store.root) / "library-files").symlink_to(outside, target_is_directory=True)
    assert call(svc, **begin(tid))["code"] == "unsafe_store"
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("damage", ["missing", "bad_record", "escape", "symlink", "checksum", "record_id"])
def test_open_damage_is_controlled(desk, tmp_path, damage):
    svc, tid = desk
    call(svc, **begin(tid))
    call(svc, **append())
    receipt = call(svc, action="commit", transfer_id="test-upload-1")["result"]["receipt"]
    importer = LibraryImporter(svc.store)
    record_path = importer.records / f"{receipt['record_id']}.json"
    blob = importer.blobs / receipt["sha256"]
    if damage == "missing":
        blob.unlink()
    elif damage == "bad_record":
        record_path.write_text("{")
    elif damage == "escape":
        record = json.loads(record_path.read_text())
        record["sha256"] = "../../outside"
        record_path.write_text(json.dumps(record))
    elif damage == "symlink":
        outside = tmp_path / "outside"
        outside.write_bytes(b"Hallo Bruecke\n")
        blob.unlink()
        blob.symlink_to(outside)
    elif damage == "record_id":
        record = json.loads(record_path.read_text())
        record["id"] = "../../outside"
        record_path.write_text(json.dumps(record))
    else:
        blob.write_bytes(b"changed")
    with pytest.raises(LibraryImportError, match="integrity"):
        importer.open_record(receipt["record_id"])


def test_annotations_do_not_offer_upload_as_read_only(desk):
    svc, _ = desk
    tools = {t["name"]: t for t in McpBridge(svc).list_tools()}
    assert tools["library_receive"]["annotations"]["readOnlyHint"] is False
    for name in ("library_receive_status", "library_search", "library_file_info"):
        assert tools[name]["annotations"]["readOnlyHint"] is True


def test_real_stdio_process_resumes_and_reads_receipt(desk):
    svc, tid = desk
    call(svc, **begin(tid))
    call(svc, **append())
    env = {**os.environ, "THREADDESK_HOME": str(svc.store.root),
           "THREADDESK_STORAGE": "sqlite" if isinstance(svc.store, SQLiteStore) else "json"}
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "library_receive_status", "arguments": {"transfer_id": "test-upload-1"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "library_receive", "arguments": {"action": "commit", "transfer_id": "test-upload-1"}}},
    ]
    process = subprocess.run([sys.executable, "-m", "threaddesk.ui.mcp_stdio"],
        input="".join(json.dumps(req) + "\n" for req in requests),
        text=True, capture_output=True, timeout=20, env=env)
    assert process.returncode == 0, process.stderr
    results = [json.loads(line)["result"] for line in process.stdout.splitlines()]
    before, after = [json.loads(r["content"][0]["text"]) for r in results]
    assert before["next_offset"] == 14 and before["receipt"] is None
    assert after["state"] == "committed"
    assert call(svc, action="status", transfer_id="test-upload-1")["result"]["receipt"] == after["receipt"]


def test_empty_file_and_quota_release(desk, monkeypatch):
    svc, tid = desk
    from threaddesk.services import library_receive
    monkeypatch.setattr(library_receive, "MAX_ACTIVE", 1)
    assert call(svc, **begin(tid, b""))["ok"]
    assert call(svc, **begin(tid, transfer_id="other"))["code"] == "receive_quota"
    assert call(svc, action="commit", transfer_id="test-upload-1")["result"]["receipt"]["size"] == 0
    assert call(svc, **begin(tid, transfer_id="other"))["ok"]
    call(svc, action="abort", transfer_id="other")
    monkeypatch.setattr(library_receive, "MAX_RESERVED", 1)
    assert call(svc, **begin(tid, transfer_id="third"))["code"] == "receive_quota"


def test_secret_payload_not_published(desk):
    svc, tid = desk
    data = b"api_key=sk-abcdefghijklmnopqrstuvwxyz\n"
    call(svc, **begin(tid, data))
    call(svc, **append(data))
    assert not call(svc, action="commit", transfer_id="test-upload-1")["ok"]
    assert not (Path(svc.store.root) / "library-files/records").exists()


@pytest.mark.parametrize("name", ["receive.sqlite3-journal", "index.json.tmp"])
def test_symlink_journal_cannot_touch_external_file(desk, tmp_path, name):
    svc, tid = desk
    call(svc, **begin(tid))
    outside = tmp_path / "outside"
    outside.write_bytes(b"preserve")
    (Path(svc.store.root) / "library-files" / name).symlink_to(outside)
    assert call(svc, **append())["code"] == "unsafe_store"
    assert outside.read_bytes() == b"preserve"


@pytest.mark.parametrize("action", ["commit", "abort"])
def test_process_exit_after_link_recovers_without_mutating_status(desk, action):
    svc, tid = desk
    call(svc, **begin(tid))
    call(svc, **append())
    env = {**os.environ, "THREADDESK_HOME": str(svc.store.workspace_path),
           "THREADDESK_STORAGE": "sqlite" if isinstance(svc.store, SQLiteStore) else "json"}
    script = '''
import os
from threaddesk.api.service import ThreadService
from threaddesk.services.mcp import McpBridge
original = os.link
def crash_after_link(source, target):
    original(source, target)
    os._exit(73)
os.link = crash_after_link
McpBridge(ThreadService()).call("library_receive", {"action":"commit", "transfer_id":"test-upload-1"})
'''
    process = subprocess.run([sys.executable, "-c", script], env=env,
                             capture_output=True, text=True, timeout=20)
    assert process.returncode == 73, process.stderr
    importer = LibraryImporter(svc.store)
    blob = importer.blobs / begin(tid)["sha256"]
    partials = list(importer.blobs.glob(".*"))
    assert len(partials) == 1 and blob.stat().st_nlink == 2
    status = McpBridge(svc).call("library_receive_status", {"transfer_id": "test-upload-1"})
    assert status["ok"] and status["result"]["state"] == "receiving"
    assert partials[0].exists() and blob.stat().st_nlink == 2  # Status remains read-only.
    result = call(svc, action=action, transfer_id="test-upload-1")
    assert result["ok"] and result["result"]["state"] == ("committed" if action == "commit" else "aborted")
    assert not partials[0].exists() and blob.stat().st_nlink == 1
    assert blob.read_bytes() == b"Hallo Bruecke\n"
    assert call(svc, **begin(tid, transfer_id="unrelated"))["ok"]


@pytest.mark.parametrize("internal_name", [False, True])
def test_recovery_refuses_unrecognized_or_external_hardlinks(desk, tmp_path, internal_name):
    svc, tid = desk
    call(svc, **begin(tid))
    importer = LibraryImporter(svc.store)
    importer.blobs.mkdir()
    blob = importer.blobs / begin(tid)["sha256"]
    blob.write_bytes(b"wrong" if internal_name else b"Hallo Bruecke\n")
    extra = importer.blobs / f".{blob.name}.abcdefgh" if internal_name else tmp_path / "external"
    os.link(blob, extra)
    assert call(svc, action="status", transfer_id="test-upload-1")["code"] == "unsafe_store"
    assert call(svc, action="abort", transfer_id="test-upload-1")["code"] == "unsafe_store"
    assert extra.exists() and blob.stat().st_nlink == 2
