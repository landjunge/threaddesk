"""Only server authorization, shared-core persistence and real replica boundaries."""
import base64
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from threaddesk.server_sync.app import create_app
from threaddesk.server_sync.auth import provision
from threaddesk.server_sync.client import SyncClient
from threaddesk.server_sync.store import SyncStore


@pytest.fixture
def server(tmp_path):
    data = tmp_path / 'server'
    tokens = {u: provision(data, u) for u in ('alice', 'bob')}
    app = create_app(data, public_origin='https://testserver')
    with TestClient(app, base_url='https://testserver') as http:
        yield data, tokens, http


def auth(token):
    return {'Authorization': 'Bearer ' + token}


def new_project(http, token):
    response = http.post('/api/projects', headers=auth(token), json={'title': 'Research'})
    assert response.status_code == 200, response.text
    return response.json()['id']


def test_project_list_uses_the_title_synchronized_through_metadata(server):
    from copy import deepcopy
    _, tokens, http = server
    headers = auth(tokens['alice'])
    pid = new_project(http, tokens['alice'])
    base = http.get(f'/api/projects/{pid}/metadata',headers=headers).json()['document']
    incoming = deepcopy(base)
    incoming['thread']['title'] = 'Renamed from the desktop'
    response = http.post(f'/api/projects/{pid}/metadata/sync',headers=headers,
                         json={'operation_id':'rename-from-desktop','base':base,'document':incoming})
    assert response.status_code == 200, response.text
    assert response.json()['document']['thread']['title'] == incoming['thread']['title']
    for _ in range(2):
        listed = http.get('/api/projects',headers=headers).json()['projects']
        assert next(value for value in listed if value['id']==pid)['title'] == incoming['thread']['title']
    assert http.get('/api/projects',headers=auth(tokens['bob'])).json()['projects'] == []


def upload(http, token, pid, transfer, content, base=None, path='note.md'):
    endpoint = f'/api/projects/{pid}/uploads/{transfer}'
    headers = auth(token)
    response = http.post(endpoint, headers=headers, json={'path': path, 'size': len(content),
                         'sha256': hashlib.sha256(content).hexdigest(), 'base_revision': base})
    assert response.status_code == 200, response.text
    if content:
        response = http.patch(endpoint, headers=headers, json={'offset': 0, 'data_base64': base64.b64encode(content).decode()})
        assert response.status_code == 200, response.text
    response = http.post(endpoint + '/commit', headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_server_scope_cookie_csrf_and_transport(server):
    data, tokens, http = server
    assert http.get('/api/projects').status_code == 401
    login = http.post('/auth/login', json={'token': tokens['alice']})
    assert login.status_code == 200
    assert 'HttpOnly' in login.headers['set-cookie'] and 'Secure' in login.headers['set-cookie']
    assert http.post('/api/projects', json={'title': 'blocked'}).status_code == 403
    csrf = {'X-ThreadDesk-CSRF': login.json()['csrf']}
    assert http.post('/api/projects', headers={**csrf, 'Origin': 'https://foreign.example'}, json={'title': 'blocked'}).status_code == 403
    pid = http.post('/api/projects', headers=csrf, json={'title': 'Private'}).json()['id']
    assert http.get(f'/api/projects/{pid}/status', headers=auth(tokens['bob'])).status_code == 404
    assert http.get('/api/projects', headers=auth(tokens['bob'])).json()['projects'] == []
    assert http.get('/api/projects', headers={'Authorization': 'Bearer wrong'}).status_code == 401
    assert http.get('/api/projects', headers={**auth(tokens['alice']), 'Host': 'evil.example'}).status_code == 400
    insecure = TestClient(create_app(data, public_origin='https://testserver'), base_url='http://testserver')
    assert insecure.get('/api/projects', headers=auth(tokens['alice'])).status_code == 403
    with pytest.raises(ValueError):
        create_app(data, public_origin='http://testserver')
    with pytest.raises(ValueError):
        provision(data, 'alice')


def test_api_integrity_metadata_default_and_retained_versions(server):
    data, tokens, http = server
    token = tokens['alice']; headers = auth(token)
    pid = new_project(http, token); api = f'/api/projects/{pid}'
    refused = http.post(api+'/uploads/x', headers=headers, json={'path':'note.md','size':1,'sha256':hashlib.sha256(b'x').hexdigest()})
    assert refused.status_code == 409
    assert http.get(api+'/files', headers=headers).json() == {'files': []}
    assert http.put(api+'/offline', headers=headers, json={'enabled':'yes'}).status_code == 400
    assert http.put(api+'/offline', headers=headers, json={'enabled':True}).status_code == 200
    first = upload(http, token, pid, 'first', b'original')
    other = upload(http, token, pid, 'second', b'remote', first['revision'])
    conflict = upload(http, token, pid, 'third', b'local', first['revision'])
    assert http.get(api+'/status', headers=headers).json()['state'] == 'conflict'
    assert http.get(api+'/revisions/'+first['revision'], headers=headers).content == b'original'
    heads = http.get(api+'/files', headers=headers).json()['files'][0]['heads']
    assert len(heads) == 2
    request = {'path':'note.md','expected_heads':[h['revision'] for h in heads], 'chosen_revision':other['revision']}
    assert http.post(api+'/resolve',headers=headers,json=request).status_code == 200
    assert http.post(api+'/resolve',headers=headers,json=request).status_code == 409
    history = http.get(api+'/history',params={'path':'note.md'},headers=headers).json()['versions']
    assert len(history) == 3
    assert http.get(api+'/revisions/'+conflict['revision'],headers=headers).content == b'local'
    assert http.put(api+'/offline', headers=headers, json={'enabled':False}).status_code == 200
    assert http.get(api+'/revisions/'+first['revision'], headers=headers).content == b'original'
    other_pid = new_project(http, token)
    assert http.get(f'/api/projects/{other_pid}/revisions/'+first['revision'],headers=headers).status_code == 404
    # Disabled mode cannot finish a new staged version; abort frees its reservation.
    http.put(api+'/offline',headers=headers,json={'enabled':True})
    pending=api+'/uploads/unfinished'
    assert http.post(pending,headers=headers,json={'path':'empty.md','size':0,'sha256':hashlib.sha256(b'').hexdigest()}).status_code==200
    assert http.get(api+'/uploads',headers=headers).json()['uploads'][0]['transfer_id']=='unfinished'
    http.put(api+'/offline',headers=headers,json={'enabled':False})
    assert http.post(pending+'/commit',headers=headers).status_code==409
    assert http.post(pending+'/abort',headers=headers).json()['state']=='aborted'
    assert http.post(pending+'/commit',headers=headers).status_code==409
    assert http.get(api+'/status',headers=headers).json()['active_transfers']==0
    assert http.post(api+'/uploads/first/abort',headers=headers).json()['receipt']==first
    absent=api+'/uploads/delayed-begin'
    assert http.post(absent+'/abort',headers=headers).json()['state']=='aborted'
    http.put(api+'/offline',headers=headers,json={'enabled':True})
    delayed=http.post(absent,headers=headers,json={'path':'late.md','size':0,'sha256':hashlib.sha256(b'').hexdigest()})
    assert delayed.status_code==200 and delayed.json()['state']=='aborted'
    assert http.post(absent+'/commit',headers=headers).status_code==409
    assert http.get(api+'/status',headers=headers).json()['active_transfers']==0


def test_shared_core_notes_cas_and_append_only_whiteboard(server):
    data, tokens, http = server
    headers = auth(tokens['alice']); pid = new_project(http,tokens['alice']); api=f'/api/projects/{pid}'
    thread = http.get(api+'/thread',headers=headers).json()
    value = {'revision':thread['revision'],'description':'Project','notes':'First notes'}
    saved = http.put(api+'/thread',headers=headers,json=value)
    assert saved.status_code == 200, saved.text
    assert http.put(api+'/thread',headers=headers,json=value).status_code == 409
    value.update(revision=saved.json()['revision'],description='New description',notes='New notes')
    assert http.put(api+'/thread',headers=headers,json=value).status_code == 200
    snapshots = list((data/'users/alice/core/snapshots'/pid).glob('*.json'))
    assert any('First notes' in p.read_text() and 'Project' in p.read_text() for p in snapshots)
    entry={'content':'Remember this','entry_type':'task','external_key':'stable-key'}
    result=http.post(api+'/whiteboard',headers=headers,json=entry)
    assert result.status_code == 200, result.text
    assert http.post(api+'/whiteboard',headers=headers,json=entry).json()['duplicate']
    assert len(http.get(api+'/whiteboard',headers=headers).json()['entries']) == 1
    # Valid existing 100000-character Unicode notes pass the actual bounded HTTP boundary.
    from copy import deepcopy
    baseline=http.get(api+'/metadata',headers=headers).json()['document']
    incoming=deepcopy(baseline);incoming['thread']['notes']='😀'*100000
    synced=http.post(api+'/metadata/sync',headers=headers,json={
        'operation_id':'unicode-http','base':baseline,'document':incoming})
    assert synced.status_code==200,synced.text[:200]
    assert http.get(api+'/thread',headers=headers).json()['context']['notes']=='😀'*100000


def test_actual_two_clients_new_files_reconnect_conflict_and_originals(server,tmp_path):
    data,tokens,http=server; token=tokens['alice'];headers=auth(token)
    pid=new_project(http,token);api=f'/api/projects/{pid}'
    one=tmp_path/'one';two=tmp_path/'two';one.mkdir();two.mkdir()
    (one/'note.md').write_text('initial')
    a=SyncClient('https://testserver',token,pid,one,state_dir=tmp_path/'state-a',transport=http)
    b=SyncClient('https://testserver',token,pid,two,state_dir=tmp_path/'state-b',transport=http)
    try:
        assert a.sync_once()['state'] == 'metadata_only'
        assert http.get(api+'/files',headers=headers).json()['files'] == []
        http.put(api+'/offline',headers=headers,json={'enabled':True})
        assert a.sync_once()['state'] == 'ready'
        b.sync_once(); assert (two/'note.md').read_text() == 'initial'
        (one/'later.md').write_text('new file');a.sync_once();b.sync_once()
        assert (two/'later.md').read_text() == 'new file'
        (one/'note.md').write_text('A offline');(two/'note.md').write_text('B offline')
        a.sync_once();result=b.sync_once();assert result['state'] == 'conflict'
        assert (one/'note.md').read_text() == 'A offline'
        assert (two/'note.md').read_text() == 'B offline'
        retained=[p.read_bytes() for p in (two/'.threaddesk-sync-conflicts/remote').glob('*')]
        assert b'A offline' in retained
        assert len(http.get(api+'/history',params={'path':'note.md'},headers=headers).json()['versions']) == 3
        # Restart both private journals, then re-read persisted conflict state.
        a.close(); b.close()
        a=SyncClient('https://testserver',token,pid,one,state_dir=tmp_path/'state-a',transport=http)
        assert a.sync_once()['state'] == 'conflict'
        assert (one/'note.md').read_text() == 'A offline'
    finally:
        a.close()
        # b was closed before restart, so only close it on the earlier failure path.
        try: b.close()
        except Exception: pass


def test_large_bounded_manifest_handles_header_and_stream_without_enlarging_uploads(server,monkeypatch):
    import json
    from threaddesk.server_sync import app as module
    _,tokens,http=server;token=tokens['alice'];headers=auth(token)
    pid=new_project(http,token);uri=f'/api/projects/{pid}'
    value={'device_id':'many-files','issues':[], 'files':[
        {'path':f'file-{i:05}.txt','size':1,'sha256':hashlib.sha256(b'x').hexdigest()} for i in range(5000)]}
    encoded=json.dumps(value,separators=(',',':')).encode()
    assert len(encoded)>module.MAX_BODY
    response=http.post(uri+'/manifest',headers=headers,json=value)
    assert response.status_code==200,response.text
    assert len(response.json()['missing_files'])==5000 and response.json()['required_bytes']==5000
    chunks=(encoded[offset:offset+8192] for offset in range(0,len(encoded),8192))
    response=http.post(uri+'/manifest',headers={**headers,'Content-Type':'application/json'},content=chunks)
    assert response.status_code==200,response.text
    # Transfer endpoints retain their original 512 KiB body boundary.
    response=http.post(uri+'/uploads/not-created',headers={**headers,'Content-Type':'application/json'},
                       content=b' '*(module.MAX_BODY+1))
    assert response.status_code==413
    assert http.get(uri+'/uploads',headers=headers).json()['uploads']==[]
    # Exercise the same bounded stream guard without allocating a 96 MiB test body.
    monkeypatch.setattr(module,'MAX_MANIFEST_BODY',64)
    response=http.post(uri+'/manifest',headers={**headers,'Content-Type':'application/json'},
                       content=(b' '*40 for _ in range(2)))
    assert response.status_code==413
    assert http.get(uri+'/status',headers=headers).json()['required_bytes']==5000
