"""Actual protected status routes and metadata-only exchange for trash lifecycle."""
from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient
from http_ui_client import UIClient

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.server_sync.app import create_app as create_server
from threaddesk.server_sync.auth import provision
from threaddesk.server_sync.desktop import BindingBook, DesktopSyncManager
from threaddesk.server_sync.metadata import export_document, synchronize
from threaddesk.services.trash import TrashService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.ui.server import create_app as create_desktop


@pytest.fixture
def remote_server(tmp_path):
    data = tmp_path / 'server'
    token = provision(data, 'owner')
    with TestClient(create_server(data, public_origin='https://server.example'),
                    base_url='https://server.example') as remote:
        yield remote, token


@pytest.mark.parametrize('backend', [JsonStore, SQLiteStore], ids=['json', 'sqlite'])
@pytest.mark.parametrize('configured', [False, True])
def test_trash_status_and_reconcile_remain_reachable_but_other_actions_are_blocked(tmp_path, monkeypatch, backend, configured):
    workspace = tmp_path / 'desktop'
    monkeypatch.setenv('THREADDESK_HOME', str(workspace))
    monkeypatch.setenv('THREADDESK_STORAGE', 'sqlite' if backend is SQLiteStore else 'json')
    core = ThreadService(backend(workspace))
    tid = core.create('Trash status').id
    if configured:
        files = tmp_path / 'files'
        files.mkdir()
        BindingBook(core).save(tid, url='https://server.example', project_id='project1', root=files,
                               token='private-owner-token-with-enough-length', automatic=False)
    stale = export_document(core, tid)
    service = TrashService(core.store)
    service.move(kind='thread', object_id=tid, expected_revision=core.get(tid).revision, operation_id='move')
    delayed = deepcopy(stale)
    delayed['thread']['notes'] = 'Late writer'
    synchronize(core, tid, 'late', stale, delayed)
    first = BindingBook(core).view(tid)
    assert first == BindingBook(core).view(tid)
    assert first['trashed'] and first['status']['state'] == 'blocked'
    assert first['thread_revision'] == core.store.get_thread(tid, include_trashed=True).revision
    assert first['local_metadata_conflicts'][0]['expected_current']['document_digest']
    client = UIClient(create_desktop())
    status = client.get(f'/api/threads/{tid}/server-sync')
    assert status.status_code == 200 and status.json()['trashed']
    page = client.get(f'/threads/{tid}/server-sync')
    assert page.status_code == 200
    assert 'name="action" value="resolve_local"' in page.text
    for action in ('configure', 'sync', 'offline'):
        assert f'name="action" value="{action}"' not in page.text
        response = client.post(f'/threads/{tid}/server-sync', data={'action':action})
        assert response.status_code == 409
    conflict = status.json()['local_metadata_conflicts'][0]
    response = client.post(f'/threads/{tid}/server-sync', data={
        'action':'resolve_local', 'conflict_id':conflict['id'], 'operation_id':conflict['operation_id'],
        'expected_current':json.dumps(conflict['expected_current']), 'chosen_value':json.dumps(conflict['current'])})
    assert response.status_code == 200
    assert client.get(f'/api/threads/{tid}/server-sync').json()['local_metadata_conflicts'] == []
    assert core.store.object_in_trash('thread', tid)
    with pytest.raises(ManagementError) as blocked:
        DesktopSyncManager(lambda: core).run_once(core, tid)
    assert blocked.value.code == 'object_in_trash'


@pytest.mark.parametrize('backend', [JsonStore, SQLiteStore], ids=['json', 'sqlite'])
def test_metadata_only_lifecycle_exchange_reuses_binding_without_files_or_offline_changes(tmp_path, monkeypatch, backend, remote_server):
    remote, token = remote_server
    headers = {'Authorization':'Bearer ' + token}
    pid = remote.post('/api/projects', json={'title':'Project'}, headers=headers).json()['id']
    core = ThreadService(backend(tmp_path / 'desktop'))
    tid = core.create('Project').id
    files = tmp_path / 'files'
    files.mkdir()
    original = files / 'Untouched.txt'
    original.write_text('Original bytes stay local')
    core.add_file(str(original), tid)
    book = BindingBook(core)
    book.save(tid, url='https://server.example', project_id=pid, root=files, token=token,
              automatic=False, offline_enabled=True)
    requests = []

    class MetadataOnlyHTTP:
        def __enter__(self):
            return self
        def __exit__(self, *arguments):
            pass
        def request(self, method, path, **options):
            requests.append((method, path))
            assert '/metadata' in path, 'Lifecycle exchange attempted a file/policy endpoint'
            return remote.request(method, path, **options)

    from threaddesk.server_sync import desktop, client
    monkeypatch.setattr(desktop, '_http_client', lambda **options: MetadataOnlyHTTP())
    def forbidden_client(*arguments, **options):
        raise AssertionError('No file SyncClient may be constructed')
    monkeypatch.setattr(client, 'SyncClient', forbidden_client)
    manager = DesktopSyncManager(lambda: core)
    assert manager.reconcile_lifecycle(core, tid)['state'] == 'metadata_only'
    service = TrashService(core.store)
    entry = service.move(kind='thread', object_id=tid, expected_revision=core.get(tid).revision,
                         operation_id='move')['entry']
    result = manager.reconcile_lifecycle(core, tid)
    assert result['mode'] == 'lifecycle_metadata' and result['files_transferred'] is False
    document = remote.get(f'/api/projects/{pid}/metadata', headers=headers).json()['document']
    assert document['lifecycle']['thread']['state'] == 'trashed'
    assert remote.get('/api/projects', headers=headers).json()['projects'] == []
    service.restore(trash_id=entry['trash_id'], generation=1, expected_revision=1, operation_id='restore')
    manager.reconcile_lifecycle(core, tid)
    document = remote.get(f'/api/projects/{pid}/metadata', headers=headers).json()['document']
    assert document['lifecycle']['thread']['state'] == 'restored'
    assert remote.get('/api/projects', headers=headers).json()['projects'][0]['id'] == pid
    assert book.load(tid)['offline_enabled'] is True and book.load(tid)['offline_pending'] is True
    assert not list((book.root / 'replicas').glob('**/files'))
    assert original.read_text() == 'Original bytes stay local'
    assert requests and all('/metadata' in path for _, path in requests)


@pytest.mark.parametrize('backend', [JsonStore, SQLiteStore], ids=['json', 'sqlite'])
def test_automatic_worker_routes_trash_to_metadata_without_blocking_live_project(tmp_path, monkeypatch, backend):
    workspace = tmp_path / 'desktop'
    core = ThreadService(backend(workspace))
    trashed = core.create('Trash project').id
    live = core.create('Live project').id
    files = tmp_path / 'files'
    files.mkdir()
    for tid in (trashed, live):
        BindingBook(core).save(tid, url='https://server.example', project_id='remote' + tid,
                              root=files, token='private-owner-token-with-enough-length', automatic=True)
    TrashService(core.store).move(kind='thread', object_id=trashed,
        expected_revision=core.get(trashed).revision, operation_id='move')
    manager = DesktopSyncManager(lambda: ThreadService(backend(workspace)))
    calls = []

    def observed(kind, service, tid):
        assert service.store.object_in_trash('thread', tid) is (kind == 'metadata')
        calls.append((kind, tid))
        if len(calls) == 2:
            manager.stop_event.set()
        return {'state':'metadata_only' if kind == 'metadata' else 'ready'}

    monkeypatch.setattr(manager, 'run_once', lambda service, tid: observed('files', service, tid))
    monkeypatch.setattr(manager, 'reconcile_lifecycle', lambda service, tid: observed('metadata', service, tid))
    manager._loop()
    assert set(calls) == {('metadata', trashed), ('files', live)}
