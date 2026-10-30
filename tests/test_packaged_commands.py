"""Both actual package entrypoints expose the same structured public CLI."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("entry", ["packaging/desktop_entry.py", "packaging/tauri/backend/server.py"])
def test_package_entry_mcp_serves_discovery_without_starting_desktop(tmp_path, entry):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "THREADDESK_HOME": str(tmp_path / "workspace"),
           "THREADDESK_STORAGE": "json", "PYTHONDONTWRITEBYTECODE": "1"}
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    completed = subprocess.run(
        [sys.executable, str(ROOT / entry), "--mcp"], cwd=ROOT, env=env,
        input="".join(json.dumps(request) + "\n" for request in requests),
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    replies = {row["id"]: row for line in completed.stdout.splitlines()
               if (row := json.loads(line)).get("id") is not None}
    assert replies[1]["result"]["serverInfo"]["name"] == "threaddesk"
    tools = replies[2]["result"]["tools"]
    assert any(tool["name"] == "command_catalog" for tool in tools)
    assert any(tool.get("_meta", {}).get("threaddesk", {}).get("command_id") == "graph.query"
               or tool["name"].startswith("td_graph") for tool in tools)
    assert not (tmp_path / "workspace" / "desktop-port.json").exists()


@pytest.mark.parametrize("entry", ["packaging/desktop_entry.py", "packaging/tauri/backend/server.py"])
def test_package_entry_catalogue_query_and_workspace_error_exit(tmp_path, entry):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "THREADDESK_HOME": str(tmp_path / "workspace"),
           "THREADDESK_STORAGE": "json", "PYTHONDONTWRITEBYTECODE": "1"}
    def run(*args):
        result = subprocess.run([sys.executable, str(ROOT / entry), *args], env=env, cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        assert len(result.stdout.encode()) < 30000
        return result.returncode, json.loads(result.stdout)
    code, catalog = run("--command-catalog")
    assert code == 0 and catalog["ok"] and catalog["workspace_id"].startswith("ws-")
    request = {"version": 1, "workspace_id": catalog["workspace_id"], "command": "graph.change_status", "arguments": {}}
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request))
    code, response = run("--command-file", str(path))
    assert code == 0 and response["ok"] and response["result"]["status"] == "ready"
    assert response["result"]["workspace_id"] == catalog["workspace_id"]
    code, error = run("--command", json.dumps({**request, "workspace_id": "ws-unrelated"}))
    assert code == 2 and error["code"] == "workspace_mismatch"
    assert not (tmp_path / "workspace" / "desktop-port.json").exists()
