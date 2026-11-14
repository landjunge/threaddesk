"""The real authenticated HTTP append joins its owner's commit boundary."""

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from threaddesk.server_sync import app as server_module
from threaddesk.server_sync.auth import provision
from threaddesk.storage.json_store import JsonStore


@pytest.fixture
def server(tmp_path, monkeypatch):
    data = tmp_path / "server"
    token = provision(data, "alice")
    cores = []
    service_type = server_module.ThreadService

    def capture_core(store):
        core = service_type(store)
        cores.append(core)
        return core

    monkeypatch.setattr(server_module, "ThreadService", capture_core)
    app = server_module.create_app(data, public_origin="https://testserver")
    headers = {"Authorization": "Bearer " + token}
    with TestClient(
        app, base_url="https://testserver", raise_server_exceptions=False
    ) as http:
        response = http.post(
            "/api/projects", headers=headers, json={"title": "Private"}
        )
        assert response.status_code == 200, response.text
        assert len(cores) == 1
        yield http, headers, response.json()["id"], cores[0]


def test_server_append_notifies_after_commit_and_deduplicates(server):
    http, headers, thread_id, core = server
    uri = f"/api/projects/{thread_id}/whiteboard"
    prior_revision = core.get(thread_id).revision
    seen = []

    def observed(_name, payload):
        if core.store.in_transaction:
            # Opening a second JSON store here would wait on the owner's lock.
            seen.append((True, payload["id"], None, None))
            return
        reopened = JsonStore(core.store.workspace_path)
        seen.append(
            (
                core.store.in_transaction,
                payload["id"],
                [entry.id for entry in reopened.list_whiteboard(thread_id)],
                reopened.get_thread(thread_id).revision,
            )
        )

    core.bus.on("whiteboard.appended", observed)
    value = {"content": "Committed", "entry_type": "result", "external_key": "http-1"}
    response = http.post(uri, headers=headers, json=value)
    assert response.status_code == 200, response.text
    entry_id = response.json()["entry"]["id"]
    duplicate = http.post(uri, headers=headers, json=value)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["entry"]["id"] == entry_id
    assert seen == [(False, entry_id, [entry_id], prior_revision + 1)]


def test_server_owner_abort_discards_entry_revision_and_notification(
    server, monkeypatch
):
    http, headers, thread_id, core = server
    uri = f"/api/projects/{thread_id}/whiteboard"
    original = core.get(thread_id).to_dict()
    events = []
    aborts = []
    core.bus.on("whiteboard.appended", lambda *args: events.append(args))
    transaction = core.store.transaction

    @contextmanager
    def abort_before_commit():
        with transaction():
            yield
            aborts.append(True)
            raise RuntimeError("injected outer commit failure")

    with monkeypatch.context() as patched:
        patched.setattr(core.store, "transaction", abort_before_commit)
        response = http.post(
            uri,
            headers=headers,
            json={
                "content": "Rolled back",
                "entry_type": "result",
                "external_key": "abort-1",
            },
        )
    assert response.status_code == 500
    assert aborts == [True]
    assert http.get(uri, headers=headers).json() == {"entries": []}
    assert core.get(thread_id).to_dict() == original
    assert events == []
