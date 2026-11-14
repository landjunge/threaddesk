"""Real receiver bytes stay tenant/project bound across browser library reads."""
import base64
import hashlib

import pytest
from fastapi.testclient import TestClient

from threaddesk.api.service import ThreadService
from threaddesk.server_sync.app import create_app
from threaddesk.server_sync.auth import provision
from threaddesk.services.library_files import LibraryFileService
from threaddesk.services.mcp import McpBridge
from threaddesk.storage.json_store import JsonStore


@pytest.fixture
def library(tmp_path):
    data = tmp_path / 'server'
    tokens = {user: provision(data, user) for user in ('alice', 'bob')}
    app = create_app(data, public_origin='https://testserver')
    with TestClient(app, base_url='https://testserver') as http:
        headers = {'Authorization': 'Bearer ' + tokens['alice']}
        pid = http.post('/api/projects', headers=headers, json={'title': 'Library test'}).json()['id']
        other = http.post('/api/projects', headers=headers, json={'title': 'Other project'}).json()['id']
        svc = ThreadService(JsonStore(data / 'users/alice/core'))
        bridge = McpBridge(svc)
        content = b'library-byte-proof <script>alert(1)</script>\n'
        calls = [
            {'action': 'begin', 'transfer_id': 'web-library-test', 'thread_id': pid,
             'filename': 'proof.txt', 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()},
            {'action': 'append', 'transfer_id': 'web-library-test', 'offset': 0,
             'data_base64': base64.b64encode(content).decode()},
            {'action': 'commit', 'transfer_id': 'web-library-test'},
        ]
        for arguments in calls:
            received = bridge.call('library_receive', arguments)
            assert received['ok'], received
        receipt = received['result']['receipt']
        yield http, tokens, headers, svc, pid, other, receipt['record_id'], content


def test_library_list_search_and_exact_inert_download(library):
    http, _, headers, _, pid, _, rid, content = library
    listed = http.get(f'/api/projects/{pid}/library', headers=headers)
    assert listed.status_code == 200
    row = listed.json()['records'][0]
    assert row['id'] == rid and row['filename'] == 'proof.txt' and row['size'] == len(content)
    assert 'origin_path' not in row
    searched = http.get(f'/api/projects/{pid}/library?query=library-byte-proof', headers=headers)
    assert searched.status_code == 200
    assert [row['id'] for row in searched.json()['records']] == [rid]
    for route in (row['download_path'], f'/library/files/{rid}'):
        response = http.get(route, headers=headers)
        assert response.status_code == 200
        assert response.content == content
        assert response.headers['content-type'] == 'application/octet-stream'
        assert response.headers['content-disposition'].startswith('attachment;')
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert response.headers['cache-control'] == 'no-store'
        assert 'sandbox' in response.headers['content-security-policy']


def test_library_search_reports_another_page_without_inventing_a_total(library):
    http, _, headers, svc, pid, _, first, _ = library
    content = b'library-byte-proof another matching document\n'
    bridge = McpBridge(svc)
    for arguments in [
        {'action': 'begin', 'transfer_id': 'web-library-second', 'thread_id': pid,
         'filename': 'second.txt', 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()},
        {'action': 'append', 'transfer_id': 'web-library-second', 'offset': 0,
         'data_base64': base64.b64encode(content).decode()},
        {'action': 'commit', 'transfer_id': 'web-library-second'},
    ]:
        received = bridge.call('library_receive', arguments)
        assert received['ok'], received
    second = received['result']['receipt']['record_id']
    one = http.get(f'/api/projects/{pid}/library?query=library-byte-proof&limit=1', headers=headers).json()
    assert len(one['records']) == 1 and one['total'] is None and one['next_offset'] == 1
    two = http.get(f'/api/projects/{pid}/library?query=library-byte-proof&limit=1&offset=1', headers=headers).json()
    assert two['total'] is None and two['next_offset'] is None
    assert {row['id'] for row in one['records'] + two['records']} == {first, second}


def test_library_search_preserves_a_full_last_owner_offset_page(library, monkeypatch):
    from threaddesk.services.library_index import LibraryIndex
    http, _, headers, _, pid, _, rid, _ = library
    offsets = []
    original = LibraryIndex.search

    def last_page(index, query, **arguments):
        offsets.append(arguments['offset'])
        if arguments['offset'] == 10000:
            return [{'id': rid, 'record_id': rid, 'filename': 'proof.txt', 'size': 1}]
        return original(index, query, **arguments)

    monkeypatch.setattr(LibraryIndex, 'search', last_page)
    response = http.get(f'/api/projects/{pid}/library?query=proof&limit=1&offset=10000', headers=headers)
    assert response.status_code == 200
    assert response.json()['records'][0]['id'] == rid
    assert response.json()['next_offset'] is None
    assert offsets == [10000], 'The valid page must not probe an unsupported next offset'
    assert http.get(f'/api/projects/{pid}/library?query=proof&offset=10001', headers=headers).status_code == 422
    assert offsets == [10000]


def test_library_auth_tls_foreign_user_and_project(library):
    http, tokens, headers, _, pid, other, rid, _ = library
    routes = (f'/api/projects/{pid}/library', f'/api/projects/{pid}/library/{rid}', f'/library/files/{rid}')
    for route in routes:
        assert http.get(route).status_code == 401
        assert http.get(route, headers={'Authorization': 'Bearer wrong'}).status_code == 401
        assert http.get(route, headers={'Authorization': 'Bearer ' + tokens['bob']}).status_code == 404
        assert http.get('http://testserver' + route, headers=headers).status_code == 403
        assert http.get(route, headers={**headers, 'Origin': 'https://foreign.example'}).status_code == 403
    assert http.get(f'/api/projects/{other}/library/{rid}', headers=headers).status_code == 404
    assert http.get(f'/api/projects/{pid}/library/not-an-id', headers=headers).status_code == 404
    assert http.get(f'/api/projects/{pid}/library?limit=101', headers=headers).status_code == 422


def test_library_cookie_read_and_owner_cleanup(library):
    http, tokens, headers, svc, pid, _, rid, _ = library
    http.post('/auth/login', json={'token': tokens['alice']})
    assert http.get(f'/library/files/{rid}').status_code == 200
    files = LibraryFileService(svc.store)
    revision = files.info(rid)['revision']
    files.manage({'action': 'trash', 'id': rid, 'operation_id': 'web-library-cleanup',
                  'expected_revision': revision, 'data': {}})
    assert http.get(f'/api/projects/{pid}/library', headers=headers).json()['records'] == []
    assert http.get(f'/api/projects/{pid}/library?query=library-byte-proof', headers=headers).json()['records'] == []
    for route in (f'/api/projects/{pid}/library/{rid}', f'/library/files/{rid}'):
        assert http.get(route, headers=headers).status_code == 404


def test_library_download_rejects_modified_stored_bytes(library):
    http, _, headers, svc, pid, _, rid, _ = library
    files = LibraryFileService(svc.store)
    blob, _ = files.importer.open_record(rid)
    blob.write_bytes(b'changed bytes')
    for route in (f'/api/projects/{pid}/library/{rid}', f'/library/files/{rid}'):
        response = http.get(route, headers=headers)
        assert response.status_code == 409
        assert b'changed bytes' not in response.content
