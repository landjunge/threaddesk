"""Private binding reporter identity migration; file checkpoints stay root-bound."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import sqlite3
import stat
import uuid

from threaddesk.server_sync.store import SyncError, validate_path


class IdentityError(ValueError):
    pass


def validate_device_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        raise IdentityError('Invalid synchronization device identifier')
    return value


def checkpoint_identity(url, project_id, root, token):
    return hashlib.sha256((url.rstrip('/') + '\0' + project_id + '\0' + str(root)
                           + '\0' + hashlib.sha256(token.encode()).hexdigest()).encode()).hexdigest()


def validate_initial_bases(value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 20000:
        raise IdentityError('Invalid initial committed bases')
    clean, seen = [], set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {'path', 'revision', 'sha256'}:
            raise IdentityError('Invalid committed base record')
        try:
            path = validate_path(item['path'])
            revision = validate_device_id(item['revision'])
        except (SyncError, IdentityError, UnicodeError) as exc:
            raise IdentityError('Invalid committed base scope') from exc
        if path in seen or not isinstance(item['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', item['sha256']):
            raise IdentityError('Invalid committed base hash or duplicate path')
        seen.add(path)
        clean.append({'path': path, 'revision': revision, 'sha256': item['sha256']})
    return clean


def _old_checkpoint(private_root, thread_id, config):
    if not isinstance(thread_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', thread_id):
        raise IdentityError('Invalid thread identifier')
    if not config or not config.get('project_id'):
        return None, None
    url, pid, root, token = (config.get(key) for key in ('url', 'project_id', 'root', 'token'))
    if not all(isinstance(value, str) and value for value in (url, pid, root, token)):
        raise IdentityError('Incomplete synchronization binding identity')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', pid) or not Path(root).is_absolute():
        raise IdentityError('Invalid synchronization binding scope')
    # Stored roots are already canonical. Do not resolve a moved/deleted root:
    # that would bind migration to its replacement rather than its saved scope.
    stored_root = str(Path(root))
    remote = url.rstrip('/') + '\0' + pid + '\0' + hashlib.sha256(token.encode()).hexdigest()
    state = Path(private_root).absolute() / 'replicas' / thread_id / hashlib.sha256(remote.encode()).hexdigest()
    current = state / 'files' / hashlib.sha256(stored_root.encode()).hexdigest() / 'checkpoint.sqlite3'
    legacy = state / 'files' / 'checkpoint.sqlite3'
    for candidate in (current, legacy):
        if any(parent.is_symlink() for parent in (candidate, *candidate.parents)):
            raise IdentityError('Unsafe synchronization checkpoint path')
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077
                or hasattr(os, 'getuid') and info.st_uid != os.getuid()):
            raise IdentityError('Synchronization checkpoint must be a private regular file')
        return candidate, checkpoint_identity(url, pid, stored_root, token)
    return None, None


def _read_checkpoint(private_root, thread_id, config):
    path, expected = _old_checkpoint(private_root, thread_id, config)
    if path is None:
        return None
    try:
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        try:
            db.execute('BEGIN')
            identities = db.execute('SELECT value FROM identity').fetchall()
            devices = db.execute('SELECT id FROM device').fetchall()
            if identities != [(expected,)] or len(devices) != 1:
                raise IdentityError('Existing checkpoint belongs to a different binding or is incomplete')
            device = validate_device_id(devices[0][0])
            if 'device_id' in config and validate_device_id(config['device_id']) != device:
                raise IdentityError('Saved binding device differs from its checkpoint')
            bases = validate_initial_bases([dict(zip(('path', 'revision', 'sha256'), row)) for row in
                                           db.execute('SELECT path,revision,sha256 FROM base ORDER BY path')])
            return {'device_id': device, 'bases': bases}
        finally:
            db.close()
    except sqlite3.Error as exc:
        raise IdentityError('Existing synchronization checkpoint cannot be safely migrated') from exc


def recover_binding_device_id(private_root, thread_id, old_config):
    """Recover the saved reporter; an existing uncertain DB never creates a new one.

    Only the explicit old URL/project/root/token identity is accepted. Root-specific
    checkpoints take precedence over legacy ``files/checkpoint.sqlite3``. Reads
    use SQLite read-only mode and do not rebind or edit the old checkpoint.
    """
    config = old_config or {}
    if 'device_id' in config:
        return validate_device_id(config['device_id'])
    saved = _read_checkpoint(private_root, thread_id, config)
    return saved['device_id'] if saved else uuid.uuid4().hex


def recover_binding_bases(private_root, thread_id, old_config):
    """Read only committed common revisions; never copy uploads or source grants."""
    saved = _read_checkpoint(private_root, thread_id, old_config or {})
    return saved['bases'] if saved else []
