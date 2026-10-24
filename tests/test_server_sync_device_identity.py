"""Binding reporter migration and root-bound checkpoints without stale manifests."""
import base64
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from threaddesk.api.service import ThreadService
from threaddesk.server_sync.app import create_app
from threaddesk.server_sync.auth import provision
from threaddesk.server_sync.client import ClientError, SyncClient
from threaddesk.server_sync.desktop import BindingBook, DesktopSyncManager
from threaddesk.server_sync.identity import (IdentityError, recover_binding_bases,
    recover_binding_device_id)
from threaddesk.storage.json_store import JsonStore


def state_paths(private_root, thread_id, config):
    remote=config['url']+'\0'+config['project_id']+'\0'+hashlib.sha256(config['token'].encode()).hexdigest()
    files=private_root/'replicas'/thread_id/hashlib.sha256(remote.encode()).hexdigest()/'files'
    current=files/hashlib.sha256(config['root'].encode()).hexdigest()
    return current, files


def transport():
    return httpx.Client(base_url='https://server.example',transport=httpx.MockTransport(lambda request:httpx.Response(404)))


def test_explicit_reporter_and_pristine_seeds_never_reset_existing_checkpoint(tmp_path):
    root=tmp_path/'files';root.mkdir()
    seeds=[{'path':'note.txt','revision':'initial-revision','sha256':hashlib.sha256(b'initial').hexdigest()}]
    http=transport()
    client=SyncClient('https://server.example','token-value','project',root,state_dir=tmp_path/'state',transport=http,
                      device_id='binding-device',initial_bases=seeds)
    assert client.device_id=='binding-device' and client._base('note.txt')['revision']=='initial-revision'
    with client.db:
        client.db.execute('UPDATE base SET revision=?',('later-common-revision',))
        client.db.execute('INSERT INTO uploads VALUES (?,?,?,?)',('note.txt',seeds[0]['sha256'],'later-common-revision','pending-transfer'))
    client.close()
    again=SyncClient('https://server.example','token-value','project',root,state_dir=tmp_path/'state',transport=http,
                    device_id='binding-device',initial_bases=seeds)
    assert again._base('note.txt')['revision']=='later-common-revision'
    assert again.db.execute('SELECT transfer FROM uploads').fetchone()[0]=='pending-transfer'
    again.close()
    with pytest.raises(ClientError,match='different synchronization device'):
        SyncClient('https://server.example','token-value','project',root,state_dir=tmp_path/'state',transport=http,device_id='different-device')
    moved=tmp_path/'moved';moved.mkdir()
    with pytest.raises(ClientError,match='different server, account, project or directory'):
        SyncClient('https://server.example','token-value','project',moved,state_dir=tmp_path/'state',transport=http,
                   device_id='binding-device',initial_bases=seeds)
    for invalid in ('../not-a-device',42,''):
        with pytest.raises(IdentityError):
            SyncClient('https://server.example','token-value','project',root,state_dir=tmp_path/'invalid',transport=http,device_id=invalid)
    assert not (tmp_path/'invalid').exists()
    http.close()


@pytest.mark.parametrize('legacy',[False,True],ids=['root-bound','legacy'])
def test_existing_checkpoint_identity_recovery_is_readonly_and_scope_checked(tmp_path,legacy):
    root=tmp_path/'files';root.mkdir()
    private=tmp_path/'private';private.mkdir(mode=0o700)
    config={'url':'https://server.example','project_id':'project','root':str(root),'token':'token-value'}
    current,old=state_paths(private,'thread',config)
    target=old if legacy else current
    seed=[{'path':'note.txt','revision':'committed-revision','sha256':hashlib.sha256(b'initial').hexdigest()}]
    http=transport()
    client=SyncClient(config['url'],config['token'],config['project_id'],root,state_dir=target,transport=http,
                      device_id='existing-reporter',initial_bases=seed)
    with client.db:
        client.db.execute('INSERT INTO uploads VALUES (?,?,?,?)',('note.txt',seed[0]['sha256'],'committed-revision','unpublished'))
        client.db.execute('INSERT INTO sources VALUES (?,?,?)',('note.txt',str(root),'note.txt'))
    client.close()
    checkpoint=target/'checkpoint.sqlite3';before=hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    assert recover_binding_device_id(private,'thread',config)=='existing-reporter'
    assert recover_binding_bases(private,'thread',config)==seed
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest()==before
    assert set(recover_binding_bases(private,'thread',config)[0])=={'path','revision','sha256'}
    with sqlite3.connect(checkpoint) as db:
        db.execute('UPDATE identity SET value=?',('poisoned-binding',))
    with pytest.raises(IdentityError,match='different binding'):
        recover_binding_device_id(private,'thread',config)
    http.close()


class BorrowedHTTP:
    def __init__(self,http,headers):self.http,self.headers=http,headers
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def request(self,method,path,**kwargs):
        return self.http.request(method,path,headers={**self.headers,**kwargs.pop('headers',{})},**kwargs)
    def post(self,path,**kwargs):return self.request('POST',path,**kwargs)
    def put(self,path,**kwargs):return self.request('PUT',path,**kwargs)


def publish(http,headers,pid,data,base):
    uri='/api/projects/'+pid+'/uploads/concurrent-server-change'
    assert http.post(uri,headers=headers,json={'path':'note.txt','size':len(data),'sha256':hashlib.sha256(data).hexdigest(),
                    'base_revision':base}).status_code==200
    assert http.patch(uri,headers=headers,json={'offset':0,'data_base64':base64.b64encode(data).decode()}).status_code==200
    result=http.post(uri+'/commit',headers=headers)
    assert result.status_code==200,result.text
    return result.json()


@pytest.mark.parametrize('mode',['edit-before-first-sync','copy-then-edit','concurrent-remote'])
def test_desktop_root_relocation_retains_one_reporter_and_all_versions(tmp_path,monkeypatch,mode):
    data=tmp_path/'server';token=provision(data,'alice')
    app=create_app(data,public_origin='https://server.example')
    core=ThreadService(JsonStore(tmp_path/'desktop'));tid=core.create('Project').id
    files=tmp_path/'files';files.mkdir();(files/'note.txt').write_bytes(b'original')
    book=BindingBook(core)
    book.save(tid,url='https://server.example',project_id='',root=files,token=token,automatic=False,offline_enabled=True)
    manager=DesktopSyncManager(lambda:core)
    with TestClient(app,base_url='https://server.example') as server:
        monkeypatch.setattr('threaddesk.server_sync.desktop._http_client',lambda **kwargs:BorrowedHTTP(server,kwargs['headers']))
        assert manager.run_once(core,tid)['state']=='ready'
        initial=book.load(tid);reporter=initial['device_id'];pid=initial['project_id'];api='/api/projects/'+pid
        headers={'Authorization':'Bearer '+token}
        original=server.get(api+'/files',headers=headers).json()['files'][0]['heads'][0]
        if mode=='concurrent-remote':
            publish(server,headers,pid,b'remote concurrent',original['revision'])
        moved=tmp_path/'moved';shutil.copytree(files,moved)
        if mode!='copy-then-edit':
            (moved/'note.txt').write_bytes(b'local moved edit')
        book.save(tid,url='https://server.example',project_id=pid,root=moved,token='',automatic=False,offline_enabled=True)
        assert book.load(tid)['device_id']==reporter
        if mode=='copy-then-edit':
            assert manager.run_once(core,tid)['state']=='ready'
            (moved/'note.txt').write_bytes(b'local moved edit')
        result=manager.run_once(core,tid)
        assert result['state']==('conflict' if mode=='concurrent-remote' else 'ready'),result
        assert result['manifest_count']==1
        assert (files/'note.txt').read_bytes()==b'original'
        assert (moved/'note.txt').read_bytes()==b'local moved edit'
        assert server.get(api+'/revisions/'+original['revision'],headers=headers).content==b'original'
        versions=server.get(api+'/history',headers=headers,params={'path':'note.txt'}).json()['versions']
        assert len(versions)==(3 if mode=='concurrent-remote' else 2)
        heads=server.get(api+'/files',headers=headers).json()['files'][0]['heads']
        assert len(heads)==(2 if mode=='concurrent-remote' else 1)
        old_state,_=state_paths(book.root,tid,initial)
        new_state,_=state_paths(book.root,tid,book.load(tid))
        assert old_state!=new_state
        with sqlite3.connect(old_state/'checkpoint.sqlite3') as old_db, sqlite3.connect(new_state/'checkpoint.sqlite3') as new_db:
            assert old_db.execute('SELECT id FROM device').fetchone()[0]==new_db.execute('SELECT id FROM device').fetchone()[0]==reporter
            assert old_db.execute('SELECT value FROM identity').fetchone()[0]!=new_db.execute('SELECT value FROM identity').fetchone()[0]


@pytest.mark.parametrize('legacy',[False,True],ids=['old-root-bound','old-legacy'])
def test_desktop_existing_configuration_without_reporter_migrates_without_stale_manifest(tmp_path,monkeypatch,legacy):
    data=tmp_path/'server';token=provision(data,'alice');app=create_app(data,public_origin='https://server.example')
    core=ThreadService(JsonStore(tmp_path/'desktop'));tid=core.create('Project').id
    files=tmp_path/'files';files.mkdir();(files/'note.txt').write_bytes(b'original')
    book=BindingBook(core)
    book.save(tid,url='https://server.example',project_id='',root=files,token=token,automatic=False,offline_enabled=True)
    manager=DesktopSyncManager(lambda:core)
    with TestClient(app,base_url='https://server.example') as server:
        monkeypatch.setattr('threaddesk.server_sync.desktop._http_client',lambda **kwargs:BorrowedHTTP(server,kwargs['headers']))
        assert manager.run_once(core,tid)['state']=='ready'
        config=book.load(tid);reporter=config.pop('device_id')
        current,previous=state_paths(book.root,tid,config)
        if legacy:
            (current/'checkpoint.sqlite3').rename(previous/'checkpoint.sqlite3')
        config_path=book.root/(tid+'.json')
        config_path.write_text(json.dumps(config))
        assert manager.run_once(core,tid)['state']=='ready'
        assert book.load(tid)['device_id']==reporter
        (files/'note.txt').write_bytes(b'edit after migration')
        result=manager.run_once(core,tid)
        assert result['state']=='ready' and result['manifest_count']==1,result


def test_blank_automatic_form_replay_keeps_reporter_but_token_change_cannot_seed_account(tmp_path,monkeypatch):
    data=tmp_path/'server';token=provision(data,'alice');app=create_app(data,public_origin='https://server.example')
    core=ThreadService(JsonStore(tmp_path/'desktop'));tid=core.create('Project').id
    files=tmp_path/'files';files.mkdir();(files/'note.txt').write_bytes(b'original')
    book=BindingBook(core)
    original_form={'url':'https://server.example','project_id':'','root':files,'token':token,
                   'automatic':False,'offline_enabled':True}
    book.save(tid,**original_form)
    manager=DesktopSyncManager(lambda:core)
    with TestClient(app,base_url='https://server.example') as server:
        monkeypatch.setattr('threaddesk.server_sync.desktop._http_client',lambda **kwargs:BorrowedHTTP(server,kwargs['headers']))
        assert manager.run_once(core,tid)['state']=='ready'
        first=book.load(tid)
        # A browser POST reload replays the original blank-PID form, although the
        # first run has since saved the server's deterministic automatic PID.
        repeated=book.save(tid,**original_form)
        assert repeated['project_id']==first['project_id']
        assert repeated['device_id']==first['device_id']
        observed=manager.run_once(core,tid)
        assert observed['state']=='ready' and observed['manifest_count']==1,observed
        api='/api/projects/'+first['project_id']
        head=server.get(api+'/files',headers={'Authorization':'Bearer '+token}).json()['files'][0]['heads'][0]
        book.update(tid,{'initial_bases':[{'path':'note.txt','revision':head['revision'],'sha256':head['sha256']}]})
        different_account=book.save(tid,url=first['url'],project_id=first['project_id'],root=files,
                                    token='different-account-token-value-12345',automatic=False,offline_enabled=True)
        assert different_account['initial_bases']==[]
        assert different_account['device_id']!=first['device_id']


def test_blank_project_does_not_reuse_an_unrelated_manual_binding(tmp_path):
    core=ThreadService(JsonStore(tmp_path/'desktop'));tid=core.create('Project').id
    files=tmp_path/'files';files.mkdir();book=BindingBook(core)
    manual=book.save(tid,url='https://server.example',project_id='unrelated-manual-project',root=files,
                     token='owner-token-value-with-enough-length',automatic=False,offline_enabled=True)
    automatic=book.save(tid,url='https://server.example',project_id='',root=files,token='',
                        automatic=False,offline_enabled=True)
    assert automatic['project_id']=='',automatic
    assert automatic['device_id']!=manual['device_id']
    assert automatic['initial_bases']==[]
