"""Conservative directory replica. No deletions, shell execution or host-wide crawl.

The selected directory is the dependency boundary. Unsupported/external references
are reported and never silently copied. A local checkpoint is not a remote receipt.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import sys
import os
import re
import sqlite3
import stat
import threading
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx

from threaddesk.server_sync.store import SyncError, validate_path
from threaddesk.server_sync.discovery import DiscoveryError, DiscoveryPlan, SourceFile, discover_project
from threaddesk.server_sync.identity import validate_device_id, validate_initial_bases
from threaddesk.core.errors import ThreadDeskError

CHUNK_BYTES = 256 * 1024
MAX_BYTES = 64 * 1024 * 1024
STATE_DIR = ".threaddesk-sync-conflicts"



class ClientError(RuntimeError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_path(value: str) -> bool:
    try:
        validate_path(value)
        return True
    except (SyncError, UnicodeError):
        return False


def _parent_fd(root: Path, relative: str, *, create=False, managed=False):
    """Walk ancestors using descriptor-bound O_NOFOLLOW, never ambient resolution."""
    if not managed and not safe_path(relative):
        raise ClientError("Unsafe project path")
    parts = Path(root).parts[1:] + tuple(relative.split("/")[:-1])
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts:
            if part in {"", ".", ".."}:
                raise ClientError("Unsafe path segment")
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor, relative.split("/")[-1]
    except BaseException:
        os.close(descriptor)
        raise


def _read_at(parent_fd, basename):
    descriptor = os.open(basename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
            raise ClientError("Unsupported or oversized file")
        data = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
        if len(data) > MAX_BYTES or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ClientError("File changed while reading")
        return data


def _read(root: Path, relative: str) -> bytes:
    parent, name = _parent_fd(root, relative)
    try:
        return _read_at(parent, name)
    finally:
        os.close(parent)


def scan_project(root: Path, references=()) -> tuple[list[dict], list[str]]:
    """Compatibility projection; supplied remote references never add read grants."""
    plan = discover_project(root, server_references=references)
    return plan.files, plan.issues


class SyncClient:
    def __init__(self, base_url, token, project_id, root, *, state_dir=None,
                 transport=None, allow_insecure_loopback=False, metadata_replica=None,
                 local_references=(), approved_roots=(), required_references=(), device_id=None,
                 initial_bases=None):
        if device_id is not None:
            validate_device_id(device_id)
        seeds = validate_initial_bases(initial_bases)
        parsed = urlsplit(base_url)
        loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (parsed.scheme != "https" and not (allow_insecure_loopback and loopback and parsed.scheme == "http")):
            raise ClientError("HTTPS is required; loopback development requires explicit opt-in")
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ClientError("Server URL must be an origin without credentials or path")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", project_id):
            raise ClientError("Invalid project id")
        selected = Path(root).expanduser()
        if selected.is_symlink() or not selected.is_dir():
            raise ClientError("Select a real project directory")
        self.root = selected.resolve()
        root_stat = self.root.stat()
        self.root_identity = (root_stat.st_dev, root_stat.st_ino)
        self.base_url = base_url.rstrip("/")
        self.project_id = project_id
        self.metadata_replica = metadata_replica
        # These owner-local grants are captured BEFORE any server metadata merge.
        self.local_references = tuple(local_references)
        self.approved_roots = dict(approved_roots) if isinstance(approved_roots, dict) else tuple(approved_roots)
        self.inventory = DiscoveryPlan()
        self.source_map = {}
        self.api = "/api/projects/" + project_id
        identity = digest((self.base_url + "\0" + project_id + "\0" + str(self.root) + "\0" + digest(token.encode())).encode())
        directory = Path(state_dir).expanduser() if state_dir else Path.home() / ".local/state/threaddesk-sync" / identity
        directory = directory.absolute()
        if directory.is_relative_to(self.root) or directory.is_symlink():
            raise ClientError("Checkpoint directory must be private and outside the project tree")
        if self._trusted_target(directory):
            raise ClientError("Checkpoint directory must be outside all approved source roots")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
        dbpath = directory / "checkpoint.sqlite3"
        if dbpath.is_symlink():
            raise ClientError("Unsafe checkpoint file")
        self.db = sqlite3.connect(dbpath)
        os.chmod(dbpath, 0o600)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""CREATE TABLE IF NOT EXISTS identity (value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS base (path TEXT PRIMARY KEY,revision TEXT NOT NULL,sha256 TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS uploads (path TEXT PRIMARY KEY,sha256 TEXT NOT NULL,base TEXT,transfer TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS device (id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sources (path TEXT PRIMARY KEY,root TEXT NOT NULL,relative TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS initialization (id INTEGER PRIMARY KEY CHECK(id=1));""")
        existing = self.db.execute("SELECT value FROM identity").fetchone()
        if existing and existing[0] != identity:
            self.db.close()
            raise ClientError("Checkpoint belongs to a different server, account, project or directory")
        if not existing:
            self.db.execute("INSERT INTO identity VALUES (?)", (identity,))
        devices = self.db.execute("SELECT id FROM device").fetchall()
        if len(devices) > 1:
            self.db.close()
            raise ClientError("Checkpoint has ambiguous device identities")
        if devices:
            try:
                saved_device = validate_device_id(devices[0][0])
            except ValueError:
                self.db.close()
                raise ClientError("Checkpoint contains an invalid device identity")
            if device_id is not None and saved_device != device_id:
                self.db.close()
                raise ClientError("Checkpoint belongs to a different synchronization device")
        else:
            self.db.execute("INSERT INTO device VALUES (?)", (device_id or uuid.uuid4().hex,))
        self.device_id = self.db.execute("SELECT id FROM device").fetchone()[0]
        initialized = self.db.execute("SELECT id FROM initialization WHERE id=1").fetchone()
        if not initialized:
            # Root relocation may explicitly carry only the binding's committed
            # common revisions into a pristine ROOT-BOUND file checkpoint.
            # Existing/pending state is never reset by a replayed configuration.
            pristine = existing is None and not any(self.db.execute("SELECT 1 FROM " + table + " LIMIT 1").fetchone()
                                                  for table in ('base', 'uploads', 'sources'))
            if pristine and seeds:
                self.db.executemany("INSERT INTO base VALUES (?,?,?)", ((v['path'], v['revision'], v['sha256']) for v in seeds))
            self.db.execute("INSERT INTO initialization VALUES (1)")
        self.db.commit()
        self.http = transport or httpx.Client(base_url=self.base_url, headers={"Authorization": "Bearer " + token},
                                             timeout=30, follow_redirects=False)
        self.token = token
        self.required_references = tuple(required_references)
        self.owns_http = transport is None

    def close(self):
        self.db.close()
        if self.owns_http:
            self.http.close()

    def _request(self, method, path, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = "Bearer " + self.token
        response = self.http.request(method, path, headers=headers, **kwargs)
        response.raise_for_status()
        return response

    def _json(self, method, path, **kwargs):
        return self._request(method, path, **kwargs).json()

    def _base(self, path):
        row = self.db.execute("SELECT revision,sha256 FROM base WHERE path=?", (path,)).fetchone()
        return {"revision": row[0], "sha256": row[1]} if row else None

    def _remember(self, path, head):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO base VALUES (?,?,?)", (path, head["revision"], head["sha256"]))
            self.db.execute("DELETE FROM uploads WHERE path=?", (path,))

    def _trusted_target(self, target):
        """Cached paths are hints; only CURRENT explicit grants grant authority."""
        target = Path(os.path.abspath(target))
        if target.is_relative_to(self.root):
            return True
        roots = self.approved_roots.values() if isinstance(self.approved_roots, dict) else self.approved_roots
        for value in tuple(roots) + self.local_references:
            if not isinstance(value, (str, Path)):
                continue
            raw = str(value)
            try:
                parsed = urlsplit(raw)
            except ValueError:
                continue
            if not parsed.scheme:
                # Plain owner paths retain percent escapes, query/hash characters
                # literally, matching discovery's exact-file grant semantics.
                grant = Path(raw).expanduser()
            elif (parsed.scheme == 'file' and raw.lower().startswith('file:')
                  and not parsed.netloc and not parsed.query and not parsed.fragment):
                try:
                    grant = Path(unquote(parsed.path, errors='strict')).expanduser()
                except UnicodeError:
                    continue
            else:
                continue
            if not grant.is_absolute():
                grant = self.root / grant
            grant = Path(os.path.abspath(grant))
            if target == grant or (grant.is_dir() and not grant.is_symlink() and target.is_relative_to(grant)):
                return True
        return False

    def _source(self, logical, *, allow_new=False):
        if not safe_path(logical):
            raise ClientError("Unsafe project path")
        source = self.source_map.get(logical)
        if source is not None:
            return source
        cached = self.db.execute("SELECT root,relative FROM sources WHERE path=?", (logical,)).fetchone()
        if cached:
            candidate = SourceFile(Path(cached[0]), cached[1])
            if self._trusted_target(candidate.path) and safe_path(candidate.relative):
                self.source_map[logical] = candidate
                return candidate
        if logical.split('/')[0] == '_external':
            # New files may use an already-known directory namespace only while
            # the corresponding directory remains an explicit current grant.
            # An exact file grant never grants any sibling path.
            parts = logical.split('/')
            if len(parts) >= 3:
                prefix = '/'.join(parts[:2]) + '/'
                known = list(self.source_map.items())
                known.extend((row[0], SourceFile(Path(row[1]), row[2])) for row in
                             self.db.execute("SELECT path,root,relative FROM sources WHERE path LIKE ?", (prefix + '%',)))
                for known_logical, known_source in known:
                    if not known_logical.startswith(prefix) or known_source.relative != known_logical[len(prefix):]:
                        continue
                    candidate = SourceFile(known_source.root, '/'.join(parts[2:]))
                    if safe_path(candidate.relative) and self._trusted_target(candidate.path):
                        self.source_map[logical] = candidate
                        return candidate
            raise ClientError("External server file lacks an approved original destination: " + logical)
        if allow_new:
            return SourceFile(self.root, logical)
        raise ClientError("File is absent from the approved inventory: " + logical)

    def _read_source(self, logical):
        return self._source(logical, allow_new=True).read_bytes()

    def _discover(self, server_references):
        plan = discover_project(self.root, local_references=self.local_references,
                                approved_roots=self.approved_roots, server_references=server_references)
        self.inventory = plan
        self.source_map = dict(plan.sources)
        with self.db:
            for logical, source in plan.sources.items():
                self.db.execute("INSERT OR REPLACE INTO sources VALUES (?,?,?)", (logical, str(source.root), source.relative))
        return plan

    def _upload(self, item, base):
        relative, sha = item["path"], item["sha256"]
        data = self._read_source(relative)
        if digest(data) != sha:
            raise ClientError("File changed before upload: " + relative)
        row = self.db.execute("SELECT sha256,base,transfer FROM uploads WHERE path=?", (relative,)).fetchone()
        if row and row[:2] == (sha, base):
            transfer = row[2]
        else:
            if row:
                # Do not leak a permanent reservation when the selected local file
                # changes during a disconnected transfer. Keep the checkpoint until
                # a definitive abort/commit answer; failed calls never allocate anew.
                previous = self._json("POST", self.api + "/uploads/" + row[2] + "/abort")
                if previous.get("state") == "committed":
                    receipt = previous.get("receipt") or {}
                    if receipt.get("sha256") != row[0] or receipt.get("path") != relative or not receipt.get("revision"):
                        raise ClientError("Invalid committed transfer receipt")
                    self._remember(relative, receipt)
                    base = receipt["revision"]
                elif previous.get("state") != "aborted":
                    raise ClientError("Previous transfer cancellation is unconfirmed")
            transfer = uuid.uuid4().hex
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO uploads VALUES (?,?,?,?)", (relative, sha, base, transfer))
        manifest = {"path": relative, "size": len(data), "sha256": sha, "base_revision": base}
        # An operator may have definitively aborted this persisted ID while the
        # client was disconnected. Its bytes/base remain unchanged, but its ID
        # is terminal. Replace only after that positive state, never on a timeout.
        for attempt in range(2):
            endpoint = self.api + "/uploads/" + transfer
            state = self._json("POST", endpoint, json=manifest)
            if state.get("state") != "aborted":
                if state.get("state") not in {"receiving", "committed"}:
                    raise ClientError("Invalid server transfer state")
                break
            if attempt == 1:
                raise ClientError("Server repeatedly canceled upload; retry deferred")
            transfer = uuid.uuid4().hex
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO uploads VALUES (?,?,?,?)", (relative, sha, base, transfer))
        offset = state["next_offset"]
        if type(offset) is not int or not 0 <= offset <= len(data):
            raise ClientError("Invalid server resume offset")
        while offset < len(data):
            block = data[offset:offset + CHUNK_BYTES]
            state = self._json("PATCH", endpoint, json={"offset": offset, "data_base64": base64.b64encode(block).decode("ascii")})
            next_offset = state["next_offset"]
            if next_offset != offset + len(block):
                raise ClientError("Invalid server chunk acknowledgement")
            offset = next_offset
        receipt = self._json("POST", endpoint + "/commit")
        # Remote readback, not a transport success, establishes the common base.
        return receipt

    def _download(self, head):
        revision = head["revision"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", revision):
            raise ClientError("Invalid remote revision")
        data = self._request("GET", self.api + "/revisions/" + revision).content
        if len(data) > MAX_BYTES or len(data) != head["size"] or digest(data) != head["sha256"]:
            raise ClientError("Remote integrity check failed")
        return data

    def _recovery_metadata(self, parent, basename, *, path, kind, sha256, revision=None):
        """A private adjacent mapping keeps generated recovery names recoverable."""
        payload = {"format": "threaddesk.sync.recovery.v1", "path": path, "kind": kind,
                   "sha256": sha256, "revision": revision, "copy": basename}
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        name = basename + ".json"
        try:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        except FileExistsError:
            if _read_at(parent, name) != data:
                raise ClientError("Recovery metadata changed; retained without overwrite")
            return
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(parent)

    def _install(self, relative, data, expected_sha):
        """Retain displaced inode, publish exclusively through bound directory fds."""
        source = self._source(relative, allow_new=True)
        parent, name = _parent_fd(source.root, source.relative, create=True)
        backup_parent = None
        backup = None
        temporary = ".td-sync-" + uuid.uuid4().hex
        try:
            try:
                current = _read_at(parent, name)
            except FileNotFoundError:
                current = None
            if (current is None and expected_sha is not None) or (current is not None and
                    (expected_sha is None or digest(current) != expected_sha)):
                raise ClientError("Local file changed; replacement refused: " + relative)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if current is not None:
                recovery_parent = Path(source.relative).parent.as_posix()
                recovery_prefix = '' if recovery_parent == '.' else recovery_parent + '/'
                backup_parent, backup = _parent_fd(source.root, recovery_prefix + STATE_DIR + "/previous/" + uuid.uuid4().hex + ".copy",
                                                  create=True, managed=True)
                os.rename(name, backup, src_dir_fd=parent, dst_dir_fd=backup_parent)
                os.fsync(backup_parent)
                actual_sha = digest(_read_at(backup_parent, backup))
                previous = self._base(relative)
                self._recovery_metadata(backup_parent, backup, path=relative, kind="previous",
                                        sha256=actual_sha, revision=previous["revision"] if previous and previous["sha256"] == actual_sha else None)
                if actual_sha != expected_sha:
                    raise ClientError("Concurrent edit retained in recovery: " + relative)
            try:
                os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
            except FileExistsError:
                raise ClientError("Concurrent file retained; download deferred: " + relative)
            os.fsync(parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
            # If publication failed, restore the original pathname exclusively.
            if backup_parent is not None:
                try:
                    os.link(backup, name, src_dir_fd=backup_parent, dst_dir_fd=parent, follow_symlinks=False)
                except FileExistsError:
                    pass
                except FileNotFoundError:
                    pass
                os.close(backup_parent)
            os.close(parent)

    def _conflict_copy(self, relative, head):
        data = self._download(head)
        source = self._source(relative, allow_new=True)
        recovery_parent = Path(source.relative).parent.as_posix()
        recovery_prefix = '' if recovery_parent == '.' else recovery_parent + '/'
        path = recovery_prefix + STATE_DIR + "/remote/" + digest(relative.encode()) + "-" + head["revision"] + ".copy"
        parent, name = _parent_fd(source.root, path, create=True, managed=True)
        try:
            try:
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            except FileExistsError:
                if digest(_read_at(parent, name)) != head["sha256"]:
                    raise ClientError("Recovery copy changed; retained without overwrite")
                self._recovery_metadata(parent, name, path=relative, kind="remote",
                                        sha256=head["sha256"], revision=head["revision"])
                return
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(parent)
            self._recovery_metadata(parent, name, path=relative, kind="remote",
                                    sha256=head["sha256"], revision=head["revision"])
        finally:
            os.close(parent)

    def _files(self):
        value = self._json("GET", self.api + "/files")
        return value["files"] if isinstance(value, dict) else value

    def _final_status(self, issues, local_metadata=None):
        status = self._json("GET", self.api + "/status")
        local_metadata = local_metadata or {}
        local_count = local_metadata.get('metadata_conflict_count', 0)
        status['local_metadata_conflict_count'] = local_count
        status['remote_metadata_conflict_count'] = status.get('metadata_conflict_count', 0)
        status['metadata_conflict_count'] = status.get('metadata_conflict_count', 0) + local_count
        if status['metadata_conflict_count']:
            status['state'] = 'conflict'
        return dict(status, local_issues=sorted(set(issues)), selected_root=str(self.root),
                    inventory_file_count=len(self.inventory.files),
                    external_file_count=sum(path.startswith('_external/') for path in self.inventory.sources),
                    discovery_limitations=list(self.inventory.limitations))

    def sync_once(self):
        root_stat = os.stat(self.root, follow_symlinks=False)
        if not stat.S_ISDIR(root_stat.st_mode) or (root_stat.st_dev, root_stat.st_ino) != self.root_identity:
            raise ClientError("Selected project directory was replaced; reselect it explicitly")
        issues = []
        local_metadata = {}
        if self.metadata_replica is not None:
            try:
                result = self.metadata_replica.sync_once(self.http, self.project_id, self.token)
                if result.get('state') == 'conflict':
                    issues.append('Metadata contains concurrent edits; all alternatives retained')
                from threaddesk.server_sync.metadata import metadata_status
                local_metadata = metadata_status(self.metadata_replica.core, self.metadata_replica.thread_id)
                if local_metadata.get('metadata_conflict_count'):
                    issues.append('Unresolved local metadata conflicts require an explicit choice')
            except (SyncError, ThreadDeskError, DiscoveryError) as exc:
                issues.append('Metadata synchronization blocked: ' + type(exc).__name__)
        # Server metadata is inspected only after merge and cannot expand grants.
        thread = self._json("GET", self.api + "/thread")
        context = thread.get("context", {})
        references = context.get("files", []) if isinstance(context, dict) else []
        references = list(references) + list(self.required_references)
        try:
            plan = self._discover(references)
        except (DiscoveryError, OSError) as exc:
            self.inventory = DiscoveryPlan(issues=['Project discovery failed: ' + type(exc).__name__])
            plan = self.inventory
        files = plan.files
        issues.extend(plan.issues)
        status = self._json("POST", self.api + "/manifest", json={"files": files, "issues": issues[:2000], "device_id": self.device_id})
        if not status["offline_enabled"]:
            return self._final_status(issues, local_metadata)
        remote = {item["path"]: item["heads"] for item in self._files()}
        for item in files:
            relative = item["path"]
            base = self._base(relative)
            heads = remote.get(relative, [])
            if any(h["sha256"] == item["sha256"] and h["size"] == item["size"] for h in heads):
                continue
            if base is None or item["sha256"] != base["sha256"] or not heads:
                try:
                    self._upload(item, base["revision"] if base else None)
                except (ClientError, DiscoveryError, OSError) as exc:
                    issues.append(str(exc))
        remote = self._files()
        local = {item["path"]: item for item in files}
        for item in remote:
            relative, heads = item["path"], item["heads"]
            if not safe_path(relative) or relative.split("/")[0] == STATE_DIR:
                issues.append("Unsafe remote project path refused")
                continue
            local_item, base = local.get(relative), self._base(relative)
            try:
                # Resolve authority before downloading even one remote byte.
                self._source(relative, allow_new=True)
                if len(heads) == 1:
                    head = heads[0]
                    if local_item and local_item["sha256"] == head["sha256"]:
                        if digest(self._read_source(relative)) == head["sha256"]:
                            self._remember(relative, head)
                        else:
                            issues.append("Local file changed after upload: " + relative)
                    elif local_item is None or (base and local_item["sha256"] == base["sha256"]):
                        self._install(relative, self._download(head), local_item["sha256"] if local_item else None)
                        self._remember(relative, head)
                    else:
                        self._conflict_copy(relative, head)
                        issues.append("Concurrent local edit retained: " + relative)
                elif len(heads) > 1:
                    for head in heads:
                        if local_item is None or local_item["sha256"] != head["sha256"]:
                            self._conflict_copy(relative, head)
                    issues.append("Unresolved version conflict: " + relative)
            except (ClientError, DiscoveryError, OSError) as exc:
                issues.append(str(exc))
        try:
            final_plan = self._discover(references)
            files = final_plan.files
            issues.extend(final_plan.issues)
        except (DiscoveryError, OSError) as exc:
            issues.append('Final project inventory failed: ' + type(exc).__name__)
        issues = sorted(set(value.encode('utf-8', errors='backslashreplace').decode('utf-8')[:1900] for value in issues))
        self._json("POST", self.api + "/manifest", json={"files": files, "issues": issues[:2000], "device_id": self.device_id})
        return self._final_status(issues, local_metadata)

    def watch(self, interval=5, stop_event=None, on_status=None):
        stop = stop_event or threading.Event()
        delay = max(1, interval)
        while not stop.is_set():
            try:
                status = self.sync_once()
                delay = max(1, interval)
            except (httpx.HTTPError, ClientError, DiscoveryError, OSError) as exc:
                status = {"state": "disconnected", "error": type(exc).__name__, "message": str(exc)}
                delay = min(max(delay * 2, 1), 60)
            if on_status:
                on_status(status)
            stop.wait(delay)


def sync_once(base_url, token, project_id, root, **kwargs):
    client = SyncClient(base_url, token, project_id, root, **kwargs)
    try:
        return client.sync_once()
    finally:
        client.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="ThreadDesk project replica; never deletes originals")
    parser.add_argument("server", nargs="?")
    parser.add_argument("project", nargs="?")
    parser.add_argument("directory", nargs="?", type=Path)
    parser.add_argument("--url", dest="server_url")
    parser.add_argument("--project", dest="project_id")
    parser.add_argument("--root", dest="root_directory", type=Path)
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--allow-insecure-loopback", "--allow-http-loopback", action="store_true")
    args = parser.parse_args(argv)
    if not math.isfinite(args.interval) or args.interval <= 0:
        parser.error("--interval must be finite and positive")
    values = []
    for positional, flagged, label in [(args.server, args.server_url, "server/--url"),
                                      (args.project, args.project_id, "project/--project"),
                                      (args.directory, args.root_directory, "directory/--root")]:
        if positional and flagged and positional != flagged:
            parser.error("Conflicting values for " + label)
        if not (positional or flagged):
            parser.error("Required: " + label)
        values.append(flagged or positional)
    client = None
    try:
        token = args.token_file.read_text().strip() if args.token_file else os.environ.get("THREADDESK_SYNC_TOKEN", "")
        if not token:
            parser.error("Provide --token-file or THREADDESK_SYNC_TOKEN")
        client = SyncClient(values[0], token, values[1], values[2], state_dir=args.state_dir,
                            allow_insecure_loopback=args.allow_insecure_loopback)
        if args.watch:
            client.watch(args.interval, on_status=lambda status: print(json.dumps(status, ensure_ascii=False), flush=True))
        else:
            print(json.dumps(client.sync_once(), ensure_ascii=False))
        return 0
    except KeyboardInterrupt:
        return 0
    except (httpx.HTTPError, ClientError, OSError, sqlite3.Error) as exc:
        print("ThreadDesk Sync: " + str(exc), file=sys.stderr)
        return 2
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
