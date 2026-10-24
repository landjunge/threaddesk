"""Core metadata sync: restart, conflict and scope checks, JSON and SQLite."""
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.models import KnowledgeNode, Relation
from threaddesk.server_sync.metadata import (MetadataReplica, export_document, list_conflicts,
    resolve_conflict, synchronize, SyncError, _empty)
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore,SQLiteStore],ids=['json','sqlite'])
def pair(tmp_path,request):
    local=ThreadService(request.param(tmp_path/'local'))
    remote=ThreadService(request.param(tmp_path/'remote'))
    a,b=local.create('Project'),remote.create('Project')
    return local,a.id,remote,b.id


def change(core,tid,**fields):
    with core.store.transaction():
        thread=core.get(tid)
        for key,value in fields.items():
            if key in {'notes','prompts','files'}:
                setattr(thread.context,key,value)
            else:
                setattr(thread,key,value)
        core.store.save_thread(thread)


class Wire:
    def __init__(self,core,tid):
        self.core,self.tid=core,tid
        self.lose=False
        self.calls=[]
        self.get_codes=[]
        self.ignore_etag=False
        # Call the actual installed GET route in this thread. SQLite's default
        # connection is intentionally not shared across TestClient worker threads.
        import threading
        from fastapi import FastAPI
        from threaddesk.server_sync.metadata_routes import install_routes
        app=FastAPI()
        async def read_body(request,required):
            return await request.json()
        install_routes(app,lambda request,pid:(None,core,threading.RLock()),read_body)
        self.metadata_get=next(route.endpoint for route in app.routes if getattr(route,'path',None)=='/api/projects/{pid}/metadata')
        self.http=httpx.Client(base_url='https://sync.example',transport=httpx.MockTransport(self.handle))

    def handle(self,request):
        import json
        assert request.headers['authorization']=='Bearer token'
        if request.method=='GET':
            from fastapi import Request
            headers=[(k.lower(),v) for k,v in request.headers.raw if not self.ignore_etag or k.lower()!=b'if-none-match']
            response=self.metadata_get(self.tid,Request({'type':'http','method':'GET','path':request.url.path,'headers':headers}))
            self.get_codes.append(response.status_code)
            return httpx.Response(response.status_code,content=response.body,headers=dict(response.headers))
        payload=json.loads(request.content)
        self.calls.append(payload['operation_id'])
        result=synchronize(self.core,self.tid,**payload)
        if self.lose:
            self.lose=False
            raise httpx.ReadError('Lost committed response',request=request)
        return httpx.Response(200,json=result)


def test_existing_core_bidirectional_graph_board_and_portable_refs(pair,tmp_path):
    local,tid,remote,pid=pair
    change(local,tid,notes='local notes',prompts=[{'label':'prompt','text':'inert'}],files=['/private/original.txt','relative.txt'])
    task=local.create_node('task','Task',metadata={'thread_id':tid})
    project=local.create_node('project','Graph project',metadata={'thread_id':tid})
    local.store.save_relation(Relation('related',project.id,task.id,'contains'))
    local.append_whiteboard(tid,actor='Human',actor_type='human',entry_type='task',content='Do not execute me')
    wire=Wire(remote,pid)
    replica=MetadataReplica(local,tid,tmp_path/'checkpoint',remote_identity='https://sync.example/'+pid)
    result=replica.sync_once(wire.http,pid,'token')
    # Existing differing values are journaled rather than silently overwritten.
    for conflict in list_conflicts(remote,pid):
        resolve_conflict(remote,pid,conflict['id'],conflict['current'],conflict['incoming'],'resolve_'+str(len(remote.store.list_management_operations())))
    replica.sync_once(wire.http,pid,'token')
    assert remote.get(pid).context.notes=='local notes'
    assert remote.get(pid).context.prompts==[{'label':'prompt','text':'inert'}]
    assert remote.get(pid).context.files==['relative.txt']
    assert '/private/original.txt' in local.get(tid).context.files
    assert {n.title for n in remote.list_nodes()}=={'Task','Graph project'}
    assert len(remote.list_relations())==1
    assert len(remote.whiteboard(pid))==1
    assert remote.whiteboard(pid)[0].entry_type=='task'
    remote.append_whiteboard(pid,actor='Remote',actor_type='human',entry_type='note',content='return note')
    change(remote,pid,title='Remote title')
    replica.sync_once(wire.http,pid,'token')
    assert local.get(tid).title=='Remote title'
    assert len(local.whiteboard(tid))==2
    replica.sync_once(wire.http,pid,'token')
    assert len(local.whiteboard(tid))==2
    assert len(remote.whiteboard(pid))==2
    assert not list_conflicts(remote,pid)
    assert not list_conflicts(local,tid)
    replica.close()


def test_concurrent_notes_cas_resolution_and_snapshot(pair,tmp_path):
    local,tid,remote,pid=pair
    wire=Wire(remote,pid)
    replica=MetadataReplica(local,tid,tmp_path/'checkpoint',remote_identity=pid)
    replica.sync_once(wire.http,pid,'token')
    change(local,tid,notes='left value')
    change(remote,pid,notes='right value')
    result=replica.sync_once(wire.http,pid,'token')
    assert result['state']=='conflict'
    conflict=next(c for c in list_conflicts(remote,pid) if c['path']=='thread/notes')
    assert conflict['incoming']=='left value' and conflict['current']=='right value'
    assert remote.get(pid).context.notes=='right value'
    with pytest.raises(SyncError,match='changed'):
        resolve_conflict(remote,pid,conflict['id'],'wrong','left value','wrong')
    resolve_conflict(remote,pid,conflict['id'],'right value','left value','choose_left')
    replica.sync_once(wire.http,pid,'token')
    assert remote.get(pid).context.notes==local.get(tid).context.notes=='left value'
    snapshots=remote.store.list_snapshots(pid)
    assert any(s.context.extra['server_sync_previous_metadata']['thread']['notes']=='right value' for s in snapshots)
    assert not list_conflicts(remote,pid)
    replica.close()


def test_lost_response_restart_replay_and_operation_identity(pair,tmp_path):
    local,tid,remote,pid=pair
    local.append_whiteboard(tid,actor='Human',actor_type='human',entry_type='note',content='Once')
    wire=Wire(remote,pid)
    replica=MetadataReplica(local,tid,tmp_path/'checkpoint',remote_identity=pid)
    wire.lose=True
    with pytest.raises(httpx.ReadError):
        replica.sync_once(wire.http,pid,'token')
    replica.close()
    # A local edit made after the uncertain request remains recoverable.
    change(local,tid,notes='changed while disconnected')
    replica=MetadataReplica(local,tid,tmp_path/'checkpoint',remote_identity=pid)
    replica.sync_once(wire.http,pid,'token')
    assert wire.calls[0]==wire.calls[1]
    assert len(remote.whiteboard(pid))==1
    assert local.get(tid).context.notes=='changed while disconnected'
    base=export_document(remote,pid)
    synchronize(remote,pid,'exact',base,base)
    different=deepcopy(base);different['thread']['notes']='different'
    with pytest.raises(SyncError,match='reused'):
        synchronize(remote,pid,'exact',base,different)
    replica.close()
    with pytest.raises(SyncError,match='another binding'):
        MetadataReplica(local,tid,tmp_path/'checkpoint',remote_identity='another server')


def test_whiteboard_append_only_and_remote_path_grant_refused(pair):
    local,tid,remote,pid=pair
    local.append_whiteboard(tid,actor='Human',actor_type='human',entry_type='note',content='Original')
    before=export_document(local,tid)
    altered=deepcopy(before)
    entry=next(iter(altered['whiteboard'].values()))
    entry['content']='Changed original'
    result=synchronize(local,tid,'alter',before,altered)
    assert result['conflicts']
    assert local.whiteboard(tid)[0].content=='Original'
    altered=deepcopy(before);altered['thread']['files']=['/etc/hosts']
    with pytest.raises(SyncError,match='relative'):
        synchronize(local,tid,'bad_paths',before,altered)


def test_new_binding_bootstrap_and_concurrent_server_edit(pair,tmp_path):
    local,tid,remote,pid=pair
    change(local,tid,description='Existing desktop description',notes='Existing notes',status='active')
    local.create_node('task','Existing desktop task',metadata={'thread_id':tid})
    initial=export_document(remote,pid)
    replica=MetadataReplica(local,tid,tmp_path/'seeded',remote_identity=pid)
    assert replica.seed_base(initial) is True
    assert replica.seed_base(_empty()) is False
    result=replica.sync_once(Wire(remote,pid).http,pid,'token')
    assert result['conflicts']==[]
    assert remote.get(pid).description=='Existing desktop description'
    assert remote.get(pid).status=='active'
    assert remote.get(pid).context.notes=='Existing notes'
    assert any(n.title=='Existing desktop task' for n in remote.list_nodes())
    replica.close()
    other=remote.create('Project')
    bootstrap=export_document(remote,other.id)
    replica=MetadataReplica(local,tid,tmp_path/'seeded-concurrent',remote_identity=other.id)
    assert replica.seed_base(bootstrap)
    change(remote,other.id,description='Concurrent server description')
    result=replica.sync_once(Wire(remote,other.id).http,other.id,'token')
    conflict=next(c for c in result['conflicts'] if c['path']=='thread/description')
    assert conflict['incoming']=='Existing desktop description'
    assert conflict['current']=='Concurrent server description'
    assert remote.get(other.id).description=='Concurrent server description'
    replica.close()


def test_core_organization_project_mapping_and_owned_tasks_roundtrip(pair,tmp_path):
    from threaddesk.services.thread_management import manage,organization
    local,tid,remote,pid=pair
    project=local.create_node('project','Existing organized project')
    other_thread=local.create('Another thread in this project')
    task=local.create_node('task','Project-owned task',metadata={'project_id':project.id,'thread_id':other_thread.id})
    unrelated=local.create_node('task','Other project task',metadata={'project_id':'another_project'})
    manage(local,{'operation_id':'organize','action':'organize','id':tid,
                  'expected_revision':local.get(tid).revision,'data':{'project_id':project.id}})
    before=export_document(local,tid)
    assert before['thread']['project_origin']
    assert {n['title'] for n in before['nodes'].values()}=={'Existing organized project','Project-owned task'}
    replica=MetadataReplica(local,tid,tmp_path/'organization-checkpoint',remote_identity=pid)
    replica.seed_base(export_document(remote,pid))
    result=replica.sync_once(Wire(remote,pid).http,pid,'token')
    assert result['conflicts']==[]
    remote_project=organization(remote.get(pid))['project_id']
    assert remote_project!=project.id
    assert remote.get_node(remote_project).title=='Existing organized project'
    remote_task=next(n for n in remote.list_nodes() if n.kind=='task')
    assert remote_task.metadata['project_id']==remote_project
    assert len(remote.list_nodes())==2
    with remote.store.transaction():
        node=remote.get_node(remote_project)
        node.details='Updated on server'
        remote.store.save_node(node)
    replica.sync_once(Wire(remote,pid).http,pid,'token')
    assert organization(local.get(tid))['project_id']==project.id
    assert local.get_node(project.id).details=='Updated on server'
    assert len(local.list_nodes())==3
    assert local.get_node(unrelated.id).title=='Other project task'
    assert local.get_node(task.id).metadata['project_id']==project.id
    assert local.get_node(task.id).metadata['thread_id']==other_thread.id
    replica.close()


def test_relocated_workspace_retains_native_origins_and_replica_replay(pair,tmp_path):
    import shutil
    from threaddesk.services.thread_management import manage,organization
    local,tid,remote,pid=pair
    project=local.create_node('project','Portable native project')
    local.create_node('task','Portable native task',metadata={'project_id':project.id})
    manage(local,{'operation_id':'portable_organize','action':'organize','id':tid,
                  'expected_revision':local.get(tid).revision,'data':{'project_id':project.id}})
    local.append_whiteboard(tid,actor='Human',actor_type='human',entry_type='note',content='Portable native note')
    before=export_document(local,tid)
    replica=MetadataReplica(local,tid,tmp_path/'before-move-state',remote_identity=pid)
    replica.seed_base(export_document(remote,pid))
    replica.sync_once(Wire(remote,pid).http,pid,'token')
    replica.close()
    source=Path(local.store.workspace_path)
    # This is an offline workspace copy, matching the restore contract.
    if hasattr(local.store,'connection'):
        local.store.connection.close()
    destination=tmp_path/'relocated-workspace'
    shutil.copytree(source,destination)
    restored=ThreadService(type(local.store)(destination))
    assert export_document(restored,tid)==before
    namespace=restored.store.get_management_operation('metadata_namespace_v1')
    assert namespace['result']['operation_id']=='metadata_namespace_v1'
    # Fresh path-bound checkpoint intentionally starts a new local binding, while
    # the portable namespace still addresses exactly the existing graph/board.
    replay=MetadataReplica(restored,tid,tmp_path/'after-move-state',remote_identity=pid)
    replay.sync_once(Wire(remote,pid).http,pid,'token')
    replay.sync_once(Wire(remote,pid).http,pid,'token')
    assert len(restored.list_nodes())==len(remote.list_nodes())==2
    assert len(restored.whiteboard(tid))==len(remote.whiteboard(pid))==1
    assert organization(restored.get(tid))['project_id']==project.id
    assert export_document(restored,tid)==export_document(remote,pid)
    replay.close()


def test_full_core_unicode_note_limit_roundtrip_without_truncation(pair,tmp_path):
    local,tid,remote,pid=pair
    note='😀'*100000
    change(local,tid,notes=note)
    replica=MetadataReplica(local,tid,tmp_path/'unicode-note-state',remote_identity=pid)
    replica.seed_base(export_document(remote,pid))
    result=replica.sync_once(Wire(remote,pid).http,pid,'token')
    assert result['conflicts']==[]
    assert remote.get(pid).context.notes==note
    assert len(remote.get(pid).context.notes)==100000
    replica.sync_once(Wire(remote,pid).http,pid,'token')
    assert local.get(tid).context.notes==note
    replica.close()


def test_idle_polling_304_does_not_grow_receipts_snapshots_or_checkpoint(pair,tmp_path):
    local,tid,remote,pid=pair
    change(local,tid,notes='Retained metadata')
    wire=Wire(remote,pid)
    replica=MetadataReplica(local,tid,tmp_path/'idle-state',remote_identity=pid)
    replica.seed_base(export_document(remote,pid))
    replica.sync_once(wire.http,pid,'token')
    counts=lambda:(len(local.store.list_management_operations()),len(remote.store.list_management_operations()),
                   len(local.store.list_snapshots(tid)),len(remote.store.list_snapshots(pid)),replica.db.total_changes)
    before=counts()
    posts=len(wire.calls)
    for _ in range(3):
        assert replica.sync_once(wire.http,pid,'token')['unchanged'] is True
    assert wire.get_codes[-3:]==[304,304,304]
    assert len(wire.calls)==posts
    assert counts()==before
    # A proxy/server that returns a complete identical 200 still must not grow
    # either journal or rewrite the local checkpoint.
    wire.ignore_etag=True
    assert replica.sync_once(wire.http,pid,'token')['unchanged'] is True
    assert wire.get_codes[-1]==200
    assert counts()==before
    replica.close()


def test_relocated_imported_graph_ids_cannot_overwrite_foreign_scope(pair):
    local,tid,remote,pid=pair
    first=local.create_node('task','First imported task',metadata={'thread_id':tid})
    second=local.create_node('task','Second imported task',metadata={'thread_id':tid})
    local.store.save_relation(Relation('scope_link',first.id,second.id,'contains'))
    document=export_document(local,tid)
    synchronize(remote,pid,'initial_scope',_empty(),document)
    imported=next(n for n in remote.list_nodes() if n.title=='First imported task')
    original=deepcopy(imported)
    foreign_thread=remote.create('Unrelated thread')
    with remote.store.transaction():
        imported.metadata['thread_id']=foreign_thread.id
        imported.title='Moved and privately edited'
        remote.store.save_node(imported)
    assert imported.metadata['sync_origin'] not in export_document(remote,pid)['nodes']
    before=imported.to_dict()
    receipts=len(remote.store.list_management_operations())
    snapshots=len(remote.store.list_snapshots(pid))
    # A new checkpoint has no old baseline; deterministic import IDs still must
    # never replace a now-foreign object left behind by a previous binding.
    with pytest.raises(SyncError) as error:
        synchronize(remote,pid,'fresh_checkpoint',_empty(),document)
    assert error.value.status==409 and error.value.code=='metadata_scope'
    assert remote.get_node(imported.id).to_dict()==before
    assert len(remote.store.list_management_operations())==receipts
    assert len(remote.store.list_snapshots(pid))==snapshots
    # Restore the task explicitly as an operator, then move just the old
    # relation outside scope. The analogous generated relation ID is protected.
    with remote.store.transaction():
        remote.store.save_node(original)
    unrelated=remote.create_node('task','Unrelated relation target',metadata={'thread_id':foreign_thread.id})
    relation=remote.list_relations()[0]
    with remote.store.transaction():
        relation.source_id=unrelated.id
        relation.target_id=unrelated.id
        remote.store.save_relation(relation)
    before_relation=relation.to_dict()
    assert not export_document(remote,pid)['relations']
    with pytest.raises(SyncError) as error:
        synchronize(remote,pid,'fresh_relation_checkpoint',_empty(),document)
    assert error.value.status==409 and error.value.code=='metadata_scope'
    assert next(r for r in remote.list_relations() if r.id==relation.id).to_dict()==before_relation
    assert remote.get_node(unrelated.id).metadata['thread_id']==foreign_thread.id
