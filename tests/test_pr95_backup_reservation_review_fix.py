"""Native command backup omits only its own proven in-flight reservation."""
import hashlib
import json
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest
from test_trash_lifecycle import seed

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError, NotFound
from threaddesk.services.commands import CommandApplication
from threaddesk.services.commands.validation import command_request_digest
from threaddesk.services.library_import import LibraryImporter
from threaddesk.services.trash import TrashService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.portable_backup import inspect_backup, restore_backup
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=['json', 'sqlite'])
def source(tmp_path, request):
    store = request.param(tmp_path / 'source')
    core = ThreadService(store)
    thread = seed(store)
    original_dir = tmp_path / 'originals'; original_dir.mkdir()
    original = original_dir / 'retained.txt'; original.write_bytes(b'Independent backup fixture original bytes')
    imported = LibraryImporter(store).import_tree(original_dir)
    assert imported['stored'] == 1
    artifact = store.root / 'artifacts' / 'nested' / 'large.bin'
    artifact.parent.mkdir(parents=True); artifact.write_bytes(bytes(range(256)) * 4096)
    task = core.create_node('task', 'Isolated synthetic purge target')
    yield core, thread.id, task, original, artifact
    if isinstance(store, SQLiteStore):
        store.connection.close()


def call_backup(core, operation='own-native-export', **envelope_fields):
    app = CommandApplication(core)
    request = {'version': 1, 'workspace_id': app.workspace_id, 'command': 'backup.create',
               'arguments': {}, 'operation_id': operation, **envelope_fields}
    return app, request, app.call(request)['result']


def open_restored(core, created, root):
    verified = inspect_backup(Path(created['path']))
    assert verified['verified'] and verified['sha256'] == created['sha256']
    profile = restore_backup(Path(created['path']), root, expected_sha256=created['sha256'])
    return ThreadService(type(core.store)(profile)), verified


def pending_key(operation):
    return 'command-' + hashlib.sha256(operation.encode()).hexdigest() + '-pending'


def test_backup_command_full_native_restore_leaves_no_self_pending_and_purge_works(source, tmp_path):
    core, identity, task, original, artifact = source
    original_before = original.read_bytes(), original.stat().st_mtime_ns
    app, request, created = call_backup(core)
    copy, verified = open_restored(core, created, tmp_path / 'restore-root')
    try:
        restored_app = CommandApplication(copy)
        assert restored_app.operation(request['operation_id'])['found'] is False
        assert app.operation(request['operation_id'])['state'] == 'complete'
        assert core.store.get_management_operation(pending_key(request['operation_id']))['state'] == 'pending'
        assert app.call(request)['duplicate'] is True
        assert copy.store.get_thread(identity).context.notes == 'Geschichte erhalten'
        assert [row.id for row in copy.store.list_snapshots(identity)] == ['snapshot1']
        assert copy.store.list_whiteboard(identity)[0].content == 'Whiteboard bleibt'
        assert {row.id for row in copy.store.list_relations()} == {'relation1'}
        assert (copy.store.root / artifact.relative_to(core.store.root)).read_bytes() == artifact.read_bytes()
        records = LibraryImporter(copy.store).catalog()['records']
        assert len(records) == 1
        assert LibraryImporter(copy.store).open_record(records[0]['id'])[0].read_bytes() == original.read_bytes()
        assert (original.read_bytes(), original.stat().st_mtime_ns) == original_before
        boundary = verified['snapshot_boundary']
        assert boundary['storage_operation_id'] == pending_key(request['operation_id'])
        assert boundary['request_hash'] == command_request_digest(app.workspace_id, 'backup.create', {}, request['operation_id'])
        assert boundary['source_record_preserved'] is True
        trash = TrashService(copy.store)
        entry = trash.move(kind='node', object_id=task.id, expected_revision=task.revision, operation_id='restored-local-trash')['entry']
        preview = trash.purge_preview(entry['trash_id'])
        assert preview['blockers'] == []
        purged = trash.purge(trash_id=entry['trash_id'], generation=entry['generation'], expected_revision=entry['revision'],
                             reference_digest=preview['reference_digest'], confirmation=preview['confirmation'], operation_id='restored-local-purge')
        assert purged['entry']['state'] == 'purged'
        with pytest.raises(NotFound):
            copy.store.get_node(task.id, include_trashed=True)
    finally:
        if isinstance(copy.store, SQLiteStore):
            copy.store.connection.close()


def lose_completion(app, request, monkeypatch):
    original = app._save
    def crash(key, digest, state, **kwargs):
        if state == 'complete':
            raise SystemExit('Synthetic process exit before command completion')
        return original(key, digest, state, **kwargs)
    with monkeypatch.context() as blocked:
        blocked.setattr(app, '_save', crash)
        with pytest.raises(SystemExit, match='before command completion'):
            app.call(request)


def assert_pending_blocks(copy, task, operation):
    trash = TrashService(copy.store)
    entry = trash.move(kind='node', object_id=task.id, expected_revision=task.revision, operation_id='restored-trash')['entry']
    preview = trash.purge_preview(entry['trash_id'])
    assert {'storage_operation_id': pending_key(operation), 'reason': 'unconfirmed_command_requires_review'} in preview['receipt_reduction']['blockers']
    with pytest.raises(ManagementError) as error:
        trash.purge(trash_id=entry['trash_id'], generation=entry['generation'], expected_revision=entry['revision'],
                    reference_digest=preview['reference_digest'], confirmation=preview['confirmation'], operation_id='blocked-purge')
    assert error.value.code == 'purge_blocked'
    assert copy.store.get_node(task.id, include_trashed=True).id == task.id


def test_unrelated_actual_pending_is_preserved_and_still_blocks_after_restore(source, tmp_path, monkeypatch):
    core, _identity, task, _original, _artifact = source
    app = CommandApplication(core)
    unrelated = {'version': 1, 'workspace_id': app.workspace_id, 'command': 'room.create',
                 'arguments': {'name': 'Synthetic pending room'}, 'operation_id': 'unrelated-room'}
    lose_completion(app, unrelated, monkeypatch)
    retained = deepcopy(core.store.get_management_operation(pending_key('unrelated-room')))
    app, _request, created = call_backup(core)
    assert app.operation('unrelated-room')['state'] == 'pending'
    copy, _verified = open_restored(core, created, tmp_path / 'restore-root')
    try:
        assert copy.store.get_management_operation(pending_key('unrelated-room')) == retained
        assert copy.store.get_management_operation(pending_key('own-native-export')) is None
        assert_pending_blocks(copy, task, 'unrelated-room')
    finally:
        if isinstance(copy.store, SQLiteStore):
            copy.store.connection.close()


def test_aborted_export_keeps_source_pending_and_later_backups_do_not_clean_history(source, tmp_path, monkeypatch):
    import threaddesk.storage.portable_backup as portable
    core, _identity, task, _original, _artifact = source
    app = CommandApplication(core)
    request = {'version': 1, 'workspace_id': app.workspace_id, 'command': 'backup.create',
               'arguments': {}, 'operation_id': 'interrupted-export'}
    def crash(*_args, **_kwargs):
        raise SystemExit('Synthetic exit at native archive publication')
    with monkeypatch.context() as blocked:
        blocked.setattr(portable, '_publish_new', crash)
        with pytest.raises(SystemExit, match='native archive publication'):
            app.call(request)
    retained = deepcopy(core.store.get_management_operation(pending_key(request['operation_id'])))
    assert retained['state'] == 'pending'
    assert app.operation(request['operation_id'])['state'] == 'pending'
    with pytest.raises(ManagementError) as error:
        app.call(request)
    assert error.value.code == 'operation_unconfirmed'
    assert not list(core.store.root.glob('command-backup-*.zip'))
    _, _, created = call_backup(core, 'fresh-later-export')
    copy, _ = open_restored(core, created, tmp_path / 'restore-root')
    try:
        assert core.store.get_management_operation(pending_key('interrupted-export')) == retained
        assert copy.store.get_management_operation(pending_key('interrupted-export')) == retained
        assert copy.store.get_management_operation(pending_key('fresh-later-export')) is None
        assert_pending_blocks(copy, task, 'interrupted-export')
    finally:
        if isinstance(copy.store, SQLiteStore):
            copy.store.connection.close()
    # The ordinary native API has no command scope and must omit nothing.
    raw = tmp_path / 'ordinary-native.zip'
    portable.export_backup(core.store, raw)
    assert 'snapshot_boundary' not in inspect_backup(raw)
    profile = restore_backup(raw, tmp_path / 'ordinary-native-restore')
    store = type(core.store)(profile)
    try:
        assert store.get_management_operation(pending_key('interrupted-export')) == retained
        assert store.get_management_operation(pending_key('fresh-later-export')) is not None
    finally:
        if isinstance(store, SQLiteStore):
            store.connection.close()


@pytest.mark.parametrize('envelope_revision', [0, 17])
def test_exact_envelope_revision_is_bound_without_public_schema_changes(source, tmp_path, envelope_revision):
    core, _identity, _task, _original, _artifact = source
    app, request, created = call_backup(core, expected_revision=envelope_revision)
    checked = inspect_backup(Path(created['path']))
    assert checked['snapshot_boundary']['expected_revision'] == envelope_revision
    assert checked['snapshot_boundary']['request_hash'] == command_request_digest(
        app.workspace_id, 'backup.create', {}, request['operation_id'], envelope_revision)
    assert app.call(request)['duplicate'] is True


@pytest.mark.parametrize('field', ['command_reservation', 'backup_reservation'])
def test_public_arguments_cannot_choose_reservation_scope(source, field):
    core, *_ = source
    app = CommandApplication(core)
    request = {'version': 1, 'workspace_id': app.workspace_id, 'command': 'backup.create',
               'arguments': {field: {'operation_id': 'another-pending', 'expected_revision': None}},
               'operation_id': 'public-injection'}
    before = deepcopy(core.store.list_management_operations())
    with pytest.raises(ManagementError) as error:
        app.call(request)
    assert error.value.code == 'validation_error'
    assert core.store.list_management_operations() == before
    assert not app.operation('public-injection')['found']


@pytest.mark.parametrize('invalid', ['request-hash', 'foreign-command', 'foreign-workspace', 'storage-id',
    'kind', 'state', 'result', 'error', 'missing', 'extra-record-field', 'terminal',
    'context-operation', 'context-revision', 'context-extra-field', 'context-bool-revision'])
def test_native_omission_rejects_any_unproven_reservation_binding(source, tmp_path, invalid):
    from threaddesk.core.models import now_iso
    from threaddesk.storage.portable_backup import export_backup
    from threaddesk.storage.workspace_backup import BackupError
    core, *_ = source
    app = CommandApplication(core)
    operation = 'exact-private-export'
    key = pending_key(operation)
    digest = command_request_digest(app.workspace_id, 'backup.create', {}, operation)
    record = {'request_hash': digest, 'recorded_at': now_iso(), 'state': 'pending', 'result': None,
              'error': None, 'kind': 'command', 'storage_operation_id': key}
    reservation = {'operation_id': operation, 'expected_revision': None}
    if invalid == 'request-hash': record['request_hash'] = '0' * 64
    elif invalid == 'foreign-command': record['request_hash'] = command_request_digest(app.workspace_id, 'room.sync', {}, operation)
    elif invalid == 'foreign-workspace': record['request_hash'] = command_request_digest('ws-' + '0' * 32, 'backup.create', {}, operation)
    elif invalid == 'storage-id': record['storage_operation_id'] = pending_key('different-operation')
    elif invalid == 'kind': record['kind'] = 'library'
    elif invalid == 'state': record['state'] = 'complete'
    elif invalid == 'result': record['result'] = {'unproven': True}
    elif invalid == 'error': record['error'] = {'code': 'prior_failure'}
    elif invalid == 'extra-record-field': record['unproven'] = True
    elif invalid == 'context-operation': reservation['operation_id'] = 'another-operation'
    elif invalid == 'context-revision': reservation['expected_revision'] = 1
    elif invalid == 'context-extra-field': reservation['command'] = 'backup.create'
    elif invalid == 'context-bool-revision': reservation['expected_revision'] = True
    with core.store.transaction():
        if invalid != 'missing': core.store.save_management_operation(key, record)
        if invalid == 'terminal': app._save(app._operation_key(operation), digest, 'complete', result={'prior': True})
    before = deepcopy(core.store.list_management_operations())
    destination = tmp_path / 'must-not-publish.zip'
    with pytest.raises(BackupError, match='reservation'):
        export_backup(core.store, destination, command_reservation=reservation)
    assert not destination.exists()
    assert core.store.list_management_operations() == before


def test_json_own_pending_symlink_is_refused_before_any_external_read(tmp_path, monkeypatch):
    from threaddesk.storage.portable_backup import export_backup
    from threaddesk.storage.workspace_backup import BackupError
    store = JsonStore(tmp_path / 'source')
    app = CommandApplication(ThreadService(store))
    operation = 'scoped-backup'
    digest = command_request_digest(app.workspace_id, 'backup.create', {}, operation)
    with store.transaction():
        app._save(app._operation_key(operation), digest, 'pending')
    pending = store.root / 'management-operations' / (pending_key(operation) + '.json')
    outside = tmp_path / 'outside-original.json'
    outside.write_bytes(pending.read_bytes())
    original_read = Path.read_text
    pending.unlink(); pending.symlink_to(outside)
    def never_external(path, *args, **kwargs):
        if path.resolve() == outside:
            pytest.fail('Command reservation read escaped its native SourceTree binding')
        return original_read(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', never_external)
    with pytest.raises(BackupError, match='Symbolic link'):
        export_backup(store, tmp_path / 'must-not-publish.zip', command_reservation={
            'operation_id': operation, 'expected_revision': None})
    assert not (tmp_path / 'must-not-publish.zip').exists()
    assert pending.is_symlink()


@pytest.mark.parametrize('terminal', ['complete', 'failed'])
def test_existing_invalid_terminal_null_is_never_treated_as_absent(source, tmp_path, terminal):
    from threaddesk.storage.portable_backup import export_backup
    from threaddesk.storage.workspace_backup import BackupError
    core, *_ = source
    app = CommandApplication(core)
    operation = 'null-terminal'
    key = app._operation_key(operation)
    digest = command_request_digest(app.workspace_id, 'backup.create', {}, operation)
    with core.store.transaction():
        app._save(key, digest, 'pending')
    terminal_key = key + '-' + terminal
    if isinstance(core.store, JsonStore):
        (core.store.root / 'management-operations' / (terminal_key + '.json')).write_text('null')
    else:
        core.store.connection.execute('INSERT INTO management_operations(id,payload) VALUES (?,?)', (terminal_key, 'null'))
        core.store.connection.commit()
    with pytest.raises(BackupError, match='reservation record'):
        export_backup(core.store, tmp_path / 'no.zip', command_reservation={
            'operation_id': operation, 'expected_revision': None})
    assert not (tmp_path / 'no.zip').exists()


def test_existing_json_terminal_directory_is_not_treated_as_absent(tmp_path):
    from threaddesk.storage.portable_backup import export_backup
    from threaddesk.storage.workspace_backup import BackupError
    store = JsonStore(tmp_path / 'source')
    app = CommandApplication(ThreadService(store))
    operation = 'directory-terminal'
    key = app._operation_key(operation)
    with store.transaction():
        app._save(key, command_request_digest(app.workspace_id, 'backup.create', {}, operation), 'pending')
    (store.root / 'management-operations' / (key + '-complete.json')).mkdir()
    with pytest.raises(BackupError, match='Nonregular command backup reservation'):
        export_backup(store, tmp_path / 'no.zip', command_reservation={
            'operation_id': operation, 'expected_revision': None})
    assert not (tmp_path / 'no.zip').exists()


@pytest.mark.parametrize('invalid', ['command', 'request-hash', 'storage-id', 'source-preserved', 'legacy-version'])
def test_manifest_boundary_must_match_its_exact_typed_command_binding(source, tmp_path, invalid):
    from threaddesk.storage.workspace_backup import BackupError
    core, *_ = source
    _, _, created = call_backup(core)
    with zipfile.ZipFile(created['path']) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(members['manifest.json'])
    boundary = manifest['snapshot_boundary']
    if invalid == 'command': boundary['command'] = 'room.sync'
    elif invalid == 'request-hash': boundary['request_hash'] = '0' * 64
    elif invalid == 'storage-id': boundary['storage_operation_id'] = pending_key('unrelated')
    elif invalid == 'source-preserved': boundary['source_record_preserved'] = 1
    else: manifest['version'] = 2
    members['manifest.json'] = json.dumps(manifest).encode()
    path = tmp_path / 'invalid-boundary.zip'
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in members.items(): archive.writestr(name, body)
    with pytest.raises(BackupError, match='boundary'):
        inspect_backup(path)
    target = tmp_path / 'must-not-activate'
    with pytest.raises(BackupError, match='boundary'):
        restore_backup(path, target)
    assert not (target / 'active-profile.json').exists()
    assert not list((target / 'profiles').glob('*'))


def test_sqlite_snapshot_omission_cannot_trigger_changes_to_other_canonical_rows(tmp_path):
    from threaddesk.storage.portable_backup import export_backup
    from threaddesk.storage.workspace_backup import BackupError
    store = SQLiteStore(tmp_path / 'source')
    try:
        core = ThreadService(store)
        task = core.create_node('task', 'Must remain in original AND backup scope')
        app = CommandApplication(core)
        operation = 'trigger-boundary'
        key = app._operation_key(operation)
        with store.transaction():
            app._save(key, command_request_digest(app.workspace_id, 'backup.create', {}, operation), 'pending')
        # This real trigger is copied by SQLite's existing backup mechanism.
        # The constrained exclusion must not silently publish its extra delete.
        store.connection.execute('''CREATE TRIGGER synthetic_backup_trigger AFTER DELETE ON management_operations
            BEGIN DELETE FROM nodes; END''')
        store.connection.commit()
        before = store.get_node(task.id).to_dict()
        pending = deepcopy(store.get_management_operation(key + '-pending'))
        with pytest.raises(BackupError, match='could not be isolated'):
            export_backup(store, tmp_path / 'must-not-publish.zip', command_reservation={
                'operation_id': operation, 'expected_revision': None})
        assert not (tmp_path / 'must-not-publish.zip').exists()
        assert store.get_node(task.id).to_dict() == before
        assert store.get_management_operation(key + '-pending') == pending
    finally:
        store.connection.close()
