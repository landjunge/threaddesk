"""Confirmed purge reduces exact active result copies without losing audit IDs."""
from copy import deepcopy
import hashlib
import io
import json
import zipfile

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.core.models import KnowledgeNode, Relation
from threaddesk.services.commands import CommandApplication
from threaddesk.services.trash import TrashService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.storage.portable_backup import download_backup, restore_backup


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def app(request, tmp_path):
    store = request.param(tmp_path / "source")
    application = CommandApplication(ThreadService(store))
    yield application
    if hasattr(store, "connection"):
        store.connection.close()


def call(app, command, arguments, operation_id=None, revision=None):
    request = {"version": 1, "workspace_id": app.workspace_id, "command": command, "arguments": arguments}
    if operation_id is not None:
        request["operation_id"] = operation_id
    if revision is not None:
        request["expected_revision"] = revision
    return app.call(request)["result"]


def prepared(app):
    created = call(app, "thread_manage", {"action": "create", "data": {"title": "Private title"}}, "create", 0)
    args = {"action": "set_note", "id": created["thread_id"], "data": {"text": "PRIVATE_NOTE_PURGE_TEST_20261027"}}
    changed = call(app, "thread_manage", args, "note", created["revision"])
    entry = call(app, "trash.move", {"kind": "thread", "object_id": created["thread_id"]}, "move", changed["revision"])["entry"]
    return entry, args, created["revision"]


def purge(app, entry, operation_id="purge", preview=None):
    preview = preview or call(app, "trash.purge_preview", {"trash_id": entry["trash_id"]})
    arguments = {key: preview[key] for key in ("reference_digest", "confirmation")}
    arguments.update(trash_id=entry["trash_id"], generation=entry["generation"])
    return call(app, "trash.purge", arguments, operation_id, entry["revision"])


def test_public_purge_reduces_owner_global_replay_and_restored_backup(app, tmp_path):
    entry, args, old_revision = prepared(app)
    store = app.store
    owner_before = deepcopy(store.get_management_operation("note"))
    global_key = app._operation_key("note") + "-complete"
    global_before = deepcopy(store.get_management_operation(global_key))
    before = deepcopy(store.list_management_operation_records())
    preview = call(app, "trash.purge_preview", {"trash_id": entry["trash_id"]})
    assert before == store.list_management_operation_records(), "Preview must not reduce audit data"
    assert preview["version"] == 2 and not preview["blockers"]
    assert {"note", global_key} <= {item["storage_operation_id"] for item in preview["receipt_reduction"]["records"]}
    assert "PRIVATE_NOTE" not in json.dumps(preview["receipt_reduction"])
    result = purge(app, entry, preview=preview)
    assert result["entry"]["content_purged"] and result["entry"]["state"] == "purged"
    owner_after = store.get_management_operation("note")
    global_after = store.get_management_operation(global_key)
    for previous, current in ((owner_before, owner_after), (global_before, global_after)):
        for key in previous.keys() - {"result"}:
            assert current[key] == previous[key]
        assert current["purge_reductions"][0]["schema"] == "threaddesk.purge-receipt-reduction.v1"
        assert current["result"]["thread"] is None
        assert current["result"]["purged_payloads"][0]["content_purged"]
    assert "PRIVATE_NOTE" not in json.dumps(call(app, "thread_operation_status", {"operation_id": "note"}))
    assert "PRIVATE_NOTE" not in json.dumps(app.operation("note"))
    replay = app.call({"version": 1, "workspace_id": app.workspace_id, "command": "thread_manage",
                       "arguments": args, "operation_id": "note", "expected_revision": old_revision})
    assert replay["duplicate"] and replay["result"]["thread"] is None
    from threaddesk.services.mcp import McpBridge
    native_replay = McpBridge(app.service).call("thread_manage", {
        **args, "operation_id": "note", "expected_revision": old_revision})
    assert native_replay["ok"] and native_replay["result"]["duplicate"]
    assert native_replay["result"]["thread"] is None
    assert not store.list_threads(include_archived=True, include_trashed=True)
    with pytest.raises(ManagementError) as conflict:
        call(app, "thread_manage", {**args, "data": {"text": "different"}}, "note", old_revision)
    assert conflict.value.code == "operation_conflict"
    body = download_backup(store)
    profile = restore_backup(body, tmp_path / "restore")
    restored = type(store)(profile)
    try:
        readback = CommandApplication(ThreadService(restored))
        assert "PRIVATE_NOTE" not in json.dumps(readback.operation("note"))
        assert "PRIVATE_NOTE" not in json.dumps(call(readback, "thread_operation_status", {"operation_id": "note"}))
        assert "PRIVATE_NOTE" not in json.dumps(restored.list_management_operations())
        assert not restored.list_threads(include_archived=True, include_trashed=True)
        if isinstance(store, JsonStore):
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                assert all(b"PRIVATE_NOTE" not in archive.read(name) for name in archive.namelist())
    finally:
        if hasattr(restored, "connection"):
            restored.connection.close()


def test_receipt_addition_invalidates_preview_and_reduction_rolls_back_with_purge(app, monkeypatch):
    entry, _, _ = prepared(app)
    trash = TrashService(app.store)
    old = trash.purge_preview(entry["trash_id"])
    app.store.save_management_operation("late-copy", {"request_hash": "a" * 64,
        "result": {"thread_id": entry["object_id"], "thread": app.store.get_thread(entry["object_id"], include_trashed=True).to_dict()}})
    with pytest.raises(ManagementError) as stale:
        purge(app, entry, "stale-purge", old)
    assert stale.value.code == "reference_conflict"
    fresh = trash.purge_preview(entry["trash_id"])
    before = deepcopy(app.store.list_management_operation_records())
    original = app.store.purge_trash_object

    def fail(*args):
        original(*args)
        raise RuntimeError("purge failure after reduction")

    monkeypatch.setattr(app.store, "purge_trash_object", fail)
    with pytest.raises(RuntimeError, match="after reduction"):
        trash.purge(trash_id=entry["trash_id"], generation=entry["generation"], expected_revision=entry["revision"],
                    reference_digest=fresh["reference_digest"], confirmation=fresh["confirmation"], operation_id="failure")
    assert app.store.list_management_operation_records() == before
    assert app.store.get_thread(entry["object_id"], include_trashed=True).context.notes.startswith("PRIVATE_NOTE")
    assert trash.get(entry["trash_id"])["state"] == "trashed"


@pytest.mark.parametrize("shape", ["pending", "opaque", "owned_unknown", "structured_text", "nested_prompt"])
def test_unknown_or_unconfirmed_result_blocks_instead_of_erasing_audit(app, shape):
    entry, _, _ = prepared(app)
    record = {"request_hash": "a" * 64, "result": None}
    identity = "unknown"
    if shape == "pending":
        identity = "command-" + "b" * 64 + "-pending"
        record.update(kind="command", state="pending")
    elif shape == "opaque":
        record["result"] = "Unattributed prompt with private content"
    elif shape == "structured_text":
        record["result"] = {"text": "Unattributed prompt with private content"}
    elif shape == "nested_prompt":
        record["result"] = {"state": "complete", "result": {"text": "Unattributed prompt"}}
    else:
        record["result"] = {"thread_id": entry["object_id"], "prompt": "Unknown private result"}
    app.store.save_management_operation(identity, record)
    preview = TrashService(app.store).purge_preview(entry["trash_id"])
    assert "receipt_reduction_requires_review" in preview["blockers"]
    with pytest.raises(ManagementError) as blocked:
        purge(app, entry, preview=preview)
    assert blocked.value.code == "purge_blocked"
    assert app.store.get_management_operation(identity) == record


def test_actual_public_prompt_without_owner_id_blocks_purge_and_retains_audit(app):
    created = call(app, "thread_manage", {"action": "create", "data": {"title": "Prompt source"}}, "create", 0)
    changed = call(app, "thread_manage", {"action": "set_note", "id": created["thread_id"],
        "data": {"text": "PRIVATE_OPAQUE_PROMPT_NOTE"}}, "note", created["revision"])
    prompt = call(app, "generate_prompt", {"id": created["thread_id"], "target": "grok",
        "variant": "detailed", "save": False}, "prompt", changed["revision"])
    assert "PRIVATE_OPAQUE_PROMPT_NOTE" in prompt["text"]
    entry = call(app, "trash.move", {"kind": "thread", "object_id": created["thread_id"]}, "move", changed["revision"])["entry"]
    preview = call(app, "trash.purge_preview", {"trash_id": entry["trash_id"]})
    assert any(item["reason"] == "unattributed_text_result" and item["path"] == "$.text"
               for item in preview["receipt_reduction"]["blockers"])
    with pytest.raises(ManagementError) as blocked:
        purge(app, entry, preview=preview)
    assert blocked.value.code == "purge_blocked"
    assert app.operation("prompt")["result"] == prompt
    assert TrashService(app.store).get(entry["trash_id"])["state"] == "trashed"


def test_same_id_foreign_pending_cannot_be_treated_as_own_purge(app):
    entry, _, _ = prepared(app)
    identity = "forged-purge"
    key = "command-" + hashlib.sha256(identity.encode()).hexdigest() + "-pending"
    app.store.save_management_operation(key, {"kind": "command", "state": "pending", "request_hash": "0" * 64, "result": None})
    trash = TrashService(app.store)
    preview = trash.purge_preview(entry["trash_id"])
    with pytest.raises(ManagementError) as blocked:
        trash.purge(trash_id=entry["trash_id"], generation=1, expected_revision=1,
                    reference_digest=preview["reference_digest"], confirmation=preview["confirmation"], operation_id=identity)
    assert blocked.value.code == "purge_blocked"


@pytest.mark.parametrize("terminal", ["complete", "failed"])
def test_unrelated_terminal_record_cannot_close_foreign_pending(app, terminal):
    entry, _, _ = prepared(app)
    prefix = "command-" + "b" * 64
    app.store.save_management_operation(prefix + "-pending", {
        "kind": "command", "state": "pending", "request_hash": "a" * 64, "result": None})
    app.store.save_management_operation(prefix + "-" + terminal, {
        "kind": "command", "state": terminal, "request_hash": "c" * 64, "result": None})
    preview = TrashService(app.store).purge_preview(entry["trash_id"])
    assert any(item["storage_operation_id"] == prefix + "-pending"
               and item["reason"] == "unconfirmed_command_requires_review"
               for item in preview["receipt_reduction"]["blockers"])
    with pytest.raises(ManagementError) as blocked:
        purge(app, entry, preview=preview)
    assert blocked.value.code == "purge_blocked"


def test_purge_reduces_prior_generations_but_preserves_other_thread_result(app):
    entry, _, _ = prepared(app)
    other = call(app, "thread_manage", {"action": "create", "data": {"title": "Other private thread"}}, "other", 0)
    other_before = deepcopy(app.store.get_management_operation("other"))
    call(app, "trash.restore", {"trash_id": entry["trash_id"], "generation": 1}, "restore", 1)
    current = call(app, "trash.move", {"kind": "thread", "object_id": entry["object_id"]}, "move-again", entry["object_revision"])["entry"]
    assert current["generation"] == 2
    purge(app, current)
    assert app.store.get_management_operation("other") == other_before
    assert app.store.get_thread(other["thread_id"]).title == "Other private thread"
    for saved in app.store.list_trash_entries():
        assert "title" not in saved and "actor" not in saved and "references" not in saved
    assert "Private title" not in json.dumps(TrashService(app.store).operation_status("move")["result"])
    assert "Private title" not in json.dumps(TrashService(app.store).operation_status("restore")["result"])


@pytest.mark.parametrize("kind", ["node", "relation"])
def test_graph_payload_receipts_reduce_only_exact_target(app, kind):
    store = app.store
    first, other = KnowledgeNode("purge-node", "project", "Private graph title"), KnowledgeNode("keep-node", "project", "Keep")
    if kind == "node":
        store.save_node(first)
        obj = first
    else:
        store.save_node(other)
        store.save_node(KnowledgeNode("second-node", "project", "Second"))
        obj = Relation("purge-relation", other.id, "second-node", "related")
        store.save_relation(obj)
    source = {"request_hash": "a" * 64, "result": {kind: obj.to_dict(), "other": other.to_dict()}}
    store.save_management_operation("graph-copy", source)
    trash = TrashService(store)
    entry = trash.move(kind=kind, object_id=obj.id, expected_revision=obj.revision, operation_id="graph-move")["entry"]
    purge(app, entry)
    saved = store.get_management_operation("graph-copy")
    assert saved["result"][kind]["content_purged"]
    assert saved["result"]["other"] == other.to_dict()


def test_native_knowledge_replay_after_explicit_node_and_thread_purge(app):
    from threaddesk.services.mcp import McpBridge
    created = call(app, "thread_manage", {"action": "create", "data": {"title": "Knowledge owner"}}, "create", 0)
    request = {"operation_id": "knowledge", "id": created["thread_id"], "expected_revision": created["revision"],
               "action": "record", "data": {"source_ref": "conversation:test", "source_revision": "message-1",
                                             "kind": "decision", "title": "Private decision", "status": "confirmed"}}
    bridge = McpBridge(app.service)
    recorded = bridge.call("knowledge_manage", request)
    assert recorded["ok"], recorded
    node = recorded["result"]["node"]
    trash = TrashService(app.store)
    node_entry = trash.move(kind="node", object_id=node["id"], expected_revision=node["revision"], operation_id="move-node")["entry"]
    purge(app, node_entry, "purge-node")
    thread = app.store.get_thread(created["thread_id"])
    thread_entry = trash.move(kind="thread", object_id=thread.id, expected_revision=thread.revision, operation_id="move-thread")["entry"]
    purge(app, thread_entry, "purge-thread")
    replay = bridge.call("knowledge_manage", request)
    assert replay["ok"] and replay["result"]["duplicate"], replay
    assert replay["result"]["thread"] is None
    assert replay["result"]["node"]["content_purged"]
    assert "Private decision" not in json.dumps(replay)
