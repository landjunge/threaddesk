"""Use download and restore through actual browser controls for both stores."""
import os
import socket
import threading
import time

import pytest
from playwright.sync_api import sync_playwright
import uvicorn

from threaddesk.ui.server import create_app, _svc


@pytest.mark.parametrize('backend', ['json', 'sqlite'])
def test_user_downloads_opens_and_switches_back(tmp_path, monkeypatch, backend):
    monkeypatch.setenv('THREADDESK_HOME', str(tmp_path))
    monkeypatch.setenv('THREADDESK_STORAGE', backend)
    svc = _svc()
    thread = svc.create('Browser-Sicherung')
    svc.set_note('Mein gespeicherter Stand', thread.id)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(128)
    url = f'http://127.0.0.1:{listener.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(create_app(), log_level='error'))
    worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(.05)
        assert server.started
        with sync_playwright() as play:
            browser = play.chromium.launch(executable_path=os.environ.get('THREADDESK_CHROMIUM') or None)
            page = browser.new_page(accept_downloads=True, viewport={'width': 1360, 'height': 900})
            page.goto(url + '/?lang=de')
            page.get_by_role('link', name='Daten', exact=True).click()
            with page.expect_download() as event:
                page.get_by_role('button', name='Sicherung herunterladen', exact=True).click()
            backup = tmp_path.parent / f'backup-{backend}.zip'
            event.value.save_as(backup)
            assert backup.is_file()
            svc.set_note('Späterer Originalstand', thread.id)
            page.locator('#backup-file').set_input_files(backup)
            page.locator('[name=confirm]').check()
            page.get_by_role('button', name='Sicherung öffnen', exact=True).click()
            page.wait_for_url(url + '/?restored=1')
            assert 'Mein gespeicherter Stand' in page.locator('body').inner_text()
            page.get_by_role('link', name='Daten', exact=True).click()
            if backend == 'json':
                page.screenshot(path='/tmp/threaddesk-data-qa.png', full_page=True)
            page.get_by_role('button', name='Zum bisherigen Arbeitsbereich', exact=True).click()
            page.wait_for_url(url + '/')
            assert 'Späterer Originalstand' in page.locator('body').inner_text()
            page.goto(url + '/data?lang=en')
            assert page.get_by_role('button', name='Download backup', exact=True).is_visible()
            page.get_by_role('button', name='Open workspace', exact=True).click()
            page.wait_for_url(url + '/')
            assert 'Mein gespeicherter Stand' in page.locator('body').inner_text()
            browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        listener.close()
