"""Explicit core-thread metadata replicas. Sync is inert data, never an agent command."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid

from threaddesk.core.errors import NotFound
from threaddesk.core.models import (ACTOR_TYPES, ENTRY_TYPES, NODE_STATUSES, STATUSES,
                                   KnowledgeNode, Relation, Snapshot, WhiteboardEntry,
                                   ThreadContext, new_id, now_iso)
from threaddesk.core.secrets import reject_secrets
from threaddesk.server_sync.store import SyncError, validate_path

FORMAT = 'threaddesk.metadata.v1'
MAX_DOCUMENT_BYTES = 1024 * 1024
MISSING = {'$missing': True}


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise SyncError('Metadata must be JSON data', 'invalid_metadata') from exc


def _hash(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def document_etag(document):
    """Stable opaque representation validator, scoped by authenticated route."""
    return '"metadata-'+_hash(document)+'"'


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        raise SyncError('Invalid metadata operation identifier')
    return value


def _origin(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_:-]{1,180}', value):
        raise SyncError('Invalid portable origin')
    return value


def _portable(value):
    try:
        return validate_path(value)
    except SyncError:
        return None


def _empty():
    return {'format': FORMAT, 'thread': {}, 'nodes': {}, 'relations': {}, 'whiteboard': {}}


def validate_document(document):
    if not isinstance(document, dict) or set(document) != {'format','thread','nodes','relations','whiteboard'} or document['format'] != FORMAT:
        raise SyncError('Invalid metadata document', 'invalid_metadata')
    encoded = _canonical(document)
    if len(encoded.encode()) > MAX_DOCUMENT_BYTES:
        raise SyncError('Metadata exceeds explicit 1 MiB document limit; no content was truncated', 'metadata_too_large', 413)
    reject_secrets(encoded)
    thread = document['thread']
    if not isinstance(thread, dict) or thread.keys() - {'title','description','status','notes','prompts','files','project_origin'}:
        raise SyncError('Invalid thread metadata')
    for field in ('title','description','notes'):
        if field in thread and (not isinstance(thread[field],str) or len(thread[field]) > 100000 or (field=='title' and not thread[field].strip())):
            raise SyncError('Invalid thread text')
    if 'status' in thread and thread['status'] not in STATUSES:
        raise SyncError('Invalid thread status')
    if 'prompts' in thread and (not isinstance(thread['prompts'],list) or any(not isinstance(p,dict) for p in thread['prompts'])):
        raise SyncError('Invalid prompt list')
    if 'files' in thread and (not isinstance(thread['files'],list) or any(_portable(p) is None for p in thread['files'])):
        raise SyncError('Only safe relative file references may be replicated')
    for section in ('nodes','relations','whiteboard'):
        if not isinstance(document[section],dict) or len(document[section]) > 2000:
            raise SyncError('Invalid metadata collection')
        for origin, item in document[section].items():
            _origin(origin)
            if not isinstance(item,dict):
                raise SyncError('Invalid metadata item')
            if section == 'nodes':
                if (not {'kind','title','status','details','metadata'} <= item.keys()
                        or item.keys()-{'kind','title','status','details','metadata','project_origin'}
                        or item['kind'] not in {'task','project'} or item['status'] not in NODE_STATUSES):
                    raise SyncError('Invalid project/task metadata')
                if any(not isinstance(item[k],str) for k in ('title','details')) or not item['title'].strip() or not isinstance(item['metadata'],dict):
                    raise SyncError('Invalid project/task value')
                if any(k in item['metadata'] for k in ('thread_id','project_id','sync_origin')):
                    raise SyncError('Portable nodes cannot choose their local binding')
            elif section == 'relations':
                if set(item) != {'source','target','kind'} or item['kind'] not in {'contains','depends_on','related_to','blocks','references'}:
                    raise SyncError('Invalid project relation')
                if item['source'] not in document['nodes'] or item['target'] not in document['nodes']:
                    raise SyncError('Relation endpoint outside this project')
            else:
                if set(item) != {'actor','actor_type','created_at','entry_type','content','metadata'} or item['actor_type'] not in ACTOR_TYPES or item['entry_type'] not in ENTRY_TYPES:
                    raise SyncError('Invalid whiteboard entry')
                if any(not isinstance(item[k],str) for k in ('actor','created_at','content')) or not isinstance(item['metadata'],dict):
                    raise SyncError('Invalid whiteboard value')
                if 'sync_origin' in item['metadata']:
                    raise SyncError('Portable entry cannot choose internal origin metadata')
    for origin in [thread.get('project_origin')]+[n.get('project_origin') for n in document['nodes'].values()]:
        if origin is not None and (origin not in document['nodes'] or document['nodes'][origin]['kind']!='project'):
            raise SyncError('Portable project origin must reference a project in this document')
    return deepcopy(document)


def _namespace(core):
    """Portable origins belong to a workspace identity, never its current path.

    Keep this identity in the same transactional journal as metadata receipts so
    backup/restore and JSON/SQLite migration retain it. No actor registration or
    dispatch service is touched. The two core backends expose transaction state
    internally; SQLite explicitly forbids opening a nested transaction.
    """
    key='metadata_namespace_v1'
    pending=getattr(core.store,'_pending',None)
    record=(pending.get('management-operations/'+key+'.json') if isinstance(pending,dict) else None)
    record=record or core.store.get_management_operation(key)
    if record is not None:
        namespace=record.get('result',{}).get('namespace')
        if not isinstance(namespace,str) or not re.fullmatch(r'[a-f0-9]{24,32}',namespace):
            raise SyncError('Stored metadata namespace is invalid','metadata_identity',409)
        return namespace
    active=pending is not None or bool(getattr(core.store,'_transaction_depth',0))
    if not active:
        with core.store.transaction():
            return _namespace(core)
    # Preserve origins emitted by the earlier development implementation when
    # their native IDs are still evidenced by committed metadata receipts.
    native_ids={n.id for n in core.store.list_nodes() if not n.metadata.get('sync_origin')}
    for thread in core.store.list_threads(include_archived=True):
        native_ids.update(e.id for e in core.store.list_whiteboard(thread.id) if not e.metadata.get('sync_origin'))
    legacy=set()
    for receipt in core.store.list_management_operations():
        if not receipt.get('kind','').startswith('metadata_'):
            continue
        document=receipt.get('result',{}).get('document') or {}
        for section in ('nodes','whiteboard'):
            for origin in document.get(section,{}):
                prefix,separator,native_id=origin.rpartition(':')
                if separator and native_id in native_ids and re.fullmatch(r'[a-f0-9]{24,32}',prefix):
                    legacy.add(prefix)
    if len(legacy)>1:
        raise SyncError('Historical metadata has multiple native namespaces; reconcile identity explicitly','metadata_identity',409)
    namespace=next(iter(legacy)) if legacy else uuid.uuid4().hex
    core.store.save_management_operation(key,{'request_hash':_hash(['metadata_namespace',1]),
        'recorded_at':now_iso(),'kind':'metadata_namespace',
        'result':{'operation_id':key,'namespace':namespace}})
    return namespace


def export_document(core, thread_id):
    thread = core.get(thread_id)
    ns = _namespace(core)
    doc = _empty()
    doc['thread'] = {'title':thread.title,'description':thread.description,'status':thread.status,
                     'notes':thread.context.notes,'prompts':deepcopy(thread.context.prompts),
                     'files':sorted({p for p in thread.context.files if _portable(p) is not None})}
    all_nodes = [n for n in core.store.list_nodes() if n.kind in {'task','project'}]
    organization=thread.context.extra.get('organization') or {}
    project_id=organization.get('project_id') or thread.context.extra.get('project_id')
    selected = {n.id:n for n in all_nodes if n.metadata.get('thread_id')==thread.id or n.id in
                {thread.context.extra.get('task_id'),project_id}}
    if project_id in selected and selected[project_id].kind=='project':
        selected.update({n.id:n for n in all_nodes if n.metadata.get('project_id')==project_id})
    relations = core.store.list_relations()
    for _ in range(len(all_nodes)+1):
        before = len(selected)
        # A task's explicit owner is a related project even when the thread
        # itself has no organization.project_id. Retain that membership too.
        owners={node.metadata.get('project_id') for node in selected.values()}
        selected.update({n.id:n for n in all_nodes if n.kind=='project' and n.id in owners})
        for relation in relations:
            if relation.kind == 'contains' and relation.source_id in selected:
                selected.update({n.id:n for n in all_nodes if n.id==relation.target_id})
        if len(selected)==before:
            break
    origins = {i:n.metadata.get('sync_origin') or ns+':'+i for i,n in selected.items()}
    for node_id,node in selected.items():
        metadata = {k:deepcopy(v) for k,v in node.metadata.items() if k not in {'thread_id','project_id','sync_origin'}}
        owner=node.metadata.get('project_id')
        owner_origin=origins.get(owner) if owner in selected and selected[owner].kind=='project' else None
        doc['nodes'][origins[node_id]] = {'kind':node.kind,'title':node.title,'status':node.status,'details':node.details,'metadata':metadata,
                                        'project_origin':owner_origin}
    doc['thread']['project_origin']=origins.get(project_id) if project_id in selected and selected[project_id].kind=='project' else None
    for relation in relations:
        if relation.source_id in selected and relation.target_id in selected and relation.kind in {'contains','depends_on','related_to','blocks','references'}:
            origin = relation.metadata.get('sync_origin') or ns+':'+relation.id
            doc['relations'][origin] = {'source':origins[relation.source_id],'target':origins[relation.target_id],'kind':relation.kind}
    for entry in core.store.list_whiteboard(thread.id):
        origin = entry.metadata.get('sync_origin') or ns+':'+entry.id
        metadata = {k:deepcopy(v) for k,v in entry.metadata.items() if k!='sync_origin'}
        # Preserve addressing as inert origin metadata, never a dispatch request.
        for key in ('task_id','handoff_id','run_id','actor_id','instance_id','room_id','external_key'):
            if not entry.metadata.get('sync_origin') and getattr(entry,key,None):
                metadata.setdefault('original_'+key,getattr(entry,key))
        doc['whiteboard'][origin] = {'actor':entry.actor,'actor_type':entry.actor_type,'created_at':entry.created_at,
                                    'entry_type':entry.entry_type,'content':entry.content,'metadata':metadata}
    return validate_document(doc)


def _flatten(document):
    fields = {}
    for key,value in document['thread'].items():
        fields['thread/'+key] = value
    for section in ('nodes','relations'):
        for origin,item in document[section].items():
            for key,value in item.items():
                fields[section+'/'+origin+'/'+key] = value
    for origin,item in document['whiteboard'].items():
        fields['whiteboard/'+origin] = item
    return fields


def _unflatten(fields):
    doc = _empty()
    for path,value in fields.items():
        section,*parts = path.split('/')
        if section in {'thread','whiteboard'}:
            doc[section][parts[0]] = deepcopy(value)
        else:
            doc[section].setdefault(parts[0],{})[parts[1]] = deepcopy(value)
    return doc


def merge_documents(base, incoming, current):
    """3-way leaf merge; absence never deletes and both concurrent values journal."""
    b,l,r = map(_flatten,(base,incoming,current))
    merged,conflicts = deepcopy(r),[]
    for path in sorted(set(b)|set(l)|set(r)):
        old,left,right = b.get(path,MISSING),l.get(path,MISSING),r.get(path,MISSING)
        if path == 'thread/files':
            merged[path]=sorted(set((left if isinstance(left,list) else [])+(right if isinstance(right,list) else [])))
            continue
        immutable = path.startswith('whiteboard/')
        if left == right or left == old:
            continue
        if immutable and right != MISSING:
            conflicts.append({'path':path,'base':old,'incoming':left,'current':right,'reason':'immutable_entry_changed'})
        elif left == MISSING:
            conflicts.append({'path':path,'base':old,'incoming':left,'current':right,'reason':'deletion_not_applied'})
        elif right == old or right == MISSING:
            merged[path]=deepcopy(left)
        else:
            conflicts.append({'path':path,'base':old,'incoming':left,'current':right,
                              'reason':'immutable_entry_changed' if immutable else 'concurrent_change'})
    return validate_document(_unflatten(merged)),conflicts


def _local_id(thread_id, origin, kind):
    return hashlib.sha256((thread_id+'\0'+kind+'\0'+origin).encode()).hexdigest()[:24]


def _apply(core, thread_id, document):
    """Caller owns the core transaction. Never invoke task/agent command services."""
    current = export_document(core,thread_id)
    if current == document:
        return
    thread = core.get(thread_id)
    previous = deepcopy(thread.context)
    previous.extra['server_sync_previous_metadata'] = current
    core.store.save_snapshot(Snapshot(new_id(),thread.id,now_iso(),'Before metadata replica merge',previous))
    fields = document['thread']
    for key in ('title','description','status'):
        if key in fields:
            setattr(thread,key,fields[key])
    for key in ('notes','prompts'):
        if key in fields:
            setattr(thread.context,key,deepcopy(fields[key]))
    # File grants do not cross replicas. Keep local originals; new references are inert relative names.
    if 'files' in fields:
        thread.context.files = list(dict.fromkeys(thread.context.files+fields['files']))
    existing = {n.metadata.get('sync_origin') or _namespace(core)+':'+n.id:n for n in core.store.list_nodes()
                if (n.metadata.get('sync_origin') or _namespace(core)+':'+n.id) in current['nodes']}
    node_ids = {origin:existing[origin].id if origin in existing else _local_id(thread_id,origin,'node')
                for origin in document['nodes']}
    for origin,item in document['nodes'].items():
        node = existing.get(origin)
        if node is None:
            node = KnowledgeNode(_local_id(thread_id,origin,'node'),item['kind'],item['title'],created_at=now_iso(),source='metadata-replica')
        metadata={**item['metadata'],'thread_id':node.metadata.get('thread_id') or thread_id,'sync_origin':origin}
        if item.get('project_origin') is not None:
            metadata['project_id']=node_ids[item['project_origin']]
        values = {k:v for k,v in item.items() if k!='project_origin'}
        values['metadata']=metadata
        if any(getattr(node,k)!=v for k,v in values.items()):
            for key,value in values.items():
                setattr(node,key,deepcopy(value))
            node.updated_at=now_iso()
            node.revision+=1
            core.store.save_node(node)
    if 'project_origin' in fields:
        organization=deepcopy(thread.context.extra.get('organization') or {})
        organization['project_id']=node_ids.get(fields['project_origin'])
        thread.context.extra['organization']=organization
        if 'project_id' in thread.context.extra:
            thread.context.extra['project_id']=organization['project_id']
    existing_rel = {r.metadata.get('sync_origin') or _namespace(core)+':'+r.id:r for r in core.store.list_relations()
                    if (r.metadata.get('sync_origin') or _namespace(core)+':'+r.id) in current['relations']}
    for origin,item in document['relations'].items():
        relation = existing_rel.get(origin)
        if relation is None:
            relation=Relation(_local_id(thread_id,origin,'relation'),node_ids[item['source']],node_ids[item['target']],item['kind'],now_iso(),source='metadata-replica',metadata={'sync_origin':origin})
        else:
            relation.source_id,relation.target_id,relation.kind=node_ids[item['source']],node_ids[item['target']],item['kind']
            relation.revision+=1
        core.store.save_relation(relation)
    board = {_e.metadata.get('sync_origin') or _namespace(core)+':'+_e.id:_e for _e in core.store.list_whiteboard(thread_id)}
    for origin,item in document['whiteboard'].items():
        if origin in board:
            continue
        # Direct append stores a historical contribution without task/wake callbacks.
        entry=WhiteboardEntry(id=_local_id(thread_id,origin,'entry'),thread_id=thread_id,
             actor=item['actor'],actor_type=item['actor_type'],created_at=item['created_at'],
             entry_type=item['entry_type'],content=item['content'],external_key='metadata:'+_hash(origin),
             metadata={**deepcopy(item['metadata']),'sync_origin':origin})
        core.store.append_whiteboard_entry(entry)
    thread.updated_at=now_iso()
    core.store.save_thread(thread)


def _journal_id(thread_id, operation_id):
    return 'metadata_'+_hash([thread_id,_identifier(operation_id)])


def _record(core, key, thread_id, request, result, *, kind='sync'):
    result=deepcopy(result)
    result['operation_id']=key  # Also compatible with core JSON -> SQLite migration.
    record={'request_hash':_hash(request),'recorded_at':now_iso(),'kind':'metadata_'+kind,
            'thread_id':thread_id,'result':result}
    core.store.save_management_operation(key,record)
    return result


def _replay(core,key,request):
    record=core.store.get_management_operation(key)
    if record is None:
        return None
    if record.get('request_hash') != _hash(request):
        raise SyncError('Metadata operation reused with different content','metadata_operation_conflict',409)
    return deepcopy(record['result'])


def synchronize(core,thread_id,operation_id,base,document):
    request={'base':validate_document(base),'document':validate_document(document)}
    key=_journal_id(thread_id,operation_id)
    with core.store.transaction():
        replay=_replay(core,key,request)
        if replay is not None:
            return replay
        current=export_document(core,thread_id)
        merged,conflicts=merge_documents(request['base'],request['document'],current)
        for index,conflict in enumerate(conflicts):
            conflict.update(id=key+':'+str(index),thread_id=thread_id)
        _apply(core,thread_id,merged)
        # JSON list_nodes/list_whiteboard enumerate committed directory entries,
        # so newly staged objects are not discoverable until transaction commit.
        # The validated merge is the exact projection just applied atomically.
        result={'document':merged,'conflicts':conflicts,'state':'conflict' if conflicts else 'synced'}
        return _record(core,key,thread_id,request,result)


def list_conflicts(core,thread_id):
    core.get(thread_id)
    records=[r for r in core.store.list_management_operations() if r.get('thread_id')==thread_id and r.get('kind','').startswith('metadata_')]
    resolved={r['result'].get('resolved_conflict') for r in records if r.get('kind')=='metadata_resolve'}
    return [deepcopy(c) for r in records for c in r['result'].get('conflicts',[]) if c['id'] not in resolved]


def metadata_status(core,thread_id):
    conflicts=list_conflicts(core,thread_id)
    return {'metadata_conflict_count':len(conflicts),'metadata_state':'conflict' if conflicts else 'synced',
            'metadata_conflicts':conflicts}


def resolve_conflict(core,thread_id,conflict_id,expected_current,chosen_value,operation_id):
    request={'conflict_id':conflict_id,'expected_current':expected_current,'chosen_value':chosen_value}
    key=_journal_id(thread_id,operation_id)
    with core.store.transaction():
        replay=_replay(core,key,request)
        if replay is not None:
            return replay
        conflict=next((c for c in list_conflicts(core,thread_id) if c['id']==conflict_id),None)
        if conflict is None:
            raise SyncError('Open metadata conflict not found','not_found',404)
        doc=export_document(core,thread_id)
        flat=_flatten(doc)
        path=conflict['path']
        actual=flat.get(path,MISSING)
        if actual != expected_current:
            raise SyncError('Metadata changed; reload conflict before resolving','metadata_conflict',409)
        if chosen_value not in (conflict['incoming'],conflict['current']) or chosen_value==MISSING:
            raise SyncError('Choose an existing non-deleted conflict value')
        if path.startswith('whiteboard/') and chosen_value!=actual:
            raise SyncError('Whiteboards are append-only; add a correction instead','immutable_whiteboard',409)
        flat[path]=deepcopy(chosen_value)
        resolved=validate_document(_unflatten(flat))
        _apply(core,thread_id,resolved)
        return _record(core,key,thread_id,request,{'document':resolved,
                       'resolved_conflict':conflict_id,'conflicts':[],'state':'synced'},kind='resolve')


class MetadataReplica:
    """Explicit existing local core/thread binding with durable uncertain-request replay."""
    def __init__(self,core,thread_id,checkpoint_dir:Path,*,remote_identity:str):
        core.get(thread_id)
        self.core,self.thread_id=core,thread_id
        directory=Path(checkpoint_dir).absolute()
        if directory.is_symlink():
            raise SyncError('Unsafe metadata checkpoint')
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        directory.chmod(0o700)
        path=directory/'metadata.sqlite3'
        if path.is_symlink():
            raise SyncError('Unsafe metadata checkpoint')
        self.db=sqlite3.connect(path)
        path.chmod(0o600)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('CREATE TABLE IF NOT EXISTS checkpoint(id INTEGER PRIMARY KEY CHECK(id=1),identity TEXT NOT NULL,base TEXT NOT NULL,pending TEXT);')
        identity=_hash([str(Path(core.store.workspace_path).resolve()),thread_id,remote_identity])
        row=self.db.execute('SELECT identity FROM checkpoint WHERE id=1').fetchone()
        if row and row[0]!=identity:
            self.db.close()
            raise SyncError('Metadata checkpoint belongs to another binding','metadata_scope',409)
        if row is None:
            self.db.execute('INSERT INTO checkpoint VALUES(1,?,?,NULL)',(identity,_canonical(_empty())))
            self.db.commit()
        self.identity=identity

    def close(self):
        self.db.close()

    def seed_base(self,document):
        """Seed a pristine binding from its actual server creation snapshot.

        The caller may only provide the bootstrap saved with a newly created
        server binding. Never seed an existing remote project from a fresh GET:
        that would conceal changes made before this local binding was created.
        Pending/replayed work and established bases are never reset.
        """
        initial=validate_document(document)
        with self.db:
            row=self.db.execute('SELECT base,pending FROM checkpoint WHERE id=1').fetchone()
            if row[1] is not None or json.loads(row[0]) != _empty():
                return False
            self.db.execute('UPDATE checkpoint SET base=? WHERE id=1',(_canonical(initial),))
            return True

    def sync_once(self,http,project_id,token):
        _identifier(project_id)
        row=self.db.execute('SELECT base,pending FROM checkpoint WHERE id=1').fetchone()
        if row[1]:
            pending=json.loads(row[1])
            if pending['project_id']!=project_id:
                raise SyncError('Pending metadata operation belongs to another project','metadata_scope',409)
        else:
            with self.core.store.transaction():
                local=export_document(self.core,self.thread_id)
            base=json.loads(row[0])
            if local == base:
                # Polling an unchanged replica must not create another full-size
                # immutable receipt every few seconds. This authenticated GET is
                # only a current-state proof; a later edit is merged next time.
                probe=http.request('GET','/api/projects/'+project_id+'/metadata',
                    headers={'Authorization':'Bearer '+token,'If-None-Match':document_etag(base)})
                if probe.status_code == 304:
                    return {'state':'synced','document':local,'conflicts':[],'unchanged':True}
                probe.raise_for_status()
                if validate_document(probe.json()['document']) == base:
                    return {'state':'synced','document':local,'conflicts':[],'unchanged':True}
            pending={'operation_id':uuid.uuid4().hex,'base':base,'document':local,'project_id':project_id}
            with self.db:
                self.db.execute('UPDATE checkpoint SET pending=? WHERE id=1',(_canonical(pending),))
        response=http.request('POST','/api/projects/'+project_id+'/metadata/sync',headers={'Authorization':'Bearer '+token},
                              json={k:v for k,v in pending.items() if k!='project_id'})
        response.raise_for_status()
        remote=response.json()
        document=validate_document(remote['document'])
        # A separate local idempotent core receipt closes the crash gap between
        # applying metadata and advancing this SQLite checkpoint.
        local_result=synchronize(self.core,self.thread_id,'local_'+pending['operation_id'],pending['document'],document)
        with self.db:
            self.db.execute('UPDATE checkpoint SET base=?,pending=NULL WHERE id=1',(_canonical(document),))
        return {'state':'conflict' if remote.get('conflicts') or local_result['conflicts'] else 'synced',
                'document':local_result['document'],'conflicts':remote.get('conflicts',[])+local_result['conflicts']}
