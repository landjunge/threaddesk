"""Remote configure cannot acquire private local owner file authority."""
from copy import deepcopy

import pytest
from http_ui_client import UIClient

from threaddesk.api.service import ThreadService
from threaddesk.server_sync.desktop import BindingBook
from threaddesk.services.commands import CommandApplication
from threaddesk.services.mcp import McpBridge
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.ui.server import create_app


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=['json', 'sqlite'])
def configured(tmp_path, request, monkeypatch):
    workspace = tmp_path / 'workspace'
    monkeypatch.setenv('THREADDESK_HOME', str(workspace))
    monkeypatch.setenv('THREADDESK_STORAGE', 'sqlite' if request.param is SQLiteStore else 'json')
    core = ThreadService(request.param(workspace))
    thread = core.create('Isolated configured source')
    project = tmp_path / 'project'; project.mkdir()
    approved = tmp_path / 'approved'; approved.mkdir()
    additional = tmp_path / 'unapproved'; additional.mkdir()
    original = tmp_path / 'approved-original.txt'; original.write_text('Synthetic approved original')
    private = tmp_path / 'private-original.txt'; private.write_text('Synthetic private original')
    book = BindingBook(core)
    book.save(thread.id, url='https://configured.example', project_id='existing-project', root=str(project),
              token='synthetic-configured-token-1234567890', approved_roots=[str(approved)],
              owner_references=[str(original)], automatic=False, offline_enabled=True)
    client = UIClient(create_app())
    yield core, thread.id, book, client, additional, private
    client.close()
    if isinstance(core.store, SQLiteStore): core.store.connection.close()


def command(core, identity, fields=None, operation='configure-test'):
    config = BindingBook(core).load(identity)
    return {'version': 1, 'workspace_id': CommandApplication(core).workspace_id,
            'command': 'server_sync.configure', 'operation_id': operation,
            'expected_revision': core.get(identity).revision,
            'arguments': {'thread_id': identity, 'url': config['url'], 'project_id': config['project_id'],
                          'root': config['root'], 'token': '', **(fields or {})}}


def remote(core, client, transport, request):
    if transport == 'http': return client.post('/api/commands', json=request).json()
    return McpBridge(core).call('command_invoke', request)


@pytest.mark.parametrize('transport', ['http', 'mcp'])
@pytest.mark.parametrize('grant', ['owner_references', 'approved_roots'])
def test_remote_cannot_extend_an_existing_private_owner_grant(configured, transport, grant):
    core, identity, book, client, additional, private = configured
    path = book.root / (identity + '.json')
    before = path.read_bytes(), path.stat().st_mtime_ns
    config = book.load(identity)
    added = str(private if grant == 'owner_references' else additional)
    request = command(core, identity, {grant: config[grant] + [added]})
    result = remote(core, client, transport, request)
    assert result['ok'] is False
    assert result['code'] == 'local_owner_cli_required'
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert book.load(identity) == config


@pytest.mark.parametrize('transport', ['http', 'mcp'])
@pytest.mark.parametrize('authority', ['root', 'url', 'project_id', 'token', 'owner_references', 'approved_roots'])
def test_remote_cannot_replace_or_revoke_binding_authority(configured, transport, authority):
    core, identity, book, client, additional, _private = configured
    values = {'root': str(additional), 'url': 'https://other.example', 'project_id': 'other-project',
              'token': 'another-synthetic-token-1234567890', 'owner_references': [], 'approved_roots': []}
    path = book.root / (identity + '.json')
    before = path.read_bytes(), path.stat().st_mtime_ns
    request = command(core, identity, {authority: values[authority]})
    result = remote(core, client, transport, request)
    assert result['ok'] is False and result['code'] == 'local_owner_cli_required'
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert CommandApplication(core).operation(request['operation_id'])['found'] is False


@pytest.mark.parametrize('transport', ['http', 'mcp'])
@pytest.mark.parametrize('explicit', [False, True], ids=['omitted-grants', 'same-explicit-grants'])
def test_remote_controls_preserve_authority_and_replay_without_reexecution(configured, transport, explicit):
    core, identity, book, client, _additional, _private = configured
    config = book.load(identity)
    fields = {'automatic': True, 'offline_enabled': False}
    if explicit:
        fields.update({key: config[key] for key in ('owner_references', 'approved_roots')})
        fields['token'] = config['token']
    request = command(core, identity, fields)
    first = remote(core, client, transport, request)
    assert first['ok']
    after = book.load(identity)
    for key in ('root', 'url', 'project_id', 'token', 'owner_references', 'approved_roots', 'device_id'):
        assert after[key] == config[key]
    assert after['automatic'] is True and after['offline_enabled'] is False
    result = first['result']
    if transport == 'mcp': result = result['result']
    assert 'token' not in result
    path = book.root / (identity + '.json')
    before_replay = path.read_bytes(), path.stat().st_mtime_ns
    replay = remote(core, client, transport, deepcopy(request))
    assert replay['ok']
    assert replay['duplicate'] if transport == 'http' else replay['result']['duplicate']
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before_replay


@pytest.mark.parametrize('transport', ['http', 'mcp'])
def test_remote_cannot_provision_authority_from_replicated_file_references(configured, transport):
    core, identity, book, client, _additional, private = configured
    new = core.create('Unconfigured target')
    core.add_file(str(private), new.id)
    request = command(core, identity)
    request['arguments']['thread_id'] = new.id
    request['expected_revision'] = core.get(new.id).revision
    before = {p.name: p.read_bytes() for p in book.root.iterdir() if p.is_file()}
    result = remote(core, client, transport, request)
    assert result['ok'] is False and result['code'] == 'local_owner_cli_required'
    assert book.load(new.id) is None
    assert {p.name: p.read_bytes() for p in book.root.iterdir() if p.is_file()} == before
    assert CommandApplication(core).operation(request['operation_id'])['found'] is False


@pytest.mark.parametrize('transport', ['http', 'mcp'])
@pytest.mark.parametrize('location', ['envelope', 'arguments'])
@pytest.mark.parametrize('spoof', ['transport', 'command_transport'])
def test_public_transport_spoof_is_rejected_before_effects(configured, transport, location, spoof):
    core, identity, book, client, _additional, private = configured
    request = command(core, identity, {'owner_references': [str(private)]})
    (request if location == 'envelope' else request['arguments'])[spoof] = 'cli'
    path = book.root / (identity + '.json'); before = path.read_bytes(), path.stat().st_mtime_ns
    result = remote(core, client, transport, request)
    assert result['ok'] is False and result['code'] == 'validation_error'
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert CommandApplication(core).operation(request['operation_id'])['found'] is False


@pytest.mark.parametrize('transport', ['http', 'mcp'])
def test_denied_authority_is_checked_before_legacy_revision_normalization_and_reservation(configured, transport):
    core, identity, book, client, additional, _private = configured
    request = command(core, identity, {'approved_roots': [str(additional)]})
    if isinstance(core.store, JsonStore):
        anchor = core.store.root / 'thread-revisions' / (identity + '.json')
        anchor.unlink()
    path = book.root / (identity + '.json'); before = path.read_bytes(), path.stat().st_mtime_ns
    original_thread = (core.store.root / 'threads' / (identity + '.json')) if isinstance(core.store, JsonStore) else None
    source_bytes = original_thread.read_bytes() if original_thread else None
    operations = deepcopy(core.store.list_management_operations())
    result = remote(core, client, transport, request)
    assert result['ok'] is False and result['code'] == 'local_owner_cli_required'
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert core.store.list_management_operations() == operations
    if original_thread:
        assert original_thread.read_bytes() == source_bytes
        assert not anchor.exists()


def save_owner_change(book, identity, additional, private):
    config = book.load(identity)
    fields = {key: config[key] for key in ('url', 'project_id', 'root', 'token', 'automatic', 'offline_enabled')}
    return book.save(identity, **fields, approved_roots=[str(additional)], owner_references=[str(private)])


@pytest.mark.parametrize('transport', ['http', 'mcp'])
@pytest.mark.parametrize('explicit', [False, True], ids=['omitted-grants', 'stale-explicit-grants'])
def test_owner_race_rechecks_current_grants_without_rewriting_public_digest(configured, transport, explicit, monkeypatch):
    core, identity, book, client, additional, private = configured
    old = book.load(identity)
    fields = {'automatic': True, 'offline_enabled': False}
    if explicit: fields.update({key: old[key] for key in ('owner_references', 'approved_roots')})
    request = command(core, identity, fields)
    original_execute = CommandApplication._execute
    changed = []
    def race(application, spec, args, **kwargs):
        if spec.id == 'server_sync.configure' and not changed:
            changed.append(save_owner_change(BindingBook(application.service), identity, additional, private))
        return original_execute(application, spec, args, **kwargs)
    monkeypatch.setattr(CommandApplication, '_execute', race)
    result = remote(core, client, transport, deepcopy(request))
    assert len(changed) == 1
    current = book.load(identity)
    assert current['owner_references'] == [str(private)]
    assert current['approved_roots'] == [str(additional)]
    assert current['token'] == old['token']
    if explicit:
        assert result['ok'] is False and result['code'] == 'local_owner_cli_required'
        assert current == changed[0]
    else:
        assert result['ok'] and current['automatic'] is True and current['offline_enabled'] is False
        before_replay = (book.root / (identity + '.json')).read_bytes()
        replay = remote(core, client, transport, deepcopy(request))
        assert replay['ok']
        assert replay['duplicate'] if transport == 'http' else replay['result']['duplicate']
        assert (book.root / (identity + '.json')).read_bytes() == before_replay
        assert 'owner_references' not in request['arguments'] and 'approved_roots' not in request['arguments']


@pytest.mark.parametrize('transport', ['http', 'mcp'])
def test_completed_omitted_grant_request_replays_after_later_owner_change(configured, transport):
    core, identity, book, client, additional, private = configured
    request = command(core, identity, {'automatic': True})
    assert remote(core, client, transport, request)['ok']
    save_owner_change(book, identity, additional, private)
    path = book.root / (identity + '.json'); before = path.read_bytes(), path.stat().st_mtime_ns
    replay = remote(core, client, transport, deepcopy(request))
    assert replay['ok']
    assert replay['duplicate'] if transport == 'http' else replay['result']['duplicate']
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize('transport', ['http', 'mcp'])
def test_remote_save_holds_existing_book_lock_through_final_authority_check(configured, transport, monkeypatch):
    import threading

    from threaddesk.server_sync.desktop import _BOOK_LOCK
    core, identity, _book, client, _additional, _private = configured
    original_save = BindingBook.save
    probes = []
    def save(book, *args, **kwargs):
        def contender():
            acquired = _BOOK_LOCK.acquire(blocking=False)
            probes.append(acquired)
            if acquired: _BOOK_LOCK.release()
        worker = threading.Thread(target=contender)
        worker.start(); worker.join(timeout=2)
        assert not worker.is_alive()
        assert probes == [False]
        return original_save(book, *args, **kwargs)
    monkeypatch.setattr(BindingBook, 'save', save)
    assert remote(core, client, transport, command(core, identity, {'automatic': True}))['ok']
    assert probes == [False]


@pytest.mark.parametrize('transport', ['local', 'cli'])
def test_owner_configure_and_owner_reference_remain_authorized(configured, transport):
    core, identity, book, _client, additional, private = configured
    app = CommandApplication(core, transport=transport)
    request = command(core, identity, {'root': str(additional), 'url': 'https://new-owner.example',
          'project_id': 'new-owner-project', 'token': 'owner-replacement-token-1234567890',
          'approved_roots': [], 'owner_references': [str(private)]})
    assert app.call(request)['result']['configured']
    assert book.load(identity)['root'] == str(additional)
    assert book.load(identity)['owner_references'] == [str(private)]
    assert 'token' not in app.call(request)['result']
    revoke = {'version': 1, 'workspace_id': app.workspace_id, 'command': 'server_sync.owner_reference',
              'arguments': {'thread_id': identity, 'path': str(private), 'allowed': False},
              'operation_id': 'local-owner-revoke', 'expected_revision': core.get(identity).revision}
    assert app.call(revoke)['result']['owner_references'] == []
    assert app.call(revoke)['duplicate']


def test_actual_owner_cli_can_provision_binding_and_change_owner_references(configured):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    core, identity, book, _client, additional, private = configured
    initial = book.load(identity)
    new = core.create('Actual CLI configured target')
    request = command(core, identity, {'root': str(additional), 'owner_references': []})
    request['arguments'].update(thread_id=new.id, token=initial['token'])
    request['expected_revision'] = new.revision
    repository = Path(__file__).resolve().parents[1]
    env = {**os.environ, 'PYTHONPATH': str(repository / 'src'), 'PYTHONDONTWRITEBYTECODE': '1'}
    def cli(request):
        process = subprocess.run([sys.executable, '-m', 'threaddesk.ui.cli', 'command', '--request', json.dumps(request)],
                                 env=env, cwd=repository, text=True, capture_output=True, timeout=30, check=False)
        assert initial['token'] not in process.stdout + process.stderr
        assert process.returncode == 0, process.stderr
        result = json.loads(process.stdout.strip().splitlines()[-1])
        assert result['ok']
        return result
    assert cli(request)['result']['configured']
    assert book.load(new.id)['root'] == str(additional)
    grant = {'version': 1, 'workspace_id': request['workspace_id'], 'command': 'server_sync.owner_reference',
             'operation_id': 'actual-cli-owner-grant', 'expected_revision': core.get(new.id).revision,
             'arguments': {'thread_id': new.id, 'path': str(private), 'allowed': True}}
    assert str(private) in cli(grant)['result']['owner_references']
    assert str(private) in book.load(new.id)['owner_references']
    assert cli(grant)['duplicate']


def owner_cli_request(core, identity, path, *, operation='parallel-owner-revoke'):
    return {'version': 1, 'workspace_id': CommandApplication(core).workspace_id,
            'command': 'server_sync.owner_reference', 'operation_id': operation,
            'expected_revision': core.get(identity).revision,
            'arguments': {'thread_id': identity, 'path': path, 'allowed': False}}


def start_instrumented_cli(request, marker):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    repository = Path(__file__).resolve().parents[1]
    code = '''
import errno,json,os,runpy,sys
from pathlib import Path
from contextlib import contextmanager
from threaddesk.server_sync.desktop import BindingBook
original = BindingBook._mutation
marker = Path(sys.argv[1])
@contextmanager
def mutation(book, identity):
    descriptor = os.open(book.root / ('.' + identity + '.config.lock'), os.O_RDWR)
    blocked = False
    try:
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError as error:
            if error.errno not in (errno.EAGAIN, errno.EACCES, errno.EDEADLK):
                raise
            blocked = True
    finally:
        os.close(descriptor)
    temporary = marker.with_name(marker.name + '.pending')
    temporary.write_text(json.dumps({'actual_cli_mutation': True, 'binding_lock_would_block': blocked}))
    temporary.replace(marker)
    with original(book, identity):
        yield
BindingBook._mutation = mutation
sys.argv = ['threaddesk.ui.cli', 'command', '--request', sys.argv[2]]
runpy.run_module('threaddesk.ui.cli', run_name='__main__')
'''
    return subprocess.Popen([sys.executable, '-c', code, str(marker), json.dumps(request)],
        cwd=repository, env={**os.environ, 'PYTHONPATH': str(repository / 'src'), 'PYTHONDONTWRITEBYTECODE': '1'},
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def wait_for_cli_marker(process, marker):
    import json
    import time
    deadline = time.monotonic() + 10
    while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.exists(), 'Actual CLI did not reach its binding-mutation boundary'
    assert json.loads(marker.read_text())['binding_lock_would_block'] is True


def finish_cli(process):
    import json
    output, error = process.communicate(timeout=20)
    assert process.returncode == 0, error
    result = json.loads(output.strip().splitlines()[-1])
    assert result['ok']
    return result


@pytest.mark.parametrize('transport', ['http', 'mcp'])
def test_actual_cli_revoke_cannot_be_overwritten_between_remote_compare_and_save(configured, transport, monkeypatch, tmp_path):
    core, identity, book, client, _additional, _private = configured
    old = book.load(identity)
    request = owner_cli_request(core, identity, old['owner_references'][0])
    original_save = BindingBook.save
    children = []
    def save(current_book, *args, **kwargs):
        marker = tmp_path / 'cli-at-config-mutation'
        process = start_instrumented_cli(request, marker); children.append(process)
        wait_for_cli_marker(process, marker)
        assert process.poll() is None, 'CLI must wait for the remote atomic mutation'
        assert current_book.load(identity)['owner_references'] == old['owner_references']
        return original_save(current_book, *args, **kwargs)
    monkeypatch.setattr(BindingBook, 'save', save)
    try:
        response = remote(core, client, transport, command(core, identity, {'automatic': True}))
        assert response['ok']
        assert len(children) == 1
        assert finish_cli(children[0])['result']['owner_references'] == []
        current = book.load(identity)
        assert current['owner_references'] == []
        assert current['automatic'] is True
        assert current['token'] == old['token']
    finally:
        for process in children:
            if process.poll() is None:
                process.terminate(); process.communicate(timeout=10)


def test_separate_cli_rmw_serializes_and_different_binding_does_not_wait(configured, tmp_path):
    core, identity, book, _client, additional, _private = configured
    old = book.load(identity)
    second = core.create('Independent second binding')
    book.save(second.id, url=old['url'], project_id='second-project', root=str(additional), token=old['token'],
              owner_references=old['owner_references'])
    children = []
    lockfile = book.root / ('.' + identity + '.config.lock')
    inode = lockfile.stat().st_ino
    try:
        with book._mutation(identity):
            waiting = start_instrumented_cli(owner_cli_request(core, identity, old['owner_references'][0]),
                                             tmp_path / 'same-binding'); children.append(waiting)
            wait_for_cli_marker(waiting, tmp_path / 'same-binding')
            assert waiting.poll() is None
            independent = start_instrumented_cli(owner_cli_request(core, second.id, old['owner_references'][0], operation='other-binding-revoke'),
                                                 tmp_path / 'other-binding'); children.append(independent)
            assert finish_cli(independent)['result']['owner_references'] == []
            # A nested mutation through another Book instance uses the same
            # PID/thread/binding lock, and preserves a concurrent control edit.
            BindingBook(core).update(identity, {'automatic': True})
        assert finish_cli(waiting)['result']['owner_references'] == []
        assert book.load(identity)['automatic'] is True
        assert lockfile.stat().st_ino == inode
    finally:
        for process in children:
            if process.poll() is None:
                process.terminate(); process.communicate(timeout=10)


def test_read_only_binding_load_and_view_create_no_private_directory_or_lock(configured, tmp_path):
    core, _identity, _book, _client, _additional, _private = configured
    fresh = ThreadService(type(core.store)(tmp_path / 'new-readonly-workspace'))
    try:
        identity = fresh.create('Read-only unconfigured binding').id
        book = BindingBook(fresh)
        before = {p.relative_to(fresh.store.root).as_posix(): p.read_bytes() for p in fresh.store.root.rglob('*') if p.is_file()}
        assert book.load(identity) is None
        assert book.view(identity)['configured'] is False
        assert not book.root.exists()
        assert {p.relative_to(fresh.store.root).as_posix(): p.read_bytes() for p in fresh.store.root.rglob('*') if p.is_file()} == before
    finally:
        if isinstance(fresh.store, SQLiteStore): fresh.store.connection.close()


def test_mutation_exception_releases_lock_for_real_cli_and_keeps_config_bytes(configured, monkeypatch, tmp_path):
    from threaddesk.server_sync import desktop

    core, identity, book, _client, _additional, _private = configured
    config = book.load(identity)
    path = book.root / (identity + '.json'); before = path.read_bytes()
    original_write = desktop._write
    def fail(path, value):
        if path.name == identity + '.json': raise OSError('Synthetic private binding write failure')
        return original_write(path, value)
    with monkeypatch.context() as blocked:
        blocked.setattr(desktop, '_write', fail)
        with pytest.raises(OSError, match='Synthetic private binding'):
            book.update(identity, {'automatic': True})
    assert path.read_bytes() == before
    process = start_instrumented_cli(owner_cli_request(core, identity, config['owner_references'][0]), tmp_path / 'after-error')
    try:
        assert finish_cli(process)['result']['owner_references'] == []
    finally:
        if process.poll() is None:
            process.terminate(); process.communicate(timeout=10)


@pytest.mark.parametrize('unsafe', ['symlink', 'hardlink', 'public-mode', 'fifo'])
def test_unsafe_binding_lock_is_rejected_without_config_write(configured, unsafe):
    import os

    _core, identity, book, _client, _additional, private = configured
    lock = book.root / ('.' + identity + '.config.lock')
    lock.unlink()  # Deliberately corrupt only this isolated test lock fixture.
    if unsafe == 'symlink': lock.symlink_to(private)
    elif unsafe == 'hardlink': os.link(private, lock)
    elif unsafe == 'fifo': os.mkfifo(lock, 0o600)
    else: lock.write_bytes(b' '); lock.chmod(0o644)
    binding = book.root / (identity + '.json'); before = binding.read_bytes(), private.read_bytes()
    from threaddesk.core.errors import InvalidState
    with pytest.raises((InvalidState, OSError)):
        book.update(identity, {'automatic': True})
    assert (binding.read_bytes(), private.read_bytes()) == before


def test_inherited_foreign_process_reentrancy_key_never_skips_real_lock(configured, monkeypatch):
    import os
    import threading

    import threaddesk.storage.json_store as storage
    from threaddesk.server_sync import desktop

    _core, identity, book, _client, _additional, _private = configured
    foreign = (os.getpid() + 1, threading.get_ident(), str(book.root.resolve()), identity)
    monkeypatch.setattr(desktop._BOOK_MUTATIONS, 'held', {foreign})
    original = storage._lock_exclusive
    seen = []
    def checked(lock):
        seen.append(lock.fileno())
        return original(lock)
    monkeypatch.setattr(storage, '_lock_exclusive', checked)
    with book._mutation(identity):
        book.update(identity, {'automatic': True})
    assert len(seen) == 1
    assert desktop._BOOK_MUTATIONS.held == {foreign}


def test_lock_mode_convention_does_not_apply_posix_permission_bits_to_windows(configured, monkeypatch):
    import os
    from types import SimpleNamespace

    from threaddesk.server_sync import desktop

    _core, identity, book, _client, _additional, _private = configured
    lock = book.root / ('.' + identity + '.config.lock')
    lock.chmod(0o644)
    # This probes only the permission-bit policy. Native Windows descriptor
    # locking is deliberately not claimed by this POSIX-hosted test.
    monkeypatch.setattr(desktop, 'os', SimpleNamespace(**{**vars(os), 'name': 'nt'}))
    book.update(identity, {'automatic': True})
    assert book.load(identity)['automatic'] is True


def test_missing_safe_open_flag_fails_before_creating_private_directory(configured, tmp_path, monkeypatch):
    import os
    from types import SimpleNamespace

    from threaddesk.core.errors import InvalidState
    from threaddesk.server_sync import desktop

    core, _identity, _book, _client, _additional, _private = configured
    fresh = ThreadService(type(core.store)(tmp_path / 'no-safe-open-workspace'))
    try:
        identity = fresh.create('Fail closed without safe open').id
        book = BindingBook(fresh)
        monkeypatch.setattr(desktop, 'os', SimpleNamespace(**{k: v for k, v in vars(os).items() if k != 'O_NOFOLLOW'}))
        with pytest.raises(InvalidState, match='Safe sync configuration locking is unavailable'):
            book.update(identity, {'automatic': True})
        assert not book.root.exists()
    finally:
        if isinstance(fresh.store, SQLiteStore): fresh.store.connection.close()


def test_missing_safe_open_cannot_follow_lock_symlink_or_write_an_empty_target(configured, tmp_path, monkeypatch):
    import os
    from types import SimpleNamespace

    from threaddesk.core.errors import InvalidState
    from threaddesk.server_sync import desktop

    _core, identity, book, _client, _additional, _private = configured
    empty = tmp_path / 'empty-original'; empty.write_bytes(b''); empty.chmod(0o600)
    lock = book.root / ('.' + identity + '.config.lock'); lock.unlink(); lock.symlink_to(empty)
    config_path = book.root / (identity + '.json'); before = config_path.read_bytes(), empty.stat().st_mtime_ns
    monkeypatch.setattr(desktop, 'os', SimpleNamespace(**{k: v for k, v in vars(os).items() if k != 'O_NOFOLLOW'}))
    with pytest.raises(InvalidState, match='Safe sync configuration locking is unavailable'):
        book.update(identity, {'automatic': True})
    assert empty.read_bytes() == b''
    assert (config_path.read_bytes(), empty.stat().st_mtime_ns) == before
