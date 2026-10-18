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
