"""Explicit local project bindings; remote metadata never grants host file access."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
import secrets
import stat
import threading
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from threaddesk.core.errors import InvalidState
from threaddesk.server_sync.store import SyncError, _id
from threaddesk.server_sync.identity import recover_binding_device_id, recover_binding_bases

_BOOK_LOCK = threading.RLock()
_RUN_LOCKS = {}


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(p.is_symlink() for p in (path, path.parent)):
        raise InvalidState('Unsafe sync configuration')
    path.parent.chmod(0o700)
    temporary = path.parent / ('.pending-' + secrets.token_hex(16))
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(value, out, ensure_ascii=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read(path):
    if not path.exists():
        return None
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077:
        raise InvalidState('Sync configuration must be a private regular file')
    return json.loads(path.read_text(encoding='utf-8'))


def check_origin(value):
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError as exc:
        raise InvalidState('Invalid server origin') from exc
    developer = os.environ.get('THREADDESK_SYNC_ALLOW_HTTP') == '1'
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {'', '/'} or parsed.scheme != 'https' and not (
                developer and parsed.scheme == 'http' and parsed.hostname in {'localhost', '127.0.0.1', '::1'})):
        raise InvalidState('An HTTPS server origin is required')
    return value.rstrip('/')


def _http_client(**kwargs):
    import httpx
    return httpx.Client(**kwargs)


class BindingBook:
    def __init__(self, core):
        self.core = core
        self.workspace = Path(core.store.workspace_path).resolve()
        self.root = self.workspace / 'server-sync-private'
        if self.root.is_symlink():
            raise InvalidState('Unsafe sync directory')

    def load(self, thread_id):
        with _BOOK_LOCK:
            return _read(self.root / (_id(thread_id) + '.json'))

    def view(self, thread_id):
        config = self.load(thread_id)
        if not config:
            references = list(self.core.get(thread_id).context.files)
            return {'configured': False, 'status': {'state': 'unconfigured'},
                    'owner_references':references,'owner_references_text':'\n'.join(references)}
        public = {k:v for k,v in config.items() if k != 'token'}
        public['owner_references_text'] = '\n'.join(config.get('owner_references',[]))
        public['approved_roots_text'] = '\n'.join(config.get('approved_roots',[]))
        public['configured'] = True
        public['token_configured'] = bool(config.get('token'))
        status = _read(self.root / (thread_id + '.status.json'))
        public['status'] = status if status and status.get('config_id') == config['config_id'] else {'state':'pending'}
        from threaddesk.server_sync.metadata import export_document, list_conflicts
        conflicts = list_conflicts(self.core,thread_id)
        public['local_metadata_conflicts'] = []
        if conflicts:
            document = export_document(self.core,thread_id)
            for conflict in conflicts:
                current = document
                for part in conflict['path'].split('/'):
                    current = current.get(part,{'$missing':True}) if isinstance(current,dict) else {'$missing':True}
                public['local_metadata_conflicts'].append({**conflict,'expected_current':current,
                    'operation_id':secrets.token_hex(16)})
        return public

    def save(self, thread_id, *, url, project_id, root, token, approved_roots=(), owner_references=None, automatic=True, offline_enabled=False):
        _id(thread_id)
        origin = check_origin(url)
        selected = Path(root).expanduser()
        if selected.is_symlink() or not selected.is_dir():
            raise InvalidState('Choose an existing project directory')
        selected = selected.resolve()
        if self.workspace.is_relative_to(selected) or selected.is_relative_to(self.workspace):
            raise InvalidState('Choose project files separately from the ThreadDesk workspace')
        approved = []
        for value in approved_roots:
            path = Path(value).expanduser()
            if path.is_symlink() or not path.is_dir():
                raise InvalidState('Approved dependency roots must be real directories')
            path = path.resolve()
            if (path == Path(path.anchor) or Path.home().resolve().is_relative_to(path)
                    or self.workspace.is_relative_to(path) or path.is_relative_to(self.workspace)):
                raise InvalidState('Do not grant the home, filesystem or ThreadDesk workspace as a dependency root')
            approved.append(str(path))
        with _BOOK_LOCK:
            old = self.load(thread_id) or {}
            if owner_references is None:
                # Never rebuild a configured binding's authority from replicated data.
                owner_references = old.get('owner_references',[]) if old else list(self.core.get(thread_id).context.files)
            if (not isinstance(owner_references,list) or len(owner_references)>128
                    or any(not isinstance(ref,str) or len(ref)>4096 for ref in owner_references)):
                raise InvalidState('Invalid owner file grants')
            if not token:
                if old.get('url') != origin:
                    raise InvalidState('Provide an access token for this server')
                token = old.get('token')
            if not isinstance(token, str) or not 20 <= len(token) <= 256 or any(c.isspace() for c in token):
                raise InvalidState('Invalid access token')
            if project_id:
                _id(project_id)
            if not project_id and old.get('url') == origin and old.get('token') == token:
                binding_id = hashlib.sha256((str(self.workspace)+'\0'+thread_id).encode()).hexdigest()
                auto_pid = hashlib.sha256(binding_id.encode()).hexdigest()[:24]
                if old.get('project_id') == auto_pid:
                    # Replaying the original automatic configure form is the
                    # same binding, even after its server ID was filled in.
                    project_id = auto_pid
            same_binding = (old.get('url') == origin and old.get('project_id') == project_id
                            and old.get('token') == token)
            device_id = recover_binding_device_id(self.root, thread_id, old if same_binding else {})
            initial_bases = old.get('initial_bases', []) if same_binding else []
            if same_binding and old.get('root') != str(selected):
                initial_bases = recover_binding_bases(self.root, thread_id, old) or initial_bases
            config = {'config_id':secrets.token_hex(16), 'thread_id':thread_id,
                      'url':origin, 'project_id':project_id, 'root':str(selected),
                      'token':token, 'approved_roots':approved, 'automatic':bool(automatic),
                      'owner_references':list(dict.fromkeys(owner_references)),
                      'device_id':device_id, 'initial_bases':initial_bases,
                      'offline_enabled':bool(offline_enabled), 'offline_pending':True}
            _write(self.root / (thread_id+'.json'), config)
            return config

    def update(self, thread_id, fields, *, config_id=None):
        with _BOOK_LOCK:
            config = self.load(thread_id)
            if not config or config_id and config['config_id'] != config_id:
                return
            config.update(fields)
            if {'offline_enabled','offline_pending','automatic','owner_references'} & fields.keys() and config_id is None:
                config['config_id'] = secrets.token_hex(16)
            _write(self.root / (thread_id+'.json'), config)

    def record(self, thread_id, config_id, status):
        with _BOOK_LOCK:
            config = self.load(thread_id)
            if config and config['config_id'] == config_id:
                _write(self.root / (thread_id+'.status.json'), {**status, 'config_id':config_id})

    def configured_threads(self):
        if not self.root.exists():
            return []
        return [p.stem for p in self.root.glob('*.json') if '.status.' not in p.name and not p.name.startswith('.')]


def record_owner_reference(core, thread_id, path, *, allowed=True):
    """Only explicit protected local file actions may amend source authority."""
    book = BindingBook(core)
    with _BOOK_LOCK:
        config = book.load(thread_id)
        if not config:
            return
        references = list(config.get('owner_references',[]))
        reference = path.strip()
        if allowed and reference not in references:
            references.append(reference)
        if not allowed:
            references = [value for value in references if value != reference]
        book.update(thread_id,{'owner_references':references})


class DesktopSyncManager:
    def __init__(self, service_factory):
        self.service_factory = service_factory
        self.stop_event = threading.Event()
        self.worker = None

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.stop_event.clear()
        self.worker = threading.Thread(target=self._loop, name='threaddesk-project-sync', daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_event.set()
        if self.worker:
            self.worker.join(timeout=2)

    def _loop(self):
        while not self.stop_event.is_set():
            core = None
            try:
                core = self.service_factory()
                book = BindingBook(core)
                for tid in book.configured_threads():
                    if self.stop_event.is_set():
                        break
                    config = book.load(tid)
                    if config and config.get('automatic'):
                        self.run_once(core, tid)
            except Exception:
                # Each bound run records its bounded error; workspace selection
                # errors retry on the next loop without starting any other task.
                pass
            finally:
                if core and hasattr(core.store, 'connection'):
                    core.store.connection.close()
            self.stop_event.wait(5)

    def run_once(self, core, thread_id):
        import httpx
        from threaddesk.server_sync.client import SyncClient
        from threaddesk.server_sync.metadata import MetadataReplica
        book = BindingBook(core)
        config = book.load(thread_id)
        if not config:
            raise InvalidState('Configure this project first')
        with _BOOK_LOCK:
            lock = _RUN_LOCKS.setdefault((str(book.workspace),thread_id), threading.Lock())
        if not lock.acquire(blocking=False):
            return {'state':'syncing'}
        replica = client = None
        try:
            if not config.get('device_id'):
                config['device_id'] = recover_binding_device_id(book.root, thread_id, config)
                book.update(thread_id, {'device_id':config['device_id']}, config_id=config['config_id'])
            book.record(thread_id,config['config_id'],{'state':'syncing'})
            # Owner grants are separate from the mutable replicated context.
            references = list(config.get('owner_references',[]))
            requirements = [ref for ref in core.get(thread_id).context.files if ref not in references]
            bootstrap = config.get('bootstrap_document')
            with _http_client(base_url=config['url'], headers={'Authorization':'Bearer '+config['token']},
                              timeout=10, follow_redirects=False) as http:
                pid = config['project_id']
                if not pid:
                    binding_id = hashlib.sha256((str(book.workspace)+'\0'+thread_id).encode()).hexdigest()
                    response = http.post('/api/projects/bind', json={'binding_id':binding_id,'title':core.get(thread_id).title})
                    response.raise_for_status()
                    bound = response.json()
                    pid = bound['id']
                    bootstrap = bound.get('bootstrap_document')
                    _id(pid)
                    book.update(thread_id, {'project_id':pid,'bootstrap_document':bootstrap}, config_id=config['config_id'])
                if config['offline_pending']:
                    response = http.put('/api/projects/'+pid+'/offline', json={'enabled':config['offline_enabled']})
                    response.raise_for_status()
                    book.update(thread_id, {'offline_pending':False}, config_id=config['config_id'])
                identity = config['url']+'\0'+pid+'\0'+hashlib.sha256(config['token'].encode()).hexdigest()
                state = book.root / 'replicas' / thread_id / hashlib.sha256(identity.encode()).hexdigest()
                file_state = state / 'files' / hashlib.sha256(str(Path(config['root']).resolve()).encode()).hexdigest()
                replica = MetadataReplica(core, thread_id, state/'metadata', remote_identity=identity)
                if bootstrap is not None:
                    replica.seed_base(bootstrap)
                client = SyncClient(config['url'],config['token'],pid,Path(config['root']),state_dir=file_state,
                                    transport=http,allow_insecure_loopback=os.environ.get('THREADDESK_SYNC_ALLOW_HTTP')=='1',
                                    metadata_replica=replica,local_references=references,approved_roots=config['approved_roots'],
                                    required_references=requirements,device_id=config['device_id'],
                                    initial_bases=config.get('initial_bases',[]))
                result = client.sync_once()
                book.update(thread_id, {'bootstrap_document':None,'initial_bases':[]}, config_id=config['config_id'])
                book.update(thread_id, {'offline_enabled':result['offline_enabled']}, config_id=config['config_id'])
                book.record(thread_id,config['config_id'],result)
                return result
        except Exception as exc:
            status = {'state':'disconnected','error':type(exc).__name__}
            if isinstance(exc, httpx.HTTPStatusError):
                status['http_status'] = exc.response.status_code
                try:
                    value = exc.response.json()
                    detail = value.get('detail') or value.get('error')
                except (ValueError,AttributeError):
                    detail = None
            else:
                detail = str(exc) if isinstance(exc,(InvalidState,SyncError,ValueError,RuntimeError)) else None
            if isinstance(detail,str):
                status['detail'] = detail.replace(config['token'],'[redacted]')[:500]
            book.record(thread_id,config['config_id'],status)
            return status
        finally:
            if client:
                client.close()
            if replica and hasattr(replica,'close'):
                replica.close()
            lock.release()


def install_routes(app, service_factory, render):
    manager = DesktopSyncManager(service_factory)
    app.state.server_sync_manager = manager

    @contextmanager
    def worker_service():
        # SQLite connections are created, used and closed on this SAME worker.
        # The async request handler must never construct a core on the event loop
        # and then hand that thread-bound connection to the pool.
        core = service_factory()
        try:
            yield core
        finally:
            connection = getattr(core.store, 'connection', None)
            if connection is not None:
                connection.close()

    @app.get('/threads/{thread_id}/server-sync')
    def sync_page(thread_id: str, request: Request):
        with worker_service() as core:
            core.get(thread_id)
            return render(request, {'sync_binding':BindingBook(core).view(thread_id)})

    @app.get('/api/threads/{thread_id}/server-sync')
    def sync_status(thread_id: str):
        with worker_service() as core:
            core.get(thread_id)
            return BindingBook(core).view(thread_id)

    def perform_action(thread_id, request, form):
        with worker_service() as core:
            core.get(thread_id)
            book = BindingBook(core)
            action = form.get('action')
            if action == 'configure':
                book.save(thread_id,url=str(form.get('url','')),project_id=str(form.get('project_id','')).strip(),
                          root=str(form.get('root','')),token=str(form.get('token','')),
                          approved_roots=[s.strip() for s in str(form.get('approved_roots','')).splitlines() if s.strip()],
                          owner_references=[s.strip() for s in str(form.get('owner_references','')).splitlines() if s.strip()],
                          automatic=form.get('automatic')=='on',offline_enabled=form.get('offline')=='on')
                manager.run_once(core,thread_id)
            elif action == 'sync':
                manager.run_once(core,thread_id)
            elif action == 'offline':
                if not book.load(thread_id):
                    raise HTTPException(409,'Configure project first')
                book.update(thread_id, {'offline_enabled':form.get('offline')=='on','offline_pending':True})
                manager.run_once(core,thread_id)
            elif action == 'resolve_local':
                from threaddesk.server_sync.metadata import resolve_conflict
                try:
                    expected = json.loads(str(form.get('expected_current','')))
                    chosen = json.loads(str(form.get('chosen_value','')))
                except ValueError as exc:
                    raise HTTPException(400,'Invalid conflict value') from exc
                resolve_conflict(core,thread_id,str(form.get('conflict_id','')),expected,chosen,str(form.get('operation_id','')))
            else:
                raise HTTPException(400,'Unsupported sync action')
            return render(request, {'sync_binding':book.view(thread_id)})

    @app.post('/threads/{thread_id}/server-sync')
    async def sync_action(thread_id: str, request: Request):
        form = await request.form()
        # Inventory hashing, SQLite and remote HTTP all belong to the worker;
        # unrelated desktop requests must keep their event loop available.
        return await run_in_threadpool(perform_action, thread_id, request, dict(form))
