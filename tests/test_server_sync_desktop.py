"""Explicit desktop authority, policy races and actual existing-core server binding."""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import InvalidState
from threaddesk.server_sync.app import create_app
from threaddesk.server_sync.auth import provision
from threaddesk.server_sync.backup import BackupError, backup
from threaddesk.server_sync.desktop import BindingBook, DesktopSyncManager
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


def test_private_binding_authority_and_offline_generation(tmp_path):
    core=ThreadService(JsonStore(tmp_path/'desk')); tid=core.create('Project').id
    root=tmp_path/'files';root.mkdir();book=BindingBook(core)
    assert book.view(tid)['configured'] is False
    assert not book.root.exists()  # GET does not provision a secret store.
    config=book.save(tid,url='https://server.example',project_id='',root=root,token='x'*32)
    assert 'token' not in book.view(tid)
    assert (book.root/(tid+'.json')).stat().st_mode & 0o077 == 0
    assert book.root.stat().st_mode & 0o077 == 0
    book.update(tid,{'offline_enabled':False,'offline_pending':True})
    book.update(tid,{'offline_enabled':True,'offline_pending':False},config_id=config['config_id'])
    assert book.load(tid)['offline_enabled'] is False
    assert book.load(tid)['offline_pending'] is True
    for directory in [core.store.workspace_path, core.store.workspace_path/'threads',tmp_path]:
        with pytest.raises(InvalidState):
            book.save(tid,url='https://server.example',project_id='',root=directory,token='x'*32)
    with pytest.raises(InvalidState):
        book.save(tid,url='https://server.example',project_id='',root=root,token='x'*32,
                  approved_roots=[core.store.workspace_path/'threads'])
    with pytest.raises(InvalidState):
        book.save(tid,url='https://other.example',project_id='',root=root,token='')


class BorrowedHTTP:
    def __init__(self,http,headers):self.http,self.headers=http,headers
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def request(self,method,path,**kwargs):
        return self.http.request(method,path,headers={**self.headers,**kwargs.pop('headers',{})},**kwargs)
    def post(self,path,**kwargs):return self.request('POST',path,**kwargs)
    def put(self,path,**kwargs):return self.request('PUT',path,**kwargs)


@pytest.mark.parametrize('backend',[JsonStore,SQLiteStore],ids=['json','sqlite'])
def test_existing_desktop_binding_metadata_files_and_option_roundtrip(tmp_path,monkeypatch,backend):
    data=tmp_path/'server';token=provision(data,'alice');app=create_app(data,public_origin='https://server.example')
    core=ThreadService(backend(tmp_path/'desktop'));thread=core.create('Existing project','Local description')
    core.set_note('Desktop notes',thread.id)
    core.append_whiteboard(thread.id,actor='Owner',actor_type='human',entry_type='task',content='Desktop task')
    files=tmp_path/'files';files.mkdir();(files/'note.md').write_text('local original')
    attachment=tmp_path/'attachment.txt';attachment.write_text('explicit attachment')
    core.add_file(str(attachment),thread.id)
    book=BindingBook(core)
    book.save(thread.id,url='https://server.example',project_id='',root=files,token=token,automatic=False,offline_enabled=True)
    manager=DesktopSyncManager(lambda:core)
    with TestClient(app,base_url='https://server.example') as server:
        monkeypatch.setattr('threaddesk.server_sync.desktop._http_client',lambda **kwargs:BorrowedHTTP(server,kwargs['headers']))
        first=manager.run_once(core,thread.id)
        assert first['state']=='ready',first
        config=book.load(thread.id);pid=config['project_id'];uri='/api/projects/'+pid
        headers={'Authorization':'Bearer '+token}
        remote=server.get(uri+'/thread',headers=headers).json()
        assert remote['description']=='Local description'
        assert remote['context']['notes']=='Desktop notes'
        assert any(e['content']=='Desktop task' for e in server.get(uri+'/whiteboard',headers=headers).json()['entries'])
        paths=[f['path'] for f in server.get(uri+'/files',headers=headers).json()['files']]
        assert 'note.md' in paths and any(p.startswith('_external/') for p in paths)
        # A reference added outside the protected owner-grant UI is required
        # data, not read authority. Surface the missing approval instead of Ready.
        unapproved=tmp_path/'unapproved-new.txt';unapproved.write_text('not granted')
        core.add_file(str(unapproved),thread.id)
        assert manager.run_once(core,thread.id)['state']=='blocked'
        assert not any(f['path'].endswith('unapproved-new.txt') for f in server.get(uri+'/files',headers=headers).json()['files'])
        core.remove_file(str(unapproved),thread.id)
        update={'revision':remote['revision'],'description':'Remote description','notes':'Remote notes'}
        assert server.put(uri+'/thread',headers=headers,json=update).status_code==200
        assert manager.run_once(core,thread.id)['metadata_conflict_count']==0
        assert core.get(thread.id).description=='Remote description'
        assert core.get(thread.id).context.notes=='Remote notes'
        assert str(attachment) in core.get(thread.id).context.files
        # Rebinding receipt is stable; it cannot reset already synchronized metadata.
        again=manager.run_once(core,thread.id)
        assert book.load(thread.id)['project_id']==pid and again['state']=='ready'
        book.update(thread.id,{'offline_enabled':False,'offline_pending':True})
        assert manager.run_once(core,thread.id)['state']=='metadata_only'
        assert (files/'note.md').read_text()=='local original' and attachment.read_text()=='explicit attachment'
        assert server.get(uri+'/files',headers=headers).json()['files']
        # Replicated references remain data across TWO runs, never new owner grants.
        private=tmp_path/'private.txt';private.write_text('not authorized for this project')
        from copy import deepcopy
        baseline=server.get(uri+'/metadata',headers=headers).json()['document']
        poisoned=deepcopy(baseline);poisoned['thread']['files'].append('%2e%2e/private.txt')
        response=server.post(uri+'/metadata/sync',headers=headers,json={
            'operation_id':'remote-reference-injection','base':baseline,'document':poisoned})
        assert response.status_code==200,response.text
        book.update(thread.id,{'offline_enabled':True,'offline_pending':True})
        for _ in range(2):
            observed=manager.run_once(core,thread.id)
            assert observed['state']=='blocked',observed
        assert '%2e%2e/private.txt' in core.get(thread.id).context.files
        assert '%2e%2e/private.txt' not in book.load(thread.id)['owner_references']
        assert not any(f['path'].endswith('private.txt') for f in server.get(uri+'/files',headers=headers).json()['files'])
        assert private.read_text()=='not authorized for this project'
        # Moving the selected file directory gets a separate file checkpoint,
        # while the metadata checkpoint/binding and existing versions survive.
        moved=tmp_path/'moved-files';moved.mkdir();(moved/'note.md').write_text('local original')
        book.save(thread.id,url='https://server.example',project_id=pid,root=moved,token='',automatic=False,offline_enabled=True)
        moved_status=manager.run_once(core,thread.id)
        assert moved_status['state']!='disconnected',moved_status
        assert book.load(thread.id)['project_id']==pid
        assert len(server.get(uri+'/history',headers=headers,params={'path':'note.md'}).json()['versions'])==1
        with pytest.raises(BackupError,match='in use'):
            backup(data,tmp_path/'online.tar')
    cold=backup(data,tmp_path/'cold.tar')
    assert cold
    if hasattr(core.store,'connection'):core.store.connection.close()


def test_desktop_form_is_csrf_protected_and_never_reflects_credential(tmp_path,monkeypatch):
    from threaddesk.ui import server as desktop
    workspace=tmp_path/'desk';core=ThreadService(JsonStore(workspace));thread=core.create('Selected project')
    other=core.create('Different active project')
    root=tmp_path/'files';root.mkdir()
    monkeypatch.setattr(desktop,'_svc',lambda:ThreadService(JsonStore(workspace)))
    monkeypatch.setattr(desktop,'_hausmeister_status',lambda *_:{'enabled':False,'models':[],'phase':'off','model':'','ollama_ok':False})
    app=desktop.create_app()
    monkeypatch.setattr(app.state.server_sync_manager,'run_once',lambda *_:{'state':'pending'})
    http=TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',51000))
    page=http.get('/threads/'+thread.id+'/server-sync')
    assert page.status_code==200 and 'Selected project' in page.text
    assert 'Different active project' not in page.text
    csrf=re.search(r'name="threaddesk-csrf" content="([a-f0-9]+)"',page.text)[1]
    fields={'action':'configure','url':'https://server.example','root':str(root),'token':'x'*32,'project_id':''}
    uri='/threads/'+thread.id+'/server-sync'
    assert http.post(uri,data=fields).status_code==403
    response=http.post(uri,data={**fields,'csrf_token':csrf})
    assert response.status_code==200 and 'x'*32 not in response.text
    state=http.get('/api/threads/'+thread.id+'/server-sync').json()
    assert state['configured'] is True and 'token' not in state
    original=tmp_path/'owner-added.txt';original.write_text('owner added')
    assert http.post('/threads/'+thread.id+'/files',data={'csrf_token':csrf,'path':str(original)}).status_code==200
    assert str(original) in BindingBook(core).load(thread.id)['owner_references']
    assert http.post('/threads/'+thread.id+'/files/remove',data={'csrf_token':csrf,'path':str(original)}).status_code==200
    assert str(original) not in BindingBook(core).load(thread.id)['owner_references']
    assert core.current().id==other.id  # Reading/configuring does not switch threads.
    from copy import deepcopy
    from threaddesk.server_sync.metadata import export_document,synchronize
    baseline=export_document(core,thread.id)
    core.set_note('Local changed notes',thread.id)
    incoming=deepcopy(baseline);incoming['thread']['notes']='Incoming changed notes'
    result=synchronize(core,thread.id,'desktop-local-conflict',baseline,incoming)
    conflict=result['conflicts'][0]
    page=http.get('/threads/'+thread.id+'/server-sync')
    assert 'Incoming changed notes' in page.text
    resolution={
        'action':'resolve_local','csrf_token':csrf,'conflict_id':conflict['id'],'operation_id':'resolve-desktop',
        'expected_current':json.dumps('Local changed notes'),'chosen_value':json.dumps('Incoming changed notes')}
    assert http.post(uri,data=resolution).status_code==200
    assert core.get(thread.id).context.notes=='Incoming changed notes'
    assert http.post(uri,data=resolution).status_code==200  # Exact retry returns saved receipt.
