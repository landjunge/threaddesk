"""Independent real HTTP/CLI acceptance of isolated operational commands."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest

from http_ui_client import UIClient
from threaddesk.api.service import ThreadService
from threaddesk.services.mcp import McpBridge
from threaddesk.services.tollgate import POLICY_INTS
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.ui.server import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def operations(request, tmp_path, monkeypatch):
    home = tmp_path / "bound-workspace"
    monkeypatch.setenv("THREADDESK_HOME", str(home))
    monkeypatch.setenv("THREADDESK_STORAGE", "sqlite" if request.param is SQLiteStore else "json")
    svc = ThreadService(request.param(home))
    client = UIClient(create_app())
    yield svc, client, home
    if hasattr(svc.store, "connection"):
        svc.store.connection.close()


def envelope(client, command, arguments=None, **fields):
    catalog = client.get("/api/commands/catalog?limit=1")
    assert catalog.status_code == 200
    return {"version": 1, "workspace_id": catalog.json()["workspace_id"],
            "command": command, "arguments": arguments or {}, **fields}


def http_command(client, command, arguments=None, **fields):
    response = client.post("/api/commands", json=envelope(client, command, arguments, **fields))
    assert response.status_code == 200, response.text
    assert response.json()["ok"], response.text
    return response.json()


def cli(home, *arguments):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "THREADDESK_HOME": str(home),
           "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, "-m", "threaddesk.ui.cli", *arguments], cwd=ROOT,
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def test_gate_published_policy_matches_real_set_status_and_freeze(operations):
    svc, client, _home = operations
    desired = {key: 20 + index for index, key in enumerate(POLICY_INTS)}
    desired["cooldown_seconds"] = 0
    first = http_command(client, "gate.set", desired, operation_id="policy-first")["result"]
    for key, value in desired.items():
        assert first["policy"][key] == value
    assert http_command(client, "gate.status")["result"]["policy"] == svc.gate()["policy"]
    frozen = http_command(client, "gate.freeze", {"frozen": True}, operation_id="freeze-first")["result"]
    assert frozen["frozen"] and svc.gate()["frozen"]
    replay = http_command(client, "gate.freeze", {"frozen": True}, operation_id="freeze-first")
    assert replay["duplicate"]
    assert http_command(client, "gate.freeze", {"frozen": False}, operation_id="unfreeze-first")["result"]["frozen"] is False
    invalid = client.post("/api/commands", json=envelope(client, "gate.set", {"max_execute_day": -1}, operation_id="invalid-policy"))
    assert invalid.status_code == 400 and invalid.json()["code"] == "validation_error"
    assert svc.gate()["policy"]["max_execute_day"] == desired["max_execute_day"]


def test_backup_verify_restore_profile_switches_preserve_bound_original(operations, tmp_path, monkeypatch):
    svc, client, home = operations
    thread = svc.create("Bound original")
    svc.set_note("Original context retained", thread.id)
    # A deliberately different environment base cannot redirect the bound
    # operational implementation into another profile tree.
    unrelated = tmp_path / "unrelated-base"
    unrelated.mkdir()
    import threaddesk.storage.portable_backup as portable
    monkeypatch.setattr(portable, "base_root", lambda: unrelated)
    # HTTP's service factory must still use the explicit isolated workspace.
    from threaddesk.ui import server
    monkeypatch.setattr(server, "_svc", lambda: ThreadService(type(svc.store)(home)))
    created = http_command(client, "backup.create", operation_id="backup-create")["result"]
    body = client.get(created["download_path"])
    assert body.status_code == 200
    assert hashlib.sha256(body.content).hexdigest() == created["sha256"]
    verified = http_command(client, "backup.verify", {"path": created["path"]})["result"]
    assert verified["verified"] and verified["sha256"] == created["sha256"]
    restored = http_command(client, "backup.restore", {"path": created["path"], "sha256": created["sha256"],
                            "confirmation": "restore_as_new_profile"}, operation_id="backup-restore")["result"]
    restored_home = Path(restored["profile_path"])
    assert restored_home.parent == home / "profiles"
    restored_store = type(svc.store)(restored_home)
    assert restored_store.get_thread(thread.id).context.notes == "Original context retained"
    if hasattr(restored_store, "connection"):
        restored_store.connection.close()
    assert not list(unrelated.iterdir())
    # Use the public CLI to obtain a fresh service for the newly selected
    # profile, then explicitly return and activate it again.
    # Restore's selector belongs to the bound root, so reset the test-only
    # service/environment redirection before invoking a fresh CLI process.
    listings = cli(home, "command", "--catalog", "--limit", "1")[-1]
    selected_workspace = listings["workspace_id"]
    request = {"version": 1, "workspace_id": selected_workspace, "command": "profiles.original", "arguments": {}, "operation_id": "return-original"}
    back = cli(home, "command", "--request", json.dumps(request))[-1]
    assert back["ok"] and back["result"]["restored_profile"] is False
    original_catalog = cli(home, "command", "--catalog", "--limit", "1")[-1]
    activate = {"version": 1, "workspace_id": original_catalog["workspace_id"], "command": "profiles.activate",
                "arguments": {"name": restored_home.name}, "operation_id": "activate-restored"}
    assert cli(home, "command", "--request", json.dumps(activate))[-1]["result"]["active"] == restored_home.name
    assert svc.store.get_thread(thread.id).context.notes == "Original context retained"
    assert not list(unrelated.iterdir())


@pytest.mark.parametrize("format_name", ["json", "markdown", "csv", "xlsx", "svg", "pdf", "zip"])
def test_export_artifacts_have_expected_bytes_and_protected_download(operations, format_name):
    svc, client, _home = operations
    node = svc.create_node("project", "Export proof", details="Exact export context", visibility="shared")
    result = http_command(client, "export.write", {"node_ids": [node.id], "format": format_name, "language": "en"},
                          operation_id="export-" + format_name)["result"]
    download = client.get(result["download_path"])
    assert download.status_code == 200
    body = download.content
    assert len(body) == result["size"]
    assert hashlib.sha256(body).hexdigest() == result["sha256"]
    assert "attachment" in download.headers["content-disposition"]
    assert download.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in download.headers["content-security-policy"]
    assert result["executed"] is False
    if format_name == "json":
        assert node.id in json.dumps(json.loads(body))
    elif format_name == "markdown":
        assert "Export proof" in body.decode()
    elif format_name == "csv":
        rows = list(csv.DictReader(io.StringIO(body.decode("utf-8-sig"))))
        assert any(row["id"] == node.id for row in rows)
    elif format_name == "xlsx":
        with ZipFile(io.BytesIO(body)) as archive:
            assert "[Content_Types].xml" in archive.namelist()
    elif format_name == "svg":
        assert ElementTree.fromstring(body).tag.endswith("svg")
    elif format_name == "pdf":
        assert body.startswith(b"%PDF-")
    else:
        with ZipFile(io.BytesIO(body)) as archive:
            assert archive.testzip() is None
            assert any(name.endswith(".json") for name in archive.namelist())
    # The digest in the published filename is checked on every download.
    Path(result["path"]).write_bytes(body + b"tampered")
    rejected = client.get(result["download_path"])
    assert rejected.status_code == 409 and rejected.json()["code"] == "artifact_conflict"


def test_owner_search_real_cli_works_but_http_and_mcp_refuse(operations):
    svc, client, home = operations
    thread = svc.create("Local owner search")
    svc.set_note("OwnerOnlyNeedle preserved locally", thread.id)
    workspace = cli(home, "command", "--catalog", "--limit", "1")[-1]["workspace_id"]
    def request(command, arguments, operation=None):
        body = {"version": 1, "workspace_id": workspace, "command": command, "arguments": arguments}
        if operation:
            body["operation_id"] = operation
        return cli(home, "command", "--request", json.dumps(body))[-1]
    assert request("search.configure", {"enabled": True}, "enable-owner")["result"]["enabled"]
    request("search.rebuild", {"batches": 100}, "build-owner")
    found = request("search.query", {"query": "OwnerOnlyNeedle", "pages": 20})["result"]
    assert any(hit["thread_id"] == thread.id for page in found["pages"] for hit in page["hits"])
    incoming = {"version": 1, "workspace_id": workspace, "command": "search.query", "arguments": {"query": "OwnerOnlyNeedle"}}
    http = client.post("/api/commands", json=incoming)
    assert http.status_code in {400, 403}
    assert http.json()["code"] == "local_owner_cli_required"
    mcp = McpBridge(svc).call("command_query", incoming)
    assert not mcp["ok"] and mcp["code"] == "local_owner_cli_required"
    assert not any(row.get("thread_id") == thread.id for row in http.json().get("hits", []))


def test_large_http_result_pages_reconstruct_without_writes(operations):
    svc, client, _home = operations
    thread = svc.create("Paged HTTP context")
    svc.set_note("Unicode ÄÖÜ content " * 4000, thread.id)
    before = svc.store.get_thread(thread.id).revision
    response = http_command(client, "get_thread", {"id": thread.id})
    assert "result_page" in response
    fragments = [response["result_page"]]
    while response["next_offset"] is not None:
        response = http_command(client, "get_thread", {"id": thread.id},
                                result_offset=response["next_offset"], result_digest=response["result_digest"])
        assert len(json.dumps(response, ensure_ascii=False).encode()) < 30000
        fragments.append(response["result_page"])
    assert "Unicode ÄÖÜ content" in json.loads("".join(fragments))["notes"]
    assert svc.store.get_thread(thread.id).revision == before


def test_large_export_preview_pages_use_a_stable_read_snapshot(operations):
    svc, client, _home = operations
    node = svc.create_node("project", "Large preview", details="Long exported description " * 2000, visibility="shared")
    args = {"node_ids": [node.id]}
    response = http_command(client, "export.preview", args)
    assert "result_page" in response
    assert isinstance(response.get("snapshot_at"), str)
    fragments = [response["result_page"]]
    while response["next_offset"] is not None:
        response = http_command(client, "export.preview", args,
                                result_offset=response["next_offset"], result_digest=response["result_digest"],
                                snapshot_at=response["snapshot_at"])
        fragments.append(response["result_page"])
    assert node.id in json.dumps(json.loads("".join(fragments)))
