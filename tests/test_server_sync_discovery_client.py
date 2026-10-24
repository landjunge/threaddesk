"""Real protected API integration for mapped originals and metadata/file ordering."""
import base64
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from threaddesk.api.service import ThreadService
from threaddesk.server_sync.app import create_app
from threaddesk.server_sync.auth import provision
from threaddesk.server_sync.client import ClientError, SyncClient
from threaddesk.server_sync.metadata import MetadataReplica
from threaddesk.storage.json_store import JsonStore


@pytest.fixture
def server(tmp_path):
    data = tmp_path / 'server'
    token = provision(data, 'alice')
    with TestClient(create_app(data, public_origin='https://testserver'), base_url='https://testserver') as http:
        yield http, token


def auth(token):
    return {'Authorization': 'Bearer ' + token}


def project(http, token, *, binding='discovery-integration'):
    response = http.post('/api/projects/bind', headers=auth(token), json={'title': 'Research', 'binding_id': binding})
    assert response.status_code == 200, response.text
    result = response.json()
    assert http.put('/api/projects/'+result['id']+'/offline', headers=auth(token), json={'enabled': True}).status_code == 200
    return result


def publish(http, token, pid, path, data, *, base=None, transfer='remote-change'):
    uri = '/api/projects/'+pid+'/uploads/'+transfer
    response = http.post(uri, headers=auth(token), json={'path':path, 'size':len(data),
                         'sha256':hashlib.sha256(data).hexdigest(), 'base_revision':base})
    assert response.status_code == 200, response.text
    if data:
        assert http.patch(uri, headers=auth(token), json={'offset':0,'data_base64':base64.b64encode(data).decode()}).status_code == 200
    response = http.post(uri+'/commit', headers=auth(token))
    assert response.status_code == 200, response.text
    return response.json()


def remote_files(http, token, pid):
    return http.get('/api/projects/'+pid+'/files', headers=auth(token)).json()['files']


def test_external_originals_update_bidirectionally_and_keep_same_filesystem_recovery(server, tmp_path):
    http, token = server
    bound = project(http, token); pid=bound['id']
    root=tmp_path/'project';root.mkdir()
    docs=tmp_path/'authorized-documents';docs.mkdir()
    (docs/'nested').mkdir();original=docs/'nested/context.txt';original.write_text('original external bytes')
    with pytest.raises(ClientError, match='outside all approved'):
        SyncClient('https://testserver',token,pid,root,state_dir=docs/'private-state',transport=http,
                   approved_roots={'documents':docs})
    assert not (docs/'private-state').exists()
    client=SyncClient('https://testserver',token,pid,root,state_dir=tmp_path/'state',transport=http,
                      approved_roots={'documents':docs})
    try:
        first=client.sync_once()
        assert first['state']=='ready' and first['external_file_count']==1
        item=remote_files(http,token,pid)[0]; logical=item['path']
        assert logical.startswith('_external/')
        second=publish(http,token,pid,logical,b'server edit',base=item['heads'][0]['revision'])
        assert client.sync_once()['state']=='ready'
        assert original.read_bytes()==b'server edit'
        assert not (root/'_external').exists()
        assert any(p.read_bytes()==b'original external bytes' for p in (docs/'nested/.threaddesk-sync-conflicts/previous').glob('*.copy'))
        # A known directory namespace permits server-created files inside that grant.
        new_logical=logical.rsplit('/',1)[0]+'/later.txt'
        publish(http,token,pid,new_logical,b'new from server',transfer='remote-added')
        assert client.sync_once()['state']=='ready'
        assert (docs/'nested/later.txt').read_bytes()==b'new from server'
        # Concurrent edits keep the chosen original and a mapped recovery copy.
        original.write_bytes(b'local concurrent edit')
        publish(http,token,pid,logical,b'remote concurrent edit',base=second['revision'],transfer='remote-concurrent')
        assert client.sync_once()['state']=='conflict'
        assert original.read_bytes()==b'local concurrent edit'
        assert any(p.read_bytes()==b'remote concurrent edit' for p in (docs/'nested/.threaddesk-sync-conflicts/remote').glob('*.copy'))
    finally:
        client.close()


def test_exact_file_grant_and_revocation_cannot_expand_to_siblings_or_unknown_namespace(server,tmp_path):
    http,token=server;pid=project(http,token)['id']
    root=tmp_path/'project';root.mkdir()
    docs=tmp_path/'docs';docs.mkdir();original=docs/'context.txt';original.write_bytes(b'local original')
    client=SyncClient('https://testserver',token,pid,root,state_dir=tmp_path/'state',transport=http,local_references=[original])
    assert client.sync_once()['state']=='ready'
    item=remote_files(http,token,pid)[0];logical=item['path']
    sibling=logical.rsplit('/',1)[0]+'/unapproved.txt'
    publish(http,token,pid,sibling,b'must not appear locally',transfer='remote-sibling')
    publish(http,token,pid,'_external/unknown-root/host.txt',b'unknown destination',transfer='remote-unknown')
    result=client.sync_once()
    assert result['state']!='ready' and any('approved original destination' in issue for issue in result['local_issues'])
    assert not (docs/'unapproved.txt').exists() and not (root/'_external').exists()
    client.close()
    # A cached mapping is never authority after the explicit grant is removed.
    publish(http,token,pid,logical,b'remote after revocation',base=item['heads'][0]['revision'],transfer='remote-revoked')
    revoked=SyncClient('https://testserver',token,pid,root,state_dir=tmp_path/'state',transport=http)
    try:
        assert revoked.sync_once()['state']!='ready'
        assert original.read_bytes()==b'local original'
    finally:
        revoked.close()


def test_real_metadata_replica_runs_first_and_unresolved_conflicts_persist_in_status(server,tmp_path):
    http,token=server;bound=project(http,token);pid=bound['id'];api='/api/projects/'+pid
    root=tmp_path/'project';root.mkdir();(root/'note.txt').write_text('project bytes')
    external=tmp_path/'context.txt';external.write_text('explicit local context')
    core=ThreadService(JsonStore(tmp_path/'local-core'));thread=core.create('Research')
    with core.store.transaction():
        local=core.get(thread.id);local.context.files=[str(external)];local.context.notes='local first notes';core.store.save_thread(local)
    replica=MetadataReplica(core,thread.id,tmp_path/'metadata',remote_identity='testserver:'+pid)
    assert replica.seed_base(bound['bootstrap_document'])

    class Recording:
        def __init__(self):self.paths=[]
        def request(self,method,path,**kwargs):
            self.paths.append(path)
            return http.request(method,path,**kwargs)

    recording=Recording()
    client=SyncClient('https://testserver',token,pid,root,state_dir=tmp_path/'files',transport=recording,
                      metadata_replica=replica,local_references=[external])
    try:
        assert client.sync_once()['state']=='ready'
        assert recording.paths[0]==api+'/metadata/sync'
        assert http.get(api+'/thread',headers=auth(token)).json()['context']['notes']=='local first notes'
        assert any(item['path'].startswith('_external/') for item in remote_files(http,token,pid))
        with core.store.transaction():
            local=core.get(thread.id);local.context.notes='local concurrent notes';core.store.save_thread(local)
        remote=http.get(api+'/thread',headers=auth(token)).json()
        assert http.put(api+'/thread',headers=auth(token),json={'revision':remote['revision'],'description':remote['description'],'notes':'remote concurrent notes'}).status_code==200
        first=client.sync_once()
        assert first['state']=='conflict' and first['metadata_conflict_count']>0
        # Subsequent exchange creates no fresh conflict but the unresolved journal
        # must continue to show up through the protected persistent status route.
        later=client.sync_once()
        assert later['state']=='conflict' and later['metadata_conflict_count']>0
        assert later['remote_metadata_conflict_count']>0
        assert external.read_text()=='explicit local context'
    finally:
        client.close();replica.close()
