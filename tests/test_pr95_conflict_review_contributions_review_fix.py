"""Thread lifecycle review covers every contribution hidden by adoption."""
from copy import deepcopy

import pytest
from test_room_sync import _entry
from test_trash_sync import paired_room

from threaddesk.core.errors import ManagementError
from threaddesk.services.trash import TrashService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=['json', 'sqlite'])
def conflict(tmp_path, request):
    pair = [request.param(tmp_path / name) for name in ('owner', 'peer')]
    owner, peer = pair
    books, room, identity = paired_room(pair)
    owner.append_whiteboard_entry(_entry(identity, 'delayed-real-contribution', 'New authenticated room contribution', room))
    delayed = books['a'].export_bundle(room)
    local = peer.get_thread(identity)
    local.context.notes = 'Private concurrent payload retained'
    peer.save_thread(local)
    TrashService(owner).move(kind='thread', object_id=identity, expected_revision=owner.get_thread(identity).revision,
                             operation_id='source-native-trash')
    token = books['b']._peers_for(room)[0]['token']
    initial = books['b'].serve_push(books['a'].instance_id(), token, books['a'].export_bundle(room))
    assert initial['conflicts'] == 1
    service = TrashService(peer)
    review = service.sync_conflicts()[0]
    yield owner, peer, books, room, identity, delayed, review
    for store in pair:
        if isinstance(store, SQLiteStore): store.connection.close()


def push_delayed(books, room, packet):
    token = books['b']._peers_for(room)[0]['token']
    return books['b'].serve_push(books['a'].instance_id(), token, deepcopy(packet))


def state(store, identity):
    return {'thread': store.get_thread(identity, include_trashed=True).to_dict(),
            'board': [row.to_dict() for row in store.list_whiteboard(identity, include_trashed=True)],
            'trash': deepcopy(store.list_trash_entries()), 'receipts': deepcopy(store.list_management_operations())}


@pytest.mark.parametrize('choice', ['keep_local', 'adopt_incoming'])
def test_delayed_authenticated_contribution_invalidates_old_review_without_receipt_then_fresh_review_works(conflict, choice):
    _owner, peer, books, room, identity, delayed, review = conflict
    service = TrashService(peer)
    before_thread = peer.get_thread(identity).to_dict()
    assert push_delayed(books, room, delayed) == {'ok': True, 'added': 1, 'conflicts': 0}
    assert peer.get_thread(identity).to_dict() == before_thread
    before = state(peer, identity)
    physical_before = {p.relative_to(peer.root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                       for p in peer.root.rglob('*') if p.is_file()}
    request = {'conflict_id': review['operation_id'], 'expected_object_digest': review['expected_object_digest'],
               'choice': choice, 'operation_id': 'explicit-review-decision'}
    with pytest.raises(ManagementError) as stale:
        service.resolve_sync_conflict(**request)
    assert stale.value.code == 'revision_conflict'
    assert state(peer, identity) == before
    assert {p.relative_to(peer.root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in peer.root.rglob('*') if p.is_file()} == physical_before
    fresh = service.sync_conflicts()[0]
    assert fresh['expected_object_digest'] != review['expected_object_digest']
    request['expected_object_digest'] = fresh['expected_object_digest']
    assert service.resolve_sync_conflict(**request)['state'] == 'resolved'
    assert peer.object_in_trash('thread', identity) is (choice == 'adopt_incoming')
    assert [row.id for row in peer.list_whiteboard(identity, include_trashed=True)] == ['shared1', 'delayed-real-contribution']
    after = state(peer, identity)
    assert service.resolve_sync_conflict(**request)['duplicate']
    assert state(peer, identity) == after


@pytest.mark.parametrize('room_scope', [None, 'another-retained-room'], ids=['private', 'other-room'])
def test_all_contributions_hidden_by_thread_trash_require_a_fresh_review(conflict, room_scope):
    _owner, peer, _books, _room, identity, _delayed, review = conflict
    before_thread = peer.get_thread(identity).to_dict()
    row = _entry(identity, 'new-private-or-other-room', 'Separate retained source', room_scope)
    peer.append_whiteboard_entry(row)
    assert peer.get_thread(identity).to_dict() == before_thread
    before = state(peer, identity)
    service = TrashService(peer)
    with pytest.raises(ManagementError) as error:
        service.resolve_sync_conflict(conflict_id=review['operation_id'], expected_object_digest=review['expected_object_digest'],
                                      choice='adopt_incoming', operation_id='private-review')
    assert error.value.code == 'revision_conflict'
    assert state(peer, identity) == before


def test_staged_new_contribution_is_checked_inside_native_transaction_and_rolls_back(conflict, monkeypatch):
    _owner, peer, _books, room, identity, _delayed, review = conflict
    service = TrashService(peer)
    before = state(peer, identity)
    native = service._operation
    def staged_operation(operation_id, request, apply):
        def staged_apply():
            peer.append_whiteboard_entry(_entry(identity, 'staged-after-review', 'Pending native row', room))
            return apply()
        return native(operation_id, request, staged_apply)
    monkeypatch.setattr(service, '_operation', staged_operation)
    with pytest.raises(ManagementError) as error:
        service.resolve_sync_conflict(conflict_id=review['operation_id'], expected_object_digest=review['expected_object_digest'],
                                      choice='adopt_incoming', operation_id='staged-review')
    assert error.value.code == 'revision_conflict'
    assert state(peer, identity) == before
    assert service.operation_status('staged-review')['found'] is False


def test_digest_is_independent_of_store_enumeration_order_and_keeps_trashed_contributions(conflict, monkeypatch):
    _owner, peer, books, room, identity, delayed, _review = conflict
    push_delayed(books, room, delayed)
    service = TrashService(peer)
    original_list = peer.list_whiteboard
    fresh = service.sync_conflicts()[0]
    monkeypatch.setattr(peer, 'list_whiteboard', lambda *a, **kw: list(reversed(original_list(*a, **kw))))
    assert service.sync_conflicts()[0]['expected_object_digest'] == fresh['expected_object_digest']
    entry = service.move(kind='thread', object_id=identity, expected_revision=peer.get_thread(identity).revision,
                         operation_id='separate-local-trash')['entry']
    trashed = service.sync_conflicts()[0]
    assert trashed['expected_object_digest'] == fresh['expected_object_digest']
    assert len(original_list(identity, include_trashed=True)) == 2
    service.restore(trash_id=entry['trash_id'], generation=1, expected_revision=1, operation_id='separate-local-restore')
    assert service.sync_conflicts()[0]['expected_object_digest'] == fresh['expected_object_digest']


def test_completed_review_replays_after_restore_and_later_contribution_without_hiding_again(conflict):
    _owner, peer, books, room, identity, delayed, _review = conflict
    push_delayed(books, room, delayed)
    service = TrashService(peer)
    fresh = service.sync_conflicts()[0]
    request = {'conflict_id': fresh['operation_id'], 'expected_object_digest': fresh['expected_object_digest'],
               'choice': 'adopt_incoming', 'operation_id': 'completed-explicit-review'}
    service.resolve_sync_conflict(**request)
    entry = peer.get_object_lifecycle('thread', identity)
    service.restore(trash_id=entry['trash_id'], generation=entry['generation'], expected_revision=entry['revision'],
                    operation_id='owner-restores-after-adoption')
    peer.append_whiteboard_entry(_entry(identity, 'new-after-completed-review', 'New live generation content', room))
    before = state(peer, identity)
    assert service.resolve_sync_conflict(**request)['duplicate']
    assert state(peer, identity) == before
    assert not peer.object_in_trash('thread', identity)


def test_unrelated_thread_and_graph_edits_do_not_invalidate_review_or_receive_lifecycle(conflict):
    from threaddesk.core.models import KnowledgeNode, Relation, new_thread

    _owner, peer, _books, _room, _identity, _delayed, review = conflict
    other = new_thread('Unrelated private thread'); peer.save_thread(other)
    peer.append_whiteboard_entry(_entry(other.id, 'unrelated-row', 'Separate private row', None))
    peer.save_node(KnowledgeNode('unrelated-project', 'project', 'Unrelated project'))
    peer.save_node(KnowledgeNode('unrelated-task', 'task', 'Unrelated task'))
    relation = Relation('unrelated-relation', 'unrelated-project', 'unrelated-task', 'contains')
    peer.save_relation(relation)
    service = TrashService(peer)
    assert service.sync_conflicts()[0]['expected_object_digest'] == review['expected_object_digest']
    service.resolve_sync_conflict(conflict_id=review['operation_id'], expected_object_digest=review['expected_object_digest'],
                                  choice='adopt_incoming', operation_id='review-only-target')
    assert peer.get_thread(other.id).title == other.title
    assert peer.list_whiteboard(other.id)[0].id == 'unrelated-row'
    assert {n.id for n in peer.list_nodes()} == {'unrelated-project', 'unrelated-task'}
    assert peer.list_relations()[0].to_dict() == relation.to_dict()
    assert peer.get_object_lifecycle('thread', other.id) is None
    assert peer.get_object_lifecycle('node', 'unrelated-task') is None
    assert peer.get_object_lifecycle('relation', relation.id) is None


def test_thread_adoption_and_restore_preserve_owned_node_relation_payloads_and_native_lifecycles(conflict):
    from threaddesk.core.models import KnowledgeNode, Relation

    _owner, peer, books, room, identity, delayed, _review = conflict
    project = KnowledgeNode('owned-project', 'project', 'Owned source', metadata={'thread_id': identity})
    outside = KnowledgeNode('outside-task', 'task', 'Independent target')
    relation = Relation('retained-edge', project.id, outside.id, 'contains')
    peer.save_node(project); peer.save_node(outside); peer.save_relation(relation)
    before_nodes = {node.id: node.to_dict() for node in peer.list_nodes(include_trashed=True)}
    before_edges = [edge.to_dict() for edge in peer.list_relations(include_trashed=True)]
    push_delayed(books, room, delayed)
    service = TrashService(peer); fresh = service.sync_conflicts()[0]
    service.resolve_sync_conflict(conflict_id=fresh['operation_id'], expected_object_digest=fresh['expected_object_digest'],
                                  choice='adopt_incoming', operation_id='graph-safe-review')
    assert {node.id for node in peer.list_nodes()} == {outside.id}
    assert peer.list_relations() == []
    assert {node.id: node.to_dict() for node in peer.list_nodes(include_trashed=True)} == before_nodes
    assert [edge.to_dict() for edge in peer.list_relations(include_trashed=True)] == before_edges
    assert peer.get_object_lifecycle('node', project.id) is None
    assert peer.get_object_lifecycle('relation', relation.id) is None
    entry = peer.get_object_lifecycle('thread', identity)
    service.restore(trash_id=entry['trash_id'], generation=1, expected_revision=1, operation_id='restore-reviewed-graph-owner')
    assert {node.id: node.to_dict() for node in peer.list_nodes()} == before_nodes
    assert [edge.to_dict() for edge in peer.list_relations()] == before_edges
    assert len(peer.list_whiteboard(identity)) == 2


def test_missing_original_keeps_existing_purged_lifecycle_digest_fallback(conflict):
    from threaddesk.core.models import new_thread
    from threaddesk.services.trash import _hash
    from threaddesk.services.trash_sync import record_conflict

    _owner, peer, _books, room, _identity, _delayed, _review = conflict
    target = new_thread('Separate synthetic local purge'); peer.save_thread(target)
    service = TrashService(peer)
    entry = service.move(kind='thread', object_id=target.id, expected_revision=target.revision,
                         operation_id='separate-target-trash')['entry']
    preview = service.purge_preview(entry['trash_id'])
    service.purge(trash_id=entry['trash_id'], generation=1, expected_revision=1,
                  reference_digest=preview['reference_digest'], confirmation=preview['confirmation'], operation_id='separate-target-purge')
    record_conflict(peer, thread_id=target.id, source='room:' + room, reason='remote_purge_requires_local_review',
                    incoming={'thread_id': target.id, 'state': 'purged', 'generation': 1})
    item = next(row for row in service.sync_conflicts() if row['thread_id'] == target.id)
    assert item['expected_object_digest'] == _hash(peer.get_object_lifecycle('thread', target.id))
    assert service.resolve_sync_conflict(conflict_id=item['operation_id'], expected_object_digest=item['expected_object_digest'],
                                         choice='keep_local', operation_id='keep-purged-local')['state'] == 'resolved'
    assert peer.get_object_lifecycle('thread', target.id)['state'] == 'purged'


def test_public_mcp_stale_error_preserves_domain_state_but_retains_existing_global_command_failure(conflict):
    from threaddesk.api.service import ThreadService
    from threaddesk.services.commands import CommandApplication
    from threaddesk.services.mcp import McpBridge

    _owner, peer, books, room, identity, delayed, review = conflict
    push_delayed(books, room, delayed)
    before = state(peer, identity)
    application = CommandApplication(ThreadService(peer))
    request = {'version': 1, 'workspace_id': application.workspace_id, 'command': 'trash.resolve_sync_conflict',
               'operation_id': 'public-stale-review', 'arguments': {'conflict_id': review['operation_id'],
                 'expected_object_digest': review['expected_object_digest'], 'choice': 'adopt_incoming'}}
    response = McpBridge(application.service).call('command_invoke', request)
    assert response['ok'] is False and response['code'] == 'revision_conflict'
    after = state(peer, identity)
    assert {k: v for k, v in after.items() if k != 'receipts'} == {k: v for k, v in before.items() if k != 'receipts'}
    assert [r for r in after['receipts'] if r.get('kind') != 'command'] == before['receipts']
    assert application.operation('public-stale-review')['state'] == 'failed'
    assert not peer.object_in_trash('thread', identity)
