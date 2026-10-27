"""External CLI commits refresh an open real graph without erasing local work."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from playwright.sync_api import expect, sync_playwright

from test_desk_browser import Desk
from threaddesk.api.service import ThreadService
from threaddesk.services.library_batch import LibraryBatchImporter
from threaddesk.storage.json_store import JsonStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=['de', 'en'])
def live_graph(tmp_path, request):
    home = tmp_path / 'workspace'
    store = JsonStore(home)
    service = ThreadService(store=store)
    thread = service.create('Live project')
    project = service.create_node('project', 'Live project', metadata={'thread_id': thread.id})
    originals = tmp_path / 'originals';originals.mkdir()
    original = originals / 'Existing.txt';original.write_text('Original content')
    importer = LibraryBatchImporter(store)
    imported = importer.run(importer.manifest_for_folder(originals.resolve(), thread_id=thread.id, node_id=project.id), operation_id='live-initial')
    record = imported['files'][0]['record_id']
    desk = Desk(home);url = desk.start()
    try:
        with sync_playwright() as play:
            browser = play.chromium.launch(executable_path=os.environ.get('THREADDESK_CHROMIUM') or None)
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            page.emulate_media(reduced_motion='reduce')
            errors = [];page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(url + '/map?lang=' + request.param, wait_until='networkidle')
            expect(page.locator('.map-node')).to_have_count(2)
            assert page.request.get(url + '/api/graph/change-status').json()['status'] == 'ready'
            yield page, url, home, project.id, thread.id, record, original, tmp_path
            assert not errors, errors
            browser.close()
    finally:
        desk.stop()


def cli(fixture, command, arguments, *, operation=None, revision=None):
    page, url, home, *_rest, temporary = fixture
    workspace = page.request.get(url + '/api/commands/catalog?limit=1').json()['workspace_id']
    body = {'version': 1, 'workspace_id': workspace, 'command': command, 'arguments': arguments}
    if operation is not None:
        body['operation_id'] = operation
    if revision is not None:
        body['expected_revision'] = revision
    path = temporary / 'external-command.json';path.write_text(json.dumps(body));path.chmod(0o600)
    env = {**os.environ, 'THREADDESK_HOME': str(home), 'THREADDESK_STORAGE': 'json', 'PYTHONPATH': str(ROOT / 'src')}
    try:
        done = subprocess.run([sys.executable, '-m', 'threaddesk.ui.cli', 'command', '--request-file', str(path)],
                              cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    finally:
        path.unlink(missing_ok=True)
    result = json.loads(done.stdout)
    assert done.returncode == 0 and result['ok'], result
    return result['result']


def snapshot(page):
    return page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot()")


def test_real_external_cli_import_and_source_change_refresh_files_nodes_and_colors(live_graph):
    page, _url, _home, project, thread, record, original, temporary = live_graph
    root = page.locator('[data-graph-endpoint]')
    expect(page.locator(f'[data-node-id="{project}"]')).to_have_attribute('data-age-band', 'unknown')
    state = snapshot(page)
    state['selection'] = [record, project]
    state['camera']['scale'] = 1.2
    state['camera']['x'] += 30
    page.evaluate("state => document.querySelector('[data-graph-endpoint]').graphController.restore(state)", state)
    page.locator('[data-map-tab="files"]').click()
    expect(page.locator(f'[data-file-record="{record}"]')).to_be_visible()
    before = snapshot(page)
    stage = page.locator('[data-map-stage]').bounding_box()
    incoming = temporary / 'incoming';incoming.mkdir()
    (incoming / 'External.txt').write_text('CLI supplied real original')
    imported = cli(live_graph, 'library_manage', {'action': 'import', 'data': {
        'source': str(incoming), 'thread_id': thread, 'node_id': project}}, operation='external-import')
    new_record = imported['files'][0]['record_id']
    expect(page.locator(f'[data-node-id="{new_record}"]')).to_have_count(1, timeout=20000)
    expect(page.locator(f'[data-file-record="{new_record}"]')).to_be_visible(timeout=10000)
    after = snapshot(page)
    assert after['camera'] == before['camera']
    assert set(after['selection']) == set(before['selection'])
    assert all(after['positions'][identity] == point for identity, point in before['positions'].items())
    assert page.locator('[data-map-stage]').bounding_box()['height'] == stage['height']
    original.write_text('Actual changed source content')
    cli(live_graph, 'library_manage', {'action': 'import', 'data': {
        'source': str(original.parent), 'thread_id': thread, 'node_id': project}}, operation='external-source-change')
    expect(page.locator(f'[data-node-id="{project}"]')).to_have_attribute('data-age-band', '24h', timeout=20000)
    expect(root).to_have_attribute('data-live-status', 'ready')
    assert snapshot(page)['camera'] == before['camera']


def test_popup_and_inspector_drafts_defer_refresh_then_preserve_input(live_graph):
    page, _url, _home, project, _thread, record, *_rest = live_graph
    root = page.locator('[data-graph-endpoint]')
    page.locator(f'[data-node-id="{project}"] .map-node-shape').click()
    page.locator('[data-map-tab="files"]').click()
    page.locator(f'[data-file-record="{record}"]').click()
    expect(page.locator('[data-file-preview]')).to_be_visible()
    page.locator('[data-file-name]').fill('Preserve popup draft.txt')
    created = cli(live_graph, 'graph.node.create', {'kind': 'task', 'title': 'External while preview'}, operation='external-preview', revision=0)
    expect(root).to_have_attribute('data-live-status', 'pending', timeout=20000)
    expect(page.locator(f'[data-node-id="{created["id"]}"]')).to_have_count(0)
    expect(page.locator('[data-file-name]')).to_have_value('Preserve popup draft.txt')
    page.locator('[data-file-close]').click()
    expect(page.locator(f'[data-node-id="{created["id"]}"]')).to_have_count(1, timeout=15000)
    expect(page.locator('[data-file-name]')).to_have_value('Preserve popup draft.txt')
    page.locator('[data-files-controls] > summary').click()
    query = page.locator('[data-file-search] input[name="query"]')
    query.fill('Unsubmitted search draft')
    second = cli(live_graph, 'graph.node.create', {'kind': 'task', 'title': 'External during input'}, operation='external-input', revision=0)
    expect(root).to_have_attribute('data-live-status', 'pending', timeout=20000)
    expect(query).to_have_value('Unsubmitted search draft')
    expect(page.locator(f'[data-node-id="{second["id"]}"]')).to_have_count(0)
    page.locator('[data-map-live-update]').click()
    expect(page.locator(f'[data-node-id="{second["id"]}"]')).to_have_count(1, timeout=10000)
    expect(query).to_have_value('Unsubmitted search draft')


def test_visibility_event_stops_polling_and_network_failure_is_visible(live_graph):
    page, *_rest = live_graph
    root = page.locator('[data-graph-endpoint]')
    calls = []
    page.on('request', lambda request: calls.append(request.url) if request.url.endswith('/api/graph/change-status') else None)
    # Drive the actual page's standard visibility event; the HTTP endpoint and
    # graph remain real. This tests the hidden-document branch explicitly.
    page.evaluate("""() => {
      Object.defineProperty(document, 'hidden', {configurable:true, get:()=>true});
      document.dispatchEvent(new Event('visibilitychange'));
    }""")
    count = len(calls)
    page.wait_for_timeout(8000)
    assert len(calls) == count
    page.route('**/api/graph/change-status', lambda route: route.abort('failed'))
    page.evaluate("""() => {
      Object.defineProperty(document, 'hidden', {configurable:true, get:()=>false});
      document.dispatchEvent(new Event('visibilitychange'));
    }""")
    expect(root).to_have_attribute('data-live-status', 'error')
    expect(page.locator('[data-map-live]')).to_be_visible()
    page.unroute('**/api/graph/change-status')
    page.locator('[data-map-live-update]').click()
    expect(root).to_have_attribute('data-live-status', 'ready')
    # A minute transition also invalidates a graph with identical canonical
    # bytes. Only the transport clock is driven here; the graph GET is real.
    page.evaluate("""() => {
      window.liveClockLoads=0;
      document.querySelector('[data-graph-endpoint]').addEventListener('threaddesk:graph-loaded',()=>window.liveClockLoads++);
    }""")
    def minute_transition(route):
        response = route.fetch();body = response.json()
        body['minute'] += '-next'
        route.fulfill(response=response, json=body)
    page.route('**/api/graph/change-status', minute_transition)
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_function('window.liveClockLoads > 0')


def test_active_drag_defers_external_commit_until_pointer_release(live_graph):
    page, *_rest = live_graph
    root = page.locator('[data-graph-endpoint]')
    stage = page.locator('[data-map-stage]').bounding_box()
    page.mouse.move(stage['x'] + 25, stage['y'] + 25)
    page.mouse.down()
    try:
        page.mouse.move(stage['x'] + 65, stage['y'] + 45, steps=3)
        during = snapshot(page)
        node = cli(live_graph, 'graph.node.create', {'kind': 'task', 'title': 'External during drag'}, operation='external-drag', revision=0)
        expect(root).to_have_attribute('data-live-status', 'pending', timeout=20000)
        expect(page.locator(f'[data-node-id="{node["id"]}"]')).to_have_count(0)
        assert snapshot(page)['camera'] == during['camera']
    finally:
        page.mouse.up()
    expect(page.locator(f'[data-node-id="{node["id"]}"]')).to_have_count(1, timeout=10000)
    assert snapshot(page)['camera'] == during['camera']


def test_real_profile_restore_invalidates_old_capability_and_preserves_draft_until_reload(live_graph):
    page, url, *_rest = live_graph
    root = page.locator('[data-graph-endpoint]')
    page.wait_for_function("Boolean(document.querySelector('[data-graph-endpoint]').dataset.viewClientId)")
    old_client = root.get_attribute('data-view-client-id')
    old_workspace = page.request.get(url + '/api/graph/change-status').json()['workspace_id']
    page.locator('.graph-view-tools > summary').click()
    draft = page.locator('[data-map-view-title]');draft.fill('Preserve profile-switch draft')
    backup = cli(live_graph, 'backup.create', {}, operation='live-profile-backup')
    registrations = []
    page.on('request', lambda request: registrations.append(request.url) if request.url.endswith('/api/graph/view-control/connect') else None)
    # If the workspace probe is temporarily unavailable after the old lease
    # is denied, never register this old document against an unknown profile.
    page.route('**/api/graph/change-status', lambda route: route.fulfill(status=503, json={'status': 'unavailable'}))
    cli(live_graph, 'backup.restore', {'path': backup['path'], 'sha256': backup['sha256'],
        'confirmation': 'restore_as_new_profile'}, operation='live-profile-restore')
    expect(root).to_have_attribute('data-view-control-status', 'waiting', timeout=10000)
    page.wait_for_timeout(1800)
    assert registrations == []
    page.unroute('**/api/graph/change-status')
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    expect(root).to_have_attribute('data-live-status', 'workspace', timeout=20000)
    expect(draft).to_have_value('Preserve profile-switch draft')
    expect(root).not_to_have_attribute('data-view-client-id', old_client)
    expect(root).to_have_attribute('data-view-control-status', 'workspace_changed')
    assert page.request.get(url + '/api/graph/change-status').json()['workspace_id'] != old_workspace
    page.locator('[data-map-live-update]').click()
    expect(root).to_have_attribute('data-live-status', 'ready', timeout=15000)
    page.wait_for_function("Boolean(document.querySelector('[data-graph-endpoint]').dataset.viewClientId)")
    assert root.get_attribute('data-view-client-id') != old_client
