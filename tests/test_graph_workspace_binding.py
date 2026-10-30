"""HTML, graph reads and client registration bind the same selected workspace."""
import re

import pytest

from http_ui_client import UIClient
from threaddesk.api.service import ThreadService
from threaddesk.services.commands.model import workspace_identity
from threaddesk.services.graph_read import GraphReadService
from threaddesk.services.graph_view_control import GraphViewControlService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.ui.server import create_app


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=['json', 'sqlite'])
def workspace(tmp_path, monkeypatch, request):
    home = tmp_path / 'current'
    monkeypatch.setenv('THREADDESK_HOME', str(home))
    monkeypatch.setenv('THREADDESK_STORAGE', 'sqlite' if request.param is SQLiteStore else 'json')
    store = request.param(home)
    service = ThreadService(store=store)
    service.create_node('task', 'Bound task')
    yield store, service, tmp_path
    if hasattr(store, 'connection'):
        store.connection.close()


def test_graph_v2_identity_comes_from_its_bound_store(workspace):
    store, service, _tmp = workspace
    graph = GraphReadService(store).query(service.graph())
    assert graph['workspace_id'] == workspace_identity(store)


def test_html_graph_and_registration_reject_foreign_identity_and_keep_csrf(workspace):
    store, _service, temporary = workspace
    expected = workspace_identity(store)
    other = workspace_identity(JsonStore(temporary / 'different'))
    client = UIClient(create_app())
    try:
        page = client.get('/map')
        assert page.status_code == 200
        assert re.search(r'data-graph-workspace-id="([^"]+)"', page.text)[1] == expected
        assert client.get('/api/graph/v2').json()['workspace_id'] == expected
        control = GraphViewControlService(store)
        assert control.clients()['clients'] == []
        stale = client.post('/api/graph/view-control/connect', json={'workspace_id': other})
        assert stale.status_code == 409 and stale.json()['code'] == 'workspace_conflict'
        missing = client.post('/api/graph/view-control/connect', json={})
        assert missing.status_code == 400 and missing.json()['code'] == 'validation_error'
        denied = client.post('/api/graph/view-control/connect', json={'workspace_id': expected},
                             headers={'X-ThreadDesk-CSRF': 'invalid'})
        assert denied.status_code == 403
        assert control.clients()['clients'] == []
        accepted = client.post('/api/graph/view-control/connect', json={'workspace_id': expected})
        assert accepted.status_code == 200
        identity = accepted.json()['result']['client_id']
        assert [row['client_id'] for row in control.clients()['clients']] == [identity]
        again = client.post('/api/graph/view-control/connect', json={'workspace_id': other})
        assert again.status_code == 409
        assert [row['client_id'] for row in control.clients()['clients']] == [identity]
    finally:
        client.close()
