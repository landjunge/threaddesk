from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
import stat
import threading
from pathlib import Path
from typing import Any, IO, Mapping
from uuid import uuid4

from threaddesk.core.errors import InvalidState, ManagementError, NotFound
from threaddesk.core.models import (
    GraphEvent,
    KnowledgeNode,
    Relation,
    Snapshot,
    Thread,
    WhiteboardEntry,
    plan_whiteboard_append,
)
from threaddesk.core.provenance import SourceRecord

DEFAULT_ROOT = Path.home() / ".threaddesk"
_WORKSPACE_LOCKS: dict[str, threading.RLock] = {}
_LOCK_REGISTRY = threading.Lock()


def _lock_exclusive(lock: IO[bytes]) -> None:
    """Hold the next ordinal until this append has stored its file."""
    if lock.seek(0, os.SEEK_END) == 0:
        lock.write(b" ")
        lock.flush()
    lock.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)


def _unlock(lock: IO[bytes]) -> None:
    lock.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class JsonStore:
    @property
    def workspace_path(self) -> Path:
        return self.root

    def search_adapter(self):
        from threaddesk.storage.search_source import JsonSearchAdapter
        return JsonSearchAdapter(self)

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or DEFAULT_ROOT).resolve()
        self.threads_dir = self.root / "threads"
        self.snaps_dir = self.root / "snapshots"
        self.nodes_dir = self.root / "nodes"
        self.relations_dir = self.root / "relations"
        self.events_dir = self.root / "graph-events"
        self.source_records_dir = self.root / "source-records"
        self.whiteboard_dir = self.root / "whiteboard"
        self.state_path = self.root / "state.json"
        self.threads_dir.mkdir(parents=True, exist_ok=True)
        self.snaps_dir.mkdir(parents=True, exist_ok=True)
        self.nodes_dir.mkdir(parents=True, exist_ok=True)
        self.relations_dir.mkdir(parents=True, exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.source_records_dir.mkdir(parents=True, exist_ok=True)
        self.whiteboard_dir.mkdir(parents=True, exist_ok=True)
        self._pending: dict[str, dict | None] | None = None
        self._lock_depth = 0
        self._control_source = None
        self._recovering = False
        with _LOCK_REGISTRY:
            self._mutex = _WORKSPACE_LOCKS.setdefault(str(self.root.resolve()), threading.RLock())
        with self._locked():
            self._recover()

    @contextmanager
    def _locked(self):
        with self._mutex:
            if self._lock_depth:
                self._lock_depth += 1
                try:
                    yield
                finally:
                    self._lock_depth -= 1
                return
            # Bind before accessing either hidden control file. A preceding
            # pathname lstat cannot protect the first lock write/journal read.
            from threaddesk.storage.workspace_backup import BackupError, _SourceTree

            operation_error = None
            try:
                if os.name == "nt":
                    from threaddesk.storage.windows_backup_source import WindowsSourceTree
                    tree = WindowsSourceTree(self.root, error_type=InvalidState,
                                             _allow_unc_controls=True)
                else:
                    tree = _SourceTree(self.root)
                with tree as source, self._control_lock(source) as (lock, validate):
                    validate()
                    _lock_exclusive(lock)
                    self._lock_depth = 1
                    self._control_source = source
                    try:
                        validate()
                        self._recover()
                        try:
                            yield
                        except BaseException as exc:
                            operation_error = exc
                            raise
                    finally:
                        self._control_source = None
                        self._lock_depth = 0
                        _unlock(lock)
            except (OSError, ValueError, BackupError) as exc:
                if exc is operation_error:
                    raise
                raise InvalidState("management_control_path") from exc

    @contextmanager
    def _control_lock(self, source):
        if os.name == "nt":
            with source.control_lock() as result:
                yield result
            return
        source._check_root()
        fd = os.open(".management.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                     0o600, dir_fd=source.fd)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise InvalidState("management_lock_path")
            identity = before.st_dev, before.st_ino

            def validate():
                source._check_root()
                current = os.stat(".management.lock", dir_fd=source.fd, follow_symlinks=False)
                if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
                        or (current.st_dev, current.st_ino) != identity):
                    raise InvalidState("management_lock_path")

            validate()
            stream = os.fdopen(fd, "r+b")
            fd = None
            with stream:
                yield stream, validate
                validate()
        finally:
            if fd is not None:
                os.close(fd)

    @property
    def _journal(self):
        return self.root / ".management-commit.json"

    def _recover(self):
        # A durable commit plan contains resulting state, never commands to repeat.
        source = self._control_source
        if source is None:
            with self._locked():
                return
        try:
            expected = source.info(".management-commit.json")
        except Exception as exc:
            cause = exc
            while cause is not None:
                if isinstance(cause, FileNotFoundError):
                    # A missing ancestor is not the same as an absent journal.
                    try:
                        source._check_root()
                    except Exception as changed:
                        raise InvalidState("management_journal_path") from changed
                    return
                cause = cause.__cause__
            raise InvalidState("management_journal_path") from exc
        try:
            with source.open(".management-commit.json", expected) as guard:
                if os.name == "nt":
                    source.check_control_journal_links(guard)
                elif os.fstat(guard.fileno()).st_nlink != 1:
                    raise InvalidState("management_journal_path")
                plan = json.loads(source.read(".management-commit.json", expected))
            self._recovering = True
            try:
                for relative, data in plan["writes"].items():
                    self._recovery_parts(relative)
                    path = self.root / relative
                    if data is None:
                        self._apply_recovery_data(relative, None)
                    else:
                        self._atomic_json(path, data)
            finally:
                self._recovering = False
            if source.info(".management-commit.json") != expected:
                raise InvalidState("management_journal_path")
            if os.name == "nt":
                source.remove_control_journal(expected)
            else:
                source._check_root()
                os.unlink(".management-commit.json", dir_fd=source.fd)
        except (OSError, ValueError) as exc:
            raise InvalidState("management_journal_path") from exc

    @contextmanager
    def transaction(self):
        with self._locked():
            if self._pending is not None:
                raise RuntimeError("Verschachtelte Transaktionen werden nicht unterstützt.")
            self._pending = {}
            try:
                yield
                writes = self._pending
                self._pending = None
                if writes:
                    self._atomic_json(self._journal, {"version": 1, "writes": writes})
                    self._recover()
            finally:
                self._pending = None

    def list_issued_handoffs(self):
        return [self._read_json(path) for path in sorted((self.root / "issued-handoffs").glob("*.json"))]

    def get_issued_handoff(self, handoff_id):
        path = self.root / "issued-handoffs" / f"{handoff_id}.json"
        return self._read_json(path) if self._staged_exists(path) else None

    def save_issued_handoff(self, handoff_id, data):
        self._write_json(self.root / "issued-handoffs" / f"{handoff_id}.json", data)

    def list_management_operations(self):
        folder = self.root / "management-operations"
        return [self._read_json(path) for path in sorted(folder.glob("*.json"))]

    def get_management_operation(self, operation_id):
        path = self.root / "management-operations" / f"{operation_id}.json"
        return self._read_json(path) if path.exists() else None

    def save_management_operation(self, operation_id, data):
        self._write_json(self.root / "management-operations" / f"{operation_id}.json", data)

    def _delete_path(self, path):
        if self._pending is not None:
            self._pending[str(path.relative_to(self.root))] = None
        else:
            path.unlink(missing_ok=True)

    def _thread_path(self, thread_id: str) -> Path:
        return self.threads_dir / f"{thread_id}.json"

    def _read_json(self, path: Path) -> dict:
        relative = str(path.relative_to(self.root))
        if self._pending is not None and relative in self._pending:
            value = self._pending[relative]
            if value is None:
                raise FileNotFoundError(path)
            return json.loads(json.dumps(value))
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, data: dict) -> None:
        if self._pending is not None:
            self._pending[str(path.relative_to(self.root))] = json.loads(json.dumps(data))
        else:
            self._atomic_json(path, data)

    def _atomic_json(self, path: Path, data: dict) -> None:
        if path == self._journal:
            self._publish_control_journal(data)
            return
        if self._recovering:
            self._apply_recovery_data(str(path.relative_to(self.root)), data)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        tmp.chmod(0o600)
        tmp.replace(path)
        # Persist rename before the commit plan can be discarded.
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def _publish_control_journal(self, data):
        """The fixed WAL has bound I/O; arbitrary data writes keep their API."""
        source = self._control_source
        if source is None:
            with self._locked():
                self._publish_control_journal(data)
            return
        body = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if os.name == "nt":
            source.publish_control_journal(body)
            return
        try:
            self._publish_recovery_bytes(source, source.fd, ".management-commit.json", body,
                                         source._check_root, prefix=".management-commit-")
        except (OSError, ValueError) as exc:
            raise InvalidState("management_journal_path") from exc

    @staticmethod
    def _recovery_parts(relative):
        if not isinstance(relative, str):
            raise InvalidState("management_journal_path")
        path = Path(relative)
        if (not path.parts or path.anchor or path.drive
                or str(path) != relative or any(part in {".", ".."} for part in path.parts)):
            raise InvalidState("management_journal_path")
        return path.parts

    @contextmanager
    def _recovery_parent(self, source, parts, *, create):
        parent, opened, guards = source.fd, [], []

        def validate():
            source._check_root()
            for directory, name, identity in guards:
                current = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if (not stat.S_ISDIR(current.st_mode)
                        or (current.st_dev, current.st_ino) != identity):
                    raise InvalidState("management_journal_path")

        try:
            validate()
            for part in parts:
                validate()
                if create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=parent)
                    except FileExistsError:
                        pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                dir_fd=parent)
                opened.append(child)
                info = os.fstat(child)
                guards.append((parent, part, (info.st_dev, info.st_ino)))
                parent = child
            validate()
            yield parent, validate
            validate()
        finally:
            for descriptor in reversed(opened):
                os.close(descriptor)

    def _apply_recovery_data(self, relative, data):
        source = self._control_source
        if source is None:
            raise InvalidState("management_journal_path")
        parts = self._recovery_parts(relative)
        body = None if data is None else (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if os.name == "nt":
            source.recover_data_entry(parts, body)
            return
        try:
            with self._recovery_parent(source, parts[:-1], create=body is not None) as (parent, validate):
                if body is None:
                    validate()
                    info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode):
                        raise InvalidState("management_journal_path")
                    os.unlink(parts[-1], dir_fd=parent)
                    os.fsync(parent)
                else:
                    self._publish_recovery_bytes(source, parent, parts[-1], body, validate)
        except FileNotFoundError:
            source._check_root()
            if body is not None:
                raise

    @staticmethod
    def _publish_recovery_bytes(source, parent, leaf, body, validate, *, prefix=".management-data-"):
        """Only the fixed WAL and its replay use this bound POSIX publisher."""
        temporary = prefix + uuid4().hex + ".tmp"
        descriptor, identity, published = None, None, False
        try:
            validate()
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=parent)
            info = os.fstat(descriptor)
            identity = info.st_dev, info.st_ino
            os.fchmod(descriptor, 0o600)
            stream = os.fdopen(descriptor, "wb")
            descriptor = None
            with stream:
                validate()
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
                current = os.stat(temporary, dir_fd=parent, follow_symlinks=False)
                if (not stat.S_ISREG(current.st_mode)
                        or (current.st_dev, current.st_ino) != identity):
                    raise InvalidState("management_journal_path")
                validate()
                os.replace(temporary, leaf, src_dir_fd=parent, dst_dir_fd=parent)
                published = True
                os.fsync(parent)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if identity is not None and not published:
                try:
                    current = os.stat(temporary, dir_fd=parent, follow_symlinks=False)
                    if stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == identity:
                        os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass

    def artifact_path(self, name: str) -> Path:
        """Resolve a top-level generated artifact without exposing store internals."""
        path = Path(name)
        if path.is_absolute() or path.name != name or name in {"", ".", ".."}:
            raise ValueError("Artefaktname muss ein einfacher Dateiname sein.")
        return self.root / name

    def write_json_artifact(self, name: str, data: Mapping[str, Any]) -> Path:
        path = self.artifact_path(name)
        self._write_json(path, dict(data))
        return path

    def write_text_artifact(self, name: str, text: str) -> Path:
        path = self.artifact_path(name)
        path.write_text(text, encoding="utf-8")
        return path

    def list_threads(self, include_archived: bool = False) -> list[Thread]:
        with self._locked():
            return self._list_threads(include_archived)

    def _list_threads(self, include_archived: bool = False) -> list[Thread]:
        items: list[Thread] = []
        for path in sorted(self.threads_dir.glob("*.json")):
            thread = self.get_thread(path.stem)
            if include_archived or thread.status != "archived":
                items.append(thread)
        items.sort(key=lambda t: (t.updated_at, t.id), reverse=True)
        return items

    @staticmethod
    def _thread_digest(thread):
        payload = thread.to_dict()
        payload.pop("revision", None)
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()

    def _staged_exists(self, path):
        relative = str(path.relative_to(self.root))
        if self._pending is not None and relative in self._pending:
            return self._pending[relative] is not None
        return path.exists()

    def _anchor_thread(self, thread):
        path = self.root / "thread-revisions" / f"{thread.id}.json"
        self._write_json(path, {"revision": thread.revision, "content_hash": self._thread_digest(thread)})

    def get_thread(self, thread_id: str) -> Thread:
        with self._locked():
            if self._pending is None:
                with self.transaction():
                    return self.get_thread(thread_id)
            path = self._thread_path(thread_id)
            if not self._staged_exists(path):
                raise NotFound(f"Thread nicht gefunden: {thread_id}")
            thread = Thread.from_dict(self._read_json(path))
            anchor_path = self.root / "thread-revisions" / f"{thread_id}.json"
            digest = self._thread_digest(thread)
            if self._staged_exists(anchor_path):
                anchor = self._read_json(anchor_path)
                changed = digest != anchor["content_hash"]
                if changed or thread.revision != anchor["revision"]:
                    # Older JSON writers discard unknown fields. The content
                    # anchor detects their changes even if revision stays zero.
                    thread.revision = max(thread.revision, anchor["revision"] + int(changed))
                    self._write_json(path, thread.to_dict())
                    self._anchor_thread(thread)
            else:
                # Observe legacy revision 0 without rewriting the source file.
                self._anchor_thread(thread)
            return thread

    def save_thread(self, thread: Thread) -> None:
        with self._locked():
            if self._pending is None:
                with self.transaction():
                    self.save_thread(thread)
                return
            path = self._thread_path(thread.id)
            exists = self._staged_exists(path)
            actual = self.get_thread(thread.id).revision if exists else 0
            if exists and thread.revision != actual:
                raise ManagementError("revision_conflict", "Thread wurde zwischenzeitlich geändert.", expected_revision=thread.revision, actual_revision=actual)
            thread.revision = actual + 1 if exists else max(1, thread.revision)
            self._write_json(path, thread.to_dict())
            self._anchor_thread(thread)

    def delete_thread(self, thread_id: str) -> None:
        path = self._thread_path(thread_id)
        if not path.exists():
            raise NotFound(f"Thread nicht gefunden: {thread_id}")
        self._delete_path(path)
        snap_dir = self.snaps_dir / thread_id
        if snap_dir.exists():
            for p in snap_dir.glob("*.json"):
                self._delete_path(p)
            if self._pending is None:
                snap_dir.rmdir()
        board_dir = self._whiteboard_dir(thread_id)
        if board_dir.exists():
            for p in board_dir.glob("*.json"):
                self._delete_path(p)
            if self._pending is None:
                board_dir.rmdir()

    def get_current_id(self) -> str | None:
        with self._locked():
            staged = self._pending is not None and "state.json" in self._pending
            if not self.state_path.exists() and not staged:
                return None
            return self._read_json(self.state_path).get("current_id")

    def set_current_id(self, thread_id: str | None) -> None:
        self._write_json(self.state_path, {"current_id": thread_id})

    def save_snapshot(self, snap: Snapshot) -> None:
        path = self.snaps_dir / snap.thread_id / f"{snap.id}.json"
        self._write_json(path, snap.to_dict())

    def get_snapshot(self, snap_id: str) -> Snapshot:
        for path in self.snaps_dir.glob(f"*/{snap_id}.json"):
            return Snapshot.from_dict(self._read_json(path))
        raise NotFound(f"Snapshot nicht gefunden: {snap_id}")

    def _whiteboard_dir(self, thread_id: str) -> Path:
        if (
            not thread_id
            or thread_id in {".", ".."}
            or "/" in thread_id
            or "\\" in thread_id
            or thread_id != Path(thread_id).name
        ):
            raise InvalidState("whiteboard_thread")
        folder = (self.whiteboard_dir / thread_id).resolve()
        if folder.parent != self.whiteboard_dir.resolve():
            raise InvalidState("whiteboard_thread")
        return folder

    def list_whiteboard(self, thread_id: str) -> list[WhiteboardEntry]:
        folder = self._whiteboard_dir(thread_id)
        if not folder.exists():
            return []
        entries = [
            WhiteboardEntry.from_dict(self._read_json(path))
            for path in folder.glob("*.json")
        ]
        entries.sort(key=lambda entry: (entry.created_at, entry.ordinal, entry.id))
        return entries

    def append_whiteboard_entry(self, entry: WhiteboardEntry) -> tuple[WhiteboardEntry, bool]:
        """Write a new file. An existing contribution is never rewritten."""
        self.get_thread(entry.thread_id)
        if (
            not entry.id
            or entry.id in {".", ".."}
            or "/" in entry.id
            or "\\" in entry.id
            or entry.id != Path(entry.id).name
        ):
            raise InvalidState("whiteboard_id")
        folder = self._whiteboard_dir(entry.thread_id)
        folder.mkdir(parents=True, exist_ok=True)
        lock_path = folder / ".append.lock"
        with lock_path.open("a+b") as lock:
            _lock_exclusive(lock)
            try:
                stored, duplicate = plan_whiteboard_append(
                    self.list_whiteboard(entry.thread_id), entry
                )
                if duplicate:
                    return stored, True
                path = folder / f"{entry.id}.json"
                if path.exists():
                    current = WhiteboardEntry.from_dict(self._read_json(path))
                    if current.same_body(entry):
                        return current, True
                    raise InvalidState("whiteboard_conflict")
                self._write_json(path, stored.to_dict())
                return stored, False
            finally:
                _unlock(lock)

    def list_snapshots(self, thread_id: str) -> list[Snapshot]:
        folder = self.snaps_dir / thread_id
        if not folder.exists():
            return []
        snaps = [Snapshot.from_dict(self._read_json(p)) for p in folder.glob("*.json")]
        snaps.sort(key=lambda s: s.created_at, reverse=True)
        return snaps

    def save_node(self, node: KnowledgeNode) -> None:
        self._write_json(self.nodes_dir / f"{node.id}.json", node.to_dict())

    def get_node(self, node_id: str) -> KnowledgeNode:
        path = self.nodes_dir / f"{node_id}.json"
        if not self._staged_exists(path):
            raise NotFound(f"Knoten nicht gefunden: {node_id}")
        return KnowledgeNode.from_dict(self._read_json(path))

    def list_nodes(self) -> list[KnowledgeNode]:
        nodes = [
            KnowledgeNode.from_dict(self._read_json(path))
            for path in self.nodes_dir.glob("*.json")
        ]
        nodes.sort(key=lambda node: (node.updated_at, node.id), reverse=True)
        return nodes

    def save_relation(self, relation: Relation) -> None:
        self._write_json(self.relations_dir / f"{relation.id}.json", relation.to_dict())

    def list_relations(self) -> list[Relation]:
        relations = [
            Relation.from_dict(self._read_json(path))
            for path in self.relations_dir.glob("*.json")
        ]
        relations.sort(key=lambda relation: (relation.created_at, relation.id))
        return relations


    def append_graph_event(self, event: GraphEvent) -> None:
        path = self.events_dir / f"{event.id}.json"
        if path.exists():
            raise ValueError(f"Ereignis existiert bereits: {event.id}")
        self._write_json(path, event.to_dict())

    def list_graph_events(self) -> list[GraphEvent]:
        events = [
            GraphEvent.from_dict(self._read_json(path))
            for path in self.events_dir.glob("*.json")
        ]
        events.sort(key=lambda event: (event.occurred_at, event.id))
        return events

    @staticmethod
    def _source_record_name(source_system: str, source_id: str) -> str:
        value = f"{source_system}\x00{source_id}".encode("utf-8")
        return hashlib.sha256(value).hexdigest() + ".json"

    def save_source_record(self, record: SourceRecord) -> None:
        path = self.source_records_dir / self._source_record_name(
            record.source_system, record.source_id
        )
        self._write_json(path, record.to_dict())

    def get_source_record(self, source_system: str, source_id: str) -> SourceRecord:
        path = self.source_records_dir / self._source_record_name(source_system, source_id)
        if not path.exists():
            raise NotFound(f"Quellbeleg nicht gefunden: {source_system}/{source_id}")
        return SourceRecord.from_dict(self._read_json(path))

    def list_source_records(self, source_system: str | None = None) -> list[SourceRecord]:
        records = [
            SourceRecord.from_dict(self._read_json(path))
            for path in self.source_records_dir.glob("*.json")
        ]
        if source_system is not None:
            records = [item for item in records if item.source_system == source_system]
        records.sort(key=lambda item: item.key)
        return records
