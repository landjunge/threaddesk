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

CHUNK_BYTES = 256 * 1024
MAX_BYTES = 64 * 1024 * 1024
STATE_DIR = ".threaddesk-sync-conflicts"
VCS_NAMES = {".git", ".hg", ".svn"}
REFS = re.compile(r'''(?:!?\[[^\]]*\]\(\s*<?([^\s)>]+)|(?:src|href)\s*=\s*["']([^"']+)|url\(\s*["']?([^\s'"\)]+))''', re.I)


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
    """Enumerate the selected tree without following links; discover known links."""
    root = Path(root).absolute()
    if root.is_symlink() or not root.is_dir():
        raise ClientError("Selected project directory is unavailable or a symbolic link")
    files, issues, links = [], [], []
    for parent, dirs, names in os.walk(root, followlinks=False,
                                       onerror=lambda exc: issues.append("Unreadable project directory: " + type(exc).__name__)):
        prefix = Path(parent).relative_to(root)
        for name in list(dirs):
            relative = (prefix / name).as_posix()
            if name == STATE_DIR or (name.casefold() in VCS_NAMES and not (Path(parent) / name).is_symlink()):
                dirs.remove(name)
                continue
            if not safe_path(relative) or (Path(parent) / name).is_symlink():
                dirs.remove(name)
                issues.append("Excluded unsafe directory: " + relative)
        for name in names:
            if name.casefold() in VCS_NAMES and not (Path(parent) / name).is_symlink():
                continue  # Worktree pointers and VCS internals are outside project content.
            if re.fullmatch(r"\.td-sync-[a-f0-9]{32}", name):
                continue  # Reserved unpublished download; never a user project file.
            relative = (prefix / name).as_posix()
            try:
                data = _read(root, relative)
                files.append({"path": relative, "sha256": digest(data), "size": len(data)})
                if Path(name).suffix.lower() in {".md", ".markdown", ".html", ".htm", ".css"}:
                    text = data.decode("utf-8", errors="replace")
                    links.extend((Path(parent), next(x for x in match.groups() if x)) for match in REFS.finditer(text))
            except (ClientError, OSError) as exc:
                issues.append("Unavailable file: " + relative + " (" + type(exc).__name__ + ")")
    links.extend((root, item) for item in references if isinstance(item, str))
    for parent, value in links:
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https", "mailto", "data", "tel"} or not parsed.path:
            continue
        if parsed.scheme and parsed.scheme != "file":
            issues.append("Unsupported dependency scheme: " + parsed.scheme)
            continue
        candidate = Path(unquote(parsed.path))
        target = candidate if candidate.is_absolute() else parent / candidate
        try:
            resolved = target.resolve()
            relative = resolved.relative_to(root).as_posix()
            if not safe_path(relative) or not target.exists() or target.is_symlink():
                raise ValueError("unsafe or missing")
        except (OSError, ValueError):
            # Do not disclose outside host paths in a remote manifest.
            issues.append("Missing, unsafe or external dependency referenced by " + parent.relative_to(root).as_posix())
    return sorted(files, key=lambda x: x["path"]), sorted(set(issues))


class SyncClient:
    def __init__(self, base_url, token, project_id, root, *, state_dir=None,
                 transport=None, allow_insecure_loopback=False):
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
        self.api = "/api/projects/" + project_id
        identity = digest((self.base_url + "\0" + project_id + "\0" + str(self.root) + "\0" + digest(token.encode())).encode())
        directory = Path(state_dir).expanduser() if state_dir else Path.home() / ".local/state/threaddesk-sync" / identity
        directory = directory.absolute()
        if directory.is_relative_to(self.root) or directory.is_symlink():
            raise ClientError("Checkpoint directory must be private and outside the project tree")
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
        CREATE TABLE IF NOT EXISTS device (id TEXT NOT NULL);""")
        existing = self.db.execute("SELECT value FROM identity").fetchone()
        if existing and existing[0] != identity:
            self.db.close()
            raise ClientError("Checkpoint belongs to a different server, account, project or directory")
        if not existing:
            self.db.execute("INSERT INTO identity VALUES (?)", (identity,))
        device = self.db.execute("SELECT id FROM device").fetchone()
        if not device:
            self.db.execute("INSERT INTO device VALUES (?)", (uuid.uuid4().hex,))
        self.device_id = self.db.execute("SELECT id FROM device").fetchone()[0]
        self.db.commit()
        self.http = transport or httpx.Client(base_url=self.base_url, headers={"Authorization": "Bearer " + token},
                                             timeout=30, follow_redirects=False)
        self.token = token
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

    def _upload(self, item, base):
        relative, sha = item["path"], item["sha256"]
        data = _read(self.root, relative)
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
        endpoint = self.api + "/uploads/" + transfer
        state = self._json("POST", endpoint, json={"path": relative, "size": len(data), "sha256": sha, "base_revision": base})
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
        parent, name = _parent_fd(self.root, relative, create=True)
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
                backup_parent, backup = _parent_fd(self.root, STATE_DIR + "/previous/" + uuid.uuid4().hex + ".copy",
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
        path = STATE_DIR + "/remote/" + digest(relative.encode()) + "-" + head["revision"] + ".copy"
        parent, name = _parent_fd(self.root, path, create=True, managed=True)
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

    def sync_once(self):
        root_stat = os.stat(self.root, follow_symlinks=False)
        if not stat.S_ISDIR(root_stat.st_mode) or (root_stat.st_dev, root_stat.st_ino) != self.root_identity:
            raise ClientError("Selected project directory was replaced; reselect it explicitly")
        issues = []
        # Existing core files are references, never authority to read outside root.
        thread = self._json("GET", self.api + "/thread")
        context = thread.get("context", {})
        references = context.get("files", []) if isinstance(context, dict) else []
        files, scan_issues = scan_project(self.root, references=references)
        issues.extend(scan_issues)
        status = self._json("POST", self.api + "/manifest", json={"files": files, "issues": issues, "device_id": self.device_id})
        if not status["offline_enabled"]:
            return dict(status, local_issues=issues, selected_root=str(self.root))
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
                except (ClientError, OSError) as exc:
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
                if len(heads) == 1:
                    head = heads[0]
                    if local_item and local_item["sha256"] == head["sha256"]:
                        if digest(_read(self.root, relative)) == head["sha256"]:
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
            except (ClientError, OSError) as exc:
                issues.append(str(exc))
        files, final_issues = scan_project(self.root, references=references)
        issues = sorted(set(issues + final_issues))
        status = self._json("POST", self.api + "/manifest", json={"files": files, "issues": issues, "device_id": self.device_id})
        return dict(status, local_issues=issues, selected_root=str(self.root))

    def watch(self, interval=5, stop_event=None, on_status=None):
        stop = stop_event or threading.Event()
        delay = max(1, interval)
        while not stop.is_set():
            try:
                status = self.sync_once()
                delay = max(1, interval)
            except (httpx.HTTPError, ClientError, OSError) as exc:
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
