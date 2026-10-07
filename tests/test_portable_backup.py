"""Real backup round trips, isolation and invalid-archive boundaries."""
import io
import json
import tempfile
import zipfile

import pytest
from fastapi.testclient import TestClient

from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.storage.portable_backup import download_backup, restore_backup, selected_profile
from threaddesk.storage.workspace_backup import BackupError
from threaddesk.ui.server import create_app, _svc


@pytest.mark.parametrize('backend', ['json', 'sqlite'])
def test_backup_round_trip_under_system_directory_alias(tmp_path, monkeypatch, backend):
    """macOS uses symlinked ancestors such as /var for temporary directories."""
    physical = tmp_path / 'physical'
    physical.mkdir()
    alias = tmp_path / 'system-alias'
    try:
        alias.symlink_to(physical, target_is_directory=True)
    except OSError:
        pytest.skip('Creating directory symlinks is unavailable on this platform')
    temp = alias / 'folders' / 'temporary'
    temp.mkdir(parents=True)
    monkeypatch.setattr(tempfile, 'tempdir', str(temp))
    root = alias / 'users' / 'workspace'
    store = SQLiteStore(root) if backend == 'sqlite' else JsonStore(root)
    try:
        svc = ThreadService(store)
        thread = svc.create('Verknüpfter Systempfad')
        svc.set_note('Dieser Stand bleibt erhalten', thread.id)
        svc.snapshot('Vor Sicherung', thread.id)
        body = download_backup(store)
        restored = restore_backup(body, tmp_path / 'restore')
        recovered = SQLiteStore(restored) if backend == 'sqlite' else JsonStore(restored)
        try:
            assert ThreadService(recovered).current().context.notes == 'Dieser Stand bleibt erhalten'
            assert len(recovered.list_snapshots(thread.id)) == 1
        finally:
            if backend == 'sqlite':
                recovered.connection.close()
        assert svc.current().context.notes == 'Dieser Stand bleibt erhalten'
    finally:
        if backend == 'sqlite':
            store.connection.close()


def test_json_backup_still_rejects_link_to_external_file(tmp_path):
    store = JsonStore(tmp_path / 'workspace')
    ThreadService(store).create('Privat')
    outside = tmp_path / 'outside.txt'
    outside.write_text('Must not be exported', encoding='utf-8')
    try:
        (store.root / 'external.txt').symlink_to(outside)
    except OSError:
        pytest.skip('Creating file symlinks is unavailable on this platform')
    with pytest.raises(BackupError, match='Symbolic links'):
        download_backup(store)


@pytest.mark.parametrize('backend', ['json', 'sqlite'])
def test_download_restore_restart_and_return_preserve_original(tmp_path, monkeypatch, backend):
    monkeypatch.setenv('THREADDESK_HOME', str(tmp_path))
    monkeypatch.setenv('THREADDESK_STORAGE', backend)
    svc = _svc()
    thread = svc.create('Mein Projekt')
    svc.set_note('Originalnotiz', thread.id)
    svc.snapshot('Vor Sicherung', thread.id)
    svc.create_node('project', 'Mein Wissensknoten', status='active')
    svc.append_whiteboard(thread.id, actor='Mensch', actor_type='human',
                         entry_type='note', content='Whiteboard bleibt')
    svc.store.write_text_artifact('handoff.json', '{"test":true}')
    svc.store.write_json_artifact('hausmeister.json', {'enabled': True, 'model': 'example'})
    svc.store.write_json_artifact('desktop-port.json', {'port': 12345})
    client = TestClient(create_app())
    assert 'Sicherung herunterladen' in client.get('/data?lang=de').text
    download = client.post('/data/download')
    assert download.status_code == 200
    assert download.headers['content-type'] == 'application/zip'
    svc.set_note('Nach Sicherung', thread.id)
    response = client.post('/data/restore', data={'confirm': 'yes'},
                           files={'backup': ('backup.zip', download.content, 'application/zip')})
    assert response.status_code == 200
    restored = _svc()
    assert restored.store.root != tmp_path
    assert restored.current().context.notes == 'Originalnotiz'
    assert len(restored.snapshots(thread.id)) == 1
    assert restored.whiteboard(thread.id)[0].content == 'Whiteboard bleibt'
    assert restored.list_nodes()[0].title == 'Mein Wissensknoten'
    assert restored.store.artifact_path('handoff.json').read_text() == '{"test":true}'
    assert json.loads(restored.store.artifact_path('hausmeister.json').read_text())['enabled'] is False
    assert json.loads(restored.store.artifact_path('desktop-port.json').read_text())['port'] == 12345
    restored.set_note('Im neuen Arbeitsbereich', thread.id)
    restarted = TestClient(create_app())
    assert 'Im neuen Arbeitsbereich' in restarted.get('/').text
    assert restarted.post('/data/original').status_code == 200
    assert _svc().current().context.notes == 'Nach Sicherung'
    assert restarted.post('/data/profile', data={'name': restored.store.root.name}).status_code == 200
    assert ThreadService().current().context.notes == 'Im neuen Arbeitsbereich'


@pytest.mark.parametrize('attack', ['path', 'checksum', 'duplicate', 'missing-db', 'symlink'])
def test_invalid_backup_never_selects_profile(tmp_path, attack):
    source = SQLiteStore(tmp_path / 'source')
    ThreadService(source).create('Sicher')
    body = download_backup(source)
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        files = {n: archive.read(n) for n in archive.namelist()}
    manifest = json.loads(files['manifest.json'])
    if attack == 'path':
        manifest['files']['../../outside.txt'] = {'size': 3, 'sha256': 'bad'}
        files['workspace/../../outside.txt'] = b'bad'
    elif attack == 'checksum':
        files['workspace/threaddesk.sqlite3'] = b'corrupted'
    elif attack == 'missing-db':
        del manifest['files']['threaddesk.sqlite3']
        del files['workspace/threaddesk.sqlite3']
    files['manifest.json'] = json.dumps(manifest).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        for name, value in files.items():
            if attack == 'symlink' and name == 'workspace/threaddesk.sqlite3':
                info = zipfile.ZipInfo(name)
                info.external_attr = 0o120777 << 16
                archive.writestr(info, value)
            else:
                archive.writestr(name, value)
        if attack == 'duplicate':
            archive.writestr('manifest.json', files['manifest.json'])
    root = tmp_path / 'target'
    with pytest.raises(BackupError):
        restore_backup(output.getvalue(), root)
    assert selected_profile(root) == (root, None)
    assert not list((root / 'profiles').iterdir())
    assert not (tmp_path / 'outside.txt').exists()


def test_restore_requires_explicit_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv('THREADDESK_HOME', str(tmp_path))
    _svc().create('Original')
    client = TestClient(create_app())
    backup = client.post('/data/download').content
    response = client.post('/data/restore', files={'backup': ('backup.zip', backup)})
    assert response.status_code == 400
    assert _svc().current().title == 'Original'
