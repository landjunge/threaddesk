"""A blocked tenant's manifest must leave the shared ASGI loop responsive."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from fastapi.testclient import TestClient

from threaddesk.server_sync.app import create_app
from threaddesk.server_sync.auth import provision
from threaddesk.server_sync.store import SyncStore


@pytest.mark.parametrize('blocked_method',['project','declare_manifest'],ids=['resolution-sqlite-wait','manifest-integrity-work'])
def test_blocked_manifest_does_not_block_other_tenant_status(tmp_path,monkeypatch,blocked_method):
    data=tmp_path/'server'
    tokens={user:provision(data,user) for user in ('alice','bob')}
    app=create_app(data,public_origin='https://testserver')
    entered,release=threading.Event(),threading.Event()
    loop_context=[]
    original=getattr(SyncStore,blocked_method)
    def blocked(self,*args,**kwargs):
        if self.root.parent.name=='alice':
            try:
                asyncio.get_running_loop()
                loop_context.append(True)
            except RuntimeError:
                loop_context.append(False)
            entered.set()
            if not release.wait(timeout=15):
                raise AssertionError('Test did not release manifest worker')
        return original(self,*args,**kwargs)
    with TestClient(app,base_url='https://testserver') as http:
        headers={user:{'Authorization':'Bearer '+token} for user,token in tokens.items()}
        # Initialize both scopes before deliberately holding Alice's store work.
        projects={user:http.post('/api/projects',headers=headers[user],json={'title':user}).json()['id']
                  for user in tokens}
        monkeypatch.setattr(SyncStore,blocked_method,blocked)
        with ThreadPoolExecutor(max_workers=2) as requests:
            manifest=requests.submit(http.post,'/api/projects/'+projects['alice']+'/manifest',
                headers=headers['alice'],json={'files':[],'issues':[],'device_id':'alice-device'})
            try:
                assert entered.wait(timeout=5),'Manifest did not reach the deliberate store wait'
                status=requests.submit(http.get,'/api/projects/'+projects['bob']+'/status',headers=headers['bob'])
                response=status.result(timeout=5)
                assert response.status_code==200,response.text
                assert not release.is_set()
                assert loop_context and not any(loop_context)
            finally:
                release.set()
            response=manifest.result(timeout=5)
            assert response.status_code==200,response.text
