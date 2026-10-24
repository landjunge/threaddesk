"""Targeted browser acceptance with a disposable workspace; no installed app.

Run from repository root with PYTHONPATH=src and the browser extra installed.
An existing Chromium executable can be selected without downloading a browser.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
from copy import deepcopy
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

from threaddesk.server_sync.auth import provision


def desktop_acceptance(browser, server_origin, token, directory, output_dir):
    """Exercise the actual protected desktop form and its automatic worker."""
    from threaddesk.api.service import ThreadService
    from threaddesk.storage.json_store import JsonStore
    workspace=Path(directory)/'desktop-workspace'
    files=Path(directory)/'desktop-project';files.mkdir()
    (files/'notes.md').write_text('Original project file',encoding='utf-8')
    attachment=Path(directory)/'attached-context.txt';attachment.write_text('Explicit attached file',encoding='utf-8')
    core=ThreadService(JsonStore(workspace));thread=core.create('Desktop binding project','Existing desktop description')
    core.set_note('Existing desktop note',thread.id)
    core.add_file(str(attachment),thread.id)
    core.create_node('task','Existing desktop task',metadata={'thread_id':thread.id})
    core.append_whiteboard(thread.id,actor='Owner',actor_type='human',entry_type='note',content='Desktop whiteboard entry')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    origin=f'http://127.0.0.1:{port}'
    env={**os.environ,'THREADDESK_HOME':str(workspace),'THREADDESK_STORAGE':'json','THREADDESK_SYNC_ALLOW_HTTP':'1'}
    command='import sys,uvicorn;from threaddesk.ui.server import create_app;uvicorn.run(create_app(),host="127.0.0.1",port=int(sys.argv[1]),log_level="error",proxy_headers=False)'
    process=subprocess.Popen([sys.executable,'-c',command,str(port)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        for _ in range(100):
            if process.poll() is not None:raise RuntimeError(process.communicate()[1])
            try:
                if httpx.get(origin,timeout=1).status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.1)
        else:raise RuntimeError('Desktop startup timeout')
        page=browser.new_page(viewport={'width':1280,'height':1000})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(origin+'/?thread='+thread.id)
        page.get_by_role('link',name='Server und Abgleich',exact=True).click()
        configure=page.locator('form:has(input[name="action"][value="configure"])')
        configure.locator('[name="url"]').fill(server_origin)
        configure.locator('[name="token"]').fill(token)
        configure.locator('[name="root"]').fill(str(files))
        configure.locator('[name="offline"]').check()
        configure.get_by_role('button',name='Verbinden und abgleichen',exact=True).click()
        expect(page.get_by_text('Gemeldeter Projektbestand geprüft und offline bereit',exact=True)).to_be_visible(timeout=20000)
        binding=page.request.get(origin+'/api/threads/'+thread.id+'/server-sync').json()
        assert binding['configured'] and 'token' not in binding
        pid=binding['project_id'];prefix='/api/projects/'+pid
        with httpx.Client(base_url=server_origin,headers={'Authorization':'Bearer '+token}) as remote:
            document=remote.get(prefix+'/metadata').json()['document']
            assert document['thread']['notes']=='Existing desktop note'
            assert any(n['title']=='Existing desktop task' for n in document['nodes'].values())
            assert any(e['content']=='Desktop whiteboard entry' for e in document['whiteboard'].values())
            inventory=remote.get(prefix+'/files').json()['files']
            assert any(f['path'].startswith('_external/') for f in inventory)
            value=remote.get(prefix+'/thread').json()
            response=remote.put(prefix+'/thread',json={'revision':value['revision'],'description':value['description'],'notes':'Remote browser note'})
            response.raise_for_status()
            for _ in range(100):
                if core.get(thread.id).context.notes=='Remote browser note':break
                time.sleep(.1)
            else:raise AssertionError('Automatic server-to-desktop metadata sync did not finish')
            core.set_note('Desktop follow-up note',thread.id)
            for _ in range(100):
                if remote.get(prefix+'/thread').json()['context']['notes']=='Desktop follow-up note':break
                time.sleep(.1)
            else:raise AssertionError('Automatic desktop-to-server metadata sync did not finish')
            page.reload()
            configure=page.locator('form:has(input[name="action"][value="configure"])')
            configure.locator('[name="automatic"]').uncheck()
            configure.get_by_role('button',name='Verbinden und abgleichen',exact=True).click()
            expect(page.get_by_text('Gemeldeter Projektbestand geprüft und offline bereit',exact=True)).to_be_visible()
            page.screenshot(path=str(output_dir/'desktop.png'),full_page=True)
            # A real concurrent metadata conflict, then selection through browser UI.
            baseline=remote.get(prefix+'/metadata').json()['document']
            incoming=deepcopy(baseline);incoming['thread']['notes']='Incoming conflict note'
            value=remote.get(prefix+'/thread').json()
            remote.put(prefix+'/thread',json={'revision':value['revision'],'description':value['description'],'notes':'Saved conflict note'}).raise_for_status()
            result=remote.post(prefix+'/metadata/sync',json={'operation_id':'browser-conflict','base':baseline,'document':incoming})
            result.raise_for_status();assert result.json()['conflicts']
        remote_page=browser.new_page(viewport={'width':1280,'height':1000})
        remote_page.goto(server_origin)
        if remote_page.locator('#login').is_visible():
            remote_page.locator('#token').fill(token);remote_page.locator('#login-form button').click()
        expect(remote_page.locator('#desk')).to_be_visible()
        remote_page.get_by_role('button',name='Desktop binding project',exact=True).click()
        remote_page.get_by_role('button',name='Eingehende Fassung verwenden',exact=True).click()
        expect(remote_page.locator('#notes')).to_have_value('Incoming conflict note')
        assert str(attachment) in core.get(thread.id).context.files
        assert attachment.read_text()=='Explicit attached file' and (files/'notes.md').read_text()=='Original project file'
        assert not errors,errors
        page.close();remote_page.close()
        return ['protected desktop project binding form','automatic bidirectional notes/tasks/whiteboard',
                'explicit attachment mapping and original preservation','metadata conflict choice in server browser']
    finally:
        process.terminate()
        try:process.communicate(timeout=15)
        except subprocess.TimeoutExpired:process.kill();process.communicate()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser-binary')
    parser.add_argument('--with-desktop',action='store_true')
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='td-server-browser-') as directory:
        # macOS commonly exposes its temp directory through /var -> /private/var.
        # Resolve only this newly created harness directory, not a user source.
        directory=str(Path(directory).resolve())
        token = provision(Path(directory)/'data', 'browser')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        origin = f'http://127.0.0.1:{port}'
        process = subprocess.Popen([
            sys.executable, '-m', 'threaddesk.server_sync.cli', 'serve',
            '--data-dir', str(Path(directory)/'data'), '--host', '127.0.0.1',
            '--port', str(port), '--public-origin', origin, '--allow-http-loopback',
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            for attempt in range(100):
                if process.poll() is not None:
                    raise RuntimeError(process.communicate()[1])
                try:
                    if httpx.get(origin, timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError('Server startup timeout')
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=args.browser_binary)
                page = browser.new_page(viewport={'width':1280, 'height':1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(origin)
                page.locator('#token').fill(token)
                page.locator('#login-form button').click()
                page.locator('#desk').wait_for(state='visible')
                page.locator('#title').fill('Server- & Offline-Projekt')
                page.locator('#create-form button').click()
                page.locator('#project').wait_for(state='visible')
                page.locator('#offline').check()
                expect(page.locator('#sync')).to_contain_text('Abgleich ausstehend')
                page.locator('#file-path').fill('docs/plan.md')
                page.locator('#file-upload').set_input_files({
                    'name':'plan.md', 'mimeType':'text/markdown',
                    'buffer':'# Plan\nBereit für Offline.'.encode(),
                })
                page.locator('#upload-form button').click()
                expect(page.locator('#sync')).to_contain_text('Offline bereit')
                page.get_by_role('button', name='Text bearbeiten', exact=True).click()
                page.locator('#edit-content').fill('# Neue Fassung\nBrowseränderung bleibt versioniert.')
                page.locator('#editor button').first.click()
                expect(page.locator('#editor')).to_be_hidden()
                page.get_by_role('button', name='Frühere Versionen', exact=True).click()
                page.get_by_role('button', name='Fassung laden', exact=True).nth(1).wait_for()
                page.locator('#description').fill('Gemeinsamer ThreadDesk-Kern')
                page.locator('#notes').fill('Diese Notiz bleibt erhalten.')
                page.locator('#metadata-form button').click()
                expect(page.locator('#message')).to_have_text('Gespeichert.')
                page.locator('#entry-content').fill('Nach Wiederverbindung abgleichen.')
                page.locator('#entry-type').select_option('task')
                page.locator('#entry-form button').click()
                page.get_by_text('Nach Wiederverbindung abgleichen.', exact=True).wait_for()
                pid = page.locator('#project-id').inner_text()
                cancelled = b'Browser retry preserves the original cancellation receipt.'
                digest = hashlib.sha256(cancelled).hexdigest()
                transfer = 'browser-cancelled-transfer'
                uri = '/api/projects/'+pid+'/uploads/'+transfer
                with httpx.Client(base_url=origin, headers={'Authorization':'Bearer '+token}) as client:
                    response = client.post(uri,json={'path':'cancelled.md','size':len(cancelled),'sha256':digest,'base_revision':None})
                    response.raise_for_status()
                    client.patch(uri,json={'offset':0,'data_base64':base64.b64encode(cancelled[:7]).decode()}).raise_for_status()
                    client.post(uri+'/abort').raise_for_status()
                key = f'td-transfer:{pid}:cancelled.md:{digest}:'
                page.evaluate('([key,value]) => sessionStorage.setItem(key,value)',[key,transfer])
                page.locator('#file-path').fill('cancelled.md')
                page.locator('#file-upload').set_input_files({'name':'cancelled.md','mimeType':'text/markdown','buffer':cancelled})
                page.locator('#upload-form button').click()
                expect(page.locator('#message')).to_have_text('Datei geprüft und versioniert gespeichert.')
                with httpx.Client(base_url=origin,headers={'Authorization':'Bearer '+token}) as client:
                    assert client.get(uri).json()['state'] == 'aborted'
                    retained = client.get('/api/projects/'+pid+'/history',params={'path':'cancelled.md'}).json()['versions']
                    assert len(retained) == 1 and retained[0]['sha256'] == digest
                assert page.evaluate('key => sessionStorage.getItem(key)',key) is None
                page.screenshot(path=str(args.output_dir/'browser.png'), full_page=True)
                with httpx.Client(base_url=origin, headers={'Authorization':'Bearer '+token}) as client:
                    versions = client.get('/api/projects/'+pid+'/history', params={'path':'docs/plan.md'}).json()['versions']
                    assert len(versions) == 2
                    assert client.get('/api/projects/'+pid+'/thread').json()['context']['notes'] == 'Diese Notiz bleibt erhalten.'
                assert not errors, errors
                page.reload()
                page.locator('#desk').wait_for(state='visible')
                page.get_by_role('button', name='Server- & Offline-Projekt', exact=True).click()
                page.locator('#project').wait_for(state='visible')
                expect(page.locator('#notes')).to_have_value('Diese Notiz bleibt erhalten.')
                page.locator('#logout').click()
                page.locator('#login').wait_for(state='visible')
                desktop_checks=desktop_acceptance(browser,origin,token,directory,args.output_dir) if args.with_desktop else []
                browser.close()
            report = {
                'browser':'Chromium', 'platform':sys.platform,
                'checks':['real CLI loopback HTTP (explicit development mode)',
                          'login/session reload/logout', 'project + Auch offline',
                          'verified upload + ready', 'edit + retained history',
                          'cancelled upload retry replaces confirmed aborted ID and retains its receipt',
                          'shared-core notes + append-only task', 'no JavaScript errors']+desktop_checks,
                'versions_retained':len(versions),
                'production_tls_linux':'not tested',
                'data':'synthetic temporary workspace only',
            }
            (args.output_dir/'browser.json').write_text(json.dumps(report, indent=2)+'\n')
            print(json.dumps(report))
        finally:
            process.terminate()
            try:
                process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()


if __name__ == '__main__':
    main()
