#!/usr/bin/env python3
"""Exercise the shipping Caddy route limits with the actual Linux application.

Only the Caddy TCP port is published, on host loopback at a random port. All
credentials, certificates and project data are synthetic and ephemeral. Docker
exec streams test inputs so remote VM daemons require no host bind mounts.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import ipaddress
import json
from pathlib import Path
import secrets
import subprocess
import tarfile
import tempfile
import textwrap


CLIENT = r'''
import base64,hashlib,json,ssl,time
from pathlib import Path
import httpx

work=Path('/tmp/td-proxy-app')
context=ssl.create_default_context(cafile=str(work/'ca.crt'))
headers={'Authorization':'Bearer '+(work/'token').read_text().strip()}
with httpx.Client(base_url='https://server.example.org',verify=context,
                  headers=headers,trust_env=False,timeout=60) as http:
    deadline=time.monotonic()+45
    while True:
        try:
            response=http.get('/api/projects')
            if response.status_code==200: break
        except httpx.HTTPError: pass
        if time.monotonic()>deadline: raise AssertionError('Caddy/app did not become ready')
        time.sleep(.2)
    assert http.get('/api/projects',headers={'Authorization':'Bearer invalid'}).status_code==401
    pid=http.post('/api/projects',json={'title':'Shipping Caddy proxy acceptance'}).json()['id']
    api='/api/projects/'+pid
    empty=hashlib.sha256(b'').hexdigest()
    files=[{'path':'project/'+str(i).zfill(5)+'-'+'x'*80+'.txt','sha256':empty,'size':0} for i in range(19000)]
    payload=json.dumps({'files':files,'issues':[],'device_id':'caddy-manifest'},separators=(',',':')).encode()
    assert len(payload)>2*1024*1024
    results=[]
    for mode in ('content-length','chunked'):
        content=payload if mode=='content-length' else (payload[i:i+65536] for i in range(0,len(payload),65536))
        response=http.post(api+'/manifest',content=content,headers={'Content-Type':'application/json'})
        assert response.status_code==200,(mode,response.status_code,response.text[:500])
        if mode=='content-length':
            assert response.request.headers['content-length']==str(len(payload))
        else:
            assert response.request.headers.get('transfer-encoding')=='chunked'
            assert 'content-length' not in response.request.headers
        status=response.json()
        assert status['state']=='metadata_only'
        assert len(status['missing_files'])==19000
        results.append({'mode':mode,'bytes':len(payload),'status':response.status_code,'files':19000})
    # 100000 emoji notes are 400KB in canonical documents, but JSON escaping
    # makes the valid base/incoming pair >2MB. Neither document is over 1MiB.
    thread=http.get(api+'/thread').json()
    notes=chr(0x1F600)*100000
    value={'revision':thread['revision'],'description':'Unicode notes','notes':notes}
    response=http.put(api+'/thread',content=json.dumps(value,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'})
    assert response.status_code==200,(response.status_code,response.text[:500])
    base=http.get(api+'/metadata').json()['document']
    incoming=json.loads(json.dumps(base));incoming['thread']['description']='Unicode metadata accepted through actual Caddy'
    for document in (base,incoming):
        assert len(json.dumps(document,ensure_ascii=False,separators=(',',':')).encode())<1024*1024
    metadata=json.dumps({'operation_id':'proxy-unicode','base':base,'document':incoming},ensure_ascii=True).encode()
    assert 2*1024*1024<len(metadata)<4*1024*1024
    response=http.post(api+'/metadata/sync',content=metadata,headers={'Content-Type':'application/json'})
    assert response.status_code==200,(response.status_code,response.text[:500])
    assert response.json()['document']['thread']['notes']==notes
    # Real ordinary upload still works; default route does not inherit a larger cap.
    assert http.put(api+'/offline',json={'enabled':True}).status_code==200
    content=b'ordinary verified project file'
    transfer=api+'/uploads/ordinary'
    assert http.post(transfer,json={'path':'ordinary.txt','size':len(content),'sha256':hashlib.sha256(content).hexdigest()}).status_code==200
    response=http.patch(transfer,json={'offset':0,'data_base64':base64.b64encode(content).decode()})
    assert response.status_code==200,(response.status_code,response.text[:500])
    receipt=http.post(transfer+'/commit').json()
    assert http.get(api+'/revisions/'+receipt['revision']).content==content
    oversized=b' '*((512*1024)+1)
    for mode in ('content-length','chunked'):
        body=oversized if mode=='content-length' else (oversized[i:i+32768] for i in range(0,len(oversized),32768))
        response=http.patch(transfer,content=body,headers={'Content-Type':'application/json'})
        assert response.status_code==413,(mode,response.status_code,response.text[:500])
        if mode=='chunked': assert response.request.headers.get('transfer-encoding')=='chunked'
    print(json.dumps({'result':'passed','tls':'private CA verified, actual shipping Caddy reverse proxy',
                      'manifest':results,'metadata_bytes':len(metadata),'metadata_status':200,
                      'default_limit':524288,'default_oversize_status':413,'ordinary_chunk':'verified'},sort_keys=True))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker-context')
    parser.add_argument('--image',default='td-codex3-server-sync-acceptance:local')
    parser.add_argument('--caddy-image',default='caddy:2')
    parser.add_argument('--skip-build',action='store_true',help='Use the image built by the preceding Linux acceptance step')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    docker=['docker']+(['--context',args.docker_context] if args.docker_context else [])

    def run(*arguments,**kwargs):
        return subprocess.run(docker+list(arguments),check=True,**kwargs)

    run('info','--format','{{.OSType}}/{{.Architecture}}')
    if not args.skip_build:
        run('build','-f',str(root/'packaging/server/Dockerfile'),'-t',args.image,str(root))
    run('pull',args.caddy_image)
    suffix=secrets.token_hex(6)
    label='td-codex3-proxy-acceptance='+suffix
    network_name='td-codex3-proxy-'+suffix
    network=None;containers=[]
    try:
        existing=run('network','ls','--format','{{.ID}}',capture_output=True,text=True).stdout.split()
        used=[]
        if existing:
            for item in json.loads(run('network','inspect',*existing,capture_output=True,text=True).stdout):
                used.extend(ipaddress.ip_network(c['Subnet']) for c in (item.get('IPAM',{}).get('Config') or []) if c.get('Subnet'))
        candidates=[ipaddress.ip_network('172.29.'+str(i)+'.0/24') for i in range(64,240)]
        subnet=next(n for n in candidates if not any(n.overlaps(old) for old in used if old.version==4))
        # A dedicated bridge isolates these containers from other Docker networks.
        # Docker's --internal mode suppresses published ports; use a private bridge
        # and assert that the sole host binding is Caddy on loopback instead.
        network=run('network','create','--label',label,'--subnet',str(subnet),network_name,capture_output=True,text=True).stdout.strip()
        app_wait='import os,sys,time; from pathlib import Path; p=Path("/tmp/td-proxy-app/bootstrap.py"); exec("while not p.exists(): time.sleep(.05)"); os.execv(sys.executable,[sys.executable,str(p)])'
        app=run('run','--detach','--label',label,'--network',network_name,'--network-alias','app',
                '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','768m','--cpus','2',
                '--tmpfs','/tmp:mode=1777,size=256m','--entrypoint','python',args.image,'-c',app_wait,
                capture_output=True,text=True).stdout.strip();containers.append(app)
        proxy=run('run','--detach','--label',label,'--network',network_name,'--network-alias','server.example.org',
                  '--publish','127.0.0.1::443','--read-only','--cap-drop','ALL','--cap-add','NET_BIND_SERVICE',
                  '--security-opt','no-new-privileges','--memory','128m','--cpus','1',
                  '--tmpfs','/tmp:mode=1777,size=16m','--tmpfs','/data:mode=0700,size=16m','--tmpfs','/config:mode=0700,size=16m',
                  '--env','THREADDESK_DOMAIN=server.example.org','--entrypoint','sh',args.caddy_image,
                  '-c','while [ ! -f /tmp/td-proxy/ready ]; do sleep .1; done; exec caddy run --config /tmp/td-proxy/Caddyfile --adapter caddyfile',
                  capture_output=True,text=True).stdout.strip();containers.append(proxy)
        with tempfile.TemporaryDirectory(prefix='td-codex3-proxy-ca-') as temporary:
            certs=Path(temporary)
            (certs/'extensions.cnf').write_text('subjectAltName=DNS:server.example.org\nextendedKeyUsage=serverAuth\n')
            for command in [
                ['req','-x509','-newkey','rsa:2048','-nodes','-days','2','-subj','/CN=ThreadDesk proxy acceptance CA','-keyout',str(certs/'ca.key'),'-out',str(certs/'ca.crt')],
                ['req','-newkey','rsa:2048','-nodes','-subj','/CN=server.example.org','-keyout',str(certs/'server.key'),'-out',str(certs/'server.csr')],
                ['x509','-req','-in',str(certs/'server.csr'),'-CA',str(certs/'ca.crt'),'-CAkey',str(certs/'ca.key'),'-CAcreateserial','-days','2','-extfile',str(certs/'extensions.cnf'),'-out',str(certs/'server.crt')],
            ]:
                subprocess.run(['openssl']+command,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            shipping=(root/'packaging/server/Caddyfile').read_text()
            adapted=shipping.replace('{$THREADDESK_DOMAIN} {','{$THREADDESK_DOMAIN} {\n    tls /tmp/td-proxy/server.crt /tmp/td-proxy/server.key',1)
            assert adapted!=shipping,'Shipping Caddy site marker changed; review test TLS injection'
            files={'Caddyfile':adapted.encode(),'server.crt':(certs/'server.crt').read_bytes(),'server.key':(certs/'server.key').read_bytes()}
            archive=io.BytesIO()
            with tarfile.open(fileobj=archive,mode='w') as tar:
                for name,data in files.items():
                    item=tarfile.TarInfo(name);item.size=len(data);item.mode=0o600
                    tar.addfile(item,io.BytesIO(data))
            run('exec','--interactive',proxy,'sh','-c','mkdir -p /tmp/td-proxy; tar -xf - -C /tmp/td-proxy',input=archive.getvalue())
            adapted_json=json.loads(run('exec',proxy,'caddy','adapt','--config','/tmp/td-proxy/Caddyfile','--adapter','caddyfile',capture_output=True,text=True).stdout)
            limits=[]
            def walk(value):
                if isinstance(value,dict):
                    if value.get('handler')=='request_body': limits.append(value.get('max_size'))
                    for item in value.values():walk(item)
                elif isinstance(value,list):
                    for item in value:walk(item)
            walk(adapted_json)
            assert sorted(limits)==[512*1024,4*1024*1024,96*1024*1024],limits
            run('exec',proxy,'caddy','validate','--config','/tmp/td-proxy/Caddyfile','--adapter','caddyfile')
            app_bootstrap=textwrap.dedent('''\
                import os,json
                from pathlib import Path
                from threaddesk.server_sync.auth import provision
                work=Path('/tmp/td-proxy-app')
                token=provision(work/'data','alice')
                (work/'token').write_text(token)
                (work/'token').chmod(0o600)
                os.execvp('threaddesk-server',['threaddesk-server','serve','--data-dir',str(work/'data'),'--host','0.0.0.0','--port','8766','--public-origin','https://server.example.org','--trusted-proxy',SUBNET])
                ''').replace('SUBNET',repr(str(subnet)))
            payload=json.dumps({'ca':(certs/'ca.crt').read_text(),'bootstrap':app_bootstrap})
            loader='import sys,json,os; from pathlib import Path; v=json.load(sys.stdin); p=Path("/tmp/td-proxy-app"); p.mkdir(mode=0o700); (p/"ca.crt").write_text(v["ca"]); t=p/"bootstrap.tmp"; t.write_text(v["bootstrap"]); t.chmod(0o600); os.replace(t,p/"bootstrap.py")'
            run('exec','--interactive',app,'python','-c',loader,input=payload,text=True)
            run('exec',proxy,'touch','/tmp/td-proxy/ready')
            bindings=json.loads(run('inspect',proxy,capture_output=True,text=True).stdout)[0]['NetworkSettings']['Ports']
            published=[binding for rows in bindings.values() if rows for binding in rows]
            assert len(published)==1 and published[0]['HostIp']=='127.0.0.1',bindings
            app_bindings=json.loads(run('inspect',app,capture_output=True,text=True).stdout)[0]['NetworkSettings']['Ports']
            assert not any(app_bindings.values()),app_bindings
            run('exec','--interactive',app,'python','-c','import sys; exec(compile(sys.stdin.read(),"proxy-client.py","exec"))',input=CLIENT,text=True)
            print(json.dumps({'shipping_caddyfile_sha256':hashlib.sha256(shipping.encode()).hexdigest(),
                'test_config_sha256':hashlib.sha256(adapted.encode()).hexdigest(),'route_limits':sorted(limits),
                'published_only':published,'trusted_proxy':str(subnet),'caddy_image':args.caddy_image,
                'caddy_image_id':run('image','inspect',args.caddy_image,'--format','{{.Id}}',capture_output=True,text=True).stdout.strip(),
                'app_image_id':run('image','inspect',args.image,'--format','{{.Id}}',capture_output=True,text=True).stdout.strip(),
                'result':'passed'},sort_keys=True))
    except BaseException:
        for container in containers:
            subprocess.run(docker+['logs','--tail','40',container],check=False)
        raise
    finally:
        for container in reversed(containers):
            run('rm','--force','--volumes',container,stdout=subprocess.DEVNULL)
        if network:
            run('network','rm',network,stdout=subprocess.DEVNULL)


if __name__=='__main__':
    main()
