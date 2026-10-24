#!/usr/bin/env python3
"""Run synthetic Linux/TLS/two-replica/restart/restore acceptance in Docker.

No public port, real workspace, external runtime restart or insecure TLS client.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import ssl
import subprocess
import sys
import tempfile
import time


def outer(args):
    root = Path(__file__).resolve().parents[2]
    docker = ['docker'] + (['--context', args.docker_context] if args.docker_context else [])
    subprocess.run(docker + ['info', '--format', '{{.OSType}}/{{.Architecture}}'], check=True)
    if not args.skip_build:
        subprocess.run(docker + ['build', '-f', str(root/'packaging/server/Dockerfile'), '-t', args.image, str(root)], check=True)
    with tempfile.TemporaryDirectory(prefix='td-codex3-tls-') as temporary:
        certs = Path(temporary)
        commands = [
            ['req','-x509','-newkey','rsa:2048','-nodes','-days','2','-subj','/CN=ThreadDesk isolated acceptance CA',
             '-keyout',str(certs/'ca.key'),'-out',str(certs/'ca.crt')],
            ['req','-newkey','rsa:2048','-nodes','-subj','/CN=localhost','-keyout',str(certs/'server.key'),'-out',str(certs/'server.csr')],
            ['x509','-req','-in',str(certs/'server.csr'),'-CA',str(certs/'ca.crt'),'-CAkey',str(certs/'ca.key'),
             '-CAcreateserial','-days','2','-extfile',str(certs/'extensions.cnf'),'-out',str(certs/'server.crt')],
        ]
        (certs/'extensions.cnf').write_text('subjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\n')
        for command in commands:
            subprocess.run(['openssl']+command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        # Only ephemeral TEST server key/certs are exposed to the nonroot test container.
        # The signing CA private key stays on the host and is never mounted.
        mounted = certs/'public-test-material'; mounted.mkdir(mode=0o755)
        for name in ('ca.crt','server.crt','server.key'):
            (mounted/name).write_bytes((certs/name).read_bytes()); (mounted/name).chmod(0o444)
        mounted.chmod(0o755)
        certs.chmod(0o755)
        payload=json.dumps({'script':Path(__file__).read_text(),
            'certs':{name:base64.b64encode((mounted/name).read_bytes()).decode()
                     for name in ('ca.crt','server.crt','server.key')}})
        bootstrap=(
            'import sys,json,base64; from pathlib import Path; '
            'payload=json.load(sys.stdin); root=Path("/tmp/td-certs"); root.mkdir(mode=0o700); '
            '[(root/name).write_bytes(base64.b64decode(data)) for name,data in payload["certs"].items()]; '
            '[(root/name).chmod(0o600) for name in payload["certs"]]; '
            'exec(compile(payload["script"],"/tmp/acceptance.py","exec"))')
        # Stream only synthetic inputs over stdin, which works for remote VM
        # daemons without host mounts and preserves a read-only container root.
        subprocess.run(docker+['run','--rm','--interactive','--label','td-codex3-acceptance=true',
            '--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--memory','768m','--cpus','2','--tmpfs','/tmp:mode=1777,size=512m',
            '--entrypoint','python',args.image,'-c',bootstrap,'--inside'],
            input=payload,text=True,check=True)



def inside():
    import httpx
    from threaddesk.server_sync.auth import provision
    from threaddesk.server_sync.backup import backup, restore, BackupError
    from threaddesk.server_sync.client import SyncClient

    assert platform.system() == 'Linux', 'Acceptance requires actual Linux kernel'
    certs = Path('/tmp/td-certs')
    context = ssl.create_default_context(cafile=str(certs/'ca.crt'))
    with tempfile.TemporaryDirectory(prefix='td-codex3-acceptance-') as temporary:
        work = Path(temporary); data=work/'server'; token=provision(data,'alice'); bob=provision(data,'bob')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0)); port=listener.getsockname()[1]
        origin=f'https://localhost:{port}'
        process=None
        log_path=work/'server.log'
        clients=[]

        def start(directory):
            nonlocal process
            program=(
                'from pathlib import Path; import uvicorn; '
                'from threaddesk.server_sync.app import create_app; '
                'import sys; '
                'app=create_app(Path(sys.argv[1]),public_origin=sys.argv[2]); '
                'uvicorn.run(app,host="127.0.0.1",port=int(sys.argv[3]),'
                'ssl_certfile="/tmp/td-certs/server.crt",ssl_keyfile="/tmp/td-certs/server.key",'
                'proxy_headers=False,access_log=False,log_level="info",timeout_graceful_shutdown=10)')
            with log_path.open('ab') as log:
                process=subprocess.Popen([sys.executable,'-c',program,str(directory),origin,str(port)],stdout=log,stderr=log)
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                if process.poll() is not None:
                    raise AssertionError('Server exited: '+log_path.read_text())
                try:
                    response=httpx.get(origin+'/',verify=context,trust_env=False,timeout=1)
                    if response.status_code==200: return
                except httpx.HTTPError: pass
                time.sleep(.1)
            raise AssertionError('Server did not become ready: '+log_path.read_text())

        def stop():
            nonlocal process
            if process is not None:
                process.terminate()
                try: process.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
                    raise AssertionError('Server failed graceful stop: '+log_path.read_text())
                process=None

        try:
            start(data)
            with httpx.Client(base_url=origin,verify=context,trust_env=False,timeout=10,
                              headers={'Authorization':'Bearer '+token}) as http:
                assert http.get('/api/projects',headers={'Authorization':'Bearer invalid'}).status_code==401
                # Default trust store must reject our private CA, proving verification is active.
                try: httpx.get(origin+'/',trust_env=False,timeout=3)
                except httpx.ConnectError: pass
                else: raise AssertionError('Untrusted certificate unexpectedly accepted')
                try: httpx.get(f'http://127.0.0.1:{port}/api/projects',trust_env=False,timeout=3)
                except httpx.HTTPError: pass
                else: raise AssertionError('TLS port accepted plaintext HTTP')
                pid=http.post('/api/projects',json={'title':'Linux TLS acceptance'}).json()['id']; api='/api/projects/'+pid
                assert http.get(api+'/status',headers={'Authorization':'Bearer '+bob}).status_code==404
                assert http.get(api+'/status').json()['state']=='metadata_only'
                assert http.put(api+'/offline',json={'enabled':True}).status_code==200
                thread=http.get(api+'/thread').json()
                assert http.put(api+'/thread',json={'revision':thread['revision'],'description':'Snapshot original','notes':'Offline notes'}).status_code==200
                thread=http.get(api+'/thread').json()
                assert http.put(api+'/thread',json={'revision':thread['revision'],'description':'Snapshot updated','notes':'Current notes'}).status_code==200
                assert http.post(api+'/whiteboard',json={'content':'Retain whiteboard','entry_type':'note','external_key':'linux-acceptance'}).status_code==200
                for name in ('replica-a','replica-b'): (work/name).mkdir()
                (work/'replica-a/note.md').write_text('original')
                for name in ('replica-a','replica-b'):
                    transport=httpx.Client(base_url=origin,verify=context,trust_env=False,timeout=10)
                    client=SyncClient(origin,token,pid,work/name,state_dir=work/(name+'-state'),transport=transport)
                    clients.append((client,transport))
                a,b=clients[0][0],clients[1][0]
                a.sync_once(); b.sync_once(); a.sync_once()
                assert (work/'replica-b/note.md').read_text()=='original'
                original=http.get(api+'/files').json()['files'][0]['heads'][0]['revision']
                (work/'replica-b/note.md').write_text('server-side edit')
                b.sync_once(); a.sync_once()
                assert (work/'replica-a/note.md').read_text()=='server-side edit'
                (work/'replica-a/note.md').write_text('local conflict')
                (work/'replica-b/note.md').write_text('remote conflict')
                a.sync_once(); b.sync_once(); a.sync_once()
                assert http.get(api+'/status').json()['conflict_count']==1
                assert (work/'replica-a/note.md').read_text()=='local conflict'
                assert (work/'replica-b/note.md').read_text()=='remote conflict'
                assert http.get(api+'/revisions/'+original).content==b'original'
                metadata_before=http.get(api+'/metadata').json()['document']
                assert metadata_before['thread']['notes']=='Current notes'
                metadata_request={'operation_id':'linux-metadata-receipt','base':metadata_before,'document':metadata_before}
                metadata_reply=http.post(api+'/metadata/sync',json=metadata_request)
                assert metadata_reply.status_code==200, metadata_reply.text
                metadata_receipt=metadata_reply.json()
                payload=b'interrupted Linux transfer'
                transfer=api+'/uploads/resume-linux'
                assert http.post(transfer,json={'path':'resumed.md','size':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}).status_code==200
                assert http.patch(transfer,json={'offset':0,'data_base64':base64.b64encode(payload[:7]).decode()}).status_code==200
                with __import__('contextlib').suppress(BackupError):
                    backup(data,work/'must-not-exist.tar')
                assert not (work/'must-not-exist.tar').exists(), 'Running server backup must fail closed'
                stop(); start(data)
                assert http.get(transfer).json()['next_offset']==7
                stop()
                artifact=work/'server-backup.tar'; manifest=backup(data,artifact)
                before={item['path']:hashlib.sha256((data/item['path']).read_bytes()).hexdigest() for item in manifest['files']}
                restored=work/'restored'; restore(artifact,restored)
                assert all(hashlib.sha256((data/path).read_bytes()).hexdigest()==digest for path,digest in before.items())
                start(restored)
                assert http.get(api+'/thread').json()['description']=='Snapshot updated'
                assert http.get(api+'/metadata').json()['document']==metadata_before, 'Portable metadata origins must survive restore'
                assert http.post(api+'/metadata/sync',json=metadata_request).json()==metadata_receipt
                assert http.get(api+'/whiteboard').json()['entries'][0]['content']=='Retain whiteboard'
                snapshots=list((restored/'users/alice/core/snapshots'/pid).glob('*.json'))
                assert snapshots and any('Snapshot original' in p.read_text() and 'Offline notes' in p.read_text() for p in snapshots)
                assert http.get(api+'/status').json()['conflict_count']==1
                assert http.get(api+'/revisions/'+original).content==b'original'
                assert http.get(transfer).json()['next_offset']==7
                assert http.patch(transfer,json={'offset':7,'data_base64':base64.b64encode(payload[7:]).decode()}).status_code==200
                receipt=http.post(transfer+'/commit').json()
                assert http.post(transfer+'/commit').json()==receipt
                assert http.get(api+'/revisions/'+receipt['revision']).content==payload
                a.sync_once(); b.sync_once()
                assert (work/'replica-a/resumed.md').read_bytes()==payload
                assert (work/'replica-b/resumed.md').read_bytes()==payload
                assert http.get(api+'/status',headers={'Authorization':'Bearer '+bob}).status_code==404
                stop()
            print(json.dumps({'platform':platform.system(),'architecture':platform.machine(),
                'tls':'private CA verified; default trust and plaintext refused',
                'replicas':2,'restart':'passed','restore':'credentials/core/snapshots/whiteboard/history/conflicts/chunks/receipts verified',
                'result':'passed'},sort_keys=True))
        finally:
            for client,transport in clients:
                client.close(); transport.close()
            stop()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker-context')
    parser.add_argument('--image',default='td-codex3-server-sync-acceptance:local')
    parser.add_argument('--inside',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--skip-build',action='store_true',help='Use existing image for diagnostic reruns only')
    args=parser.parse_args()
    inside() if args.inside else outer(args)


if __name__=='__main__':
    main()
