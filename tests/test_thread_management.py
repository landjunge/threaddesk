"""M1 V01/V02/V04: isolated workspaces, no agent process or real thread."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.services.mcp import McpBridge
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.ui.mcp_stdio import handle


@pytest.fixture(params=[JsonStore, SQLiteStore])
def bridge(request, tmp_path):
    return McpBridge(ThreadService(request.param(tmp_path)))


def mutation(bridge, operation, action, thread=None, data=None):
    args = {"operation_id": operation, "action": action, "expected_revision": thread["revision"] if thread else 0, "data": data or {}}
    if thread:
        args["id"] = thread["id"]
    result = bridge.call("thread_manage", args)
    assert result["ok"], result
    return result["result"]


def test_complete_lifecycle_and_exact_repetition(bridge):
    events = []
    bridge.svc.bus.on("*", lambda name, _: events.append(name))
    created = mutation(bridge, "create-1", "create", data={"title": "Synthetic M1", "description": "Only test context"})
    thread = created["thread"]
    assert thread["revision"] == 1
    duplicate = mutation(bridge, "create-1", "create", data={"title": "Synthetic M1", "description": "Only test context"})
    assert duplicate["duplicate"] and duplicate["thread_id"] == thread["id"]
    assert len(bridge.svc.list()) == 1
    thread = mutation(bridge, "edit-1", "update", thread, {"title": "Synthetic changed", "status": "active"})["thread"]
    thread = mutation(bridge, "note-1", "set_note", thread, {"text": "No instruction to execute"})["thread"]
    thread = mutation(bridge, "note-2", "set_note", thread, {"text": "second", "append": True})["thread"]
    assert "second" in thread["notes"]
    thread = mutation(bridge, "file-1", "add_file", thread, {"path": "reference-only.md"})["thread"]
    assert thread["files"] == ["reference-only.md"]
    parent = mutation(bridge, "parent-1", "create", data={"title": "Parent"})["thread"]
    project = bridge.svc.create_node("project", "Synthetic project")
    thread = mutation(bridge, "org-1", "organize", thread, {"project_id": project.id, "parent_thread_id": parent["id"], "related_thread_ids": [parent["id"]]})["thread"]
    assert thread["organization"]["project_id"] == project.id
    thread = mutation(bridge, "remove-1", "remove_file", thread, {"path": "reference-only.md"})["thread"]
    mutation(bridge, "switch-1", "switch", thread)
    assert bridge.call("current_thread")["result"]["id"] == thread["id"]
    denied = bridge.call("thread_manage", {"operation_id": "early-delete", "action": "delete", "id": thread["id"], "expected_revision": thread["revision"]})
    assert denied["code"] == "invalid_state"
    thread = mutation(bridge, "archive-1", "archive", thread)["thread"]
    thread = mutation(bridge, "restore-1", "unarchive", thread)["thread"]
    assert thread["status"] == "paused"
    thread = mutation(bridge, "archive-2", "archive", thread)["thread"]
    deleted = mutation(bridge, "delete-1", "delete", thread)
    assert deleted["deleted"] and deleted["thread"] is None
    again = mutation(bridge, "delete-1", "delete", thread)
    assert again["duplicate"]
    assert not bridge.call("get_thread", {"id": thread["id"]})["ok"]
    assert not any(name in {"grok.packet", "gnom.packet", "handoff.written"} for name in events)


def test_snapshot_is_idempotent_and_listed_for_thread(bridge):
    thread = mutation(bridge, "snapshot-thread", "create", data={"title": "Snapshot"})["thread"]
    first = mutation(bridge, "snapshot-before-edit", "snapshot", thread, {"label": "Before edit"})
    duplicate = mutation(bridge, "snapshot-before-edit", "snapshot", thread, {"label": "Before edit"})

    assert first["snapshot_id"] == duplicate["snapshot_id"]
    assert duplicate["duplicate"] is True
    listed = bridge.call("list_snapshots", {"id": thread["id"]})["result"]
    assert [item["id"] for item in listed] == [first["snapshot_id"]]


def test_graph_snapshot_restore_is_idempotent(bridge):
    thread = mutation(bridge, "restore-thread", "create", data={"title": "Graph restore"})["thread"]
    project = bridge.svc.create_node(
        "project", "Before", metadata={"thread_id": thread["id"]}
    )
    snapshot = mutation(bridge, "save-graph-snapshot", "snapshot", thread)
    project.title = "After"
    project.revision += 1
    bridge.svc.store.save_node(project)
    current = bridge.svc.get(thread["id"])

    restored = mutation(
        bridge,
        "restore-graph-snapshot",
        "restore_snapshot",
        current.to_dict(),
        {"snapshot_id": snapshot["snapshot_id"]},
    )
    duplicate = mutation(
        bridge,
        "restore-graph-snapshot",
        "restore_snapshot",
        current.to_dict(),
        {"snapshot_id": snapshot["snapshot_id"]},
    )

    assert bridge.svc.get_node(project.id).title == "Before"
    assert duplicate["duplicate"] is True
    assert restored["snapshot_id"] == snapshot["snapshot_id"]


def test_stale_legacy_edit_and_operation_collision(bridge):
    first = mutation(bridge, "first", "create", data={"title": "Synthetic"})["thread"]
    bridge.svc.rename(first["id"], "From existing UI/CLI")
    denied = bridge.call("thread_manage", {"operation_id": "stale", "action": "set_note", "id": first["id"], "expected_revision": first["revision"], "data": {"text": "Must not replace"}})
    assert denied["code"] == "revision_conflict"
    assert denied["details"]["actual_revision"] == first["revision"] + 1
    collision = bridge.call("thread_manage", {"operation_id": "first", "action": "create", "expected_revision": 0, "data": {"title": "Different"}})
    assert collision["code"] == "operation_conflict"
    assert bridge.svc.get(first["id"]).context.notes == ""
    current = bridge.svc.get(first["id"])
    old = bridge.svc.get(first["id"])
    current.title = "New"
    bridge.svc.store.save_thread(current)
    old.title = "Stale"
    with pytest.raises(ManagementError):
        bridge.svc.store.save_thread(old)


def test_strict_fields_foreign_ids_and_cycles(bridge):
    thread = mutation(bridge, "new", "create", data={"title": "Synthetic"})["thread"]
    base = {"operation_id": "bad", "action": "update", "expected_revision": thread["revision"], "id": thread["id"], "data": {"title": "X"}}
    for patch in [{"owner": "other"}, {"expected_revision": True}, {"data": {"execute": True}}, {"id": "../outside"}, {"data": {"status": 1}}, {"action": "execute"}]:
        assert bridge.call("thread_manage", {**base, **patch})["code"] == "validation_error"
    assert bridge.call("thread_manage", {**base, "id": "foreign-thread"})["code"] == "not_found"
    assert bridge.call("thread_manage", {**base, "action": "organize", "data": {"parent_thread_id": thread["id"]}})["code"] == "validation_error"
    assert bridge.call("thread_manage", {**base, "action": "organize", "data": {"parent_thread_id": "missing"}})["code"] == "not_found"
    child = mutation(bridge, "child", "create", data={"title": "Child", "parent_thread_id": thread["id"]})["thread"]
    assert bridge.call("thread_manage", {**base, "action": "organize", "data": {"parent_thread_id": child["id"]}})["code"] == "validation_error"
    # Failed multi-field mutation rolls back even its first successful field.
    assert bridge.call("thread_manage", {**base, "data": {"title": "Must rollback", "status": "invalid"}})["code"] == "invalid_state"
    assert bridge.svc.get(thread["id"]).title == "Synthetic"


def test_receipt_survives_process_reopen(bridge):
    expected = mutation(bridge, "persistent-create", "create", data={"title": "Synthetic"})
    reopened = McpBridge(ThreadService(type(bridge.svc.store)(bridge.svc.store.root)))
    actual = mutation(reopened, "persistent-create", "create", data={"title": "Synthetic"})
    assert actual["duplicate"] and actual["thread_id"] == expected["thread_id"]
    rpc = handle(reopened, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "thread_manage", "arguments": {"operation_id": "persistent-create", "action": "create", "expected_revision": 0, "data": {"title": "Collision"}}}})
    assert json.loads(rpc["result"]["content"][0]["text"])["code"] == "operation_conflict"


def test_json_recovery_replays_state_not_mutation(tmp_path, monkeypatch):
    bridge = McpBridge(ThreadService(JsonStore(tmp_path)))
    original = bridge.svc.store._atomic_json
    count = 0
    def power_loss(path, data):
        nonlocal count
        original(path, data)
        count += 1
        if count == 2:
            raise OSError("synthetic interruption after commit plan and first data write")
    monkeypatch.setattr(bridge.svc.store, "_atomic_json", power_loss)
    interrupted = bridge.call("thread_manage", {"operation_id": "crash-create", "action": "create", "expected_revision": 0, "data": {"title": "Recover once"}})
    assert interrupted["isError"] and (tmp_path / ".management-commit.json").exists()
    reopened = McpBridge(ThreadService(JsonStore(tmp_path)))
    recovered = mutation(reopened, "crash-create", "create", data={"title": "Recover once"})
    assert recovered["duplicate"] and len(reopened.svc.list()) == 1
    assert not (tmp_path / ".management-commit.json").exists()


@pytest.mark.parametrize("store_type", [JsonStore, SQLiteStore])
def test_concurrent_identical_create_once(tmp_path, store_type):
    def worker(_):
        return mutation(McpBridge(ThreadService(store_type(tmp_path))), "parallel-create", "create", data={"title": "Only one"})
    # Establish schema before racing application requests, as normal startup does.
    store_type(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(worker, range(4)))
    assert len({item["thread_id"] for item in results}) == 1
    assert sum(not item["duplicate"] for item in results) == 1
    assert len(store_type(tmp_path).list_threads()) == 1


def test_json_to_sqlite_preserves_receipt_and_revision(tmp_path):
    from threaddesk.storage.json_migration import migrate_json_store
    source = JsonStore(tmp_path / "source")
    original = mutation(McpBridge(ThreadService(source)), "before-migration", "create", data={"title": "Preserve"})
    target = SQLiteStore(tmp_path / "target")
    migrate_json_store(source, target)
    repeated = mutation(McpBridge(ThreadService(target)), "before-migration", "create", data={"title": "Preserve"})
    assert repeated["duplicate"] and repeated["revision"] == original["revision"]
    assert len(target.list_threads()) == 1


def test_old_json_writer_changes_are_detected_at_legacy_revision_zero(tmp_path):
    path = tmp_path / "threads" / "legacy.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"id": "legacy", "title": "Old", "context": {"notes": "before"}}))
    bridge = McpBridge(ThreadService(JsonStore(tmp_path)))
    first = bridge.call("get_thread", {"id": "legacy"})["result"]
    assert first["revision"] == 0
    assert "revision" not in json.loads(path.read_text())  # Read preserves legacy source.
    # Simulate desktop0.1.1 writer dropping every unknown field.
    old = json.loads(path.read_text())
    old["context"]["notes"] = "Written by old app"
    old.pop("revision", None)
    path.write_text(json.dumps(old))
    stale = bridge.call("thread_manage", {"operation_id": "legacy-stale", "action": "set_note", "id": "legacy", "expected_revision": 0, "data": {"text": "Must not overwrite"}})
    assert stale["code"] == "revision_conflict"
    assert stale["details"]["actual_revision"] == 1
    assert bridge.call("get_thread", {"id": "legacy"})["result"]["revision"] == 1
    assert bridge.svc.get("legacy").context.notes == "Written by old app"


def test_read_receipt_after_lost_response_without_reexecution(bridge):
    missing = bridge.call("thread_operation_status", {"operation_id": "known-operation"})["result"]
    assert missing == {"operation_id": "known-operation", "found": False, "result": None}
    made = mutation(bridge, "known-operation", "create", data={"title": "Once"})
    receipt = bridge.call("thread_operation_status", {"operation_id": "known-operation"})["result"]
    assert receipt["found"] and receipt["result"] == made
    assert "<untrusted" in receipt["result"]["thread"]["notes"]
    assert len(bridge.svc.list()) == 1
    assert bridge.call("thread_operation_status", {"operation_id": "../unsafe"})["code"] == "validation_error"


def test_portable_json_backup_keeps_operation_receipt(tmp_path):
    from threaddesk.storage.portable_backup import download_backup, restore_backup
    source = JsonStore(tmp_path / "source")
    expected = mutation(McpBridge(ThreadService(source)), "backup-create", "create", data={"title": "Backup"})
    restored_root = restore_backup(download_backup(source), tmp_path / "restored-home")
    restored = McpBridge(ThreadService(JsonStore(restored_root)))
    actual = mutation(restored, "backup-create", "create", data={"title": "Backup"})
    assert actual["duplicate"] and actual["thread_id"] == expected["thread_id"]


def test_real_stdio_peer_uses_fixed_home_and_operation_receipts(tmp_path):
    import os
    import subprocess
    import sys
    source = Path(__file__).parents[1] / "src"
    calls = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "thread_manage", "arguments": {"operation_id": "stdio-create", "action": "create", "expected_revision": 0, "data": {"title": "Synthetic stdio only"}}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "thread_operation_status", "arguments": {"operation_id": "stdio-create"}}},
    ]
    env = {**os.environ, "PYTHONPATH": str(source), "THREADDESK_HOME": str(tmp_path), "THREADDESK_STORAGE": "json"}
    result = subprocess.run([sys.executable, "-m", "threaddesk.ui.mcp_stdio"], input="\n".join(json.dumps(item) for item in calls) + "\n", text=True, capture_output=True, env=env, timeout=10, check=True)
    messages = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(messages) == 3  # initialized notification must not pollute MCP stdout.
    from importlib.metadata import version
    assert messages[0]["result"]["serverInfo"]["version"] == version("threaddesk")
    created = json.loads(messages[1]["result"]["content"][0]["text"])
    receipt = json.loads(messages[2]["result"]["content"][0]["text"])
    assert receipt["result"] == created and receipt["found"]
    assert len(JsonStore(tmp_path).list_threads()) == 1
