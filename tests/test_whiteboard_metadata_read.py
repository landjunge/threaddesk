"""Metadata and selected-content reads use isolated stores, never a live profile."""
import hashlib
import json

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.core.models import WhiteboardEntry
from threaddesk.services.commands import CommandApplication
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore])
def board(tmp_path, request):
    store = request.param(tmp_path / 'workspace')
    service = ThreadService(store)
    thread = service.create('Metadata fixture')
    # Filenames/IDs and ordinals deliberately disagree with timestamp order.
    for identity, stamp, ordinal in [('z', '03', 1), ('b', '01', 3), ('a', '01', 3), ('c', '02', 2)]:
        store.append_whiteboard_entry(WhiteboardEntry(
            id=identity, thread_id=thread.id, actor='Operator 雪 🐈', actor_type='human',
            created_at='2026-11-14T10:00:' + stamp, ordinal=ordinal,
            entry_type='note', content='Geheim 雪 🐈 ' * 600,
            task_id='task-1', run_id='run-1', external_key='key-' + identity,
            content_hash=hashlib.sha256(identity.encode()).hexdigest(),
            metadata={'return_id': 'return-1', 'job_id': 'job-1',
                      'whiteboard_edit': {'entry_id': 'old', 'previous_entry_id': 'previous'},
                      'incoming': {'content': 'NESTED SECRET'}}))
    app = CommandApplication(service)
    yield app, thread.id
    if isinstance(store, SQLiteStore):
        store.connection.close()


def read(app, identity, **args):
    return app.call({'version': 1, 'workspace_id': app.workspace_id,
                     'command': 'whiteboard.list', 'arguments': {'id': identity, **args}})


def unpack(app, identity, args, response):
    if 'result' in response:
        return response['result']
    assert len(response['result_page'].encode()) <= app.result_budget
    chunks = [response['result_page']]
    digest = response['result_digest']
    while response['next_offset'] is not None:
        response = app.call({'version': 1, 'workspace_id': app.workspace_id,
            'command': 'whiteboard.list', 'arguments': {'id': identity, **args},
            'result_offset': response['next_offset'], 'result_digest': digest})
        assert len(response['result_page'].encode()) <= app.result_budget
        assert len(json.dumps(response, ensure_ascii=False).encode()) < 30000
        chunks.append(response['result_page'])
    return json.loads(''.join(chunks))


def test_default_metadata_and_selected_content(board, monkeypatch):
    app, identity = board
    full = unpack(app, identity, {}, read(app, identity))
    assert [row['id'] for row in full['items']] == ['a', 'b', 'c', 'z']
    explicit = unpack(app, identity, {'metadata_only': False}, read(app, identity, metadata_only=False))
    assert explicit == full
    monkeypatch.setattr(app.store, 'list_whiteboard', lambda *a, **k: pytest.fail('full log loaded'))
    result = read(app, identity, metadata_only=True)['result']
    assert result['total'] == 4 and result['next_offset'] is None
    assert [r['id'] for r in result['items']] == [r['id'] for r in full['items']]
    assert 'Geheim' not in json.dumps(result) and 'NESTED SECRET' not in json.dumps(result)
    for meta, original in zip(result['items'], full['items']):
        assert 'content' not in meta
        for key in ('ordinal', 'entry_type', 'content_hash', 'task_id', 'run_id', 'external_key'):
            assert meta[key] == original[key]
        assert meta['metadata']['return_id'] == 'return-1'
        assert meta['metadata']['whiteboard_edit']['entry_id'] == 'old'
        selected = unpack(app, identity, {'entry_id': meta['id']}, read(app, identity, entry_id=meta['id']))
        assert selected == {'items': [original], 'total': 1, 'next_offset': None}


@pytest.mark.parametrize('offset,limit,ids,next_offset', [(0, 2, ['a', 'b'], 2),
    (2, 2, ['c', 'z'], None), (4, 2, [], None), (1, 1, ['b'], 2)])
def test_metadata_page_boundaries(board, offset, limit, ids, next_offset):
    app, identity = board
    result = read(app, identity, metadata_only=True, offset=offset, limit=limit)['result']
    assert [r['id'] for r in result['items']] == ids
    assert (result['total'], result['next_offset']) == (4, next_offset)


def test_metadata_unicode_result_budget_and_digest(board):
    app, identity = board
    app.result_budget = 700
    args = {'metadata_only': True, 'limit': 3}
    first = read(app, identity, **args)
    assert 'result_page' in first
    result = unpack(app, identity, args, first)
    assert len(result['items']) == 3
    assert 'content' not in result['items'][0]
    changed = {**args, 'offset': 1}
    with pytest.raises(ManagementError) as error:
        app.call({'version': 1, 'workspace_id': app.workspace_id, 'command': 'whiteboard.list',
            'arguments': {'id': identity, **changed}, 'result_offset': 1,
            'result_digest': first['result_digest']})
    assert error.value.code == 'result_changed'


@pytest.mark.parametrize('args', [{'metadata_only': 'true'}, {'entry_id': '../a'}])
def test_new_fields_reject_invalid_values(board, args):
    app, identity = board
    with pytest.raises(ManagementError) as error:
        read(app, identity, **args)
    assert error.value.code == 'validation_error'


def test_missing_selected_entry_is_an_empty_page(board):
    app, identity = board
    assert read(app, identity, entry_id='missing')['result'] == {
        'items': [], 'total': 0, 'next_offset': None}


def test_sqlite_projects_and_limits_before_loading_payload(board, monkeypatch):
    app, identity = board
    if not isinstance(app.store, SQLiteStore):
        return
    statements, loaded = [], []
    original = app.store._load

    def observe(row):
        data = original(row)
        if 'thread_id' in data and 'entry_type' in data:
            assert 'content' not in data
            assert 'incoming' not in data.get('metadata', {})
            loaded.append(data['id'])
        return data

    monkeypatch.setattr(app.store, '_load', observe)
    app.store.connection.set_trace_callback(statements.append)
    try:
        result = read(app, identity, metadata_only=True, limit=1, offset=1)['result']
    finally:
        app.store.connection.set_trace_callback(None)
    assert loaded == ['b'] and result['items'][0]['id'] == 'b'
    assert any('json_remove(payload' in sql and 'LIMIT 1 OFFSET 1' in sql for sql in statements)


def test_transaction_staged_reads_and_backdated_append(board):
    app, identity = board
    original = read(app, identity, metadata_only=True, limit=1)
    with app.store.transaction():
        app.store.append_whiteboard_entry(WhiteboardEntry(
            id='backdated', thread_id=identity, actor='Operator', actor_type='human',
            created_at='2020-01-01', entry_type='note', content='Later append, earlier time'))
        selected = read(app, identity, metadata_only=True, entry_id='backdated')['result']
        assert selected['items'][0]['content_hash'] is None
        assert selected['total'] == 1
    # Offset traversal has no snapshot: the earlier page moves on backdated append.
    current = read(app, identity, metadata_only=True, limit=1)
    assert current['result']['items'][0]['id'] == 'backdated'
    assert original['result_digest'] != current['result_digest']
    assert read(app, identity, metadata_only=True, offset=1, limit=1)['result']['items'][0]['id'] == 'a'


@pytest.mark.parametrize('value', [True, False, 0, 1, -1, 1.0, 0.0, -0.0, -0.25,
    2**63, -(2**63) - 1, 'true', '1', '', '雪 🐈', None, ['ref'], {'content': 'secret'}])
def test_reference_scalar_types_and_supersedes_parity(board, value):
    app, identity = board
    # Exercise every whitelisted path, including nested correction references.
    metadata = {key: value for key in (
        'return_id', 'job_id', 'event_id', 'handoff_revision', 'supersedes_entry_id')}
    metadata['whiteboard_edit'] = {'entry_id': value, 'previous_entry_id': value}
    app.store.append_whiteboard_entry(WhiteboardEntry(
        id='typed-ref', thread_id=identity, actor='Operator', actor_type='human',
        created_at='2026-11-14', entry_type='note', content='Private content', metadata=metadata))
    args = {'entry_id': 'typed-ref'}
    full = read(app, identity, **args)['result']['items'][0]
    explicit_full = read(app, identity, metadata_only=False, **args)['result']['items'][0]
    # JSON encodings distinguish bool/int and int/float, unlike Python equality.
    assert json.dumps(full['metadata'], sort_keys=True) == json.dumps(metadata, sort_keys=True)
    assert json.dumps(explicit_full, sort_keys=True) == json.dumps(full, sort_keys=True)
    result = read(app, identity, metadata_only=True, **args)['result']['items'][0]
    if value is None or isinstance(value, (list, dict)):
        assert result['metadata'] == {}
    else:
        assert json.dumps(result['metadata'], sort_keys=True) == json.dumps(metadata, sort_keys=True)
        for key in ('return_id', 'job_id', 'event_id', 'handoff_revision', 'supersedes_entry_id'):
            assert type(result['metadata'][key]) is type(value)
        assert type(result['metadata']['whiteboard_edit']['entry_id']) is type(value)
        assert type(result['metadata']['whiteboard_edit']['previous_entry_id']) is type(value)
    assert 'content' not in result
