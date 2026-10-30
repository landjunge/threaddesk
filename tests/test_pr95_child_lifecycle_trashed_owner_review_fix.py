"""Child lifecycle sync keeps a retained trashed owner completely untouched."""
from copy import deepcopy

import httpx
import pytest
from test_pr95_sync_review_fixes import graph
from test_server_sync_metadata import Wire

from threaddesk.api.service import ThreadService
from threaddesk.server_sync.metadata import (
    MetadataReplica,
    export_document,
    synchronize,
)
from threaddesk.services.trash import TrashService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=['json', 'sqlite'])
def replica_pair(request, tmp_path):
    local, remote = (ThreadService(request.param(tmp_path / name)) for name in ('local', 'remote'))
    tid, pid = local.create('Owner').id, remote.create('Owner').id
    for core, identity, marker in ((local, tid, 'local private'), (remote, pid, 'remote private')):
        with core.store.transaction():
            owner = core.get(identity)
            owner.context.extra['private_owner_marker'] = marker
            owner.context.files = ['/private/' + marker + '/original.txt']
            core.store.save_thread(owner)
    _project, task, relation = graph(local, tid)
    wire = Wire(remote, pid)
    checkpoint = tmp_path / 'checkpoint'
    replica = MetadataReplica(local, tid, checkpoint, remote_identity=pid)
    replica.sync_once(wire.http, pid, 'token')
    yield local, tid, remote, pid, task, relation, wire, replica, checkpoint
    replica.close()
    wire.http.close()
    for core in (local, remote):
        if isinstance(core.store, SQLiteStore):
            core.store.connection.close()


def owner_payload(store, identity):
    """Read raw payload bytes, anchors and retained snapshots without live access."""
    if isinstance(store, JsonStore):
        names = [store.root / 'threads' / (identity + '.json'),
                 store.root / 'thread-revisions' / (identity + '.json')]
        names.extend(sorted((store.root / 'snapshots' / identity).glob('*.json')))
        return {path.relative_to(store.root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in names}
    thread = store.connection.execute('SELECT payload FROM threads WHERE id=?', (identity,)).fetchone()
    snapshots = store.connection.execute(
        'SELECT id,payload FROM snapshots WHERE thread_id=? ORDER BY id', (identity,)).fetchall()
    return {'thread': thread[0].encode(), 'snapshots': [(row[0], row[1].encode()) for row in snapshots]}


def move(core, kind, obj, operation):
    return TrashService(core.store).move(kind=kind, object_id=obj.id,
        expected_revision=obj.revision, operation_id=operation)['entry']


def restore(core, entry, operation):
    return TrashService(core.store).restore(trash_id=entry['trash_id'], generation=entry['generation'],
        expected_revision=entry['revision'], operation_id=operation)


def retained_owner(replica_pair, kind):
    local, tid, remote, pid, task, relation, wire, replica, _checkpoint = replica_pair
    child = task if kind == 'node' else relation
    entry = move(local, kind, child, 'child-trash-first')
    assert replica.sync_once(wire.http, pid, 'token')['conflicts'] == []
    owner_entry = move(local, 'thread', local.get(tid), 'owner-trash')
    assert replica.sync_once(wire.http, pid, 'token')['conflicts'] == []
    remote_entry = next(row for row in remote.store.list_trash_entries() if row['kind'] == kind)
    return child, entry, owner_entry, remote_entry['object_id']


def assert_hidden(core, identity):
    assert core.store.object_in_trash('thread', identity)
    assert core.list_nodes() == []
    assert core.list_relations() == []


@pytest.mark.parametrize('kind', ['node', 'relation'])
@pytest.mark.parametrize('lost_response', [False, True], ids=['normal', 'lost-response-restart'])
def test_child_restore_two_generations_and_replay_never_write_trashed_owner(
        replica_pair, kind, lost_response, monkeypatch):
    local, tid, remote, pid, _task, _relation, wire, replica, checkpoint = replica_pair
    child, entry, owner_entry, remote_child = retained_owner(replica_pair, kind)
    local_owner, remote_owner = owner_payload(local.store, tid), owner_payload(remote.store, pid)
    owner_lifecycles = [deepcopy(core.store.get_object_lifecycle('thread', identity))
                       for core, identity in ((local, tid), (remote, pid))]
    remote_nodes = {item.id for item in remote.store.list_nodes(include_trashed=True)}
    remote_relations = {item.id for item in remote.store.list_relations(include_trashed=True)}

    def forbidden(*_args, **_kwargs):
        pytest.fail('A lifecycle-only update invoked a live owner reader or payload writer')

    # Existing TrashService may test an unresolved owner through its guarded
    # store read; metadata must never enter core.get or submit owner payloads.
    monkeypatch.setattr(remote, 'get', forbidden)
    monkeypatch.setattr(remote.store, 'save_thread', forbidden)
    monkeypatch.setattr(remote.store, 'save_snapshot', forbidden)
    try:
        for generation in (1, 2):
            if generation == 2:
                entry = move(local, kind, child, 'child-trash-second')
                assert entry['generation'] == 2
                assert replica.sync_once(wire.http, pid, 'token')['conflicts'] == []
            restore(local, entry, 'child-restore-' + str(generation))
            if generation == 1 and lost_response:
                wire.lose = True
                with pytest.raises(httpx.ReadError, match='Lost committed response'):
                    replica.sync_once(wire.http, pid, 'token')
                committed_operation = wire.calls[-1]
                assert remote.store.get_object_lifecycle(kind, remote_child)['state'] == 'restored'
                replica.close()
                replica = MetadataReplica(local, tid, checkpoint, remote_identity=pid)
            else:
                committed_operation = None
            result = replica.sync_once(wire.http, pid, 'token')
            assert result['state'] == 'synced' and result['conflicts'] == []
            if committed_operation is not None:
                assert wire.calls[-2:] == [committed_operation, committed_operation]
            assert remote.store.get_object_lifecycle(kind, remote_child)['generation'] == generation
            assert remote.store.get_object_lifecycle(kind, remote_child)['state'] == 'restored'
            assert owner_payload(local.store, tid) == local_owner
            assert owner_payload(remote.store, pid) == remote_owner
            for number, (core, identity) in enumerate(((local, tid), (remote, pid))):
                assert_hidden(core, identity)
                assert core.store.get_object_lifecycle('thread', identity) == owner_lifecycles[number]
            if generation == 1:
                first_restore = export_document(local, tid)
            assert replica.sync_once(wire.http, pid, 'token')['unchanged'] is True

        stale = synchronize(remote, pid, 'stale-first-restore', first_restore, first_restore)
        assert stale['state'] == 'conflict'
        assert any(row['reason'] == 'stale_generation' for row in stale['conflicts'])
        assert remote.store.get_object_lifecycle(kind, remote_child)['generation'] == 2
        assert owner_payload(remote.store, pid) == remote_owner
        assert_hidden(remote, pid)
        histories = [row for row in remote.store.list_trash_entries()
                     if row['kind'] == kind and row['object_id'] == remote_child]
        assert sorted((row['generation'], row['state']) for row in histories) == [(1, 'restored'), (2, 'restored')]

        # Only a subsequent explicit owner restore makes the child visible.
        restore(local, owner_entry, 'explicit-owner-restore')
        assert replica.sync_once(wire.http, pid, 'token')['conflicts'] == []
        assert not remote.store.object_in_trash('thread', pid)
        assert {item.id for item in remote.list_nodes()} == remote_nodes
        assert {item.id for item in remote.list_relations()} == remote_relations
        assert owner_payload(remote.store, pid) == remote_owner
    finally:
        replica.close()


@pytest.mark.parametrize('kind', ['node', 'relation'])
def test_child_restore_cannot_smuggle_owner_edit_through_unchanged_tombstone(replica_pair, kind):
    local, tid, remote, pid, _task, _relation, _wire, _replica, _checkpoint = replica_pair
    _child, entry, _owner_entry, remote_child = retained_owner(replica_pair, kind)
    before = export_document(remote, pid)
    payload = owner_payload(remote.store, pid)
    lifecycle = deepcopy(remote.store.get_object_lifecycle(kind, remote_child))
    restore(local, entry, 'child-restore')
    incoming = export_document(local, tid)
    incoming['thread']['notes'] = 'Forbidden edit under unchanged owner tombstone'

    result = synchronize(remote, pid, 'restore-plus-owner-edit', before, incoming)

    assert result['state'] == 'conflict'
    assert any(row['reason'] == 'edit_of_trashed_object' for row in result['conflicts'])
    assert export_document(remote, pid) == before
    assert owner_payload(remote.store, pid) == payload
    assert remote.store.get_object_lifecycle(kind, remote_child) == lifecycle
    assert_hidden(remote, pid)


@pytest.mark.parametrize('new_value', [True, 1.0], ids=['bool-vs-int', 'float-vs-int'])
@pytest.mark.parametrize('kind', ['node', 'relation'])
def test_direct_apply_never_calls_typed_metadata_change_lifecycle_only(
        replica_pair, kind, new_value):
    # Exercise the actual adapter body independently of the existing generic
    # leaf merge's equality rules, which this scoped correction does not alter.
    from threaddesk.core.errors import ManagementError
    from threaddesk.server_sync.metadata import _apply, validate_document

    local, _tid, remote, pid, task, _relation, _wire, _replica, _checkpoint = replica_pair
    # Establish the typed value while the child and its owner are still live;
    # the actual import/trash sync then records a valid retained payload digest.
    task.metadata['typed_flag'] = 1
    local.store.save_node(task)
    _child, _entry, _owner_entry, remote_child = retained_owner(replica_pair, kind)
    before = export_document(remote, pid)
    document = deepcopy(before)
    section = kind + 's'
    origin = next(iter(document['lifecycle'][section]))
    document['lifecycle'][section][origin].update(state='restored', revision=2)
    task_origin = next(key for key, row in document['nodes'].items() if row['title'] == 'Task')
    document['nodes'][task_origin]['metadata']['typed_flag'] = new_value
    document = validate_document(document)
    owner = owner_payload(remote.store, pid)
    entries = deepcopy(remote.store.list_trash_entries())

    with pytest.raises(ManagementError) as failed, remote.store.transaction():
        _apply(remote, pid, document)

    assert failed.value.code == 'object_in_trash'
    assert owner_payload(remote.store, pid) == owner
    assert remote.store.list_trash_entries() == entries
    assert export_document(remote, pid) == before
    assert remote.store.get_object_lifecycle(kind, remote_child)['state'] == 'trashed'
    assert_hidden(remote, pid)
