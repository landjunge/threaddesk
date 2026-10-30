"""Manual sync never blocks the desktop loop or crosses SQLite thread ownership."""
import asyncio
import threading

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from threaddesk.api.service import ThreadService
from threaddesk.server_sync.desktop import BindingBook, install_routes
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


class BoundConnection:
    def __init__(self,connection):
        self.connection=connection
        self.owner=threading.get_ident()
        self.closed=False
        self.close_thread=None

    def __getattr__(self,name):
        value=getattr(self.connection,name)
        if not callable(value):return value
        def owned(*args,**kwargs):
            assert threading.get_ident()==self.owner,'SQLite connection crossed worker threads'
            assert not self.closed
            return value(*args,**kwargs)
        return owned

    def close(self):
        assert threading.get_ident()==self.owner,'SQLite connection closed from another thread'
        assert not self.closed
        self.connection.close()
        self.closed=True
        self.close_thread=threading.get_ident()


def routes(tmp_path,backend):
    workspace=tmp_path/'desktop'
    seed=ThreadService(backend(workspace));tid=seed.create('Project').id
    root=tmp_path/'files';root.mkdir()
    BindingBook(seed).save(tid,url='https://server.example',project_id='',root=root,
                           token='owner-token-with-enough-length',automatic=False,offline_enabled=True)
    if hasattr(seed.store,'connection'):seed.store.connection.close()
    app=FastAPI()
    created=[]
    connections=[]
    loop_threads=set()

    @app.middleware('http')
    async def observe_loop(request,call_next):
        loop_threads.add(threading.get_ident())
        return await call_next(request)

    @app.get('/unrelated-status')
    async def unrelated():
        return {'available':True}

    def factory():
        owner=threading.get_ident()
        store=backend(workspace)
        created.append(owner)
        if hasattr(store,'connection'):
            store.connection=BoundConnection(store.connection)
            connections.append(store.connection)
        original=store.get_thread
        def owned_get(thread_id, **options):
            assert threading.get_ident()==owner,'Core crossed worker threads'
            return original(thread_id, **options)
        store.get_thread=owned_get
        return ThreadService(store)

    def render(request:Request,extra):
        assert threading.get_ident() not in loop_threads
        return JSONResponse({'binding':extra['sync_binding'],'render_thread':threading.get_ident()})

    install_routes(app,factory,render)
    return app,tid,root,created,connections,loop_threads


@pytest.mark.parametrize('backend',[JsonStore,SQLiteStore],ids=['json','sqlite'])
@pytest.mark.parametrize('action',['configure','offline','sync'])
def test_manual_action_keeps_unrelated_status_and_binding_status_responsive(tmp_path,backend,action):
    app,tid,root,created,connections,loop_threads=routes(tmp_path,backend)
    entered=threading.Event();release=threading.Event();manual_threads=[]

    def blocked(core,thread_id):
        manual_threads.append(threading.get_ident())
        assert threading.get_ident() not in loop_threads
        core.get(thread_id)
        entered.set()
        if not release.wait(5):raise AssertionError('Manual sync was not released')
        return {'state':'ready'}

    app.state.server_sync_manager.run_once=blocked

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as http:
            form={'action':action,'offline':'on'}
            if action=='configure':
                form.update(url='https://server.example',project_id='',root=str(root),
                            token='owner-token-with-enough-length')
            manual=asyncio.create_task(http.post('/threads/'+tid+'/server-sync',data=form))
            try:
                for _ in range(100):
                    if entered.is_set():break
                    await asyncio.sleep(.01)
                assert entered.is_set() and not manual.done()
                health=await asyncio.wait_for(http.get('/unrelated-status'),timeout=1)
                assert health.status_code==200 and health.json()['available']
                status=await asyncio.wait_for(http.get('/api/threads/'+tid+'/server-sync'),timeout=1)
                assert status.status_code==200 and status.json()['configured']
                assert not manual.done()
            finally:
                release.set()
            result=await manual
            assert result.status_code==200,result.text
            assert result.json()['render_thread']==manual_threads[0]

    asyncio.run(scenario())
    assert len(created)==2 and all(owner not in loop_threads for owner in created)
    assert all(connection.closed and connection.close_thread==connection.owner for connection in connections)
    if backend is SQLiteStore:assert len(connections)==2


@pytest.mark.parametrize('backend',[JsonStore,SQLiteStore],ids=['json','sqlite'])
def test_manual_failure_closes_its_worker_owned_service(tmp_path,backend):
    app,tid,root,created,connections,loop_threads=routes(tmp_path,backend)

    def fail(core,thread_id):
        assert threading.get_ident() not in loop_threads
        core.get(thread_id)
        raise RuntimeError('Injected manual synchronization failure')

    app.state.server_sync_manager.run_once=fail

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as http:
            with pytest.raises(RuntimeError,match='Injected manual'):
                await http.post('/threads/'+tid+'/server-sync',data={'action':'sync'})

    asyncio.run(scenario())
    assert created and all(owner not in loop_threads for owner in created)
    assert all(connection.closed and connection.close_thread==connection.owner for connection in connections)
    if backend is SQLiteStore:assert len(connections)==1
