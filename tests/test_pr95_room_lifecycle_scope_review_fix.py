"""Room lifecycle mutations require preexisting local room ownership."""
from copy import deepcopy

import pytest
from test_room_sync import _books, _entry, _pair

from threaddesk.core.errors import InvalidState
from threaddesk.core.models import new_thread
from threaddesk.services.trash import TrashService
from threaddesk.services.trash_sync import ROOM_SCHEMA, content_digest
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=['json', 'sqlite'])
def desks(tmp_path, request):
    values = [request.param(tmp_path / name) for name in ('owner', 'peer')]
    yield values
    for store in values:
        if isinstance(store, SQLiteStore):
            store.connection.close()


def inventory(store):
    return {path.relative_to(store.root).as_posix(): path.read_bytes()
            for path in store.root.rglob('*') if path.is_file()}


def packet(books, room_id, rows, entries=None):
    return {'schema': ROOM_SCHEMA, 'room_id': room_id,
            'instance_id': books['b'].instance_id(), 'entries': entries or [],
            'threads': [], 'lifecycle': rows}


def push(books, room_id, bundle):
    token = books['a']._peers_for(room_id)[0]['token']
    return books['a'].serve_push(books['b'].instance_id(), token, bundle)


def lifecycle(store, thread_id, room_id, state='trashed', generation=1):
    return {'thread_id': thread_id, 'generation': generation, 'revision': 1,
            'state': state, 'content_digest': content_digest(store, thread_id, room_id)}


def thread_with_entry(store, name, room_id):
    thread = new_thread(name)
    store.save_thread(thread)
    store.append_whiteboard_entry(_entry(thread.id, 'entry-' + thread.id, name + ' bytes', room_id))
    return thread.id


@pytest.mark.parametrize('history', ['live', 'trashed', 'restored'])
@pytest.mark.parametrize('incoming_state', ['trashed', 'restored', 'purged'])
@pytest.mark.parametrize('foreign_room', [None, 'unrelated-room'])
@pytest.mark.parametrize('forge_bundle_contribution', [False, True])
def test_authenticated_foreign_thread_lifecycle_rejected_without_writes(
        desks, history, incoming_state, foreign_room, forge_bundle_contribution):
    owner, peer = desks
    books = _books(owner, peer)
    room_id = _pair(books)
    identity = thread_with_entry(owner, 'Private unrelated original', foreign_room)
    service = TrashService(owner)
    if history != 'live':
        entry = service.move(kind='thread', object_id=identity,
                             expected_revision=owner.get_thread(identity).revision,
                             operation_id='private-local-trash')['entry']
        if history == 'restored':
            service.restore(trash_id=entry['trash_id'], generation=1,
                            expected_revision=entry['revision'], operation_id='private-local-restore')
    # The trashed case even uses the existing matching state/generation: scope
    # authorization must precede the duplicate shortcut.
    generation = 2 if history == 'restored' else 1
    row = lifecycle(owner, identity, room_id, state=incoming_state, generation=generation)
    entries = [_entry(identity, 'forged-room-contribution', 'Untrusted room proof', room_id).to_dict()] if forge_bundle_contribution else []
    malicious = packet(books, room_id, [row], entries)
    before = inventory(owner)
    for _ in range(2):
        code = 'room_thread_scope' if forge_bundle_contribution else 'room_lifecycle_scope'
        with pytest.raises(InvalidState, match=code):
            push(books, room_id, malicious)
        assert inventory(owner) == before
        assert not any(e.room_id == room_id for e in owner.list_whiteboard(identity, include_trashed=True))


@pytest.mark.parametrize('foreign_first', [False, True])
def test_mixed_bundle_preflights_every_lifecycle_target_before_any_write(desks, foreign_first):
    owner, peer = desks
    books = _books(owner, peer)
    room_id = _pair(books)
    shared = thread_with_entry(owner, 'Owned room original', room_id)
    private = thread_with_entry(owner, 'Private original', None)
    rows = [lifecycle(owner, shared, room_id), lifecycle(owner, private, room_id)]
    if foreign_first:
        rows.reverse()
    before = inventory(owner)
    with pytest.raises(InvalidState, match='room_lifecycle_scope'):
        push(books, room_id, packet(books, room_id, rows))
    assert inventory(owner) == before
    assert owner.list_trash_entries() == []
    assert owner.list_management_operations() == []


def test_unknown_target_cannot_be_authorized_by_incoming_room_entry(desks):
    owner, peer = desks
    books = _books(owner, peer)
    room_id = _pair(books)
    row = {'thread_id': 'unknown-private-thread', 'generation': 1, 'revision': 1,
           'state': 'restored', 'content_digest': '0' * 64}
    entry = _entry(row['thread_id'], 'forged-room-proof', 'Incoming contribution', room_id).to_dict()
    before = inventory(owner)
    with pytest.raises(InvalidState, match='room_lifecycle_scope'):
        push(books, room_id, packet(books, room_id, [row], [entry]))
    assert inventory(owner) == before


def test_authenticated_owned_history_trash_restore_generation_and_exact_replay(desks):
    owner, peer = desks
    books = _books(owner, peer)
    room_id = _pair(books)
    identity = thread_with_entry(owner, 'Room original', room_id)
    original = deepcopy(owner.get_thread(identity).to_dict())
    whiteboard = [e.to_dict() for e in owner.list_whiteboard(identity)]
    trash_row = lifecycle(owner, identity, room_id)
    assert push(books, room_id, packet(books, room_id, [trash_row]))['conflicts'] == 0
    assert owner.object_in_trash('thread', identity)

    before = inventory(owner)
    assert push(books, room_id, packet(books, room_id, [trash_row]))['conflicts'] == 0
    assert inventory(owner) == before
    # These contributions are hidden by the thread tombstone, yet their
    # retained ownership must still permit an authenticated matching restore.
    restore_row = {**trash_row, 'state': 'restored', 'revision': 2}
    assert push(books, room_id, packet(books, room_id, [restore_row]))['conflicts'] == 0
    assert not owner.object_in_trash('thread', identity)
    assert owner.get_thread(identity).title == original['title']
    assert [e.to_dict() for e in owner.list_whiteboard(identity)] == whiteboard
    before = inventory(owner)
    assert push(books, room_id, packet(books, room_id, [restore_row]))['conflicts'] == 0
    assert inventory(owner) == before
    second = lifecycle(owner, identity, room_id, generation=2)
    assert push(books, room_id, packet(books, room_id, [second]))['conflicts'] == 0
    assert owner.get_object_lifecycle('thread', identity)['generation'] == 2
    # A stale restore stays a conflict, without reviving the newer generation.
    assert push(books, room_id, packet(books, room_id, [restore_row]))['conflicts'] == 1
    assert owner.object_in_trash('thread', identity)


@pytest.mark.parametrize('foreign_room', [None, 'unrelated-room'])
@pytest.mark.parametrize('schema', ['threaddesk.room.v1', ROOM_SCHEMA])
def test_two_step_room_contribution_injection_then_lifecycle_is_blocked(desks, foreign_room, schema):
    owner, peer = desks
    books = _books(owner, peer)
    room_id = _pair(books)
    identity = thread_with_entry(owner, 'Private original', foreign_room)
    injection = _entry(identity, 'injected-room-proof', 'Untrusted contribution', room_id).to_dict()
    first = packet(books, room_id, [], [injection])
    first['schema'] = schema
    if schema != ROOM_SCHEMA:
        first.pop('lifecycle')
    # Arbitrary bundle titles are not ownership evidence either.
    first['threads'] = [{'id': identity, 'title': 'Room-owned title claim'}]
    before = inventory(owner)
    with pytest.raises(InvalidState, match='room_thread_scope'):
        push(books, room_id, first)
    assert inventory(owner) == before
    second = packet(books, room_id, [lifecycle(owner, identity, room_id)])
    with pytest.raises(InvalidState, match='room_lifecycle_scope'):
        push(books, room_id, second)
    assert inventory(owner) == before
    assert not owner.object_in_trash('thread', identity)


@pytest.mark.parametrize('private_first', [False, True])
def test_mixed_content_preflight_precedes_shell_and_owned_lifecycle_changes(desks, private_first):
    owner, peer = desks
    books = _books(owner, peer)
    room_id = _pair(books)
    shared = thread_with_entry(owner, 'Shared original', room_id)
    private = thread_with_entry(owner, 'Private original', None)
    rows = [_entry('new-remote-room-thread', 'remote-new-entry', 'New room bytes', room_id).to_dict(),
            _entry(private, 'injected-room-proof', 'Injected proof', room_id).to_dict()]
    if private_first:
        rows.reverse()
    before = inventory(owner)
    with pytest.raises(InvalidState, match='room_thread_scope'):
        push(books, room_id, packet(books, room_id, [lifecycle(owner, shared, room_id)], rows))
    assert inventory(owner) == before
    assert owner.list_trash_entries() == []


@pytest.mark.parametrize('schema', ['threaddesk.room.v1', ROOM_SCHEMA])
def test_new_remote_room_thread_shell_and_later_owned_lifecycle_remain_allowed(desks, schema):
    owner, peer = desks
    books = _books(owner, peer)
    room_id = _pair(books)
    identity = 'new-remote-room-thread'
    entry = _entry(identity, 'remote-room-entry', 'Legitimate remote bytes', room_id).to_dict()
    bundle = packet(books, room_id, [], [entry])
    bundle['schema'] = schema
    bundle['threads'] = [{'id': identity, 'title': 'New room thread'}]
    if schema != ROOM_SCHEMA:
        bundle.pop('lifecycle')
    assert push(books, room_id, bundle) == {'ok': True, 'added': 1, 'conflicts': 0}
    assert owner.get_thread(identity).title == 'New room thread'
    assert owner.list_whiteboard(identity)[0].id == entry['id']
    assert push(books, room_id, bundle) == {'ok': True, 'added': 0, 'conflicts': 0}
    trash_row = lifecycle(owner, identity, room_id)
    assert push(books, room_id, packet(books, room_id, [trash_row]))['conflicts'] == 0
    assert owner.object_in_trash('thread', identity)
    assert push(books, room_id, packet(books, room_id, [{**trash_row, 'state': 'restored', 'revision': 2}]))['conflicts'] == 0
    assert owner.get_thread(identity).title == 'New room thread'
    assert owner.list_whiteboard(identity)[0].id == entry['id']


@pytest.mark.parametrize('legacy_shape', ['missing-anchor', 'divergent-anchor', 'legacy-source'])
@pytest.mark.parametrize('target_case', ['private-content', 'mixed-content', 'mixed-lifecycle'])
def test_json_legacy_scope_rejection_rolls_back_all_observation_writes(tmp_path, legacy_shape, target_case):
    import json

    owner, peer = JsonStore(tmp_path / 'owner'), JsonStore(tmp_path / 'peer')
    books = _books(owner, peer)
    room_id = _pair(books)
    for identity, room in [('a-owned-original', room_id), ('z-private-original', None)]:
        thread = new_thread(identity)
        thread.id = identity
        owner.save_thread(thread)
        owner.append_whiteboard_entry(_entry(identity, 'original-' + identity, identity + ' bytes', room))
    private_row = _entry('z-private-original', 'incoming-private', 'Injected proof', room_id).to_dict()
    owned_row = _entry('a-owned-original', 'incoming-owned', 'Allowed room bytes', room_id).to_dict()
    entries = [private_row] if target_case == 'private-content' else [owned_row, private_row]
    records = []
    if target_case == 'mixed-lifecycle':
        entries = [owned_row]
        records = [lifecycle(owner, 'z-private-original', room_id)]
    bundle = packet(books, room_id, records, entries)
    # Force get_thread to stage real normalizations for both targets. A sorted
    # preflight observes the allowed target before the foreign content/lifecycle
    # target in the mixed cases, so rollback must encompass ALL scope checks.
    for identity in ('a-owned-original', 'z-private-original'):
        anchor = owner.root / 'thread-revisions' / (identity + '.json')
        source = owner.root / 'threads' / (identity + '.json')
        if legacy_shape == 'missing-anchor':
            anchor.unlink()
        elif legacy_shape == 'divergent-anchor':
            value = json.loads(anchor.read_text())
            value.update(revision=10, content_hash='0' * 64)
            anchor.write_text(json.dumps(value))
        else:
            value = json.loads(source.read_text())
            value.pop('revision')
            source.write_text(json.dumps(value))
    before = {path.relative_to(owner.root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
              for path in owner.root.rglob('*') if path.is_file()}
    error = 'room_lifecycle_scope' if target_case == 'mixed-lifecycle' else 'room_thread_scope'
    for _ in range(2):
        with pytest.raises(InvalidState, match=error):
            push(books, room_id, bundle)
        after = {path.relative_to(owner.root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                 for path in owner.root.rglob('*') if path.is_file()}
        assert after == before
        assert owner.list_management_operations() == []
        assert owner.list_trash_entries() == []
