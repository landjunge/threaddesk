"""A queued intent is not an applied graph view; client state is read back."""
from __future__ import annotations

from copy import deepcopy

import pytest

from threaddesk.core.errors import ManagementError
from threaddesk.services.graph_view_control import GraphViewControlService
from threaddesk.services.graph_views import GraphViewService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def control(tmp_path, request):
    store = request.param(tmp_path / "workspace")
    views = GraphViewService(store)
    views.manage({"action": "save", "id": "work", "expected_revision": 0, "operation_id": "save-work",
                  "data": {"title": "Working view", "state": {"camera": {"x": 30, "y": 50, "scale": .8},
                           "positions": {"abc": {"x": 10, "y": 20, "fixed": True}},
                           "selection": ["abc"], "filters": {"mode": "work"}}}})
    yield GraphViewControlService(store), views
    if hasattr(store, "connection"):
        store.connection.close()


def test_waiting_claim_apply_ack_and_exact_replay(control):
    service, views = control
    request = {"id": "work", "expected_revision": 1, "operation_id": "apply-work"}
    assert service.apply(request)["status"] == "waiting"
    assert service.apply(request)["duplicate"]
    assert service.apply_status("apply-work")["result"]["acknowledgement"] is None
    client = service.register();identity, token = client["client_id"], client["client_token"]
    pending = service.pending(identity, token)["requests"]
    assert len(pending) == 1 and pending[0]["status"] == "waiting"
    assert service.claim(identity, token, "apply-work")["status"] == "queued"
    assert service.apply_status("apply-work")["result"]["status"] == "queued"
    observed = views.get("work")["state"]
    result = service.acknowledge(identity, token, "apply-work", "applied", observed)
    assert result["status"] == "applied"
    assert result["acknowledgement"]["observation"]["matched"]
    assert service.apply(request)["status"] == "applied"
    assert service.pending(identity, token)["requests"] == []
    assert service.acknowledge(identity, token, "apply-work", "applied", observed)["duplicate"]
    changed = deepcopy(observed);changed["camera"]["x"] += 1
    with pytest.raises(ManagementError) as error:
        service.acknowledge(identity, token, "apply-work", "applied", changed)
    assert error.value.code == "operation_conflict"


def test_applied_requires_matching_client_and_observed_state(control):
    service, views = control
    first, other = service.register(), service.register()
    with pytest.raises(ManagementError) as error:
        service.apply({"id": "work", "expected_revision": 1, "operation_id": "ambiguous"})
    assert error.value.code == "client_required"
    result = service.apply({"id": "work", "expected_revision": 1, "operation_id": "apply", "client_id": first["client_id"]})
    assert result["status"] == "queued"
    with pytest.raises(ManagementError) as error:
        service.acknowledge(other["client_id"], other["client_token"], "apply", "applied", views.get("work")["state"])
    assert error.value.code == "view_client_conflict"
    with pytest.raises(ManagementError) as error:
        service.pending(first["client_id"], "0" * 64)
    assert error.value.code == "view_client_denied"
    observed = deepcopy(views.get("work")["state"]);observed["camera"]["x"] += 50
    failed = service.acknowledge(first["client_id"], first["client_token"], "apply", "applied", observed)
    assert failed["status"] == "failed"
    assert failed["acknowledgement"]["error_code"] == "view_observation_mismatch"


def test_stale_view_and_changed_payload_conflict(control):
    service, views = control
    request = {"id": "work", "expected_revision": 1, "operation_id": "apply"}
    service.apply(request)
    with pytest.raises(ManagementError) as error:
        service.apply({**request, "expected_revision": 2})
    assert error.value.code == "operation_conflict"
    views.manage({"action": "save", "id": "work", "expected_revision": 1, "operation_id": "update-work",
                  "data": {"title": "Changed", "state": {}}})
    with pytest.raises(ManagementError) as error:
        service.apply({**request, "operation_id": "stale"})
    assert error.value.code == "revision_conflict"
    client = service.register();service.claim(client["client_id"], client["client_token"], "apply")
    result = service.acknowledge(client["client_id"], client["client_token"], "apply", "applied", views.get("work")["state"])
    assert result["status"] == "revision_conflict"


def test_restart_cancels_queued_intents_and_invalidates_tokens(control):
    service, _views = control
    client = service.register()
    service.apply({"id": "work", "expected_revision": 1, "operation_id": "before-restart"})
    assert service.reset_runtime()["cancelled"] == 1
    assert service.apply_status("before-restart")["result"]["status"] == "cancelled_restart"
    with pytest.raises(ManagementError) as error:
        service.pending(client["client_id"], client["client_token"])
    assert error.value.code == "view_client_denied"
    new_client = service.register()
    assert service.pending(new_client["client_id"], new_client["client_token"])["requests"] == []


def test_read_operations_and_owner_verification_are_inert(control):
    service, views = control
    path = service.document.path
    assert service.clients() == {"clients": []}
    assert not service.apply_status("missing")["found"]
    request = {"id": "work", "expected_revision": 1, "operation_id": "missing"}
    assert not service.verify_recorded_request(request)["found"]
    assert not path.exists()
    service.apply(request)
    before = path.read_bytes()
    assert service.verify_recorded_request(request)["found"]
    assert path.read_bytes() == before
    view_request = {"action": "save", "id": "work", "expected_revision": 0, "operation_id": "save-work",
                    "data": {"title": "Working view", "state": {"camera": {"x": 30, "y": 50, "scale": .8},
                             "positions": {"abc": {"x": 10, "y": 20, "fixed": True}},
                             "selection": ["abc"], "filters": {"mode": "work"}}}}
    original = views.document.path.read_bytes()
    assert views.verify_recorded_request(view_request)["found"]
    assert views.document.path.read_bytes() == original
