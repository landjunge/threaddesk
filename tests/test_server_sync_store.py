import hashlib
import sqlite3

import pytest

from threaddesk.server_sync import store as module
from threaddesk.server_sync.store import SyncError, SyncStore


def digest(body):
    return hashlib.sha256(body).hexdigest()


def setup(tmp_path):
    store = SyncStore(tmp_path)
    project = store.create_project('Example', 'project')['id']
    store.set_offline(project, True)
    return store, project


def upload(store, project, transfer, body, base=None, path='note.txt'):
    store.start_upload(project, transfer, path, len(body), digest(body), base)
    if body:
        store.append_chunk(project, transfer, 0, body)
    return store.finish_upload(project, transfer)['revision']


def test_restart_exact_replay_and_receipt(tmp_path):
    store, project = setup(tmp_path)
    store.start_upload(project, 'resume', 'note.txt', 6, digest(b'abcdef'))
    store.append_chunk(project, 'resume', 0, b'abc')
    store = SyncStore(tmp_path)
    assert store.upload_status(project, 'resume')['next_offset'] == 3
    assert store.append_chunk(project, 'resume', 0, b'abc')['next_offset'] == 3
    with pytest.raises(SyncError, match='differs'):
        store.append_chunk(project, 'resume', 0, b'xyz')
    with pytest.raises(SyncError, match='incomplete'):
        store.finish_upload(project, 'resume')
    store.append_chunk(project, 'resume', 3, b'def')
    receipt = store.finish_upload(project, 'resume')
    assert SyncStore(tmp_path).finish_upload(project, 'resume') == receipt
    assert store.read_revision(project, receipt['revision']) == b'abcdef'


def test_stale_and_missing_bases_preserve_all_versions_and_cas(tmp_path):
    store, project = setup(tmp_path)
    original = upload(store, project, 'one', b'one')
    second = upload(store, project, 'two', b'two', original)
    stale = upload(store, project, 'stale', b'stale', original)
    unbased = upload(store, project, 'unbased', b'unbased')
    heads = store.list_files(project)[0]['heads']
    assert {h['revision'] for h in heads} == {second, stale, unbased}
    assert store.status(project)['state'] == 'conflict'
    with pytest.raises(SyncError, match='changed'):
        store.resolve(project, 'note.txt', [second, stale], second)
    store.resolve(project, 'note.txt', [second, stale, unbased], second)
    for revision, body in [(original,b'one'),(second,b'two'),(stale,b'stale'),(unbased,b'unbased')]:
        assert store.read_revision(project, revision) == body
    store.set_offline(project, False)
    assert store.read_revision(project, stale) == b'stale'
    with pytest.raises(SyncError, match='disabled'):
        store.start_upload(project, 'disabled', 'other.txt', 0, digest(b''))


def test_manifest_readiness_integrity_and_device_disagreement(tmp_path):
    store, project = setup(tmp_path)
    body = b'correct'
    manifest = [{'path':'note.txt', 'size':len(body), 'sha256':digest(body)}]
    assert store.declare_manifest(project, manifest, [], 'mac')['state'] == 'pending'
    revision = upload(store, project, 'correct', body)
    assert store.status(project)['state'] == 'ready'
    store.declare_manifest(project, [{'path':'note.txt','size':3,'sha256':digest(b'old')}], [], 'linux')
    assert store.status(project)['state'] == 'blocked'
    store.declare_manifest(project, manifest, [], 'linux')
    assert store.status(project)['state'] == 'ready'
    with sqlite3.connect(store.db_path) as db:
        db.execute('UPDATE versions SET body=? WHERE revision=?', (b'corrupt', revision))
    with pytest.raises(SyncError, match='integrity'):
        store.read_revision(project, revision)
    assert store.status(project)['state'] == 'blocked'


def test_checksum_failure_preserves_journal_and_quota_counts_history(tmp_path, monkeypatch):
    store, project = setup(tmp_path)
    monkeypatch.setattr(module, 'MAX_TENANT_BYTES', 9)
    first = upload(store, project, 'first', b'1234')
    upload(store, project, 'second', b'5678', first)
    with pytest.raises(SyncError, match='quota'):
        store.start_upload(project, 'third', 'note.txt', 2, digest(b'ab'))
    store.start_upload(project, 'bad', 'bad.txt', 1, digest(b'a'))
    store.append_chunk(project, 'bad', 0, b'b')
    with pytest.raises(SyncError, match='integrity'):
        store.finish_upload(project, 'bad')
    assert store.upload_status(project, 'bad')['state'] == 'receiving'
    assert store.read_revision(project, first) == b'1234'
    with pytest.raises(SyncError, match='quota'):
        store.start_upload(project, 'reserved', 'reserved.txt', 1, digest(b'c'))


def test_manifest_fail_closed_and_cross_project_transfer_isolation(tmp_path):
    store, project = setup(tmp_path)
    for path in ('../outside','/absolute','a//b','.env','a/.env.local','a/.git/config','a\\b','id_rsa','secret.txt',
                 '.threaddesk-sync-conflicts/remote/x', 'a/.td-sync-publish'):
        with pytest.raises(SyncError):
            store.declare_manifest(project, [{'path':path,'size':0,'sha256':digest(b'')}], [], 'mac')
    assert store.status(project)['state'] == 'pending'
    store.declare_manifest(project,[{'path':'core/secrets.py','size':0,'sha256':digest(b'')}],[], 'source')
    with pytest.raises(SyncError):
        store.declare_manifest(project,[{'path':'server-sync-private/a.json','size':0,'sha256':digest(b'')}],[],'source')
    other = store.create_project('Other', 'other')['id']
    revision = upload(store, project, 'private', b'private')
    with pytest.raises(SyncError):
        store.start_upload(project, 'alias', 'NOTE.TXT', 0, digest(b''))
    with pytest.raises(SyncError):
        store.start_upload(project, 'directory', 'note.txt/nested', 0, digest(b''))
    store.declare_manifest(project, [{'path':'Dir/a.txt','size':0,'sha256':digest(b'')}], [], 'mac')
    with pytest.raises(SyncError):
        store.start_upload(project, 'directory-alias', 'dir/b.txt', 0, digest(b''))
    with pytest.raises(SyncError):
        store.start_upload(project, 'manifest-parent', 'Dir', 0, digest(b''))
    with pytest.raises(SyncError):
        store.read_revision(other, revision)
    with pytest.raises(SyncError):
        store.upload_status(other, 'private')
