"""Exercise the real standalone MCP endpoint using disposable JSON/SQLite data.

No KiraBridge process, configuration or terminal is used. --server selects the
actual packaged ThreadDeskServer; otherwise the current source runs via stdio.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]


def digest(value):
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode()).hexdigest()


class Client:
    def __init__(self, argv, env):
        self.proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.messages = queue.Queue()
        self.sequence = 0
        self.notifications = []
        self.receipts = []

        def reader():
            for line in self.proc.stdout:
                try:
                    self.messages.put(json.loads(line))
                except ValueError:
                    self.messages.put({"invalid_stdout": line[:200]})
            self.messages.put({"eof": True})

        threading.Thread(target=reader, daemon=True).start()

    def rpc(self, method, params=None):
        self.sequence += 1
        request = {"jsonrpc": "2.0", "id": self.sequence, "method": method, "params": params or {}}
        self.proc.stdin.write(json.dumps(request) + "\n")
        self.proc.stdin.flush()
        while True:
            message = self.messages.get(timeout=30)
            if message.get("method"):
                self.notifications.append(message["method"])
                continue
            assert message.get("id") == self.sequence and "error" not in message, message
            return message["result"]

    def call(self, command, arguments, *, error=None, **bindings):
        tool = self.tools[command]
        result = self.rpc("tools/call", {"name": tool["name"], "arguments": {
            "workspace_id": self.workspace_id, "arguments": arguments, **bindings}})
        body = result.get("structuredContent") or json.loads(result["content"][0]["text"])
        if error:
            assert result["isError"] and body["code"] == error, body
            return body
        assert not result["isError"], body
        assert body["schema"] == "threaddesk.command-result.v1" and body["command"] == command, body
        assert "result" in body and digest(body["result"]) == body["result_digest"], body
        self.receipts.append({key: body[key] for key in ("command", "result_digest", "operation_id", "duplicate") if key in body})
        return body

    def close(self):
        self.proc.stdin.close()
        try:
            code = self.proc.wait(timeout=15)
            assert code == 0, self.proc.stderr.read()[-2000:]
        finally:
            if self.proc.poll() is None:
                self.proc.terminate()
                self.proc.wait(timeout=5)


def check(argv, backend, folder, *, packaged=False):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "THREADDESK_HOME": str(folder),
           "THREADDESK_STORAGE": backend, "PYTHONDONTWRITEBYTECODE": "1"}
    if packaged:
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
    client = Client(argv, env)
    try:
        hello = client.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                         "clientInfo": {"name": "threaddesk-acceptance", "version": "1"}})
        assert hello["capabilities"]["tools"]["listChanged"] is True
        client.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        client.proc.stdin.flush()
        tools = client.rpc("tools/list")["tools"]
        client.tools = {tool["_meta"]["threaddesk"]["id"]: tool for tool in tools
                        if "threaddesk" in tool.get("_meta", {})}
        assert not any(identity.startswith("search.") for identity in client.tools)
        assert "server_sync.owner_reference" not in client.tools
        client.workspace_id = client.tools["whiteboard.create"]["_meta"]["threaddesk"]["workspace_id"]
        create_args = {"title": "MCP acceptance board", "description": "Synthetic fixture"}
        created = client.call("whiteboard.create", create_args, operation_id="qa-create", expected_revision=0)
        thread = created["result"]["thread"]
        identity = thread["id"]
        assert client.call("whiteboard.create", create_args, operation_id="qa-create", expected_revision=0)["duplicate"]
        client.call("whiteboard.create", {"title": "Conflict"}, operation_id="qa-create", expected_revision=0,
                    error="operation_conflict")

        def board():
            return client.call("whiteboard.get", {"id": identity})["result"]

        def mutate(command, arguments=None, operation=None):
            return client.call(command, {"id": identity, **(arguments or {})},
                               operation_id=operation or "qa-" + command.replace(".", "-"),
                               expected_revision=board()["revision"])

        appended = mutate("whiteboard.append", {"actor": "Acceptance", "actor_type": "human",
                          "entry_type": "note", "content": "Original"})["result"]["entry"]
        mutate("whiteboard.edit", {"entry_id": appended["id"], "content": "Correction"})
        history = client.call("whiteboard.list", {"id": identity})["result"]["items"]
        assert [row["content"] for row in history] == ["Original", "Correction"]
        mutate("whiteboard.rename", {"title": "Renamed board"})
        client.call("whiteboard.rename", {"id": identity, "title": "Stale"}, operation_id="qa-stale",
                    expected_revision=thread["revision"], error="revision_conflict")
        states = []

        def graph(expected):
            current = board()
            result = client.call("graph.query", {"node_ids": [current["graph_node_id"]]})["result"]
            assert len(result["nodes"]) == 1, result
            node = result["nodes"][0]
            assert node["metadata"]["whiteboard_status"] == expected and node["title"] == "Renamed board", node
            states.append({"state": expected, "node_id": node["id"], "revision": node["revision"]})

        mutate("whiteboard.close")
        graph("closed")
        mutate("whiteboard.open")
        graph("open")
        mutate("whiteboard.archive")
        graph("archived")
        mutate("whiteboard.unarchive")
        graph("open")
        preview = client.call("whiteboard.delete_preview", {"id": identity})["result"]
        assert preview["external_originals_preserved"] and preview["lifecycle_scope"] == "owning_thread"
        client.call("whiteboard.delete", {"id": identity}, operation_id="qa-no-confirm",
                    expected_revision=board()["revision"], error="validation_error")
        deleted = mutate("whiteboard.delete", {"confirm_thread_move": True})["result"]["entry"]
        hidden = client.call("graph.query", {"node_ids": ["wb-" + identity]})["result"]
        assert hidden["nodes"] == []
        purge = client.call("trash.purge_preview", {"trash_id": deleted["trash_id"]})["result"]
        client.call("trash.purge", {"trash_id": deleted["trash_id"], "generation": deleted["generation"],
                    "reference_digest": purge["reference_digest"], "confirmation": "unapproved"},
                    operation_id="qa-reject-purge", expected_revision=deleted["revision"], error="explicit_confirmation_required")
        client.call("whiteboard.restore", {"trash_id": deleted["trash_id"], "generation": deleted["generation"]},
                    operation_id="qa-restore", expected_revision=deleted["revision"])
        graph("open")
        restored = client.call("whiteboard.list", {"id": identity})["result"]["items"]
        assert [row["id"] for row in restored] == [row["id"] for row in history]
        return {"backend": backend, "passed": True, "tools": len(tools), "registered_available": len(client.tools),
                "graph_states": states, "receipts": client.receipts,
                "purge_without_approval": "rejected", "restore_ids": "preserved"}
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    argv = [str(args.server.resolve()), "--mcp"] if args.server else [sys.executable, "-m", "threaddesk.ui.mcp_stdio"]
    with tempfile.TemporaryDirectory(prefix="td-mcp-whiteboards-") as temporary:
        results = [check(argv, backend, Path(temporary) / backend, packaged=bool(args.server))
                   for backend in ("json", "sqlite")]
    report = {"endpoint": "packaged" if args.server else "source", "checks": results,
              "kirabridge": "not controlled or modified; standalone MCP proof only"}
    if args.server:
        report["executable_sha256"] = hashlib.sha256(args.server.read_bytes()).hexdigest()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"endpoint": report["endpoint"], "report": str(args.report) if args.report else None,
                      "checks": [{"backend": row["backend"], "passed": row["passed"],
                                  "tools": row["tools"], "registered_available": row["registered_available"],
                                  "verified_result_digests": len(row["receipts"]),
                                  "graph_states": [state["state"] for state in row["graph_states"]],
                                  "restore_ids": row["restore_ids"],
                                  "purge_without_approval": row["purge_without_approval"]}
                                 for row in results]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
