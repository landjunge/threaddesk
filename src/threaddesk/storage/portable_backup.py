"""Downloadable, checked backups; restore into a separate selectable profile."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
from datetime import datetime, timezone
import tempfile
from uuid import uuid4
import zipfile

from threaddesk.storage.json_store import DEFAULT_ROOT, JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.storage.workspace_backup import BackupError, WorkspaceBackup

LIMIT = 128 * 1024 * 1024
DATA_DIRS = {'threads', 'snapshots', 'nodes', 'relations', 'graph-events',
             'source-records', 'whiteboard', 'artifacts', 'imports'}
RUNTIME_FILES = {'desktop-port.json', 'desktop.lock', 'active-profile.json'}


def base_root() -> Path:
    import os
    from threaddesk.storage import json_store
    return Path(os.environ.get('THREADDESK_HOME') or json_store.DEFAULT_ROOT)


def selected_profile(root: Path) -> tuple[Path, str | None]:
    marker = root / 'active-profile.json'
    if not marker.exists():
        return root, None
    try:
        data = json.loads(marker.read_text(encoding='utf-8'))
        name, backend = data['name'], data['backend']
        if (not isinstance(name, str) or len(name) != 32 or
                any(c not in '0123456789abcdef' for c in name) or backend not in {'json', 'sqlite'}):
            raise ValueError('profile')
        target = root / 'profiles' / name
        if target.is_symlink() or target.resolve().parent != (root / 'profiles').resolve() or not target.is_dir():
            raise ValueError('profile')
        return target, backend
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BackupError('The selected workspace cannot be opened.') from exc


def _allowed(name: str, backend: str) -> bool:
    path = PurePosixPath(name)
    if (not name or '\\' in name or path.is_absolute() or name != str(path)
            or any(p in {'', '.', '..'} or p.startswith('.') for p in path.parts)):
        return False
    if len(path.parts) == 1:
        return (name == 'threaddesk.sqlite3' and backend == 'sqlite') or (
            name not in RUNTIME_FILES and path.suffix in {'.json', '.txt', '.md'})
    return path.parts[0] in DATA_DIRS


def download_backup(store) -> bytes:
    backend = 'sqlite' if isinstance(store, SQLiteStore) else 'json'
    with tempfile.TemporaryDirectory(prefix='threaddesk-backup-') as temp:
        source = store.root
        if backend == 'sqlite':
            backup = WorkspaceBackup(Path(temp)).create(store)
            source = Path(temp) / 'profile'
            WorkspaceBackup(Path(temp)).restore_verified(backup, source)
        # System directory aliases (for example macOS /var) are not links in
        # the workspace. Canonicalize the root before checking its contents.
        source = source.resolve()
        files = {}
        bodies = {}
        for path in sorted(source.rglob('*')):
            name = path.relative_to(source).as_posix()
            if not _allowed(name, backend):
                continue
            if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != source.parent):
                raise BackupError('Symbolic links cannot be backed up.')
            if not path.is_file():
                continue
            body = path.read_bytes()
            if sum(len(value) for value in bodies.values()) + len(body) > LIMIT:
                raise BackupError('Workspace exceeds the backup size limit.')
            bodies[name] = body
            files[name] = {'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
        # JSON has no database snapshot: refuse a changing source rather than
        # silently return a mixture of versions.
        if backend == 'json':
            current = {p.relative_to(source).as_posix() for p in source.rglob('*')
                       if p.is_file() and _allowed(p.relative_to(source).as_posix(), backend)}
            if current != set(bodies) or any((source / n).read_bytes() != b for n, b in bodies.items()):
                raise BackupError('Workspace changed during backup. Please try again.')
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json', json.dumps({
                'kind': 'threaddesk.portable-backup', 'version': 1,
                'backend': backend, 'files': files}, sort_keys=True))
            for name, body in bodies.items():
                archive.writestr('workspace/' + name, body)
        return output.getvalue()


def restore_backup(body: bytes, root: Path) -> Path:
    if len(body) > LIMIT:
        raise BackupError('Backup exceeds the size limit.')
    root.mkdir(parents=True, exist_ok=True)
    profiles = root / 'profiles'
    profiles.mkdir(mode=0o700, exist_ok=True)
    if profiles.is_symlink():
        raise BackupError('Invalid profile directory.')
    name = uuid4().hex
    target = profiles / name
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            members = archive.infolist()
            if len(members) > 20000 or sum(m.file_size for m in members) > LIMIT:
                raise BackupError('Backup exceeds the size limit.')
            names = [m.filename for m in members]
            if len(names) != len(set(names)) or 'manifest.json' not in names:
                raise BackupError('Invalid backup manifest.')
            manifest = json.loads(archive.read('manifest.json'))
            backend = manifest.get('backend')
            files = manifest.get('files')
            if (manifest.get('kind') != 'threaddesk.portable-backup' or manifest.get('version') != 1
                    or backend not in {'json', 'sqlite'} or not isinstance(files, dict)):
                raise BackupError('Unknown backup format.')
            if set(names) != {'manifest.json'} | {'workspace/' + n for n in files}:
                raise BackupError('Unexpected backup files.')
            if any(not _allowed(n, backend) for n in files):
                raise BackupError('Invalid backup path.')
            if any(stat.S_ISLNK(m.external_attr >> 16) for m in members):
                raise BackupError('Symbolic links are not allowed.')
            target.mkdir(mode=0o700)
            for relative, expected in files.items():
                data = archive.read('workspace/' + relative)
                if len(data) != expected['size'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
                    raise BackupError('Backup checksum does not match.')
                path = target / relative
                path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                path.write_bytes(data)
                path.chmod(0o600)
        if backend == 'sqlite' and 'threaddesk.sqlite3' not in files:
            raise BackupError('Missing workspace database.')
        store = SQLiteStore(target) if backend == 'sqlite' else JsonStore(target)
        try:
            threads = store.list_threads(True)
            for thread in threads:
                store.list_snapshots(thread.id)
                store.list_whiteboard(thread.id)
            store.list_nodes()
            store.list_relations()
            store.list_graph_events()
            current = store.get_current_id()
            if current and current not in {t.id for t in threads}:
                raise BackupError('Invalid active thread.')
        finally:
            if backend == 'sqlite':
                store.connection.close()
        # Preserve this installation's listening port, never import another
        # machine's port. Housekeeper remains off until explicitly enabled.
        active, _ = selected_profile(root)
        port = active / 'desktop-port.json'
        if port.is_file():
            shutil.copy2(port, target / 'desktop-port.json')
        caretaker = target / 'hausmeister.json'
        if caretaker.exists():
            data = json.loads(caretaker.read_text(encoding='utf-8'))
            data['enabled'] = False
            caretaker.write_text(json.dumps(data), encoding='utf-8')
        (target / '.profile-info.json').write_text(json.dumps({'backend': backend, 'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}), encoding='utf-8')
        temporary = root / ('profile-' + uuid4().hex + '.tmp')
        temporary.write_text(json.dumps({'name': name, 'backend': backend}), encoding='utf-8')
        temporary.replace(root / 'active-profile.json')
        return target
    except Exception as exc:
        shutil.rmtree(target, ignore_errors=True)
        if isinstance(exc, BackupError):
            raise
        raise BackupError('Backup could not be opened.') from exc


def profiles(root: Path) -> list[dict]:
    result = []
    for path in sorted((root / 'profiles').glob('*')):
        if path.is_symlink() or not path.is_dir():
            continue
        try:
            info = json.loads((path / '.profile-info.json').read_text(encoding='utf-8'))
            if len(path.name) == 32 and all(c in '0123456789abcdef' for c in path.name) and info['backend'] in {'json', 'sqlite'}:
                result.append({'name': path.name, **info})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return result


def activate_profile(root: Path, name: str) -> None:
    available = {p['name']: p for p in profiles(root)}
    if name not in available:
        raise BackupError('Unknown workspace.')
    temporary = root / ('profile-' + uuid4().hex + '.tmp')
    temporary.write_text(json.dumps({'name': name, 'backend': available[name]['backend']}), encoding='utf-8')
    temporary.replace(root / 'active-profile.json')
