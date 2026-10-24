"""Targeted browser acceptance with a disposable workspace; no installed app.

Run from repository root with PYTHONPATH=src and the browser extra installed.
An existing Chromium executable can be selected without downloading a browser.
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

from threaddesk.server_sync.auth import provision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser-binary')
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='td-server-browser-') as directory:
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
                browser.close()
            report = {
                'browser':'Chromium', 'platform':sys.platform,
                'checks':['real CLI loopback HTTP (explicit development mode)',
                          'login/session reload/logout', 'project + Auch offline',
                          'verified upload + ready', 'edit + retained history',
                          'shared-core notes + append-only task', 'no JavaScript errors'],
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
