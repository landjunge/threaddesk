"""Real local stdio peer: knowledge/re-entry and operation recovery across restart."""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_real_stdio_knowledge_and_restart_receipt(tmp_path, backend):
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "THREADDESK_HOME": str(tmp_path),
        "THREADDESK_STORAGE": backend,
    }

    def exchange(process, request):
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        lines = []
        reader = threading.Thread(
            target=lambda: lines.append(process.stdout.readline()), daemon=True
        )
        reader.start()
        reader.join(timeout=10)
        if reader.is_alive():
            process.kill()
            reader.join(timeout=2)
            raise TimeoutError("isolated MCP peer did not answer within 10 seconds")
        return json.loads(lines[0])

    def peer():
        process = subprocess.Popen(
            [sys.executable, "-m", "threaddesk.ui.mcp_stdio"],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        response = exchange(
            process, {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}}
        )
        assert response["result"]["serverInfo"]["name"] == "threaddesk"
        process.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )
        process.stdin.flush()
        return process

    def call(process, name, arguments):
        response = exchange(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
        )
        assert not response["result"].get("isError"), response
        return json.loads(response["result"]["content"][0]["text"])

    def close(process):
        process.stdin.close()
        process.wait(timeout=10)
        assert process.returncode == 0, process.stderr.read()

    process = peer()
    try:
        created = call(
            process,
            "thread_manage",
            {
                "operation_id": "stdio-create",
                "expected_revision": 0,
                "action": "create",
                "data": {"title": "Synthetic stdio context"},
            },
        )
        request = {
            "operation_id": "stdio-remember",
            "id": created["thread_id"],
            "expected_revision": created["revision"],
            "action": "record",
            "data": {
                "kind": "decision",
                "status": "confirmed",
                "title": "Keep local",
                "source_ref": "Synthetic stdio",
                "source_revision": "message-1",
            },
        }
        remembered = call(process, "knowledge_manage", request)
    finally:
        close(process)
    process = peer()
    try:
        assert call(process, "knowledge_manage", request) == {
            **remembered,
            "duplicate": True,
        }
        value = call(process, "get_reentry", {"id": created["thread_id"]})
        assert value["decisions"][0]["id"] == remembered["node_id"]
        assert value["revision"] == remembered["revision"]
        assert value["sources"][0]["source_verification"] == "referenced_unverified"
        assert value["open_tasks"] == []
    finally:
        close(process)
