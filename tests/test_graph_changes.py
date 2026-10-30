"""Graph invalidation is bounded, read-only and independent of transport writes."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.models import Relation
from threaddesk.services.activity import ActivityService
from threaddesk.services.graph_changes import GraphChangeService
from threaddesk.services.graph_read import GraphReadService
from threaddesk.services.library_batch import LibraryBatchImporter
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=['json', 'sqlite'])
def profile(tmp_path, request):
    store = request.param(tmp_path / 'workspace')
    yield store
    if hasattr(store, 'connection'):
        store.connection.close()


def status(store):
    return GraphReadService(store).change_status(workspace_id='ws-fixture')


def fingerprint(store):
    result = status(store)
    assert result['status'] == 'ready', result
    return result['fingerprint']


def test_node_revision_relations_and_deletion_are_observed(profile):
    service = ThreadService(store=profile)
    first = fingerprint(profile)
    source = service.create_node('project', 'Source')
    target = service.create_node('task', 'Target')
    added = fingerprint(profile)
    assert added != first
    profile.save_node(replace(source, title='Changed', revision=source.revision + 1))
    renamed = fingerprint(profile)
    assert renamed != added
    relation = Relation('relation-first', source.id, target.id, 'contains')
    profile.save_relation(relation)
    linked = fingerprint(profile)
    assert linked != renamed
    # Equal relation counts still detect changed endpoints/kind/revision.
    profile.save_relation(replace(relation, kind='related_to', revision=2))
    assert fingerprint(profile) != linked


def test_import_overlay_and_activity_change_the_signature_without_reading_contents(profile, tmp_path):
    service = ThreadService(store=profile)
    node = service.create_node('project', 'Files')
    initial = fingerprint(profile)
    source = tmp_path / 'originals';source.mkdir()
    (source / 'actual.txt').write_text('Actual original')
    importer = LibraryBatchImporter(profile)
    result = importer.run(importer.manifest_for_folder(source.resolve(), node_id=node.id), operation_id='import')
    identity = result['files'][0]['record_id']
    imported = fingerprint(profile)
    assert imported != initial
    ActivityService(profile).record_open_receipt({'action': 'open', 'operation_id': 'evidence', 'record_id': identity,
        'status': 'launch_requested', 'sha256': 'a' * 64, 'launch_requested_at': '2026-10-27T10:00:00Z'})
    active = fingerprint(profile)
    assert active != imported
    state = profile.workspace_path / 'library-file-state.json'
    state.write_text(json.dumps({'generation': 1}))
    assert fingerprint(profile) != active


def test_unrelated_control_index_and_command_writes_do_not_invalidate(profile):
    library = profile.workspace_path / 'library-files'
    library.mkdir(exist_ok=True)
    first = fingerprint(profile)
    for name in ('graph-view-control.json', 'command-operation-receipts.json', 'graph-views.json'):
        (profile.workspace_path / name).write_text('{"technical":true}')
    (library / 'index.sqlite3').write_bytes(b'derived index')
    (library / 'journal.json').write_text('{"technical":true}')
    if hasattr(profile, 'connection'):
        profile.connection.execute("INSERT OR REPLACE INTO app_state(key,value) VALUES('unrelated-control','1')")
        profile.connection.commit()
    assert fingerprint(profile) == first
    result = status(profile)
    assert result['workspace_id'] == 'ws-fixture'
    assert result['minute'] == result['as_of'][:16]
    assert result['as_of'].endswith('+00:00')
    assert str(profile.workspace_path) not in json.dumps(result)


def test_json_probe_cost_is_constant_and_never_opens_documents(tmp_path, monkeypatch):
    store = JsonStore(tmp_path / 'workspace')
    for index in range(1000):
        (store.nodes_dir / f'{index}.json').write_text('{"fixture":true}')
    before = {path.relative_to(store.workspace_path): path.read_bytes() for path in store.workspace_path.rglob('*') if path.is_file()}
    calls = []
    original = Path.lstat
    def counted(path, *args, **kwargs):
        calls.append(path)
        return original(path, *args, **kwargs)
    def forbidden(*_args, **_kwargs):
        raise AssertionError('Change status must not read documents or enumerate object files')
    with monkeypatch.context() as context:
        context.setattr(Path, 'lstat', counted)
        context.setattr(Path, 'read_text', forbidden)
        context.setattr(Path, 'read_bytes', forbidden)
        context.setattr(Path, 'glob', forbidden)
        assert fingerprint(store) == fingerprint(store)
    assert len(calls) < 100
    after = {path.relative_to(store.workspace_path): path.read_bytes() for path in store.workspace_path.rglob('*') if path.is_file()}
    assert before == after


def test_partial_commit_changing_snapshot_and_symlinks_are_honest(tmp_path, monkeypatch):
    store = JsonStore(tmp_path / 'workspace')
    journal = store.workspace_path / '.management-commit.json'
    journal.write_text('{}')
    assert status(store)['error'] == 'graph_state_changing'
    journal.unlink()
    service = GraphChangeService(store)
    samples = iter([['first'], ['second'], ['third'], ['fourth']])
    monkeypatch.setattr(service, '_files', lambda: next(samples))
    changing = service.status(workspace_id='ws-fixture')
    assert changing['status'] == 'unavailable' and changing['fingerprint'] is None
    outside = tmp_path / 'outside';outside.write_text('preserved')
    (store.workspace_path / 'file-activity.json').symlink_to(outside)
    denied = status(store)
    assert denied['status'] == 'unavailable'
    assert outside.read_text() == 'preserved'


def test_sqlite_migrated_activity_is_visible_and_repeated_reads_are_inert(tmp_path):
    store = SQLiteStore(tmp_path / 'sqlite')
    try:
        initial = fingerprint(store)
        store.save_migrated_owner_documents({'file-activity.json': {'schema_version': 1, 'revision': 4, 'files': {}, 'operations': {}}})
        migrated = fingerprint(store)
        assert migrated != initial
        before = store.connection.total_changes
        assert fingerprint(store) == migrated
        assert store.connection.total_changes == before
    finally:
        store.connection.close()


def test_json_profile_does_not_infer_backend_from_leftover_database(tmp_path):
    store = JsonStore(tmp_path / 'workspace')
    first = fingerprint(store)
    (store.workspace_path / 'threaddesk.sqlite3').write_bytes(b'Old unrelated database')
    assert fingerprint(store) == first
