"""Isolated real CLI acceptance; suitable for an authorized visible bridge task.

Every domain operation runs in a fresh CLI process and is independently read
back. No test mutates the operator's ThreadDesk workspace or original files.
Principal and visible-terminal evidence belong to the actual bridge receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


class Client:
    def __init__(self, root, binary=None):
        self.root, self.binary, self.calls = root, binary, []
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        self.env = {**os.environ, "THREADDESK_HOME": str(self.workspace), "THREADDESK_STORAGE": "json",
                    "PYTHONDONTWRITEBYTECODE": "1"}
        self.workspace_id = self.catalog()["workspace_id"]

    def process(self, argv):
        done = subprocess.run(argv, env=self.env, text=True, capture_output=True, timeout=60)
        try:
            data = json.loads(done.stdout)
        except (ValueError, TypeError):
            raise AssertionError({"exit": done.returncode, "output": done.stdout[-2000:], "error": done.stderr[-2000:]})
        assert len(done.stdout.encode()) < 30000, "CLI response exceeded bridge page budget"
        return done.returncode, data

    def catalog(self):
        argv = [self.binary, "--command-catalog"] if self.binary else [sys.executable, "-m", "threaddesk.ui.cli", "command", "--catalog"]
        code, data = self.process(argv)
        assert code == 0 and data["ok"], data
        return data

    def call(self, command, arguments=None, *, operation=None, revision=None, error=None):
        request = {"version": 1, "workspace_id": self.workspace_id, "command": command, "arguments": arguments or {}}
        if operation is not None:
            request["operation_id"] = operation
        if revision is not None:
            request["expected_revision"] = revision
        path = self.root / "request.json"
        path.write_text(json.dumps(request, ensure_ascii=False))
        path.chmod(0o600)
        argv = ([self.binary, "--command-file", str(path)] if self.binary else
                [sys.executable, "-m", "threaddesk.ui.cli", "command", "--request-file", str(path)])
        started = time.monotonic()
        code, data = self.process(argv)
        self.calls.append({"command": command, "request": request, "exit_code": code,
                           "response": data, "elapsed_ms": round((time.monotonic() - started) * 1000, 1)})
        if error:
            assert code == 2 and data.get("code") == error, data
            return data
        assert code == 0 and data["ok"] and "result" in data, data
        return data["result"]


def run(root, *, binary=None, open_text=False):
    client = Client(root, binary)
    catalogue, offset = [], 0
    while offset is not None:
        result = client.call("command.catalog", {"limit": 10, "offset": offset})
        catalogue.extend(result["commands"])
        offset = result["next_offset"]
    create = {"action": "create", "data": {"title": "ThreadDesk workspace acceptance"}}
    first = client.call("thread_manage", create, operation="create-one", revision=0)["thread"]
    repeated = client.call("thread_manage", create, operation="create-one", revision=0)
    assert repeated["thread"]["id"] == first["id"]
    client.call("thread_manage", {"action": "create", "data": {"title": "Different request"}},
                operation="create-one", revision=0, error="operation_conflict")
    identity = first["id"]
    note = {"action": "set_note", "id": identity, "data": {"text": "Preserve the first saved note"}}
    saved = client.call("thread_manage", note, operation="note-one", revision=first["revision"])["thread"]
    client.call("thread_manage", {**note, "data": {"text": "Stale overwrite must fail"}},
                operation="note-stale", revision=first["revision"], error="revision_conflict")
    assert "Preserve the first" in client.call("get_thread", {"id": identity})["notes"]
    board = client.call("whiteboard.append", {"id": identity, "actor": "Acceptance operator", "actor_type": "human",
                                              "entry_type": "note", "content": "CLI whiteboard readback"},
                        operation="board-one", revision=saved["revision"])
    assert board["entry"]["content"] == "CLI whiteboard readback"
    assert client.call("whiteboard.list", {"id": identity})["total"] == 1
    client.call("whiteboard.stand", {"id": identity})
    current = client.call("get_thread", {"id": identity})
    snapshot = client.call("thread_manage", {"action": "snapshot", "id": identity, "data": {"label": "Before change"}},
                           operation="snapshot-one", revision=current["revision"])["snapshot"]
    current = client.call("get_thread", {"id": identity})
    changed = client.call("thread_manage", {"action": "set_note", "id": identity, "data": {"text": "Later note"}},
                          operation="note-two", revision=current["revision"])["thread"]
    client.call("restore_snapshot", {"snap_id": snapshot["id"]}, operation="restore-snapshot", revision=changed["revision"])
    assert "Preserve the first" in client.call("get_thread", {"id": identity})["notes"]
    project = client.call("graph.node.create", {"kind": "project", "title": "Bridge acceptance project", "metadata": {"thread_id": identity}},
                          operation="project-one", revision=0)
    task = client.call("graph.node.create", {"kind": "task", "title": "Bridge acceptance task"}, operation="task-one", revision=0)
    relation_args = {"source_id": project["id"], "target_id": task["id"], "kind": "contains", "expected_target_revision": task["revision"]}
    relation = client.call("graph.relation.create", relation_args, operation="relation-one", revision=project["revision"])
    assert client.call("graph.relations", {"id": project["id"]})["items"][0]["id"] == relation["id"]
    source = root / "originals"; source.mkdir()
    original = source / "ThreadDesk-WorkspaceTest.txt"
    original.write_text("Gültige Größe: workspacecontentneedle first version", encoding="utf-8")
    imported = client.call("library_manage", {"action": "import", "data": {"source": str(source), "thread_id": identity, "node_id": project["id"]}}, operation="files-one")
    assert imported["complete"]
    record_id = imported["files"][0]["record_id"]
    assert client.call("library_query", {"action": "search", "query": "workspacecontentneedle"})["hits"]
    assert client.call("library_query", {"action": "search", "query": "WorkspaceTest"})["hits"]
    assert client.call("library_query", {"action": "preview", "id": record_id})
    assert client.call("activity.files", {"record_ids": [record_id]})["files"][record_id] == {}
    if open_text:
        info = client.call("library_query", {"action": "info", "id": record_id})
        receipt = client.call("library_manage", {"action": "open", "id": record_id, "expected_revision": info["revision"]}, operation="open-text", revision=info["revision"])
        assert receipt["status"] == "launch_requested", receipt
        assert client.call("library_query", {"action": "operation", "operation_id": "open-text"})["result"]["status"] == "launch_requested"
        assert client.call("activity.files", {"record_ids": [record_id]})["files"][record_id]["accessed"]["human_read_confirmed"] is False
    original.write_text("Gültige Größe: workspacecontentneedle changed original", encoding="utf-8")
    original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    client.call("library_manage", {"action": "refresh_sources"}, operation="source-refresh")
    records = client.call("library_query", {"action": "list", "node_id": project["id"]})["records"]
    fresh = next(row for row in records if row.get("predecessor_record_id") == record_id)
    activities = client.call("activity.files", {"record_ids": [fresh["id"]]})
    assert activities["files"][fresh["id"]]["modified"]["sha256"] == original_hash
    graph = client.call("graph.query", {"mode": "work", "limit": 10})
    assert graph["schema"] == "threaddesk.graph.v2" and graph["activity_revision"] > 0
    view_request = {"action": "save", "id": "acceptance-view", "data": {"title": "Acceptance view", "state": {"camera": {"x": 0, "y": 0, "scale": 1}, "positions": {}, "filters": {"mode": "work"}, "selection": [project["id"]]}}}
    view = client.call("graph_view.manage", view_request, operation="save-view", revision=0)["view"]
    assert client.call("graph_view.get", {"id": view["id"]})["state"]["filters"]["mode"] == "work"
    client.call("graph_view.manage", view_request, operation="save-view", revision=0)
    client.call("graph_view.manage", {**view_request, "data": {"title": "Stale view", "state": {}}},
                operation="save-view-stale", revision=0, error="revision_conflict")
    moved = client.call("trash.move", {"kind": "node", "object_id": task["id"]}, operation="trash-task", revision=task["revision"])["entry"]
    assert not any(n["id"] == task["id"] for n in client.call("graph.query", {"limit": 10})["nodes"])
    restored = client.call("trash.restore", {"trash_id": moved["trash_id"], "generation": moved["generation"]},
                           operation="restore-task", revision=moved["revision"])
    assert restored["entry"]["object_id"] == task["id"]
    assert client.call("graph.node", {"id": task["id"]})["id"] == task["id"]
    assert client.call("graph.relations", {"id": project["id"]})["items"][0]["id"] == relation["id"]
    current = client.call("get_thread", {"id": identity})
    moved = client.call("trash.move", {"kind": "thread", "object_id": identity}, operation="trash-thread", revision=current["revision"])["entry"]
    client.call("trash.get", {"trash_id": moved["trash_id"]})
    client.call("get_thread", {"id": identity}, error="object_in_trash")
    client.call("trash.restore", {"trash_id": moved["trash_id"], "generation": moved["generation"]},
                operation="restore-thread", revision=moved["revision"])
    assert client.call("whiteboard.list", {"id": identity})["total"] == 1
    assert client.call("command.operation", {"operation_id": "restore-thread"})["state"] == "complete"
    assert hashlib.sha256(original.read_bytes()).hexdigest() == original_hash
    report = {"fixture_only": True, "principal_identity": "take from actual bridge task evidence",
              "catalogue_commands": len(catalogue), "commands": client.calls, "open_text_requested": open_text,
              "original_preserved": True, "thread_id": identity, "file_id": fresh["id"], "ok": True}
    path = root / "workspace-command-result.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    path.chmod(0o600)
    print(json.dumps({"ok": True, "calls": len(client.calls), "catalogue_commands": len(catalogue), "fixture_only": True,
                      "original_preserved": True, "open_text_requested": open_text, "report": str(path)}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True)
    parser.add_argument("--command-binary")
    parser.add_argument("--open-text", action="store_true")
    args = parser.parse_args()
    root = Path(args.directory).resolve()
    root.mkdir(mode=0o700)
    run(root, binary=args.command_binary, open_text=args.open_text)


if __name__ == "__main__":
    main()
