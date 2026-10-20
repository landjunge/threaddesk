"""Real backup round trips, isolation and invalid-archive boundaries."""
import io
import json
import os
import zipfile
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.storage.portable_backup import download_backup, restore_backup, selected_profile
from threaddesk.storage.workspace_backup import BackupError
from threaddesk.storage import workspace_backup
from threaddesk.ui.server import create_app, _svc


def source_reader_type():
    if workspace_backup._WINDOWS_SOURCE:
        from threaddesk.storage.windows_backup_source import WindowsSourceTree
        return WindowsSourceTree
    return workspace_backup._SourceTree


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


@pytest.mark.parametrize('backend', ['json', 'sqlite'])
def test_download_refuses_external_symlink_before_opening_it(tmp_path, monkeypatch, backend):
    store = JsonStore(tmp_path / 'source') if backend == 'json' else SQLiteStore(tmp_path / 'source')
    ThreadService(store).create('Synthetische Testdaten')
    secret = tmp_path / 'external.json'
    secret.write_bytes(b'EXTERNAL-CONTENT-MUST-NOT-BE-READ')
    (store.root / 'linked.json').symlink_to(secret)
    original = os.open
    external_inode = secret.stat().st_ino
    opened_external = []

    def observed(*args, **kwargs):
        fd = original(*args, **kwargs)
        if os.fstat(fd).st_ino == external_inode:
            opened_external.append(fd)
        return fd

    monkeypatch.setattr(os, 'open', observed)
    with pytest.raises(BackupError):
        download_backup(store)
    assert not opened_external


def test_json_download_refuses_link_exchange_at_first_read(tmp_path, monkeypatch):
    store = JsonStore(tmp_path / 'source')
    ThreadService(store).create('Synthetic')
    selected = store.root / 'handoff.json'
    selected.write_bytes(b'{"safe":true}')
    secret = tmp_path / 'external.json'
    secret.write_bytes(b'EXTERNAL-CONTENT')
    root_inode = store.root.stat().st_ino
    original = os.open
    changed = False
    opened_external = []

    def swap(name, flags, *args, **kwargs):
        nonlocal changed
        directory = kwargs.get('dir_fd')
        if name == 'handoff.json' and directory is not None and os.fstat(directory).st_ino == root_inode and not changed:
            changed = True
            selected.unlink()
            selected.symlink_to(secret)
        fd = original(name, flags, *args, **kwargs)
        if os.fstat(fd).st_ino == secret.stat().st_ino:
            opened_external.append(fd)
        return fd

    if workspace_backup._WINDOWS_SOURCE:
        from test_workspace_backup import native_before_open

        def native_swap(relative):
            nonlocal changed
            if relative == 'handoff.json' and not changed:
                changed = True
                selected.unlink()
                selected.symlink_to(secret)
        native_before_open(monkeypatch, native_swap)
    else:
        monkeypatch.setattr(os, 'open', swap)
    with pytest.raises(BackupError):
        download_backup(store)
    assert changed and not opened_external


@pytest.mark.parametrize('replacement', ['link', 'regular'])
def test_json_comparison_read_uses_the_original_descriptor_binding(tmp_path, monkeypatch, replacement):
    store = JsonStore(tmp_path / 'source')
    ThreadService(store).create('Synthetic')
    selected = store.root / 'handoff.json'
    selected.write_bytes(b'{"safe":true}')
    secret = tmp_path / 'external.json'
    secret.write_bytes(b'EXTERNAL-CONTENT')
    reader = source_reader_type()
    original = reader.open
    calls = 0

    @contextmanager
    def change_on_second_read(self, relative, expected):
        nonlocal calls
        if relative == 'handoff.json':
            calls += 1
            if calls == 2:
                selected.rename(store.root / 'previous')
                if replacement == 'link':
                    selected.symlink_to(secret)
                else:
                    selected.write_bytes(b'{"safe":true}')
        with original(self, relative, expected) as handle:
            yield handle

    monkeypatch.setattr(reader, 'open', change_on_second_read)
    with pytest.raises(BackupError):
        download_backup(store)
    assert calls == 2


@pytest.mark.parametrize('backend', ['json', 'sqlite'])
def test_portable_restore_rejects_extra_non_manifest_member(tmp_path, backend):
    store = JsonStore(tmp_path / 'source') if backend == 'json' else SQLiteStore(tmp_path / 'source')
    ThreadService(store).create('Synthetic')
    original = download_backup(store)
    body = io.BytesIO(original)
    with zipfile.ZipFile(body, 'a') as archive:
        archive.writestr('workspace/unlisted.json', b'not verified')
    target = tmp_path / 'target'
    with pytest.raises(BackupError, match='Unexpected'):
        restore_backup(body.getvalue(), target)
    assert selected_profile(target) == (target, None)
    assert not list((target / 'profiles').iterdir())


def test_json_ancestor_directory_exchange_at_first_open_never_reads_external(tmp_path, monkeypatch):
    store = JsonStore(tmp_path / 'source')
    ThreadService(store).create('Synthetic')
    actual = store.root / 'artifacts'
    actual.mkdir()
    (actual / 'captured.txt').write_bytes(b'internal')
    outside = tmp_path / 'outside'
    outside.mkdir()
    secret = outside / 'captured.txt'
    secret.write_bytes(b'EXTERNAL-CONTENT')
    root_inode = store.root.stat().st_ino
    original = os.open
    changed = False
    opened_external = []

    def swap(name, flags, *args, **kwargs):
        nonlocal changed
        directory = kwargs.get('dir_fd')
        if name == 'artifacts' and directory is not None and os.fstat(directory).st_ino == root_inode and not changed:
            changed = True
            actual.rename(store.root / 'previous-artifacts')
            actual.symlink_to(outside, target_is_directory=True)
        fd = original(name, flags, *args, **kwargs)
        if os.fstat(fd).st_ino == secret.stat().st_ino:
            opened_external.append(fd)
        return fd

    if workspace_backup._WINDOWS_SOURCE:
        reader = source_reader_type()
        original_scan = reader.scan

        def native_swap(self, *args):
            nonlocal changed
            if not changed:
                changed = True
                actual.rename(store.root / 'previous-artifacts')
                actual.symlink_to(outside, target_is_directory=True)
            return original_scan(self, *args)
        monkeypatch.setattr(reader, 'scan', native_swap)
    else:
        monkeypatch.setattr(os, 'open', swap)
    with pytest.raises(BackupError):
        download_backup(store)
    assert changed and not opened_external


@pytest.mark.parametrize('name', ['NUL.json', 'CON.txt', 'COM1.md', 'LPT9.json', 'safe.json.',
                                 'safe.json ', 'C:outside.json', 'notes.json:stream'])
def test_portable_restore_rejects_windows_normalization_aliases_before_any_write(tmp_path, name):
    import hashlib

    store = JsonStore(tmp_path / 'source')
    ThreadService(store).create('Synthetic')
    with zipfile.ZipFile(io.BytesIO(download_backup(store))) as original:
        files = {n: original.read(n) for n in original.namelist()}
    manifest = json.loads(files['manifest.json'])
    relative = 'artifacts/' + name
    body = b'{"synthetic":true}'
    manifest['files'][relative] = {'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
    files['workspace/' + relative] = body
    files['manifest.json'] = json.dumps(manifest).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        for member, content in files.items():
            archive.writestr(member, content)
    root = tmp_path / 'target'
    with pytest.raises(BackupError, match='Invalid backup path'):
        restore_backup(output.getvalue(), root)
    assert selected_profile(root) == (root, None)
    assert not list((root / 'profiles').iterdir())


def test_nonportable_json_filename_is_refused_instead_of_silently_omitted():
    from threaddesk.storage.portable_backup import _allowed

    assert not _allowed('CON.json', 'json')
    with pytest.raises(BackupError, match='portable'):
        _allowed('CON.json', 'json', strict=True)


@pytest.mark.parametrize('extra_names', [
    ('artifacts/A.txt', 'artifacts/a.txt'),
    ('artifacts/é.txt', 'artifacts/e\u0301.txt'),
    ('artifacts/Folder/a.txt', 'artifacts/folder/b.txt'),
])
def test_actual_filesystem_aliases_never_publish_an_incomplete_manifest(tmp_path, extra_names):
    import hashlib

    # Probe this actual destination filesystem. No universal normalization or
    # case-folding guarantee is inferred from the test operating system name.
    probe = tmp_path / 'probe'
    probe.mkdir()
    can_coexist = True
    for name in extra_names:
        path = probe / name
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open('xb') as handle:
                handle.write(b'probe')
        except FileExistsError:
            can_coexist = False
            break
    actual = {p.relative_to(probe).as_posix() for p in probe.rglob('*') if p.is_file()}
    can_coexist = can_coexist and actual == set(extra_names)
    store = JsonStore(tmp_path / 'source')
    ThreadService(store).create('Synthetic')
    with zipfile.ZipFile(io.BytesIO(download_backup(store))) as original:
        files = {name: original.read(name) for name in original.namelist()}
    manifest = json.loads(files['manifest.json'])
    contents = {extra_names[0]: b'UPPER', extra_names[1]: b'lower'}
    for name, body in contents.items():
        files['workspace/' + name] = body
        manifest['files'][name] = {'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
    files['manifest.json'] = json.dumps(manifest).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    root = tmp_path / 'target'
    if can_coexist:
        restored = restore_backup(output.getvalue(), root)
        for name, body in contents.items():
            assert (restored / name).read_bytes() == body
    else:
        with pytest.raises(BackupError):
            restore_backup(output.getvalue(), root)
        assert selected_profile(root) == (root, None)
        assert not list((root / 'profiles').iterdir())


def test_existing_portable_profile_directory_survives_uuid_collision(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from threaddesk.storage import portable_backup

    store = JsonStore(tmp_path / 'source')
    ThreadService(store).create('Synthetic')
    body = download_backup(store)
    fixed = SimpleNamespace(hex='deadbeef123456789012345678901234')
    root = tmp_path / 'target'
    existing = root / 'profiles' / fixed.hex
    existing.mkdir(parents=True)
    (existing / 'keep').write_bytes(b'foreign existing profile')
    monkeypatch.setattr(portable_backup, 'uuid4', lambda: fixed)
    with pytest.raises(BackupError):
        restore_backup(body, root)
    assert (existing / 'keep').read_bytes() == b'foreign existing profile'
    assert selected_profile(root) == (root, None)


def test_portable_readback_refuses_corruption_of_the_captured_copy(tmp_path, monkeypatch):
    from threaddesk.storage import portable_backup

    store = JsonStore(tmp_path / 'source')
    ThreadService(store).create('Synthetic')
    store.write_text_artifact('handoff.json', '{"safe":true}')
    body = download_backup(store)
    original = portable_backup._verify_captured

    def corrupted(root, files):
        (root / 'handoff.json').write_bytes(b'{"changed":true}')
        return original(root, files)

    monkeypatch.setattr(portable_backup, '_verify_captured', corrupted)
    root = tmp_path / 'target'
    with pytest.raises(BackupError):
        restore_backup(body, root)
    assert selected_profile(root) == (root, None)
    assert not list((root / 'profiles').iterdir())


def test_json_journal_link_is_a_clear_backup_failure_without_reading_external(tmp_path, monkeypatch):
    from pathlib import Path

    store = JsonStore(tmp_path / 'source')
    ThreadService(store).create('Synthetic')
    external = tmp_path / 'external-journal.json'
    contents = b'{"version":1,"writes":{}}'
    external.write_bytes(contents)
    journal = store.root / '.management-commit.json'
    journal.symlink_to(external)
    original = Path.read_text
    unsafe_reads = []

    def watched(path, *args, **kwargs):
        if path == journal or path == external:
            unsafe_reads.append(str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', watched)
    with pytest.raises(BackupError):
        download_backup(store)
    assert unsafe_reads == []
    assert journal.is_symlink() and external.read_bytes() == contents


def test_runtime_filename_case_alias_is_not_importable_or_silently_omitted():
    from threaddesk.storage.portable_backup import _allowed

    assert not _allowed('Desktop-port.json', 'json')
    with pytest.raises(BackupError, match='runtime filename alias'):
        _allowed('Desktop-port.json', 'json', strict=True)
