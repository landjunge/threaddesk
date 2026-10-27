"""Real domain contracts through the complete command boundary on both stores."""
from __future__ import annotations

import hashlib
import json

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.services.commands import CommandApplication
from threaddesk.services.commands.model import CommandSpec
from threaddesk.services.commands.registry import CommandRegistry
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore])
def application(tmp_path, request):
    store = request.param(tmp_path / "workspace")
    app = CommandApplication(ThreadService(store))
    yield app
    if hasattr(store, "connection"):
        store.connection.close()


def invoke(app, command, arguments=None, **fields):
    return app.call({"version": 1, "workspace_id": app.workspace_id,
                     "command": command, "arguments": arguments or {}, **fields})


def create(app, title="Command project", operation="create-project"):
    return invoke(app, "thread_manage", {"action": "create", "data": {"title": title}},
                  operation_id=operation, expected_revision=0)["result"]["thread"]


def test_global_command_reservations_do_not_break_trash_conflict_reads(application):
    create(application)
    assert invoke(application, "trash.sync_conflicts")["result"]["items"] == []


def test_catalogue_pages_are_bounded_and_cover_existing_mcp(application):
    from threaddesk.services.mcp import TOOLS
    rows, offset = [], 0
    while offset is not None:
        result = application.catalog(limit=25, offset=offset)
        assert len(json.dumps(result, ensure_ascii=False).encode()) < 30000
        rows.extend(result["commands"])
        offset = result["next_offset"]
    names = {row["id"] for row in rows}
    assert {row["name"] for row in TOOLS} - {"command_catalog", "command_query", "command_invoke"} <= names
    assert {"graph.node.create", "graph.node.transition", "graph.relation.create", "trash.restore", "whiteboard.append"} <= names
    assert len(names) == len(rows)
    migration = next(row for row in rows if row["id"] == "migration.stage")
    assert migration["backends"] == ["sqlite"]
    assert migration["availability"] == ("available" if isinstance(application.store, SQLiteStore) else "unsupported_backend")


def test_native_thread_replay_conflict_and_wrong_workspace(application):
    thread = create(application)
    repeated = invoke(application, "thread_manage", {"action": "create", "data": {"title": "Command project"}},
                      operation_id="create-project", expected_revision=0)
    assert repeated["duplicate"] and repeated["result"]["thread"]["id"] == thread["id"]
    with pytest.raises(ManagementError, match="different request") as conflict:
        create(application, title="Different payload")
    assert conflict.value.code == "operation_conflict"
    request = {"version": 1, "workspace_id": "ws-unrelated", "command": "thread_manage", "operation_id": "wrong-workspace",
               "arguments": {"action": "create", "data": {"title": "Must not exist"}}, "expected_revision": 0}
    with pytest.raises(ManagementError) as mismatch:
        application.call(request)
    assert mismatch.value.code == "workspace_mismatch"
    assert len(application.store.list_threads()) == 1
    assert not application.operation("wrong-workspace")["found"]


def test_graph_mutations_share_cas_operations_and_committed_events(application):
    events = []
    application.service.bus.on("*", lambda name, payload: events.append(name))
    first = invoke(application, "graph.node.create", {"kind": "task", "title": "Task"},
                   operation_id="node-one", expected_revision=0)["result"]
    second = invoke(application, "graph.node.create", {"kind": "project", "title": "Project"},
                    operation_id="node-two", expected_revision=0)["result"]
    args = {"source_id": first["id"], "target_id": second["id"], "kind": "contains", "expected_target_revision": second["revision"]}
    result = invoke(application, "graph.relation.create", args, operation_id="relation", expected_revision=first["revision"])
    count = len(events)
    replay = invoke(application, "graph.relation.create", args, operation_id="relation", expected_revision=first["revision"])
    assert replay["duplicate"] and replay["result"] == result["result"] and len(events) == count
    with pytest.raises(ManagementError) as stale:
        invoke(application, "graph.node.transition", {"id": first["id"], "status": "active"}, operation_id="stale-node", expected_revision=0)
    assert stale.value.code == "revision_conflict"
    assert not application.operation("stale-node")["found"]


def test_whiteboard_append_replay_conflict_and_readback(application):
    thread = create(application)
    args = {"id": thread["id"], "actor": "Test operator", "actor_type": "human", "entry_type": "note", "content": "Shared domain content"}
    result = invoke(application, "whiteboard.append", args, operation_id="board-one", expected_revision=thread["revision"])
    invoke(application, "whiteboard.append", args, operation_id="board-one", expected_revision=thread["revision"])
    assert len(application.service.whiteboard(thread["id"])) == 1
    assert invoke(application, "whiteboard.list", {"id": thread["id"]})["result"]["items"][0]["content"] == "Shared domain content"
    with pytest.raises(ManagementError) as stale:
        invoke(application, "whiteboard.append", args, operation_id="board-stale", expected_revision=thread["revision"])
    assert stale.value.code == "revision_conflict"
    status = invoke(application, "command.operation", {"operation_id": "board-one"})["result"]
    assert status["found"] and status["state"] == "complete" and status["result"] == result["result"]


def test_snapshot_restore_and_saved_prompt_require_current_revision(application):
    thread = create(application)
    snapshot = invoke(application, "thread_manage", {"action": "snapshot", "id": thread["id"]},
                      operation_id="snapshot-one", expected_revision=thread["revision"])["result"]["snapshot"]
    with pytest.raises(ManagementError) as missing:
        invoke(application, "restore_snapshot", {"snap_id": snapshot["id"]}, operation_id="restore-missing")
    assert missing.value.code == "validation_error"
    current = application.service.get(thread["id"])
    invoke(application, "generate_prompt", {"id": thread["id"], "save": True},
           operation_id="prompt-one", expected_revision=current.revision)
    with pytest.raises(ManagementError) as stale:
        invoke(application, "restore_snapshot", {"snap_id": snapshot["id"]},
               operation_id="restore-stale", expected_revision=current.revision)
    assert stale.value.code == "revision_conflict"


@pytest.mark.parametrize("fields,code", [({"version": 2}, "unsupported_version"),
    ({"unexpected": True}, "validation_error"), ({"arguments": {"id": "x", "unknown": True}}, "validation_error")])
def test_invalid_envelopes_never_dispatch(application, fields, code):
    request = {"version": 1, "workspace_id": application.workspace_id, "command": "get_thread", "arguments": {"id": "x"}, **fields}
    with pytest.raises(ManagementError) as error:
        application.call(request)
    assert error.value.code == code


def test_large_readback_is_digest_bound_and_reconstructs_without_writes(application):
    thread = create(application)
    current = application.service.get(thread["id"])
    application.service.set_note("Äöü page content " * 7000, current.id)
    before = _snapshot(application.store.workspace_path)
    response = invoke(application, "get_thread", {"id": current.id})
    assert "result_page" in response
    pages = [response["result_page"]]
    while response["next_offset"] is not None:
        response = invoke(application, "get_thread", {"id": current.id}, result_offset=response["next_offset"], result_digest=response["result_digest"])
        assert len(json.dumps(response, ensure_ascii=False).encode()) < 30000
        pages.append(response["result_page"])
    rebuilt = json.loads("".join(pages))
    assert "Äöü page content" in rebuilt["notes"]
    assert _snapshot(application.store.workspace_path) == before
    digest = response["result_digest"]
    application.service.set_note("Changed", current.id)
    with pytest.raises(ManagementError) as changed:
        invoke(application, "get_thread", {"id": current.id}, result_offset=100, result_digest=digest)
    assert changed.value.code == "result_changed"


def test_catalogue_permission_revocation_and_external_uncertainty(application):
    calls = []
    def effect(svc, args):
        calls.append(1)
        raise TimeoutError("Synthetic result loss after side effect")
    spec = CommandSpec("fixture.effect", "fixture", "isolated side effect", {"type": "object", "additionalProperties": False}, effect,
                       effect="external", scope="fixture.write")
    registry = CommandRegistry(application.store, [spec])
    allowed = CommandApplication(application.service, registry=registry, allowed_scopes={"fixture.write"})
    denied = CommandApplication(application.service, registry=registry, allowed_scopes=set())
    assert allowed.catalog()["revision"] != denied.catalog()["revision"]
    with pytest.raises(ManagementError) as missing:
        invoke(denied, "fixture.effect", operation_id="external-one")
    assert missing.value.code == "permission_required" and not calls
    with pytest.raises(ManagementError, match="Execution could not be confirmed"):
        invoke(allowed, "fixture.effect", operation_id="external-one")
    assert len(calls) == 1
    assert allowed.operation("external-one")["safe_to_retry"] is False
    with pytest.raises(ManagementError) as uncertain:
        invoke(allowed, "fixture.effect", operation_id="external-one")
    assert uncertain.value.code == "operation_unconfirmed" and len(calls) == 1


def test_profiles_are_bound_to_the_store_not_global_home(application, tmp_path, monkeypatch):
    other = tmp_path / "unrelated"
    other.mkdir()
    import threaddesk.storage.portable_backup as portable
    monkeypatch.setattr(portable, "base_root", lambda: other)
    result = invoke(application, "profiles.list")["result"]
    assert result["active"] == application.store.workspace_path.name
    assert not (other / "profiles").exists()


def _snapshot(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file() and not path.name.endswith(("-wal", "-shm", ".lock"))}
