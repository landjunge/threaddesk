"""Tenant-scoped inert project content with durable transfers and immutable history."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
import uuid

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_CHUNK_BYTES = 256 * 1024
MAX_TENANT_BYTES = 1024 * 1024 * 1024
MAX_ACTIVE_TRANSFERS = 32
MAX_RESERVED_BYTES = 512 * 1024 * 1024
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_SECRET = re.compile(r"(?i)(^|[._-])(credentials?|secrets?|id_rsa|id_dsa|id_ecdsa|id_ed25519|cookies)($|[._-])|\.(pem|key|p12|pfx|kdbx)$")


class SyncError(Exception):
    def __init__(self, message, code='invalid', status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def _id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise SyncError('Invalid identifier')
    return value


def _path(value):
    if (not isinstance(value, str) or not value or len(value) > 2048
            or '\\' in value or ':' in value or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise SyncError('Unsafe project path', 'unsafe_path')
    try:
        if len(value.encode('utf-8')) > 2048:
            raise SyncError('Unsafe project path', 'unsafe_path')
    except UnicodeEncodeError as exc:
        raise SyncError('Unsafe project path', 'unsafe_path') from exc
    parts = value.split('/')
    if any(p in {'', '.', '..'} or p.casefold() in {'.git', '.svn', '.hg', '.ssh', '.aws', '.gnupg', '.netrc', '.npmrc', '.pypirc', '.threaddesk-sync-conflicts'}
           or p.casefold().startswith('.td-sync-')
           or p.casefold() == '.env' or p.casefold().startswith('.env.') or _SECRET.search(p) for p in parts):
        raise SyncError('Unsafe project path', 'unsafe_path')
    return value


validate_path = _path


def _path_collision(first, second):
    """Reject aliases at any shared directory and file/directory ambiguity."""
    if first == second:
        return False
    left, right = first.split('/'), second.split('/')
    for a, b in zip(left, right):
        if unicodedata.normalize('NFC', a).casefold() != unicodedata.normalize('NFC', b).casefold():
            return False
        if a != b:
            return True
    return True


def _size_hash(size, digest):
    if type(size) is not int or not 0 <= size <= MAX_FILE_BYTES:
        raise SyncError('Invalid file size')
    if not isinstance(digest, str) or not _HASH.fullmatch(digest):
        raise SyncError('Invalid SHA-256')


class SyncStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        if self.root.is_symlink():
            raise SyncError('Unsafe tenant directory', 'unsafe_store')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db_path = self.root / 'sync.sqlite3'
        if self.db_path.is_symlink():
            raise SyncError('Unsafe tenant database', 'unsafe_store')
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,title TEXT NOT NULL,offline INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS manifests(project TEXT,device TEXT,files TEXT NOT NULL,issues TEXT NOT NULL,PRIMARY KEY(project,device));
                CREATE TABLE IF NOT EXISTS versions(revision TEXT PRIMARY KEY,project TEXT NOT NULL,path TEXT NOT NULL,sha256 TEXT NOT NULL,size INTEGER NOT NULL,body BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS heads(project TEXT,path TEXT,revision TEXT,PRIMARY KEY(project,path,revision));
                CREATE TABLE IF NOT EXISTS uploads(project TEXT,transfer TEXT,path TEXT NOT NULL,size INTEGER NOT NULL,sha256 TEXT NOT NULL,base TEXT,state TEXT NOT NULL,offset INTEGER NOT NULL DEFAULT 0,receipt TEXT,PRIMARY KEY(project,transfer));
                CREATE TABLE IF NOT EXISTS chunks(project TEXT,transfer TEXT,offset INTEGER,body BLOB NOT NULL,PRIMARY KEY(project,transfer,offset));
            ''')
            if 'updated_at' not in {r['name'] for r in db.execute('PRAGMA table_info(manifests)')}:
                db.execute("ALTER TABLE manifests ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")

    @contextmanager
    def _db(self):
        if self.db_path.is_symlink():
            raise SyncError('Unsafe tenant database', 'unsafe_store')
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _project(self, db, project_id):
        row = db.execute('SELECT * FROM projects WHERE id=?', (_id(project_id),)).fetchone()
        if row is None:
            raise SyncError('Project not found', 'not_found', 404)
        return {'id': row['id'], 'title': row['title'], 'offline_enabled': bool(row['offline'])}

    def create_project(self, title, project_id=None):
        if not isinstance(title, str) or not title.strip() or len(title) > 500:
            raise SyncError('Invalid project title')
        project_id = _id(project_id) if project_id is not None else uuid.uuid4().hex
        with self._db() as db:
            if db.execute('SELECT 1 FROM projects WHERE id=?', (project_id,)).fetchone():
                raise SyncError('Project already exists', 'conflict', 409)
            db.execute('INSERT INTO projects(id,title) VALUES (?,?)', (project_id, title))
            return self._project(db, project_id)

    def projects(self):
        with self._db() as db:
            return [self._project(db, row[0]) for row in db.execute('SELECT id FROM projects ORDER BY id').fetchall()]

    def project(self, project_id):
        with self._db() as db:
            return self._project(db, project_id)

    def set_offline(self, project_id, enabled):
        if type(enabled) is not bool:
            raise SyncError('enabled must be boolean')
        with self._db() as db:
            self._project(db, project_id)
            db.execute('UPDATE projects SET offline=? WHERE id=?', (int(enabled), project_id))
            return self._project(db, project_id)

    def declare_manifest(self, project_id, files, issues, device_id):
        _id(device_id)
        if not isinstance(files, list) or len(files) > 20000:
            raise SyncError('Invalid manifest')
        if (not isinstance(issues, list) or len(issues) > 2000
                or any(not isinstance(v, str) or not v or len(v) > 2000 for v in issues)):
            raise SyncError('Invalid manifest issues')
        clean = []
        seen = set()
        folded = set()
        for f in files:
            if not isinstance(f, dict) or set(f) != {'path', 'sha256', 'size'}:
                raise SyncError('Invalid manifest file')
            path = _path(f['path'])
            _size_hash(f['size'], f['sha256'])
            portable = unicodedata.normalize('NFC', path).casefold()
            if path in seen or portable in folded:
                raise SyncError('Duplicate or ambiguous manifest path')
            if any(_path_collision(path, previous) for previous in seen):
                raise SyncError('File and directory paths conflict')
            seen.add(path)
            folded.add(portable)
            clean.append(dict(f))
        with self._db() as db:
            self._project(db, project_id)
            db.execute('INSERT OR REPLACE INTO manifests(project,device,files,issues,updated_at) VALUES (?,?,?,?,?)',
                       (project_id, device_id, json.dumps(clean), json.dumps(issues), datetime.now(timezone.utc).isoformat()))
            return self._status(db, project_id)

    def _files(self, db, project_id):
        rows = db.execute('SELECT h.path,v.revision,v.sha256,v.size FROM heads h JOIN versions v ON h.revision=v.revision WHERE h.project=? ORDER BY h.path,v.revision', (project_id,)).fetchall()
        result = {}
        for r in rows:
            result.setdefault(r['path'], []).append({k: r[k] for k in ('revision','sha256','size')})
        return [{'path': p, 'heads': h} for p, h in result.items()]

    def list_files(self, project_id):
        with self._db() as db:
            self._project(db, project_id)
            return self._files(db, project_id)

    def history(self, project_id, path):
        """List all retained immutable versions, including resolved branches."""
        _path(path)
        with self._db() as db:
            self._project(db, project_id)
            return [dict(row) for row in db.execute(
                'SELECT v.revision,v.sha256,v.size,EXISTS(SELECT 1 FROM heads h WHERE h.revision=v.revision) AS is_head '
                'FROM versions v WHERE v.project=? AND v.path=? ORDER BY v.rowid DESC', (project_id,path))]

    def _verified(self, row):
        body = bytes(row['body'])
        if len(body) != row['size'] or hashlib.sha256(body).hexdigest() != row['sha256']:
            raise SyncError('Stored content integrity check failed', 'integrity', 409)
        return body

    def _status(self, db, project_id):
        project = self._project(db, project_id)
        manifests = db.execute('SELECT * FROM manifests WHERE project=?', (project_id,)).fetchall()
        issues = []
        desired = {}
        for manifest in manifests:
            issues.extend(json.loads(manifest['issues']))
            for f in json.loads(manifest['files']):
                desired.setdefault(f['path'], {})[(f['sha256'], f['size'])] = f
        files = self._files(db, project_id)
        heads = {f['path']: f['heads'] for f in files}
        conflicts = sum(len(f['heads']) > 1 for f in files)
        missing = []
        required = 0
        for path, variants in desired.items():
            if len(variants) > 1:
                issues.append('Device manifests disagree: ' + path)
            for (digest, size), _ in variants.items():
                matches = [h for h in heads.get(path, []) if h['sha256'] == digest and h['size'] == size]
                valid = False
                for h in matches:
                    row = db.execute('SELECT * FROM versions WHERE revision=?', (h['revision'],)).fetchone()
                    try:
                        self._verified(row)
                        valid = True
                    except SyncError:
                        issues.append('Stored content integrity check failed: ' + path)
                if not valid:
                    missing.append(path)
                    required += size
        # Every current head is checked, including paths absent from old declarations.
        for f in files:
            if f['path'] not in desired:
                issues.append('Manifest does not include current file: ' + f['path'])
            for h in f['heads']:
                try:
                    self._verified(db.execute('SELECT * FROM versions WHERE revision=?', (h['revision'],)).fetchone())
                except SyncError:
                    issues.append('Stored content integrity check failed: ' + f['path'])
        active = db.execute("SELECT COUNT(*) FROM uploads WHERE project=? AND state='receiving'", (project_id,)).fetchone()[0]
        state = ('metadata_only' if not project['offline_enabled'] else 'conflict' if conflicts else
                 'blocked' if issues else 'pending' if not manifests or missing or active else 'ready')
        used = db.execute('SELECT COALESCE(SUM(size),0) FROM versions').fetchone()[0]
        return {**project, 'state': state, 'missing_files': sorted(set(missing)), 'required_bytes': required,
                'conflict_count': conflicts, 'issues': sorted(set(issues)), 'manifest_count': len(manifests),
                'active_transfers': active, 'stored_bytes': used,
                'last_sync_at': max((m['updated_at'] for m in manifests), default=None)}

    def status(self, project_id):
        with self._db() as db:
            return self._status(db, project_id)

    def _upload(self, db, project_id, transfer_id):
        self._project(db, project_id)
        row = db.execute('SELECT * FROM uploads WHERE project=? AND transfer=?', (project_id, _id(transfer_id))).fetchone()
        if row is None:
            raise SyncError('Transfer not found', 'not_found', 404)
        return row

    def _upload_dict(self, row):
        return {'next_offset': row['offset'], 'state': row['state'],
                'receipt': json.loads(row['receipt']) if row['receipt'] else None,
                'transfer_id': row['transfer'], 'max_chunk_bytes': MAX_CHUNK_BYTES}

    def start_upload(self, project_id, transfer_id, path, size, sha256, base_revision=None):
        _id(transfer_id)
        _path(path)
        _size_hash(size, sha256)
        if base_revision is not None:
            _id(base_revision)
        with self._db() as db:
            project = self._project(db, project_id)
            old = db.execute('SELECT * FROM uploads WHERE project=? AND transfer=?', (project_id, transfer_id)).fetchone()
            if old:
                if (old['path'],old['size'],old['sha256'],old['base']) != (path,size,sha256,base_revision):
                    raise SyncError('Transfer manifest changed', 'transfer_conflict', 409)
                return self._upload_dict(old)
            if not project['offline_enabled']:
                raise SyncError('Offline copies disabled', 'offline_disabled', 409)
            if base_revision is not None and not db.execute('SELECT 1 FROM versions WHERE project=? AND path=? AND revision=?', (project_id,path,base_revision)).fetchone():
                raise SyncError('Base revision does not belong to this file', 'invalid_base', 409)
            # Case aliases cannot safely round-trip to common desktop filesystems.
            paths = db.execute("SELECT path FROM versions WHERE project=? UNION SELECT path FROM uploads WHERE project=? AND state<>'aborted'", (project_id,project_id)).fetchall()
            known_paths = {r[0] for r in paths}
            for manifest in db.execute('SELECT files FROM manifests WHERE project=?', (project_id,)):
                known_paths.update(f['path'] for f in json.loads(manifest[0]))
            if any(_path_collision(path, previous) for previous in known_paths):
                raise SyncError('Ambiguous project path', 'unsafe_path', 409)
            used = db.execute('SELECT COALESCE(SUM(size),0) FROM versions').fetchone()[0]
            active, reserved = db.execute("SELECT COUNT(*),COALESCE(SUM(size),0) FROM uploads WHERE state='receiving'").fetchone()
            if active >= MAX_ACTIVE_TRANSFERS or reserved + size > MAX_RESERVED_BYTES or used + reserved + size > MAX_TENANT_BYTES:
                raise SyncError('Tenant storage quota exceeded', 'quota', 413)
            db.execute("INSERT INTO uploads(project,transfer,path,size,sha256,base,state) VALUES (?,?,?,?,?,?,'receiving')", (project_id,transfer_id,path,size,sha256,base_revision))
            return self._upload_dict(self._upload(db,project_id,transfer_id))

    def upload_status(self, project_id, transfer_id):
        with self._db() as db:
            return self._upload_dict(self._upload(db,project_id,transfer_id))

    def pending_uploads(self, project_id):
        with self._db() as db:
            self._project(db,project_id)
            return [{**self._upload_dict(row), 'path':row['path'], 'size':row['size']}
                    for row in db.execute("SELECT * FROM uploads WHERE project=? AND state='receiving' ORDER BY transfer", (project_id,))]

    def abort_upload(self, project_id, transfer_id):
        """Free an unpublished reservation; committed versions are immutable."""
        with self._db() as db:
            self._project(db,project_id)
            row = db.execute('SELECT * FROM uploads WHERE project=? AND transfer=?', (project_id,_id(transfer_id))).fetchone()
            if row is None:
                # Cancel is also a barrier to a delayed begin whose reply was lost.
                db.execute("INSERT INTO uploads(project,transfer,path,size,sha256,state) VALUES (?,?,?,0,?,'aborted')",
                           (project_id,transfer_id,'',hashlib.sha256(b'').hexdigest()))
                return self._upload_dict(self._upload(db,project_id,transfer_id))
            if row['state'] == 'receiving':
                db.execute('DELETE FROM chunks WHERE project=? AND transfer=?', (project_id,transfer_id))
                db.execute("UPDATE uploads SET state='aborted' WHERE project=? AND transfer=?", (project_id,transfer_id))
            return self._upload_dict(self._upload(db,project_id,transfer_id))

    def append_chunk(self, project_id, transfer_id, offset, data: bytes):
        if type(offset) is not int or not 0 <= offset <= MAX_FILE_BYTES or not isinstance(data, bytes) or not 1 <= len(data) <= MAX_CHUNK_BYTES:
            raise SyncError('Invalid chunk')
        with self._db() as db:
            row = self._upload(db,project_id,transfer_id)
            if row['state'] != 'receiving':
                raise SyncError('Transfer already committed', 'transfer_closed', 409)
            previous = db.execute('SELECT body FROM chunks WHERE project=? AND transfer=? AND offset=?', (project_id,transfer_id,offset)).fetchone()
            if previous:
                if bytes(previous[0]) == data:
                    return self._upload_dict(row)
                raise SyncError('Repeated chunk differs', 'chunk_conflict', 409)
            if not self._project(db, project_id)['offline_enabled']:
                raise SyncError('Offline copies disabled', 'offline_disabled', 409)
            if offset != row['offset'] or offset + len(data) > row['size']:
                raise SyncError('Unexpected chunk offset or size', 'offset_conflict', 409)
            db.execute('INSERT INTO chunks VALUES (?,?,?,?)', (project_id,transfer_id,offset,data))
            db.execute('UPDATE uploads SET offset=? WHERE project=? AND transfer=?', (offset+len(data),project_id,transfer_id))
            return self._upload_dict(self._upload(db,project_id,transfer_id))

    def finish_upload(self, project_id, transfer_id):
        with self._db() as db:
            row = self._upload(db,project_id,transfer_id)
            if row['state'] == 'committed':
                return json.loads(row['receipt'])
            if row['state'] == 'aborted':
                raise SyncError('Transfer aborted; use a new identifier', 'transfer_closed', 409)
            if not self._project(db, project_id)['offline_enabled']:
                raise SyncError('Offline copies disabled', 'offline_disabled', 409)
            if row['offset'] != row['size']:
                raise SyncError('Transfer incomplete', 'incomplete', 409)
            blocks = db.execute('SELECT offset,body FROM chunks WHERE project=? AND transfer=? ORDER BY offset', (project_id,transfer_id)).fetchall()
            parts, offset = [], 0
            for block in blocks:
                if block['offset'] != offset:
                    raise SyncError('Transfer journal corrupt', 'integrity', 409)
                part = bytes(block['body'])
                offset += len(part)
                parts.append(part)
            body = b''.join(parts)
            self._verified({'body':body,'sha256':row['sha256'],'size':row['size']})
            revision = uuid.uuid4().hex
            db.execute('INSERT INTO versions VALUES (?,?,?,?,?,?)', (revision,project_id,row['path'],row['sha256'],row['size'],body))
            if row['base'] is not None:
                db.execute('DELETE FROM heads WHERE project=? AND path=? AND revision=?', (project_id,row['path'],row['base']))
            db.execute('INSERT INTO heads VALUES (?,?,?)', (project_id,row['path'],revision))
            receipt = {'revision': revision, 'path':row['path'], 'sha256':row['sha256'], 'size':row['size'],
                       'project_id':project_id, 'transfer_id':transfer_id}
            db.execute("UPDATE uploads SET state='committed',receipt=? WHERE project=? AND transfer=?", (json.dumps(receipt),project_id,transfer_id))
            db.execute('DELETE FROM chunks WHERE project=? AND transfer=?', (project_id,transfer_id))
            return receipt

    def read_revision(self, project_id, revision):
        with self._db() as db:
            self._project(db,project_id)
            row = db.execute('SELECT * FROM versions WHERE project=? AND revision=?', (project_id,_id(revision))).fetchone()
            if row is None:
                raise SyncError('Revision not found', 'not_found', 404)
            return self._verified(row)

    def resolve(self, project_id, path, expected_heads: list[str], chosen_revision):
        _path(path)
        _id(chosen_revision)
        if not isinstance(expected_heads,list) or not expected_heads:
            raise SyncError('Invalid expected heads')
        for revision in expected_heads:
            _id(revision)
        if len(expected_heads) != len(set(expected_heads)):
            raise SyncError('Invalid expected heads')
        with self._db() as db:
            self._project(db,project_id)
            current = [r[0] for r in db.execute('SELECT revision FROM heads WHERE project=? AND path=?', (project_id,path))]
            if set(current) != set(expected_heads) or chosen_revision not in current:
                raise SyncError('File heads changed', 'conflict', 409)
            self._verified(db.execute('SELECT * FROM versions WHERE revision=? AND project=?', (chosen_revision,project_id)).fetchone())
            db.execute('DELETE FROM heads WHERE project=? AND path=? AND revision<>?', (project_id,path,chosen_revision))
            return next(f for f in self._files(db,project_id) if f['path'] == path)
