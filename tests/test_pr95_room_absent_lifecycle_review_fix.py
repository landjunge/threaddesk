"""A missing room tombstone cannot block unrelated first reception."""
from copy import deepcopy

import pytest
from test_room_sync import _books, _entry, _pair

from threaddesk.core.errors import InvalidState, NotFound
from threaddesk.core.models import Thread, new_thread
from threaddesk.services.trash import TrashService
from threaddesk.services.trash_sync import ROOM_SCHEMA, content_digest
from threaddesk.services.whiteboard_merge import body_hash, merge_whiteboard
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=['json', 'sqlite'])
def desks(tmp_path, request):
    pair = [request.param(tmp_path / name) for name in ('owner', 'peer')]
    yield pair
    for store in pair:
        if isinstance(store, SQLiteStore): store.connection.close()


def new_shared(store, room, title, count=1, cached_hash=False):
    thread = new_thread(title)
    store.save_thread(thread)
    for index in range(count):
        entry = _entry(thread.id, 'entry-' + thread.id + '-' + str(index), title + str(index), room)
        if cached_hash: entry.content_hash = body_hash(entry)
        store.append_whiteboard_entry(entry)
    return thread


def source_trash(store, identity, operation):
    return TrashService(store).move(kind='thread', object_id=identity,
        expected_revision=store.get_thread(identity).revision, operation_id=operation)['entry']


def source_restore(store, entry, operation):
    return TrashService(store).restore(trash_id=entry['trash_id'], generation=entry['generation'],
        expected_revision=entry['revision'], operation_id=operation)


@pytest.mark.parametrize('cached_hash', [False, True], ids=['hash-none', 'hash-set'])
def test_first_hidden_room_thread_defers_then_restore_and_generation_two_recover(desks, cached_hash):
    owner, peer = desks
    books = _books(owner, peer)
    room = _pair(books)
    hidden = new_shared(owner, room, 'Hidden before first sync', count=2, cached_hash=cached_hash)
    other = new_shared(owner, room, 'Unrelated public row')
    first = source_trash(owner, hidden.id, 'source-trash-first')
    assert books['b'].sync()['ok'] is True
    assert peer.get_thread(other.id).title == other.title
    with pytest.raises(NotFound): peer.get_thread(hidden.id, include_trashed=True)
    assert peer.get_object_lifecycle('thread', hidden.id) is None
    assert TrashService(peer).sync_conflicts() == []
    source_restore(owner, first, 'source-restore-first')
    restored_packet = books['a'].export_bundle(room)
    assert books['b'].sync()['ok'] is True
    assert peer.get_thread(hidden.id).title == hidden.title
    assert len(peer.list_whiteboard(hidden.id)) == 2
    current = deepcopy(peer.get_object_lifecycle('thread', hidden.id))
    assert (current['generation'], current['revision'], current['state']) == (1, 2, 'restored')
    histories = deepcopy(peer.list_trash_entries())
    receipts = deepcopy(peer.list_management_operations())
    assert books['b'].apply_bundle(deepcopy(restored_packet))['added'] == 0
    assert peer.list_trash_entries() == histories
    assert peer.list_management_operations() == receipts
    second = source_trash(owner, hidden.id, 'source-trash-second')
    assert second['generation'] == 2
    assert books['b'].sync()['ok'] is True
    assert peer.object_in_trash('thread', hidden.id)
    assert books['b'].apply_bundle(deepcopy(restored_packet))['conflicts'] > 0
    assert peer.get_object_lifecycle('thread', hidden.id)['generation'] == 2
    source_restore(owner, second, 'source-restore-second')
    assert books['b'].sync()['ok'] is True
    assert peer.get_thread(hidden.id).title == hidden.title
    assert (peer.get_object_lifecycle('thread', hidden.id)['generation'],
            peer.get_object_lifecycle('thread', hidden.id)['state']) == (2, 'restored')


def push_to_peer(books, room, packet):
    token = books['b']._peers_for(room)[0]['token']
    return books['b'].serve_push(books['a'].instance_id(), token, packet)


def record(identity, state='restored', generation=1, revision=2, digest='0' * 64):
    return {'thread_id': identity, 'state': state, 'generation': generation,
            'revision': revision, 'content_digest': digest}


def assert_absent(store, identity):
    with pytest.raises(NotFound): store.get_thread(identity, include_trashed=True)
    assert store.get_object_lifecycle('thread', identity) is None
    try: entries = store.list_whiteboard(identity, include_trashed=True)
    except NotFound: entries = []
    assert entries == []


@pytest.mark.parametrize('state', ['trashed', 'restored', 'purged'])
def test_lifecycle_only_genuinely_missing_target_is_deferred_without_becoming_a_scope(desks, state):
    owner, peer = desks
    books = _books(owner, peer); room = _pair(books)
    other = new_shared(owner, room, 'Allowed independent row')
    packet = books['a'].export_bundle(room)
    packet.update(schema=ROOM_SCHEMA, lifecycle=[record('not-yet-received', state,
                                                     revision=1 if state == 'trashed' else 2)])
    first = push_to_peer(books, room, packet)
    assert first == {'ok': True, 'added': 1, 'conflicts': 0}
    assert peer.get_thread(other.id).title == other.title
    assert_absent(peer, 'not-yet-received')
    assert TrashService(peer).sync_conflicts() == []
    assert push_to_peer(books, room, deepcopy(packet))['added'] == 0


@pytest.mark.parametrize('state', ['trashed', 'purged'])
def test_incoming_rows_under_a_missing_tombstone_do_not_create_payloads(desks, state):
    owner, peer = desks
    books = _books(owner, peer); room = _pair(books)
    hidden = new_shared(owner, room, 'Must remain missing')
    other = new_shared(owner, room, 'Allowed independent row')
    packet = books['a'].export_bundle(room)
    packet.update(schema=ROOM_SCHEMA, lifecycle=[record(hidden.id, state, revision=1 if state == 'trashed' else 2)])
    assert push_to_peer(books, room, packet) == {'ok': True, 'added': 1, 'conflicts': 0}
    assert peer.get_thread(other.id).title == other.title
    assert_absent(peer, hidden.id)


@pytest.mark.parametrize('generation', [2, 1000000000])
def test_unknown_higher_restore_is_a_bounded_conflict_without_blocking_other_rows(desks, generation, monkeypatch):
    owner, peer = desks
    books = _books(owner, peer); room = _pair(books)
    missing = new_shared(owner, room, 'Higher unknown history')
    other = new_shared(owner, room, 'Allowed independent row')
    packet = books['a'].export_bundle(room)
    packet.update(schema=ROOM_SCHEMA, lifecycle=[record(missing.id, generation=generation,
                                                       digest=content_digest(owner, missing.id, room))])
    def forbidden(*args, **kwargs): pytest.fail('Higher history must never create a generation loop')
    monkeypatch.setattr(TrashService, '_move_in_transaction', forbidden)
    result = push_to_peer(books, room, packet)
    assert result == {'ok': True, 'added': 1, 'conflicts': 1}
    assert peer.get_thread(other.id).title == other.title
    assert_absent(peer, missing.id)
    assert TrashService(peer).sync_conflicts()[0]['reason'] == 'restore_without_matching_generation'
    receipts = deepcopy(peer.list_management_operations())
    assert push_to_peer(books, room, deepcopy(packet))['added'] == 0
    assert peer.list_management_operations() == receipts


def test_fault_between_real_move_and_restore_rolls_back_initial_payload_and_history_then_retries(desks, monkeypatch):
    owner, peer = desks
    books = _books(owner, peer); room = _pair(books)
    hidden = new_shared(owner, room, 'Atomic fresh restoration', count=2)
    entry = source_trash(owner, hidden.id, 'source-trash')
    source_restore(owner, entry, 'source-restore')
    packet = books['a'].export_bundle(room)
    before = deepcopy(peer.list_management_operations())
    original_restore = TrashService._restore_in_transaction
    def fault(service, **kwargs):
        if service.store is peer:
            assert peer.get_object_lifecycle('thread', hidden.id)['state'] == 'trashed'
            assert len(peer.list_whiteboard(hidden.id, include_trashed=True)) == 2
            raise OSError('Injected failure after actual initial move')
        return original_restore(service, **kwargs)
    with monkeypatch.context() as blocked:
        blocked.setattr(TrashService, '_restore_in_transaction', fault)
        with pytest.raises(OSError, match='actual initial move'):
            push_to_peer(books, room, packet)
    assert_absent(peer, hidden.id)
    assert peer.list_management_operations() == before
    if isinstance(peer, JsonStore):
        assert not (peer.root / 'threads' / (hidden.id + '.json')).exists()
        assert not (peer.root / 'thread-revisions' / (hidden.id + '.json')).exists()
        assert not list((peer.root / 'whiteboard' / hidden.id).glob('*.json'))
    assert push_to_peer(books, room, deepcopy(packet)) == {'ok': True, 'added': 2, 'conflicts': 0}
    assert peer.get_object_lifecycle('thread', hidden.id)['state'] == 'restored'
    assert [row.ordinal for row in peer.list_whiteboard(hidden.id)] == [1, 2]


@pytest.mark.parametrize('local_scope', ['private', 'other-room', 'purged'])
def test_existing_native_or_purged_target_never_becomes_a_new_import_scope(desks, local_scope):
    owner, peer = desks
    books = _books(owner, peer); room = _pair(books)
    target = new_shared(owner, room, 'Incoming claimed target')
    new_shared(owner, room, 'Other incoming public row')
    local = Thread.from_dict(target.to_dict()); local.context.notes = 'Retained local private note'
    peer.save_thread(local)
    peer.append_whiteboard_entry(_entry(target.id, 'local-private-proof', 'Retained local contribution',
                                      'another-room' if local_scope == 'other-room' else None))
    if local_scope == 'purged':
        trash = TrashService(peer)
        entry = source_trash(peer, target.id, 'local-private-trash')
        preview = trash.purge_preview(entry['trash_id'])
        assert preview['blockers'] == []
        trash.purge(trash_id=entry['trash_id'], generation=1, expected_revision=1,
                    reference_digest=preview['reference_digest'], confirmation=preview['confirmation'], operation_id='local-private-purge')
    packet = books['a'].export_bundle(room)
    packet.update(schema=ROOM_SCHEMA, lifecycle=[record(target.id, digest=content_digest(owner, target.id, room))])
    before = {p.relative_to(peer.root).as_posix(): p.read_bytes() for p in peer.root.rglob('*') if p.is_file()}
    for _ in range(2):
        with pytest.raises(InvalidState, match='room_(thread|lifecycle)_scope'):
            push_to_peer(books, room, deepcopy(packet))
        assert {p.relative_to(peer.root).as_posix(): p.read_bytes() for p in peer.root.rglob('*') if p.is_file()} == before
    if local_scope == 'purged':
        assert peer.get_object_lifecycle('thread', target.id)['state'] == 'purged'
        with pytest.raises(NotFound): peer.get_thread(target.id, include_trashed=True)


@pytest.mark.parametrize('bad', ['digest', 'source-private-payload'])
def test_first_restored_import_requires_exact_actual_payload_and_keeps_other_rows(desks, bad):
    owner, peer = desks
    books = _books(owner, peer); room = _pair(books)
    target = new_shared(owner, room, 'Digest constrained source')
    other = new_shared(owner, room, 'Allowed independent row')
    if bad == 'source-private-payload':
        target.context.notes = 'Private notes must never cross a room shell'
        owner.save_thread(target)
    entry = source_trash(owner, target.id, 'source-trash')
    source_restore(owner, entry, 'source-restore')
    packet = books['a'].export_bundle(room)
    if bad == 'digest': packet['lifecycle'][0]['content_digest'] = '0' * 64
    result = push_to_peer(books, room, packet)
    assert result == {'ok': True, 'added': 1, 'conflicts': 1}
    assert peer.get_thread(other.id).title == other.title
    assert_absent(peer, target.id)
    assert TrashService(peer).sync_conflicts()[0]['reason'] == 'concurrent_content_change'


def test_two_initial_restored_threads_share_the_committed_native_workspace_identity(desks):
    owner, peer = desks
    books = _books(owner, peer); room = _pair(books)
    threads = [new_shared(owner, room, 'First fresh target', count=2),
               new_shared(owner, room, 'Second fresh target', count=2, cached_hash=True)]
    for index, thread in enumerate(threads):
        entry = source_trash(owner, thread.id, 'source-trash-' + str(index))
        source_restore(owner, entry, 'source-restore-' + str(index))
    packet = books['a'].export_bundle(room)
    assert push_to_peer(books, room, packet) == {'ok': True, 'added': 4, 'conflicts': 0}
    identity = peer.get_management_operation('lifecycle_workspace_v1')['result']['workspace_id']
    assert all(peer.get_object_lifecycle('thread', thread.id)['workspace_id'] == identity for thread in threads)
    assert len(peer.list_trash_entries()) == 2
    assert push_to_peer(books, room, deepcopy(packet))['added'] == 0


def test_read_only_member_cannot_publish_an_absent_history_to_the_owner(desks):
    owner, peer = desks
    books = _books(owner, peer); room = _pair(books, role='read_only')
    target = new_shared(peer, room, 'Malicious readonly fresh target')
    packet = {'schema': ROOM_SCHEMA, 'room_id': room, 'instance_id': books['b'].instance_id(),
              'entries': [row.to_dict() for row in peer.list_whiteboard(target.id)],
              'threads': [{'id': target.id, 'title': target.title}],
              'lifecycle': [record(target.id, digest=content_digest(peer, target.id, room))]}
    before = deepcopy(owner.list_management_operations())
    with pytest.raises(InvalidState, match='room_forbidden'):
        books['a'].serve_push(books['b'].instance_id(), books['a']._peers_for(room)[0]['token'], packet)
    assert_absent(owner, target.id)
    assert owner.list_management_operations() == before


def test_preexisting_legacy_hash_normalization_stays_a_visible_content_conflict(desks):
    owner, peer = desks
    books = _books(owner, peer); room = _pair(books)
    target = new_shared(owner, room, 'Previously normalized peer')
    peer.save_thread(Thread.from_dict(target.to_dict()))
    original_rows = owner.list_whiteboard(target.id)
    merge_whiteboard(peer, original_rows)  # Existing offline/default enrichment remains unchanged.
    assert original_rows[0].content_hash is None
    cached_before = peer.list_whiteboard(target.id)[0].content_hash
    assert cached_before is not None
    source_trash(owner, target.id, 'source-trash')
    result = push_to_peer(books, room, books['a'].export_bundle(room))
    assert result['ok'] and result['conflicts'] == 1
    assert not peer.object_in_trash('thread', target.id)
    assert peer.list_whiteboard(target.id)[0].content_hash == cached_before
    assert owner.list_whiteboard(target.id, include_trashed=True)[0].content_hash is None
    assert TrashService(peer).sync_conflicts()[0]['reason'] == 'concurrent_content_change'


@pytest.mark.parametrize('cached_hash', [False, True], ids=['hash-none', 'hash-set'])
def test_ordinary_first_receipt_preserves_raw_hash_for_subsequent_native_generations(desks, cached_hash):
    owner, peer = desks
    books = _books(owner, peer); room = _pair(books)
    target = new_shared(owner, room, 'Live first receipt', count=2, cached_hash=cached_hash)
    assert books['b'].sync()['ok'] is True
    assert [row.content_hash for row in peer.list_whiteboard(target.id)] == [
        row.content_hash for row in owner.list_whiteboard(target.id)]
    assert content_digest(owner, target.id, room) == content_digest(peer, target.id, room)
    for generation in (1, 2):
        entry = source_trash(owner, target.id, 'ordinary-source-trash-' + str(generation))
        assert entry['generation'] == generation
        assert books['b'].sync()['ok'] is True
        assert peer.get_object_lifecycle('thread', target.id)['state'] == 'trashed'
        source_restore(owner, entry, 'ordinary-source-restore-' + str(generation))
        packet = books['a'].export_bundle(room)
        assert push_to_peer(books, room, packet)['conflicts'] == 0
        current = deepcopy(peer.get_object_lifecycle('thread', target.id))
        assert (current['generation'], current['state']) == (generation, 'restored')
        before = deepcopy(peer.list_management_operations())
        assert push_to_peer(books, room, deepcopy(packet))['added'] == 0
        assert peer.list_management_operations() == before
        assert peer.get_object_lifecycle('thread', target.id) == current
