"""Isolated real CLI + browser graph acceptance for an authorized bridge task.

No store writes, backend patches, synthetic ACKs, production data or terminal
history. The launching ChatGPT/KiraBridge principal is established separately
by the actual bridge task receipt. Reports contain IDs, hashes and conclusions.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import subprocess
import time
from urllib.parse import urlsplit

from check_workspace_commands import Client
from check_workspace_operations import call_summaries, digest, http_get, loopback_server


def executable_digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as incoming:
        for chunk in iter(lambda: incoming.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


@contextmanager
def packaged_server(root, client, shutdown):
    """Run the actual Tauri backend protocol; never replace its server code."""
    log_path = root / 'packaged-server.log'
    with log_path.open('wb') as log:
        log_path.chmod(0o600)
        process = subprocess.Popen([client.binary], env=client.env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=log)
        try:
            output, url, deadline = b'', None, time.monotonic() + 30
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while time.monotonic() < deadline and url is None:
                    assert process.poll() is None, 'Packaged server exited before readiness'
                    for _key, _events in selector.select(.1):
                        chunk = os.read(process.stdout.fileno(), 4096)
                        assert chunk, 'Packaged server closed its startup channel'
                        output += chunk
                        assert len(output) < 16384, 'Packaged startup response exceeds budget'
                        for line in output.splitlines():
                            if line.startswith(b'THREADDESK_URL '):
                                url = line.split(b' ', 1)[1].decode('ascii')
                                break
            assert url, 'Packaged server readiness timed out'
            address = urlsplit(url)
            assert (address.scheme == 'http' and address.hostname == '127.0.0.1'
                    and address.port and address.path in {'', '/'} and not address.query
                    and not address.fragment and not address.username and not address.password)
            body, _headers = http_get(url + '/api/commands/catalog?limit=1')
            assert json.loads(body)['workspace_id'] == client.workspace_id
            yield url
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass
            method = 'stdin_eof'
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                method = 'terminate';process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    method = 'kill';process.kill();process.wait(timeout=5)
            process.stdout.close()
            shutdown.update(method=method, exit_code=process.returncode, process_exited=True)


def manage(client, action, identity, revision, operation, data=None, *, error=None):
    args = {'action': action, 'id': identity, 'expected_revision': revision, 'operation_id': operation}
    if data is not None:
        args['data'] = data
    return client.call('graph_view.manage', args, operation=operation, revision=revision, error=error)


def apply(client, identity, revision, operation, client_id=None, *, error=None):
    args = {'id': identity, 'expected_revision': revision, 'operation_id': operation}
    if client_id is not None:
        args['client_id'] = client_id
    return client.call('graph_view.apply', args, operation=operation, revision=revision, error=error)


def snapshot(page):
    return page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot()")


def same_camera(actual, expected):
    return all(math.isclose(actual[key], expected[key], abs_tol=1e-5) for key in ('x', 'y', 'scale'))


def initial_graph(client, root):
    thread = client.call('thread_manage', {'action': 'create', 'data': {'title': 'Graph acceptance'}},
                         operation='graph-thread', revision=0)['thread']
    project = client.call('graph.node.create', {'kind': 'project', 'title': 'Graph acceptance project',
        'metadata': {'thread_id': thread['id']}}, operation='graph-project', revision=0)
    task = client.call('graph.node.create', {'kind': 'task', 'title': 'Graph acceptance task'},
                       operation='graph-task', revision=0)
    allowed = client.call('graph.node.transitions', {'id': task['id']})
    assert task['status'] == 'idea' and allowed == {'id': task['id'], 'transitions': ['ready']}
    before = client.call('graph.change_status')
    transition = {'id': task['id'], 'status': 'ready'}
    changed = client.call('graph.node.transition', transition, operation='graph-transition', revision=task['revision'])
    assert changed['status'] == 'ready'
    current = client.call('graph.node', {'id': task['id']})
    assert current['revision'] == changed['revision'] and current['status'] == 'ready'
    allowed = client.call('graph.node.transitions', {'id': task['id']})
    assert allowed == {'id': task['id'], 'transitions': ['assigned']}
    replay = client.call('graph.node.transition', transition, operation='graph-transition', revision=task['revision'])
    assert replay['revision'] == changed['revision']
    client.call('graph.node.transition', {'id': task['id'], 'status': 'assigned'},
                operation='graph-transition', revision=task['revision'], error='operation_conflict')
    client.call('graph.node.transition', {'id': task['id'], 'status': 'assigned'},
                operation='graph-transition-stale', revision=task['revision'], error='revision_conflict')
    after = client.call('graph.change_status')
    assert before['status'] == after['status'] == 'ready' and before['fingerprint'] != after['fingerprint']
    events = client.call('graph.events', {'limit': 100})['items']
    assert len([row for row in events if row['name'] == 'node.transitioned' and row['entity_id'] == task['id']]) == 1
    relation = client.call('graph.relation.create', {'source_id': project['id'], 'target_id': task['id'],
        'kind': 'contains', 'expected_target_revision': changed['revision']},
        operation='graph-relation', revision=project['revision'])
    assert relation['id'] in {row['id'] for row in client.call('graph.relations', {'id': project['id']})['items']}
    neighbors = client.call('graph.query', {'center': project['id'], 'hops': 1, 'mode': 'work', 'limit': 10})
    assert {project['id'], task['id']} <= {row['id'] for row in neighbors['nodes']}
    for mode in ('status', 'modified', 'accessed', 'work'):
        graph = client.call('graph.query', {'mode': mode, 'kind': 'task', 'query': 'acceptance', 'limit': 10})
        assert graph['schema'] == 'threaddesk.graph.v2' and [row['id'] for row in graph['nodes']] == [task['id']]
        assert graph['nodes'][0]['activity']['band'] == 'unknown'
    source = root / 'originals';source.mkdir(mode=0o700)
    original = source / 'Graph-Original.txt'
    original.write_text('GraphAcceptanceOriginalNeedle actual original bytes', encoding='utf-8')
    imported = client.call('library_manage', {'action': 'import', 'data': {
        'source': str(source), 'thread_id': thread['id'], 'node_id': project['id']}}, operation='graph-original-import')
    assert imported['complete'] and len(imported['files']) == 1
    record = imported['files'][0]['record_id']
    assert client.call('activity.files', {'record_ids': [record]})['files'][record] == {}
    return thread['id'], project['id'], task['id'], record, original


def waiting_view(client, project):
    state = {'camera': {'x': 500, 'y': 350, 'scale': .8}, 'positions': {},
             'filters': {'mode': 'work'}, 'selection': [project]}
    data = {'title': 'Graph acceptance view', 'state': state}
    saved = manage(client, 'save', 'graph-acceptance-view', 0, 'graph-view-save', data)
    view = client.call('graph_view.get', {'id': saved['view']['id']})
    assert view['revision'] == 1 and view['state']['selection'] == [project]
    assert any(row['id'] == view['id'] for row in client.call('graph_view.list', {'limit': 10})['views'])
    assert client.call('graph_view.operation', {'operation_id': 'graph-view-save'})['found']
    repeated = manage(client, 'save', view['id'], 0, 'graph-view-save', data)
    assert repeated['view']['revision'] == 1
    manage(client, 'save', view['id'], 0, 'graph-view-save', {**data, 'title': 'Conflicting title'}, error='operation_conflict')
    manage(client, 'save', view['id'], 0, 'graph-view-stale', data, error='revision_conflict')
    assert client.call('graph_view.clients')['clients'] == []
    queued = apply(client, view['id'], 1, 'graph-view-waiting')
    assert queued['status'] == 'waiting' and queued['acknowledgement'] is None
    status = client.call('graph_view.apply_status', {'operation_id': 'graph-view-waiting'})
    assert status['found'] and status['result']['status'] == 'waiting'
    return view['id']


def connected_view(client, page, project, task, view):
    from playwright.sync_api import expect
    root = page.locator('[data-graph-endpoint]')
    expect(root).to_have_attribute('data-view-control-operation', 'graph-view-waiting', timeout=15000)
    expect(root).to_have_attribute('data-view-control-status', 'applied')
    first = client.call('graph_view.apply_status', {'operation_id': 'graph-view-waiting'})['result']
    assert first['acknowledgement']['observation']['matched']
    page.locator('[data-map-reset]').click()
    page.locator(f'[data-node-id="{project}"] .map-node-shape').click()
    page.locator(f'[data-node-id="{task}"] .map-node-shape').click(modifiers=['Shift'])
    page.locator('[data-map-tab="selection"]').click()
    page.locator('[data-map-fix-selected]').click()
    page.locator('[data-map-zoom-in]').click()
    state = snapshot(page)
    assert set(state['selection']) == {project, task}
    data = {'title': 'Graph acceptance view', 'state': state}
    manage(client, 'save', view, 1, 'graph-view-update', data)
    confirmed = client.call('graph_view.get', {'id': view})
    assert confirmed['revision'] == 2
    assert client.call('graph_view.operation', {'operation_id': 'graph-view-update'})['result']['view']['revision'] == 2
    page.locator('[data-map-zoom-out]').click();page.locator('[data-map-zoom-out]').click()
    assert not same_camera(snapshot(page)['camera'], state['camera'])
    target = root.get_attribute('data-view-client-id')
    assert target in {row['client_id'] for row in client.call('graph_view.clients')['clients'] if row['active']}
    intent = apply(client, view, 2, 'graph-view-apply', target)
    assert intent['status'] == 'queued' and intent['acknowledgement'] is None
    expect(root).to_have_attribute('data-view-control-operation', 'graph-view-apply', timeout=15000)
    expect(root).to_have_attribute('data-view-control-status', 'applied')
    observed = client.call('graph_view.apply_status', {'operation_id': 'graph-view-apply'})['result']
    assert observed['status'] == 'applied' and observed['acknowledgement']['observation']['matched']
    actual = snapshot(page)
    assert same_camera(actual['camera'], state['camera']) and set(actual['selection']) == set(state['selection'])
    assert all(actual['positions'][identity] == point for identity, point in state['positions'].items())
    page.locator('[data-map-zoom-out]').click()
    later = snapshot(page)['camera']
    apply(client, view, 2, 'graph-view-apply', target)
    page.wait_for_timeout(1800)
    assert same_camera(snapshot(page)['camera'], later)
    replay_status = client.call('graph_view.apply_status', {'operation_id': 'graph-view-apply'})['result']
    assert replay_status['acknowledgement'] == observed['acknowledgement']
    apply(client, 'conflicting-view', 2, 'graph-view-apply', target, error='operation_conflict')
    apply(client, view, 1, 'graph-view-apply-stale', target, error='revision_conflict')
    return {'view_id': view, 'client_id': target, 'observed_state_sha256': digest(actual),
            'acknowledgement_sha256': digest(observed['acknowledgement']), 'replay_kept_later_camera': True,
            'waiting_then_observed_applied': True, 'revision_and_operation_conflicts': True}


def attachments_and_live(client, page, root_path, thread, project, record, original):
    from playwright.sync_api import expect
    root = page.locator('[data-graph-endpoint]')
    page.locator('[data-map-reset]').click()
    page.locator(f'[data-node-id="{project}"] .map-node-shape').click()
    page.locator('[data-map-tab="files"]').click()
    expect(page.locator(f'[data-file-record="{record}"]')).to_be_visible()
    page.locator(f'[data-file-record="{record}"]').click()
    expect(page.locator('[data-file-preview]')).to_be_visible()
    expect(page.locator('[data-file-body]')).to_contain_text('GraphAcceptanceOriginalNeedle')
    preview = client.call('library_query', {'action': 'preview', 'id': record})
    assert 'GraphAcceptanceOriginalNeedle' in preview['text']
    assert preview['record']['sha256'] == digest(original.read_bytes())
    assert client.call('activity.files', {'record_ids': [record]})['files'][record] == {}
    page.locator('[data-file-name]').fill('Preserved acceptance draft.txt')
    before = snapshot(page)
    incoming = root_path / 'incoming';incoming.mkdir(mode=0o700)
    addition = incoming / 'External-Graph.txt';addition.write_text('GraphExternalNeedle new actual attachment')
    old_status = client.call('graph.change_status')
    imported = client.call('library_manage', {'action': 'import', 'data': {
        'source': str(incoming), 'thread_id': thread, 'node_id': project}}, operation='graph-external-import')
    assert imported['complete']
    new_record = imported['files'][0]['record_id']
    new_status = client.call('graph.change_status')
    assert old_status['fingerprint'] != new_status['fingerprint']
    expect(root).to_have_attribute('data-live-status', 'pending', timeout=20000)
    expect(page.locator(f'[data-node-id="{new_record}"]')).to_have_count(0)
    expect(page.locator('[data-file-name]')).to_have_value('Preserved acceptance draft.txt')
    page.locator('[data-file-close]').click()
    expect(page.locator(f'[data-node-id="{new_record}"]')).to_have_count(1, timeout=15000)
    expect(page.locator(f'[data-file-record="{new_record}"]')).to_be_visible(timeout=10000)
    actual = snapshot(page)
    assert same_camera(actual['camera'], before['camera']) and actual['selection'] == before['selection']
    assert all(actual['positions'][identity] == point for identity, point in before['positions'].items())
    assert len(client.call('library_query', {'action': 'list', 'node_id': project})['records']) >= 2
    original.write_text('GraphAcceptanceOriginalNeedle actual changed source bytes', encoding='utf-8')
    updated = client.call('library_manage', {'action': 'import', 'data': {
        'source': str(original.parent), 'thread_id': thread, 'node_id': project}}, operation='graph-source-change')
    current = updated['files'][0]['record_id']
    evidence = client.call('activity.files', {'record_ids': [current]})['files'][current]
    assert evidence['modified']['sha256'] == digest(original.read_bytes())
    expect(page.locator(f'[data-node-id="{project}"]')).to_have_attribute('data-age-band', '24h', timeout=20000)
    client.call('activity.reconcile', {'limit': 5, 'offset': 0}, operation='graph-activity-reconcile')
    assert client.call('activity.files', {'record_ids': [current]})['files'][current] == evidence
    graph = client.call('graph.query', {'mode': 'modified', 'band': '24h', 'limit': 10})
    assert {current, project} <= {row['id'] for row in graph['nodes']}
    return {'initial_record_id': record, 'external_record_id': new_record, 'changed_record_id': current,
            'preview_sha256': digest(preview), 'current_original_sha256': digest(original.read_bytes()),
            'external_original_sha256': digest(addition.read_bytes()), 'popup_and_draft_preserved': True,
            'attachments_and_activity_refreshed_without_reload': True, 'camera_selection_positions_preserved': True,
            'preview_created_no_file_activity': True}


def delete_view(client, view):
    deleted = manage(client, 'delete', view, 2, 'graph-view-delete')
    assert deleted['view']['deleted'] and deleted['view']['revision'] == 3
    repeated = manage(client, 'delete', view, 2, 'graph-view-delete')
    assert repeated['view']['revision'] == 3
    assert not any(row['id'] == view for row in client.call('graph_view.list', {'limit': 10})['views'])
    client.call('graph_view.get', {'id': view}, error='not_found')
    assert client.call('graph_view.operation', {'operation_id': 'graph-view-delete'})['result']['view']['deleted']
    return {'view_id': view, 'revision': 3, 'deleted_readback': True, 'identical_delete_replay': True}


def run(root, binary=None, *, chromium=None, headed=False):
    clients, proof, shutdown = [], {}, {}
    phase = 'initialization'
    report = {'fixture_only': True, 'workspace_backend': 'json', 'fresh_process_per_command': True,
              'principal_identity': 'must come from actual ChatGPT/KiraBridge task receipt',
              'provider_boundary': 'no model invocation requested or claimed',
              'browser_boundary': 'actual Playwright Chromium; native WKWebView not claimed',
              'server_boundary': 'actual packaged startup' if binary else 'original loopback app; lifespan off, background/startup probes not claimed',
              'command_binary': str(binary) if binary else None,
              'command_binary_sha256': executable_digest(binary) if binary else None,
              'script_sha256': digest(Path(__file__).read_bytes())}
    try:
        client = Client(root, binary);clients.append(client)
        report['runtime_build'] = client.call('library_query', {'action': 'status'})['build']
        phase = 'graph_commands';print('Checking ' + phase, flush=True)
        thread, project, task, record, original = initial_graph(client, root)
        proof['graph_commands'] = {'thread_id': thread, 'project_id': project, 'task_id': task,
            'transition_replay_conflicts_and_readback': True, 'allowed_transitions_before_after': True,
            'neighborhood_and_four_modes': True}
        phase = 'server_start';print('Checking ' + phase, flush=True)
        from playwright.sync_api import sync_playwright
        server = packaged_server(root, client, shutdown) if binary else loopback_server(root, client.env)
        with server as url, sync_playwright() as play:
            # Startup invalidates old runtime intents by design. Queue the
            # deliberate waiting request only after this actual server is ready.
            phase = 'saved_view_commands';print('Checking ' + phase, flush=True)
            view = waiting_view(client, project)
            phase = 'real_browser';print('Checking ' + phase, flush=True)
            browser = play.chromium.launch(executable_path=chromium or None, headless=not headed)
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 900})
                page.emulate_media(reduced_motion='reduce')
                errors, requests = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: requests.append(request.url))
                page.goto(url + '/map?lang=en', wait_until='networkidle')
                body, _headers = http_get(url + '/api/library/query?action=status')
                assert json.loads(body)['result']['build'] == report['runtime_build']
                phase = 'connected_apply';print('Checking ' + phase, flush=True)
                proof['view_control'] = connected_view(client, page, project, task, view)
                phase = 'popup_external_import';print('Checking ' + phase, flush=True)
                proof['files_live'] = attachments_and_live(client, page, root, thread, project, record, original)
                assert not errors, 'Browser raised an error'
                address = urlsplit(url)
                assert all(urlsplit(value).netloc == address.netloc for value in requests if value.startswith(('http:', 'https:')))
                proof['browser'] = {'page_errors': 0, 'page_request_count': len(requests), 'page_network_local_only': True,
                                    'renderer': page.locator('[data-graph-endpoint]').get_attribute('data-renderer'),
                                    'rendered_node_count': page.locator('.map-node').count(),
                                    'graph_state_sha256': digest(snapshot(page))}
            finally:
                browser.close()
        try:
            http_get(url + '/api/commands/catalog?limit=1')
        except OSError:
            proof['server_process_cleanup'] = {'endpoint_closed': True, **shutdown}
        else:
            raise AssertionError('Owned acceptance server remained reachable')
        phase = 'view_delete';print('Checking ' + phase, flush=True)
        proof['view_delete'] = delete_view(client, view)
        report['ok'] = True
    except Exception as exc:
        report.update(ok=False, failure_phase=phase, failure_type=type(exc).__name__, failure_sha256=digest(str(exc).encode()))
    finally:
        for client in clients:
            (client.root / 'request.json').unlink(missing_ok=True)
        report['proof'] = proof
        report['calls'] = call_summaries(clients)
        path = root / 'graph-control-result.json'
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2));path.chmod(0o600)
    print(json.dumps({'ok': report['ok'], 'calls': len(report['calls']), 'fixture_only': True,
                      'failure_phase': report.get('failure_phase'), 'failure_type': report.get('failure_type'),
                      'report': str(path)}), flush=True)
    return 0 if report['ok'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, help='New private fixture directory; must not exist')
    parser.add_argument('--command-binary', help='Actual Tauri backend executable, for both commands and server')
    parser.add_argument('--chromium', default=os.environ.get('THREADDESK_CHROMIUM'), help='Actual Chromium executable')
    parser.add_argument('--headed', action='store_true')
    args = parser.parse_args()
    root = Path(args.directory).resolve();root.mkdir(mode=0o700)
    binary = str(Path(args.command_binary).resolve(strict=True)) if args.command_binary else None
    return run(root, binary, chromium=args.chromium, headed=args.headed)


if __name__ == '__main__':
    raise SystemExit(main())
