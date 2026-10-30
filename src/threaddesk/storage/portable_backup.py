"""Streaming portable backups; verified restore into a separate profile."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4

from threaddesk.core.errors import InvalidState
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.portable_stream import (
    FLEX_DIRS,
    check_member_names,
    checked_links,
    copy_hash,
    input_file,
    limits,
    preflight_zip,
    safe_relative,
    scan,
)
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.storage.workspace_backup import (
    BackupError,
    _cleanup_owned,
    _publish_new,
    _SourceTree,
    _stamp,
    _verify_captured,
)

LIMIT = 8 * 1024 * 1024 * 1024
LEGACY_LIMIT = 128 * 1024 * 1024
MAX_FILES = 200000
MANIFEST_LIMIT = 32 * 1024 * 1024
DATA_DIRS = {'threads', 'snapshots', 'nodes', 'relations', 'graph-events',
             'source-records', 'whiteboard', 'artifacts', 'imports',
             'management-operations', 'thread-revisions', 'issued-handoffs', 'library-files', 'trash',
             'grok-runtime', 'authority-live-watch', 'handoffs'} | set(FLEX_DIRS)
RUNTIME_FILES = {'desktop-port.json', 'desktop.lock', 'active-profile.json', 'graph-view-control.json'}
POINT_IN_TIME_FILES = frozenset({'library-watch.json'})
HIDDEN_DATA_DIRS = FLEX_DIRS | {'grok-runtime', 'authority-live-watch', 'handoffs'}


def base_root() -> Path:
    from threaddesk.storage import json_store
    return Path(os.environ.get('THREADDESK_HOME') or json_store.DEFAULT_ROOT)


def selected_profile(root: Path) -> tuple[Path, str | None]:
    marker = root / 'active-profile.json'
    if not marker.exists():
        return root, None
    try:
        if marker.is_symlink():
            raise ValueError('profile')
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
        safe_relative(name)
    except BackupError:
        if strict:
            raise
        return False
    if any(p.startswith('.') for p in path.parts) and path.parts[0] not in HIDDEN_DATA_DIRS:
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


def _inherited_links(tree, inventory, direct_links, max_manifest_bytes):
    # Restored links remain inert across subsequent exports. This hidden profile
    # metadata is read through the same pinned descriptor boundary, never used
    # to resolve a source pathname or to create a link.
    try:
        expected = tree.info('.profile-info.json')
    except FileNotFoundError:
        return {}
    info = json.loads(tree.read('.profile-info.json', expected, limit=max_manifest_bytes))
    links = checked_links(info.get('inert_symlinks', {}))
    leaves = {name.casefold() for name in (*inventory, *direct_links)}
    occupied = set(leaves)
    for name in (*inventory, *direct_links, *getattr(tree, 'directories', {})):
        occupied.add(name.casefold())
        occupied.update(parent.as_posix().casefold() for parent in PurePosixPath(name).parents if parent.as_posix() != '.')
    result = {}
    for name, value in links.items():
        if (name.casefold() not in occupied
                and not any(parent.as_posix().casefold() in leaves for parent in PurePosixPath(name).parents if parent.as_posix() != '.')):
            result[name] = value
    return result


def _reservation_identity(workspace_id, reservation):
    from threaddesk.services.commands.validation import ID, command_request_digest
    if (not isinstance(reservation, dict) or set(reservation) != {'operation_id', 'expected_revision'}
            or not isinstance(reservation['operation_id'], str) or not ID.fullmatch(reservation['operation_id'])
            or reservation['expected_revision'] is not None and (
                type(reservation['expected_revision']) is not int or reservation['expected_revision'] < 0)):
        raise BackupError('Invalid command backup reservation binding.')
    operation = reservation['operation_id']
    key = 'command-' + hashlib.sha256(operation.encode()).hexdigest() + '-pending'
    digest = command_request_digest(workspace_id, 'backup.create', {}, operation, reservation['expected_revision'])
    return key, digest


def _command_snapshot_boundary(store, reservation, tree, inventory):
    """Only dispatch's exact current backup export is outside its own snapshot.

    The source receipt remains durable and completes after publication. No
    other pending operation or previous backup is inferred safe to discard.
    """
    if reservation is None:
        return None, None
    from threaddesk.services.commands.model import workspace_identity
    workspace_id = workspace_identity(store)
    key, digest = _reservation_identity(workspace_id, reservation)
    def read_record(identity):
        if isinstance(store, SQLiteStore):
            row = store.connection.execute('SELECT payload FROM management_operations WHERE id=?', (identity,)).fetchone()
            if row is None:
                return None
            if len(row[0].encode()) > 65536:
                raise BackupError('Invalid command backup reservation record size.')
            value = json.loads(row[0])
        else:
            name = 'management-operations/' + identity + '.json'
            expected = inventory.get(name)
            if expected is None:
                if name in tree.directories:
                    raise BackupError('Nonregular command backup reservation record.')
                return None
            value = json.loads(tree.read(name, expected, limit=65536))
        if not isinstance(value, dict):
            raise BackupError('Invalid command backup reservation record.')
        return value
    record = read_record(key)
    fields = {'request_hash', 'recorded_at', 'state', 'result', 'error', 'kind', 'storage_operation_id'}
    if (not isinstance(record, dict) or set(record) != fields or record['kind'] != 'command'
            or record['state'] != 'pending' or record['storage_operation_id'] != key
            or record['request_hash'] != digest or record['result'] is not None or record['error'] is not None
            or not isinstance(record['recorded_at'], str) or not record['recorded_at']
            or any(read_record(key.removesuffix('-pending') + '-' + state) is not None
                   for state in ('complete', 'failed'))):
        raise BackupError('Command backup reservation does not match its in-flight export.')
    boundary = {'command': 'backup.create', **reservation, 'workspace_id': workspace_id,
                'storage_operation_id': key, 'request_hash': digest,
                'record_sha256': hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':'),
                                                         ensure_ascii=False).encode()).hexdigest(),
                'reason': 'own_in_flight_export', 'source_record_preserved': True}
    return boundary, record


def export_backup(store, target: Path, *, max_bytes=LIMIT, max_files=MAX_FILES,
                  max_manifest_bytes=MANIFEST_LIMIT, command_reservation=None) -> dict:
    """Publish one bounded ZIP64 file, without overwriting a destination.

    Existing JSON stores retain their transaction/snapshot boundary. A caller
    supplying a read-only workspace_path source receives the same descriptor,
    inventory and comparison-hash checks without constructing a live JsonStore.
    """
    limits(max_bytes, max_files, max_manifest_bytes)
    target = Path(target).absolute()
    source = Path(store.workspace_path).resolve()
    destination = target.parent.resolve(strict=True) / target.name
    if destination == source or source in destination.parents:
        raise BackupError('Backup destination must be outside its source workspace.')
    if target.exists() or target.is_symlink():
        raise BackupError('Backup destination already exists.')
    try:
        if isinstance(store, JsonStore):
            with store.transaction():
                return _export_backup(store, target, max_bytes, max_files, max_manifest_bytes, command_reservation)
        return _export_backup(store, target, max_bytes, max_files, max_manifest_bytes, command_reservation)
    except BackupError:
        raise
    except (OSError, ValueError, TypeError, InvalidState, zipfile.BadZipFile) as exc:
        raise BackupError('Backup source cannot be read safely.') from exc


def _export_backup(store, target, max_bytes, max_files, max_manifest_bytes, command_reservation=None):
    backend = 'sqlite' if isinstance(store, SQLiteStore) else 'json'
    with tempfile.TemporaryDirectory(prefix='threaddesk-backup-') as temp:
        stage = Path(temp)
        zip_path = stage / 'backup.zip'
        library_stage = stage / 'library-capture'
        files, symlinks = {}, {}
        total = 0
        source = Path(store.workspace_path)
        def allowed(name):
            return not name.startswith('library-files/') and _allowed(name, backend, strict=True)
        def descend(name):
            return PurePosixPath(name).parts[0] in DATA_DIRS - {'library-files'}
        with _SourceTree(source) as tree:
            inventory, direct_links, directories = scan(tree, allowed, descend, max_entries=max_files)
            boundary, pending_record = _command_snapshot_boundary(store, command_reservation, tree, inventory)
            omitted = 'management-operations/' + boundary['storage_operation_id'] + '.json' if boundary else None
            if boundary and backend == 'json' and omitted not in inventory:
                raise BackupError('Command backup reservation file is missing from its source inventory.')
            inherited = _inherited_links(tree, inventory, direct_links, max_manifest_bytes)
            symlinks = {**inherited, **{name: {'target': row['target']} for name, row in direct_links.items()}}
            if len(inventory) + len(symlinks) + len(directories) + 1 > max_files:
                raise BackupError('Backup exceeds the file limit.')
            sqlite_snapshot = None
            version_before = changes_before = None
            if backend == 'sqlite':
                import sqlite3
                identity = tree.info('threaddesk.sqlite3')
                version_before = store.connection.execute('PRAGMA data_version').fetchone()[0]
                changes_before = store.connection.total_changes
                sqlite_snapshot = stage / 'threaddesk.sqlite3'
                with tree.open('threaddesk.sqlite3', identity):
                    connection = sqlite3.connect(sqlite_snapshot)
                    try:
                        store.connection.backup(connection)
                        if boundary:
                            key = boundary['storage_operation_id']
                            row = connection.execute('SELECT payload FROM management_operations WHERE id=?', (key,)).fetchone()
                            if row is None or json.loads(row[0]) != pending_record:
                                raise BackupError('Command backup reservation changed in the private snapshot.')
                            with connection:
                                changes = connection.total_changes
                                removed = connection.execute('DELETE FROM management_operations WHERE id=? AND payload=?', (key, row[0]))
                                if removed.rowcount != 1 or connection.total_changes - changes != 1:
                                    raise BackupError('Command backup snapshot reservation could not be isolated.')
                    finally:
                        connection.close()
            omitted_digest = None
            with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                for name, expected in inventory.items():
                    if backend == 'json' and name == omitted:
                        raw = tree.read(name, expected, limit=65536)
                        if json.loads(raw) != pending_record:
                            raise BackupError('Command backup reservation changed during capture.')
                        omitted_digest = {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                        continue
                    if name in POINT_IN_TIME_FILES:
                        expected = tree.info(name)
                    with archive.open('workspace/' + name, 'w', force_zip64=True) as output:
                        if name == 'threaddesk.sqlite3' and sqlite_snapshot is not None:
                            with sqlite_snapshot.open('rb') as incoming:
                                row = copy_hash(incoming, output, limit=max_bytes - total)
                        else:
                            with tree.open(name, expected) as incoming:
                                row = copy_hash(incoming, output, limit=max_bytes - total)
                    files[name] = row
                    total += row['size']
                from threaddesk.storage.library_backup import allowed as library_allowed
                from threaddesk.storage.library_backup import capture
                from threaddesk.storage.library_backup import descend as library_descend
                has_library = capture(source, library_stage, limit=max_bytes - total, source_tree=tree)
                library_directories = {'library-files', 'library-files/blobs', 'library-files/records'}
                directories.update({name: () for name in tree.directories if name in library_directories})
                if len(files) + len(symlinks) + len(directories) + 1 > max_files:
                    raise BackupError('Backup exceeds the file limit.')
                if has_library:
                    with _SourceTree(library_stage) as library:
                        library_inventory = library.scan(library_allowed, library_descend)
                        for name, expected in library_inventory.items():
                            if len(files) + len(symlinks) + len(directories) + 2 > max_files:
                                raise BackupError('Backup exceeds the file limit.')
                            with library.open(name, expected) as incoming, archive.open('workspace/' + name, 'w', force_zip64=True) as output:
                                row = copy_hash(incoming, output, limit=max_bytes - total)
                            files[name] = row
                            total += row['size']
                after_files, after_links, after_dirs = scan(tree, allowed, descend, max_entries=max_files)
                stable_before = {name: row for name, row in inventory.items() if name not in POINT_IN_TIME_FILES}
                stable_after = {name: row for name, row in after_files.items() if name not in POINT_IN_TIME_FILES}
                source_dirs = {name: value for name, value in directories.items() if not name.startswith('library-files')}
                if stable_after != stable_before or after_links != direct_links or after_dirs != source_dirs:
                    raise BackupError('Workspace changed during backup. Please try again.')
                # Hash the same bound regular files again. Memory remains one
                # chunk even for multi-gigabyte artifacts; equal bytes at a new
                # inode still fail the source descriptor checks.
                for name, expected in inventory.items():
                    if name in POINT_IN_TIME_FILES:
                        continue
                    if name == 'threaddesk.sqlite3' and backend == 'sqlite':
                        continue
                    with tree.open(name, expected) as incoming:
                        expected_hash = omitted_digest if backend == 'json' and name == omitted else files[name]
                        if copy_hash(incoming, limit=max_bytes) != expected_hash:
                            raise BackupError('Workspace changed during backup. Please try again.')
                if backend == 'sqlite' and (store.connection.execute('PRAGMA data_version').fetchone()[0] != version_before
                                           or store.connection.total_changes != changes_before):
                    raise BackupError('Workspace changed during backup. Please try again.')
                if _inherited_links(tree, inventory, direct_links, max_manifest_bytes) != inherited:
                    raise BackupError('Restored link metadata changed during backup.')
                final_files, final_links, final_dirs = scan(tree, allowed, descend, max_entries=max_files)
                if ({name: value for name, value in final_files.items() if name not in POINT_IN_TIME_FILES} != stable_before
                        or final_links != direct_links or final_dirs != source_dirs):
                    raise BackupError('Workspace changed during backup. Please try again.')
                check_member_names(files, symlinks, directories)
                manifest = {'kind': 'threaddesk.portable-backup', 'version': 3,
                            'backend': backend, 'files': files, 'symlinks': symlinks,
                            'directories': sorted(directories),
                            'consistency': {name: 'point_in_time' for name in POINT_IN_TIME_FILES if name in files}}
                if boundary:
                    manifest['snapshot_boundary'] = boundary
                manifest_body = json.dumps(manifest, sort_keys=True).encode('utf-8')
                if len(manifest_body) > max_manifest_bytes or total + len(manifest_body) > max_bytes:
                    raise BackupError('Backup manifest or data exceeds the size limit.')
                archive.writestr('manifest.json', manifest_body)
            if zip_path.stat().st_size > max_bytes:
                raise BackupError('Backup exceeds the size limit.')
            # Output is first fully completed and verified, then copied into a
            # private file in the destination directory and published NOREPLACE.
            handle, temporary = tempfile.mkstemp(prefix='.threaddesk-backup-', dir=target.parent)
            try:
                with os.fdopen(handle, 'wb') as output, zip_path.open('rb') as incoming:
                    os.fchmod(output.fileno(), 0o600)
                    summary_hash = copy_hash(incoming, output, limit=max_bytes)
                    output.flush()
                    os.fsync(output.fileno())
                verified = inspect_backup(Path(temporary), max_bytes=max_bytes, max_files=max_files,
                                          max_manifest_bytes=max_manifest_bytes)
                if verified['sha256'] != summary_hash['sha256']:
                    raise BackupError('Backup output changed during publication.')
                _publish_new(Path(temporary), target)
            finally:
                Path(temporary).unlink(missing_ok=True)
        return _summary(manifest, summary_hash, max_bytes, max_files, max_manifest_bytes)


def download_backup(store) -> bytes:
    """Compatibility wrapper; large callers must use file-backed export_backup."""
    with tempfile.TemporaryDirectory(prefix='threaddesk-backup-download-') as temp:
        path = Path(temp) / 'backup.zip'
        export_backup(store, path, max_bytes=LIMIT)
        if path.stat().st_size > LEGACY_LIMIT:
            raise BackupError('Backup exceeds the legacy bytes limit; use export_backup with a file destination.')
        with path.open('rb') as incoming:
            return incoming.read(LEGACY_LIMIT + 1)


def _checked_manifest(archive, *, max_bytes=LIMIT, max_files=MAX_FILES,
                      max_manifest_bytes=MANIFEST_LIMIT):
    members = archive.infolist()
    if len(members) > max_files or sum(m.file_size for m in members) > max_bytes:
        raise BackupError('Backup exceeds the size limit or file limit.')
    names = [member.filename for member in members]
    if len(names) != len(set(names)) or 'manifest.json' not in names:
        raise BackupError('Invalid backup manifest.')
    if archive.getinfo('manifest.json').file_size > max_manifest_bytes:
        raise BackupError('Backup manifest exceeds the size limit.')
    with archive.open('manifest.json') as incoming:
        raw = incoming.read(max_manifest_bytes + 1)
    if len(raw) > max_manifest_bytes:
        raise BackupError('Backup manifest exceeds the size limit.')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise BackupError('Duplicate backup manifest key.')
            result[key] = value
        return result
    manifest = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(manifest, dict):
        raise BackupError('Invalid backup manifest.')
    backend, files = manifest.get('backend'), manifest.get('files')
    if (manifest.get('kind') != 'threaddesk.portable-backup' or type(manifest.get('version')) is not int
            or manifest['version'] not in {1, 2, 3} or backend not in {'json', 'sqlite'} or not isinstance(files, dict)):
        raise BackupError('Unknown backup format.')
    if 'snapshot_boundary' in manifest:
        boundary = manifest['snapshot_boundary']
        fields = {'command', 'operation_id', 'expected_revision', 'workspace_id', 'storage_operation_id',
                  'request_hash', 'record_sha256', 'reason', 'source_record_preserved'}
        if (manifest['version'] != 3 or not isinstance(boundary, dict) or set(boundary) != fields
                or boundary['command'] != 'backup.create' or boundary['reason'] != 'own_in_flight_export'
                or boundary['source_record_preserved'] is not True
                or not isinstance(boundary['workspace_id'], str) or not boundary['workspace_id'].startswith('ws-')
                or len(boundary['workspace_id']) != 35
                or any(c not in '0123456789abcdef' for c in boundary['workspace_id'][3:])
                or not isinstance(boundary['record_sha256'], str) or len(boundary['record_sha256']) != 64
                or any(c not in '0123456789abcdef' for c in boundary['record_sha256'])):
            raise BackupError('Invalid command backup snapshot boundary.')
        key, digest = _reservation_identity(boundary['workspace_id'],
            {name: boundary[name] for name in ('operation_id', 'expected_revision')})
        if (boundary['storage_operation_id'] != key or boundary['request_hash'] != digest
                or backend == 'json' and 'management-operations/' + key + '.json' in files):
            raise BackupError('Command backup snapshot boundary does not match its archive.')
    symlinks = checked_links(manifest.get('symlinks', {}))
    directories = manifest.get('directories', [])
    if (not isinstance(directories, list) or any(not isinstance(name, str) for name in directories)
            or len(set(directories)) != len(directories)):
        raise BackupError('Invalid backup directories.')
    for directory in directories:
        parts = safe_relative(directory)
        if (parts[0] not in DATA_DIRS or any(part.startswith('.') for part in parts) and parts[0] not in HIDDEN_DATA_DIRS
                or parts[0] == 'library-files' and directory not in {'library-files', 'library-files/blobs', 'library-files/records'}):
            raise BackupError('Invalid backup directory path.')
    consistency = manifest.get('consistency', {})
    if (not isinstance(consistency, dict) or set(consistency) - (set(files) & POINT_IN_TIME_FILES)
            or any(value != 'point_in_time' for value in consistency.values())):
        raise BackupError('Invalid backup consistency metadata.')
    if manifest['version'] < 3 and (symlinks or directories or consistency):
        raise BackupError('Inert links, directories and consistency metadata require portable backup version 3.')
    if len(files) + len(symlinks) + len(directories) + 1 > max_files:
        raise BackupError('Backup exceeds the file limit.')
    if manifest['version'] < 2 and any(name.startswith('library-files/') for name in files):
        raise BackupError('Library files require portable backup version 2.')
    if set(names) != {'manifest.json'} | {'workspace/' + name for name in files}:
        raise BackupError('Unexpected backup files.')
    if any(not _allowed(name, backend) for name in files):
        raise BackupError('Invalid backup path.')
    # v1/v2 permitted distinct-case files on case-sensitive destinations. Keep
    # those archives readable; exclusive writes and post-copy inventory still
    # reject aliases on a destination that cannot represent both originals.
    check_member_names(files, symlinks, directories, legacy_case_sensitive=manifest['version'] < 3)
    for member in members:
        kind = stat.S_IFMT(member.external_attr >> 16)
        if kind not in {0, stat.S_IFREG} or member.is_dir() or member.flag_bits & 1:
            raise BackupError('Only unencrypted regular ZIP members are allowed.')
    for relative, expected in files.items():
        if (not isinstance(expected, dict) or type(expected.get('size')) is not int or expected['size'] < 0
                or not isinstance(expected.get('sha256'), str) or len(expected['sha256']) != 64
                or any(char not in '0123456789abcdef' for char in expected['sha256'])):
            raise BackupError('Invalid backup checksum metadata.')
        member = archive.getinfo('workspace/' + relative)
        if member.file_size != expected['size']:
            raise BackupError('Backup checksum size does not match.')
        with archive.open(member) as incoming:
            if copy_hash(incoming, limit=expected['size']) != expected:
                raise BackupError('Backup checksum does not match.')
    if backend == 'sqlite' and 'threaddesk.sqlite3' not in files:
        raise BackupError('Missing workspace database.')
    return manifest


def _summary(manifest, digest, max_bytes, max_files, max_manifest_bytes):
    return {'kind': manifest['kind'], 'version': manifest['version'], 'backend': manifest['backend'],
            'files': len(manifest['files']), 'bytes': digest['size'], 'sha256': digest['sha256'],
            'symlinks': len(manifest.get('symlinks', {})), 'verified': True,
            'directories': len(manifest.get('directories', [])),
            'point_in_time_files': sorted(manifest.get('consistency', {})),
            'limits': {'bytes': max_bytes, 'files': max_files, 'manifest_bytes': max_manifest_bytes},
            'restore_behavior': 'new_separate_profile; symlinks remain inert metadata',
            'verification_scope': 'archive_paths_sizes_and_checksums; restore validates workspace models separately',
            **({'snapshot_boundary': dict(manifest['snapshot_boundary'])} if 'snapshot_boundary' in manifest else {})}


def inspect_backup(source, *, max_bytes=LIMIT, max_files=MAX_FILES,
                   max_manifest_bytes=MANIFEST_LIMIT) -> dict:
    """Verify bytes/path/seekable input without extraction or activation."""
    limits(max_bytes, max_files, max_manifest_bytes)
    try:
        with input_file(source, limit=max_bytes) as (handle, size):
            preflight_zip(handle, size, max_files=max_files, max_manifest_bytes=max_manifest_bytes)
            with zipfile.ZipFile(handle) as archive:
                manifest = _checked_manifest(archive, max_bytes=max_bytes, max_files=max_files,
                                             max_manifest_bytes=max_manifest_bytes)
            handle.seek(0)
            digest = copy_hash(handle, limit=max_bytes)
        return _summary(manifest, digest, max_bytes, max_files, max_manifest_bytes)
    except Exception as exc:
        if isinstance(exc, BackupError):
            raise
        raise BackupError('Backup could not be opened.') from exc


def restore_backup(source, root: Path, *, max_bytes=LIMIT, max_files=MAX_FILES,
                   max_manifest_bytes=MANIFEST_LIMIT, expected_sha256=None) -> Path:
    limits(max_bytes, max_files, max_manifest_bytes)
    root = Path(root)
    if root.is_symlink() or (root / 'profiles').is_symlink():
        raise BackupError('Invalid profile directory.')
    root.mkdir(parents=True, exist_ok=True)
    profiles_dir = root / 'profiles'
    profiles_dir.mkdir(mode=0o700, exist_ok=True)
    if root.is_symlink() or profiles_dir.is_symlink():
        raise BackupError('Invalid profile directory.')
    name = uuid4().hex
    target = profiles_dir / name
    owned = None
    try:
        with input_file(source, limit=max_bytes) as (handle, size):
            preflight_zip(handle, size, max_files=max_files, max_manifest_bytes=max_manifest_bytes)
            with zipfile.ZipFile(handle) as archive:
                manifest = _checked_manifest(archive, max_bytes=max_bytes, max_files=max_files,
                                             max_manifest_bytes=max_manifest_bytes)
                backend, files = manifest['backend'], manifest['files']
                target.mkdir(mode=0o700)
                owned = _stamp(target.lstat())[:2]
                for directory in manifest.get('directories', []):
                    (target / directory).mkdir(mode=0o700, parents=True, exist_ok=True)
                for relative, expected in files.items():
                    path = target / relative
                    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                    with archive.open('workspace/' + relative) as incoming, path.open('xb') as output:
                        path.chmod(0o600)
                        if copy_hash(incoming, output, limit=expected['size']) != expected:
                            raise BackupError('Backup checksum does not match.')
                _verify_captured(target, files)
                if expected_sha256 is not None:
                    handle.seek(0)
                    if copy_hash(handle, limit=max_bytes)['sha256'] != expected_sha256:
                        raise BackupError('Backup checksum changed since preview.')
        # Source descriptor checks complete BEFORE profile selection changes.
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
            if current and current not in {thread.id for thread in threads}:
                raise BackupError('Invalid active thread.')
        finally:
            if backend == 'sqlite':
                store.connection.close()
        from threaddesk.storage.library_backup import validate
        validate(target / 'library-files')
        active, _ = selected_profile(root)
        with _SourceTree(active) as tree:
            inventory = tree.scan(lambda name: name == 'desktop-port.json', lambda _: False)
            if 'desktop-port.json' in inventory:
                port = tree.read('desktop-port.json', inventory['desktop-port.json'], limit=1024)
                with (target / 'desktop-port.json').open('xb') as output:
                    output.write(port)
        caretaker = target / 'hausmeister.json'
        if caretaker.exists():
            data = json.loads(caretaker.read_text(encoding='utf-8'))
            data['enabled'] = False
            caretaker.write_text(json.dumps(data), encoding='utf-8')
        with (target / '.profile-info.json').open('x', encoding='utf-8') as output:
            output.write(json.dumps({'backend': backend, 'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                                     'inert_symlinks': manifest.get('symlinks', {})}))
        temporary = root / ('profile-' + uuid4().hex + '.tmp')
        try:
            with temporary.open('x', encoding='utf-8') as output:
                output.write(json.dumps({'name': name, 'backend': backend}))
            temporary.replace(root / 'active-profile.json')
        finally:
            temporary.unlink(missing_ok=True)
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
            if len(path.name) == 32 and all(char in '0123456789abcdef' for char in path.name) and info['backend'] in {'json', 'sqlite'}:
                result.append({'name': path.name, 'backend': info['backend'], 'created_at': info.get('created_at'),
                               'inert_symlink_count': len(info.get('inert_symlinks', {}))})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return result


def activate_profile(root: Path, name: str) -> None:
    if name not in {profile['name'] for profile in profiles(root)}:
        raise BackupError('Unknown workspace.')
    temporary = root / ('profile-' + uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as output:
            output.write(json.dumps({'name': name, 'backend': next(profile['backend'] for profile in profiles(root) if profile['name'] == name)}))
        temporary.replace(root / 'active-profile.json')
    finally:
        temporary.unlink(missing_ok=True)
