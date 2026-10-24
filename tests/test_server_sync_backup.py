"""Cold snapshot completeness, data-loss protection and hostile restore inputs."""
import hashlib
import io
import json
from pathlib import Path
import tarfile

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.server_sync.auth import Credentials, provision
from threaddesk.server_sync.backup import BackupError, FORMAT, backup, restore, server_lock
from threaddesk.server_sync.store import SyncStore
from threaddesk.storage.json_store import JsonStore


def put(store, pid, tid, data, base=None):
    store.start_upload(pid, tid, 'note.md', len(data), hashlib.sha256(data).hexdigest(), base)
    if data:
        store.append_chunk(pid, tid, 0, data)
    return store.finish_upload(pid, tid)


@pytest.fixture
def populated(tmp_path):
    root = tmp_path/'source'
    token = provision(root, 'alice')
    provision(root, 'bob')
    core = ThreadService(JsonStore(root/'users/alice/core'))
    thread = core.create('Backup project', 'Keep original description')
    core.append_whiteboard(thread.id, actor='alice', actor_type='human', entry_type='note',
                           content='Keep this whiteboard', external_key='original')
    core.snapshot('Original context', thread.id)
    sync = SyncStore(root/'users/alice/sync')
    pid = sync.create_project(thread.title, thread.id)['id']
    sync.set_offline(pid, True)
    first = put(sync, pid, 'first', b'original-content')
    second = put(sync, pid, 'second', b'server-content', first['revision'])
    third = put(sync, pid, 'third', b'local-content', first['revision'])
    data = b'interrupted-content'
    sync.start_upload(pid, 'interrupted', 'later.md', len(data), hashlib.sha256(data).hexdigest())
    sync.append_chunk(pid, 'interrupted', 0, data[:5])
    (root/'empty-dir').mkdir()
    return root, token, pid, (first, second, third), data


def test_backup_restore_preserves_credentials_history_conflicts_chunks_and_core(populated, tmp_path):
    root, token, pid, receipts, data = populated
    artifact = tmp_path/'snapshot.tar'
    manifest = backup(root, artifact)
    assert manifest['format'] == FORMAT
    assert artifact.stat().st_mode & 0o077 == 0
    target = tmp_path/'restored'
    assert restore(artifact, target) == manifest
    assert Credentials(target).authenticate(token) == 'alice'
    assert (target/'empty-dir').is_dir()
    sync = SyncStore(target/'users/alice/sync')
    assert sync.status(pid)['conflict_count'] == 1
    for receipt, expected in zip(receipts, (b'original-content', b'server-content', b'local-content')):
        assert sync.read_revision(pid, receipt['revision']) == expected
    assert sync.finish_upload(pid, 'first') == receipts[0]
    assert sync.upload_status(pid, 'interrupted')['next_offset'] == 5
    sync.append_chunk(pid, 'interrupted', 5, data[5:])
    result = sync.finish_upload(pid, 'interrupted')
    assert sync.read_revision(pid, result['revision']) == data
    core = ThreadService(JsonStore(target/'users/alice/core'))
    assert core.get(pid).description == 'Keep original description'
    assert core.whiteboard(pid)[0].content == 'Keep this whiteboard'
    assert len(core.snapshots(pid)) == 1
    # Restoring/changing the restored copy cannot modify source state.
    original = SyncStore(root/'users/alice/sync')
    assert original.upload_status(pid, 'interrupted')['next_offset'] == 5
    assert original.status(pid)['conflict_count'] == 1


def test_running_server_refused_and_existing_artifacts_targets_preserved(populated, tmp_path):
    root, *_ = populated
    artifact = tmp_path/'snapshot.tar'
    with server_lock(root), pytest.raises(BackupError, match='Stop the server'):
        backup(root, artifact)
    assert not artifact.exists()
    backup(root, artifact)
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    with pytest.raises(BackupError, match='already exists'):
        backup(root, artifact)
    with pytest.raises(BackupError, match='NEW directory'):
        restore(artifact, root)
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == digest
    with pytest.raises(BackupError, match='byte limit'):
        backup(root, tmp_path/'too-small.tar', max_bytes=1)
    assert not (tmp_path/'too-small.tar').exists()


def test_corrupt_archive_rolls_back_without_publishing_or_altering_artifact(populated, tmp_path):
    root, *_ = populated
    artifact = tmp_path/'snapshot.tar'
    backup(root, artifact)
    raw = artifact.read_bytes()
    # Marker lives inside a stored SQLite BLOB, leaving header and manifest intact.
    offset = raw.index(b'local-content')
    corrupted = raw[:offset] + b'X' + raw[offset+1:]
    bad = tmp_path/'corrupted.tar'; bad.write_bytes(corrupted)
    target = tmp_path/'restored'
    with pytest.raises(BackupError, match='hash mismatch'):
        restore(bad, target)
    assert not target.exists()
    assert artifact.read_bytes() == raw
    assert not list(tmp_path.glob('.td-restore-*'))


def test_insufficient_space_refuses_before_publication(populated, tmp_path, monkeypatch):
    import shutil
    root, *_ = populated
    artifact = tmp_path/'snapshot.tar'
    backup(root, artifact)
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(shutil, 'disk_usage', lambda path: usage._replace(free=0))
    with pytest.raises(BackupError, match='free space'):
        backup(root, tmp_path/'no-room.tar')
    with pytest.raises(BackupError, match='free space'):
        restore(artifact, tmp_path/'no-room')
    assert not (tmp_path/'no-room.tar').exists()
    assert not (tmp_path/'no-room').exists()


def test_logically_corrupt_version_cannot_be_certified_as_healthy_backup(populated, tmp_path):
    import sqlite3
    root, _, _, receipts, _ = populated
    with sqlite3.connect(root/'users/alice/sync/sync.sqlite3') as connection:
        connection.execute('UPDATE versions SET body=? WHERE revision=?', (b'bad content', receipts[0]['revision']))
    with pytest.raises(BackupError, match='corrupt file version'):
        backup(root, tmp_path/'corrupt-source.tar')
    assert not (tmp_path/'corrupt-source.tar').exists()


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'traversal', 'extra', 'duplicate', 'pax'])
def test_hostile_archive_members_never_escape_staging(tmp_path, kind):
    artifact = tmp_path/'hostile.tar'
    manifest = {'format':FORMAT, 'files':[], 'directories':[], 'total_bytes':0}
    encoded = json.dumps(manifest).encode()
    with tarfile.open(artifact, 'w', format=tarfile.USTAR_FORMAT) as archive:
        item=tarfile.TarInfo('manifest.json'); item.size=len(encoded)
        archive.addfile(item, io.BytesIO(encoded))
        item=tarfile.TarInfo('data/../../escaped')
        if kind=='symlink': item.type=tarfile.SYMTYPE; item.linkname='../../escaped'
        elif kind=='hardlink': item.type=tarfile.LNKTYPE; item.linkname='../../escaped'
        elif kind=='extra': item.name='data/extra'
        elif kind=='duplicate': item.name='manifest.json'
        elif kind=='pax': item.type=tarfile.XHDTYPE
        archive.addfile(item, io.BytesIO())
    with pytest.raises(BackupError):
        restore(artifact, tmp_path/'restored')
    assert not (tmp_path/'restored').exists()
    assert not (tmp_path/'escaped').exists()


@pytest.mark.parametrize('kind', ['symlink','hardlink'])
def test_backup_refuses_linked_source_data(populated, tmp_path, kind):
    root, *_ = populated
    if kind=='symlink': (root/'unsafe').symlink_to(root/'users.json')
    else: (root/'unsafe').hardlink_to(root/'users.json')
    with pytest.raises(BackupError, match='symlinks, hardlinks|hardlinks only'):
        backup(root, tmp_path/'snapshot.tar')
    assert not (tmp_path/'snapshot.tar').exists()
