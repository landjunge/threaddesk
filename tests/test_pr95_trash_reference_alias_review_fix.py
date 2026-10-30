"""Reference sorting preserves the payload that native Trash hashes/restores."""
from copy import deepcopy

import pytest

from threaddesk.core.errors import ManagementError
from threaddesk.core.models import KnowledgeNode, Relation, new_thread
from threaddesk.services.trash import TrashService, _hash
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=['json', 'sqlite'])
def profile(tmp_path, request):
    store = request.param(tmp_path / 'workspace')
    yield store
    if isinstance(store, SQLiteStore): store.connection.close()


def physical_state(root):
    return {'directories': sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_dir()),
            'files': {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                      for p in root.rglob('*') if p.is_file()}}


def prepared_thread(store, tmp_path, order):
    originals = tmp_path / 'synthetic-originals'; originals.mkdir()
    for name in ('z.txt', 'a.txt'):
        (originals / name).write_bytes(('Retained original ' + name).encode())
    values = ([str(originals / name) for name in ('z.txt', 'a.txt')] if order == 'absolute'
              else ['z.txt', 'a.txt', 'z.txt'] if order == 'duplicates' else ['z.txt', 'a.txt'])
    thread = new_thread('Synthetic original reference order')
    thread.context.files = list(values)
    thread.context.extra['owner_order'] = ['z-last', 'a-first']
    store.save_thread(thread)
    return thread.id, values, originals


@pytest.mark.parametrize('order', ['relative', 'duplicates', 'absolute'])
def test_preview_is_detached_nullwrite_and_native_restore_keeps_exact_original_order(profile, tmp_path, order):
    identity, values, originals = prepared_thread(profile, tmp_path, order)
    service = TrashService(profile)
    before = profile.get_thread(identity).to_dict()
    storage_before = physical_state(profile.root)
    originals_before = physical_state(originals)
    preview = service.preview(kind='thread', object_id=identity)
    assert physical_state(profile.root) == storage_before
    assert preview['object'] == before
    assert preview['object']['context']['files'] == values
    assert preview['references']['external_files_preserved'] == sorted(values)
    assert preview['references']['external_files_preserved'] is not preview['object']['context']['files']
    # Changes to either returned list stay detached from the other and storage.
    preview['references']['external_files_preserved'].append('caller-inventory-only')
    assert preview['object']['context']['files'] == values
    preview['object']['context']['files'].append('caller-payload-only')
    assert 'caller-payload-only' not in preview['references']['external_files_preserved']
    assert profile.get_thread(identity).to_dict() == before
    entry = service.move(kind='thread', object_id=identity, expected_revision=before['revision'],
                         operation_id='unsorted-reference-move')['entry']
    assert entry['object_digest'] == _hash(before)
    assert entry['references']['external_files_preserved'] == sorted(values)
    assert profile.get_thread(identity, include_trashed=True).to_dict() == before
    restore = {'trash_id': entry['trash_id'], 'generation': 1, 'expected_revision': 1,
               'operation_id': 'unsorted-reference-restore'}
    assert service.restore(**restore)['entry']['state'] == 'restored'
    assert profile.get_thread(identity).to_dict() == before
    assert profile.get_thread(identity).context.files == values
    after = physical_state(profile.root)
    assert service.restore(**restore)['duplicate']
    assert physical_state(profile.root) == after
    assert physical_state(originals) == originals_before


def test_immediate_native_restore_works_without_any_prior_preview(profile, tmp_path):
    identity, values, _originals = prepared_thread(profile, tmp_path, 'relative')
    service = TrashService(profile)
    original = profile.get_thread(identity).to_dict()
    entry = service.move(kind='thread', object_id=identity, expected_revision=original['revision'],
                         operation_id='direct-unsorted-move')['entry']
    service.restore(trash_id=entry['trash_id'], generation=1, expected_revision=1, operation_id='direct-unsorted-restore')
    assert profile.get_thread(identity).context.files == values
    assert profile.get_thread(identity).to_dict() == original


@pytest.mark.parametrize('kind', ['node', 'relation'])
def test_node_and_relation_nested_payload_lists_are_not_sorted_and_native_roundtrip_is_unchanged(profile, kind):
    nodes = [KnowledgeNode('z-project', 'project', 'Left', metadata={'owner_order': ['z', 'a']}),
             KnowledgeNode('a-task', 'task', 'Right', metadata={'related_items': ['z', 'a']})]
    for node in nodes: profile.save_node(node)
    relation = Relation('edge', nodes[0].id, nodes[1].id, 'contains', metadata={'owner_order': ['z', 'a']})
    profile.save_relation(relation)
    service = TrashService(profile)
    identity = nodes[0].id if kind == 'node' else relation.id
    original = deepcopy(service._object(kind, identity))
    before = physical_state(profile.root)
    preview = service.preview(kind=kind, object_id=identity)
    assert preview['object'] == original
    assert physical_state(profile.root) == before
    for items in preview['references'].values(): assert items == sorted(items)
    entry = service.move(kind=kind, object_id=identity, expected_revision=original['revision'],
                         operation_id='nested-' + kind + '-move')['entry']
    assert entry['object_digest'] == _hash(original)
    service.restore(trash_id=entry['trash_id'], generation=1, expected_revision=1, operation_id='nested-' + kind + '-restore')
    assert service._object(kind, identity) == original
    assert profile.list_relations()[0].to_dict() == relation.to_dict()


def test_copy_fix_keeps_real_out_of_contract_changes_in_trash_rejected(profile, tmp_path):
    identity, _values, _originals = prepared_thread(profile, tmp_path, 'relative')
    service = TrashService(profile)
    entry = service.move(kind='thread', object_id=identity, expected_revision=profile.get_thread(identity).revision,
                         operation_id='guarded-reference-move')['entry']
    modified = profile.get_thread(identity, include_trashed=True)
    modified.context.files.reverse()  # Actual unauthorized payload edit, not an inventory sort.
    # Bypass the public live-only writer solely to corrupt this private fixture.
    if isinstance(profile, JsonStore):
        import json
        (profile.threads_dir / (identity + '.json')).write_text(json.dumps(modified.to_dict()))
    else:
        profile.connection.execute('UPDATE threads SET payload=? WHERE id=?',
                                   (profile._dump(modified.to_dict()), identity))
        profile.connection.commit()
    before = physical_state(profile.root)
    with pytest.raises(ManagementError) as error:
        service.restore(trash_id=entry['trash_id'], generation=1, expected_revision=1, operation_id='reject-real-reference-change')
    assert error.value.code == 'object_changed_in_trash'
    assert physical_state(profile.root) == before
    assert service.operation_status('reject-real-reference-change')['found'] is False


def test_existing_wrong_legacy_digest_is_not_silently_rewritten_or_accepted(profile, tmp_path):
    identity, _values, _originals = prepared_thread(profile, tmp_path, 'relative')
    service = TrashService(profile)
    # Simulate exactly the old preview-payload alias without changing Source.
    original_preview = service.preview
    def legacy_preview(**kwargs):
        result = original_preview(**kwargs)
        result['object']['context']['files'].sort()
        return result
    service.preview = legacy_preview
    entry = service.move(kind='thread', object_id=identity, expected_revision=profile.get_thread(identity).revision,
                         operation_id='legacy-bad-reference-move')['entry']
    service.preview = original_preview
    before = physical_state(profile.root)
    with pytest.raises(ManagementError) as error:
        service.restore(trash_id=entry['trash_id'], generation=1, expected_revision=1, operation_id='legacy-remains-for-review')
    assert error.value.code == 'object_changed_in_trash'
    assert physical_state(profile.root) == before


def test_related_thread_lists_and_all_reference_inventories_remain_detached(profile, tmp_path):
    identity, values, _originals = prepared_thread(profile, tmp_path, 'relative')
    related = new_thread('Related private model data')
    related.context.extra['organization'] = {'related_thread_ids': ['z-related', identity, 'a-related']}
    profile.save_thread(related)
    before_related = profile.get_thread(related.id).to_dict()
    service = TrashService(profile)
    preview = service.preview(kind='thread', object_id=identity)
    assert preview['references']['threads'] == [related.id]
    for items in preview['references'].values(): items.append('caller-inventory-only')
    assert preview['object']['context']['files'] == values
    assert profile.get_thread(related.id).to_dict() == before_related
    assert profile.get_thread(identity).context.files == values
