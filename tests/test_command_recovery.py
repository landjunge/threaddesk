"""Lost outer receipts recover only from exact, already committed owner proof."""
import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.services.commands import CommandApplication
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore])
def app(tmp_path, request):
    store = request.param(tmp_path / "workspace")
    yield CommandApplication(ThreadService(store))
    if hasattr(store, "connection"):
        store.connection.close()


def test_lost_command_completion_adopts_exact_thread_owner_without_replay(app, monkeypatch):
    request = {"version": 1, "workspace_id": app.workspace_id, "command": "thread_manage",
               "arguments": {"action": "create", "data": {"title": "Committed owner"}},
               "operation_id": "lost-completion", "expected_revision": 0}
    original = app._save
    lost = [False]
    def fail_once(key, digest, state, **kwargs):
        if key == app._operation_key("lost-completion") and state == "complete" and not lost[0]:
            lost[0] = True
            raise OSError("Synthetic outer receipt loss after native commit")
        return original(key, digest, state, **kwargs)
    monkeypatch.setattr(app, "_save", fail_once)
    with pytest.raises(ManagementError) as uncertain:
        app.call(request)
    assert uncertain.value.code == "command_unconfirmed"
    assert app.operation("lost-completion")["state"] == "pending"
    assert len(app.store.list_threads()) == 1
    def forbidden(*args, **kwargs):
        raise AssertionError("Domain mutation repeated during receipt reconciliation")
    monkeypatch.setattr(app.service, "create", forbidden)
    result = app.call({"version": 1, "workspace_id": app.workspace_id, "command": "command.reconcile",
                       "arguments": {"request": request}, "operation_id": "adopt-completion"})["result"]
    assert result["adopted"] and result["external_effect_repeated"] is False
    assert result["result"]["thread"]["title"] == "Committed owner"
    assert app.operation("lost-completion")["state"] == "complete"
    assert len(app.store.list_threads()) == 1
    replay = app.call(request)
    assert replay["duplicate"] and replay["result"]["thread"]["title"] == "Committed owner"


def test_reconcile_requires_existing_matching_workspace_bound_reservation(app, monkeypatch):
    request = {"version": 1, "workspace_id": app.workspace_id, "command": "thread_manage",
               "arguments": {"action": "create", "data": {"title": "No reservation"}},
               "operation_id": "not-started", "expected_revision": 0}
    with pytest.raises(ManagementError) as absent:
        app.reconcile(request)
    assert absent.value.code == "operation_not_found"
    assert not app.store.list_threads()
    app.call(request)
    wrong = {**request, "arguments": {"action": "create", "data": {"title": "Different request"}}}
    with pytest.raises(ManagementError) as conflict:
        app.reconcile(wrong)
    assert conflict.value.code == "operation_conflict"
    with pytest.raises(ManagementError) as workspace:
        app.reconcile({**request, "workspace_id": "ws-unrelated"})
    assert workspace.value.code == "workspace_mismatch"
    assert len(app.store.list_threads()) == 1


def test_global_data_failure_rolls_back_domain_and_events(app, monkeypatch):
    events = []
    app.service.bus.on("*", lambda name, payload: events.append(name))
    def fail(*args, **kwargs):
        raise OSError("Synthetic atomic receipt failure")
    monkeypatch.setattr(app, "_save", fail)
    request = {"version": 1, "workspace_id": app.workspace_id, "command": "graph.node.create",
               "arguments": {"kind": "task", "title": "Must roll back"},
               "operation_id": "atomic-failure", "expected_revision": 0}
    with pytest.raises(ManagementError):
        app.call(request)
    assert not app.store.list_nodes() and not app.store.list_graph_events() and not events
    assert not app.operation("atomic-failure")["found"]
