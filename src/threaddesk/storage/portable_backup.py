"""Downloadable, checked backups; restore into a separate selectable profile."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
from datetime import datetime, timezone
import tempfile
from uuid import uuid4
import zipfile

from threaddesk.storage.json_store import DEFAULT_ROOT, JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.core.errors import InvalidState
from threaddesk.storage.workspace_backup import (
    BackupError, WorkspaceBackup, _SourceTree, _relative, _verify_captured, _cleanup_owned, _stamp,
)

LIMIT = 128 * 1024 * 1024
DATA_DIRS = {'threads', 'snapshots', 'nodes', 'relations', 'graph-events',
             'source-records', 'whiteboard', 'artifacts', 'imports',
             'management-operations', 'thread-revisions', 'issued-handoffs', 'library-files', 'trash'}
RUNTIME_FILES = {'desktop-port.json', 'desktop.lock', 'active-profile.json', 'graph-view-control.json'}


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


def _allowed(name: str, backend: str, *, strict: bool = False) -> bool:
    path = PurePosixPath(name)
    try:
        _relative(name, portable=True)
    except BackupError:
        if strict:
            raise
        return False
    if any(p.startswith('.') for p in path.parts):
        return False
    if path.parts[0] == 'library-files':
        from threaddesk.storage.library_backup import allowed
        return allowed(name)
    if len(path.parts) == 1:
        if name.casefold() in RUNTIME_FILES:
            if strict and name not in RUNTIME_FILES:
                raise BackupError('Reserved runtime filename alias.')
            return False
        return (name == 'threaddesk.sqlite3' and backend == 'sqlite') or (
            name not in RUNTIME_FILES and path.suffix in {'.json', '.txt', '.md'})
    return path.parts[0] in DATA_DIRS


def download_backup(store) -> bytes:
    try:
        if isinstance(store, JsonStore):
            # Recover committed state and hold the same writer lock for the snapshot.
            with store.transaction():
                return _download_backup(store)
        return _download_backup(store)
    except BackupError:
        raise
    except (OSError, InvalidState) as exc:
        raise BackupError('Backup source cannot be read safely.') from exc


def _download_backup(store) -> bytes:
    backend = 'sqlite' if isinstance(store, SQLiteStore) else 'json'
    with tempfile.TemporaryDirectory(prefix='threaddesk-backup-') as temp:
        source = store.workspace_path
        if backend == 'sqlite':
            backup = WorkspaceBackup(Path(temp)).create(store, library_limit=LIMIT)
            source = Path(temp) / 'profile'
            WorkspaceBackup(Path(temp)).restore_verified(backup, source)
        files = {}
        bodies = {}
        def allowed(name):
            return ((backend == 'sqlite' or not name.startswith('library-files/'))
                    and _allowed(name, backend, strict=True))

        def descend(name):
            folders = DATA_DIRS - ({'library-files'} if backend == 'json' else set())
            return PurePosixPath(name).parts[0] in folders
        stage = Path(temp) / 'library-capture'
        has_library = False
        with _SourceTree(source) as tree:
            inventory = tree.scan(allowed, descend)
            total = 0
            for name, expected in inventory.items():
                body = tree.read(name, expected, limit=LIMIT - total)
                total += len(body)
                bodies[name] = body
                files[name] = {'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
            if backend == 'json':
                from threaddesk.storage.library_backup import capture
                has_library = capture(store.workspace_path, stage, limit=LIMIT - total, source_tree=tree)
            # JSON has no database snapshot: both reads must use the same
            # descriptor-bound names/inodes, including this comparison read.
            if (tree.scan(allowed, descend) != inventory or backend == 'json' and any(
                    tree.read(name, inventory[name], limit=LIMIT) != body
                    for name, body in bodies.items())):
                raise BackupError('Workspace changed during backup. Please try again.')
        if has_library:
            from threaddesk.storage.library_backup import allowed as library_allowed, descend as library_descend
            with _SourceTree(stage) as library:
                for name, expected in library.scan(library_allowed, library_descend).items():
                    body = library.read(name, expected, limit=LIMIT - total)
                    total += len(body)
                    bodies[name] = body
                    files[name] = {'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
        output = io.BytesIO()
        manifest_body = json.dumps({
            'kind': 'threaddesk.portable-backup', 'version': 2,
            'backend': backend, 'files': files}, sort_keys=True).encode('utf-8')
        if sum(len(body) for body in bodies.values()) + len(manifest_body) > LIMIT or len(files) + 1 > 20000:
            raise BackupError('Backup exceeds the size limit or file limit.')
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json', manifest_body)
            for name, body in bodies.items():
                archive.writestr('workspace/' + name, body)
        body = output.getvalue()
        if len(body) > LIMIT:
            raise BackupError('Backup exceeds the size limit.')
        return body


def _checked_manifest(archive):
    members = archive.infolist()
    if len(members) > 20000 or sum(m.file_size for m in members) > LIMIT:
        raise BackupError('Backup exceeds the size limit.')
    names = [m.filename for m in members]
    if len(names) != len(set(names)) or 'manifest.json' not in names:
        raise BackupError('Invalid backup manifest.')
    manifest = json.loads(archive.read('manifest.json'))
    backend, files = manifest.get('backend'), manifest.get('files')
    if (manifest.get('kind') != 'threaddesk.portable-backup' or manifest.get('version') not in {1, 2}
            or backend not in {'json', 'sqlite'} or not isinstance(files, dict)):
        raise BackupError('Unknown backup format.')
    if manifest['version'] < 2 and any(n.startswith('library-files/') for n in files):
        raise BackupError('Library files require portable backup version 2.')
    if set(names) != {'manifest.json'} | {'workspace/' + n for n in files}:
        raise BackupError('Unexpected backup files.')
    if any(not _allowed(n, backend) for n in files):
        raise BackupError('Invalid backup path.')
    if any(stat.S_ISLNK(m.external_attr >> 16) for m in members):
        raise BackupError('Symbolic links are not allowed.')
    for relative, expected in files.items():
        if (not isinstance(expected, dict) or type(expected.get('size')) is not int
                or expected['size'] < 0 or not isinstance(expected.get('sha256'), str)):
            raise BackupError('Invalid backup checksum metadata.')
        data = archive.read('workspace/' + relative)
        if len(data) != expected['size'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            raise BackupError('Backup checksum does not match.')
    if backend == 'sqlite' and 'threaddesk.sqlite3' not in files:
        raise BackupError('Missing workspace database.')
    return manifest


def inspect_backup(body: bytes) -> dict:
    """Verify a portable archive without extraction, activation or data writes."""
    if not isinstance(body, bytes) or len(body) > LIMIT:
        raise BackupError('Backup exceeds the size limit.')
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            manifest = _checked_manifest(archive)
        return {'kind': manifest['kind'], 'version': manifest['version'],
                'backend': manifest['backend'], 'files': len(manifest['files']),
                'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
                'restore_behavior': 'new_separate_profile', 'verified': True,
                'verification_scope': 'archive_paths_sizes_and_checksums; restore validates workspace models separately'}
    except Exception as exc:
        if isinstance(exc, BackupError):
            raise
        raise BackupError('Backup could not be opened.') from exc


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
    owned = None
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            manifest = _checked_manifest(archive)
            backend, files = manifest['backend'], manifest['files']
            target.mkdir(mode=0o700)
            owned = _stamp(target.lstat())[:2]
            for relative, expected in files.items():
                data = archive.read('workspace/' + relative)
                path = target / relative
                path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                with path.open('xb') as output:
                    path.chmod(0o600)
                    output.write(data)
            _verify_captured(target, files)
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
        from threaddesk.storage.library_backup import validate
        validate(target / 'library-files')
        # Preserve this installation's listening port, never import another
        # machine's port. Housekeeper remains off until explicitly enabled.
        active, _ = selected_profile(root)
        with _SourceTree(active) as source:
            inventory = source.scan(lambda name: name == 'desktop-port.json', lambda _: False)
            if 'desktop-port.json' in inventory:
                port = source.read('desktop-port.json', inventory['desktop-port.json'], limit=LIMIT)
                with (target / 'desktop-port.json').open('xb') as output:
                    output.write(port)
        caretaker = target / 'hausmeister.json'
        if caretaker.exists():
            data = json.loads(caretaker.read_text(encoding='utf-8'))
            data['enabled'] = False
            caretaker.write_text(json.dumps(data), encoding='utf-8')
        with (target / '.profile-info.json').open('x', encoding='utf-8') as output:
            output.write(json.dumps({'backend': backend, 'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}))
        temporary = root / ('profile-' + uuid4().hex + '.tmp')
        with temporary.open('x', encoding='utf-8') as output:
            output.write(json.dumps({'name': name, 'backend': backend}))
        temporary.replace(root / 'active-profile.json')
        return target
    except Exception as exc:
        _cleanup_owned(target, owned)
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
