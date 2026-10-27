"""SQLite implementation of the local ThreadDesk store contract."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterator, Mapping

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
from threaddesk.storage.lifecycle import SQLiteLifecycleStore
from threaddesk.storage.owner_documents import MigratedOwnerDocuments
from threaddesk.storage.schema import FTS_SQL, MIGRATIONS, SCHEMA_SQL, SCHEMA_VERSION


class SQLiteStore(SQLiteLifecycleStore, MigratedOwnerDocuments):
    def search_adapter(self):
        from threaddesk.storage.search_sqlite import SQLiteSearchAdapter
        return SQLiteSearchAdapter(self)

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or Path.home() / ".threaddesk")
        self.root.mkdir(parents=True, exist_ok=True)
        self.database_path = self.root / "threaddesk.sqlite3"
        self.connection = sqlite3.connect(self.database_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_info (version INTEGER NOT NULL)"
        )
        row = self.connection.execute("SELECT version FROM schema_info").fetchone()
        if row is None:
            self.connection.executescript(SCHEMA_SQL)
            self.connection.execute("INSERT INTO schema_info(version) VALUES (?)", (SCHEMA_VERSION,))
        elif row["version"] > SCHEMA_VERSION:
            raise RuntimeError(f"Nicht unterstützte Schema-Version: {row['version']}")
        else:
            version = int(row["version"])
            while version < SCHEMA_VERSION:
                next_version = version + 1
                migration = MIGRATIONS.get(next_version)
                if migration is None:
                    raise RuntimeError(
                        f"Keine Migration für Schema-Version {next_version}."
                    )
                self.connection.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + migration
                    + f"\nUPDATE schema_info SET version = {next_version};\nCOMMIT;"
                )
                version = next_version
            self.connection.executescript(SCHEMA_SQL)
        try:
            self.connection.executescript(FTS_SQL)
        except sqlite3.OperationalError:
            pass
        self.connection.commit()
        self._transaction_depth = 0
        self._transaction_owner: int | None = None

    @property
    def workspace_path(self) -> Path:
        return self.root

    @property
    def in_transaction(self) -> bool:
        """A SQLite connection's transaction may only be joined by its owner."""
        return bool(self._transaction_depth) and self._transaction_owner == threading.get_ident()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._transaction_depth:
            if self._transaction_owner != threading.get_ident():
                raise RuntimeError("SQLite transaction belongs to another thread.")
            raise RuntimeError("Verschachtelte Transaktionen werden nicht unterstützt.")
        self.connection.execute("BEGIN IMMEDIATE")
        self._transaction_depth = 1
        self._transaction_owner = threading.get_ident()
        try:
            yield
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()
        finally:
            self._transaction_depth = 0
            self._transaction_owner = None

    def _commit(self) -> None:
        if not self._transaction_depth:
            self.connection.commit()

    @staticmethod
    def _dump(data: Mapping[str, Any]) -> str:
        return json.dumps(dict(data), ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _load(row: sqlite3.Row) -> dict[str, Any]:
        return json.loads(row["payload"])

    def artifact_path(self, name: str) -> Path:
        path = Path(name)
        if path.is_absolute() or path.name != name or name in {"", ".", ".."}:
            raise ValueError("Artefaktname muss ein einfacher Dateiname sein.")
        return self.root / name

    def write_json_artifact(self, name: str, data: Mapping[str, Any]) -> Path:
        return self.write_text_artifact(name, json.dumps(dict(data), ensure_ascii=False, indent=2) + "\n")

    def read_json_artifact(self, name: str) -> dict[str, Any] | None:
        """Filesystem artifacts are immediate, outside SQLite rollback."""
        try:
            value = json.loads(self.artifact_path(name).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if not isinstance(value, dict):
            raise InvalidState("artifact_json_object")
        return value

    def write_text_artifact(self, name: str, text: str) -> Path:
        path = self.artifact_path(name)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
        return path

    def list_threads(self, include_archived: bool = False, *, include_trashed: bool = False) -> list[Thread]:
        sql = "SELECT payload FROM threads"
        values: tuple[str, ...] = ()
        if not include_archived:
            sql += " WHERE status != ?"
            values = ("archived",)
        rows = self.connection.execute(sql, values).fetchall()
        items = [Thread.from_dict(self._load(row)) for row in rows]
        if not include_trashed:
            items = [item for item in items if not self.object_in_trash("thread", item.id)]
        items.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
        return items

    def get_thread(self, thread_id: str, *, include_trashed: bool = False) -> Thread:
        if not include_trashed:
            self.require_live_object("thread", thread_id)
        row = self.connection.execute("SELECT payload FROM threads WHERE id = ?", (thread_id,)).fetchone()
        if row is None:
            raise NotFound(f"Thread nicht gefunden: {thread_id}")
        return Thread.from_dict(self._load(row))

    def save_thread(self, thread: Thread) -> None:
        self.require_live_object("thread", thread.id)
        if not self._transaction_depth:
            with self.transaction():
                self.save_thread(thread)
            return
        row = self.connection.execute("SELECT payload FROM threads WHERE id=?", (thread.id,)).fetchone()
        actual = int(self._load(row).get("revision") or 0) if row else 0
        if row is not None and thread.revision != actual:
            raise ManagementError("revision_conflict", "Thread wurde zwischenzeitlich geändert.", expected_revision=thread.revision, actual_revision=actual)
        thread.revision = actual + 1 if row is not None else max(1, thread.revision)
        payload = self._dump(thread.to_dict())
        self.connection.execute(
            "INSERT INTO threads(id,status,updated_at,payload) VALUES (?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at, payload=excluded.payload",
            (thread.id, thread.status, thread.updated_at, payload),
        )
        self.search_adapter().changed(thread.id)

    def list_issued_handoffs(self):
        return [self._load(row) for row in self.connection.execute("SELECT payload FROM issued_handoffs ORDER BY id")]

    def get_issued_handoff(self, handoff_id):
        row = self.connection.execute("SELECT payload FROM issued_handoffs WHERE id=?", (handoff_id,)).fetchone()
        return self._load(row) if row else None

    def save_issued_handoff(self, handoff_id, data):
        self.connection.execute("INSERT INTO issued_handoffs(id,payload) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (handoff_id, self._dump(data)))
        self._commit()

    def list_management_operations(self):
        return [self._load(row) for row in self.connection.execute("SELECT payload FROM management_operations ORDER BY id")]

    def get_management_operation(self, operation_id):
        row = self.connection.execute("SELECT payload FROM management_operations WHERE id=?", (operation_id,)).fetchone()
        return self._load(row) if row else None

    def save_management_operation(self, operation_id, data):
        self.connection.execute("INSERT INTO management_operations(id,payload) VALUES (?,?)", (operation_id, self._dump(data)))
        self._commit()

    def delete_thread(self, thread_id: str) -> None:
        if not self._transaction_depth:
            with self.transaction():
                self.delete_thread(thread_id)
            return
        cursor = self.connection.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
        if not cursor.rowcount:
            raise NotFound(f"Thread nicht gefunden: {thread_id}")
        self.search_adapter().changed(thread_id, deleted=True)
        self._commit()

    def get_current_id(self) -> str | None:
        row = self.connection.execute("SELECT value FROM app_state WHERE key='current_id'").fetchone()
        return None if row is None else row["value"]

    def set_current_id(self, thread_id: str | None) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO app_state(key,value) VALUES ('current_id',?)", (thread_id,)
        )
        self._commit()

    def save_snapshot(self, snap: Snapshot) -> None:
        if not self._transaction_depth:
            with self.transaction():
                self.save_snapshot(snap)
            return
        self.require_live_object("thread", snap.thread_id)
        self.connection.execute(
            "INSERT OR REPLACE INTO snapshots(id,thread_id,created_at,payload) VALUES (?,?,?,?)",
            (snap.id, snap.thread_id, snap.created_at, self._dump(snap.to_dict())),
        )
        self._commit()

    def get_snapshot(self, snap_id: str) -> Snapshot:
        row = self.connection.execute("SELECT payload FROM snapshots WHERE id = ?", (snap_id,)).fetchone()
        if row is None:
            raise NotFound(f"Snapshot nicht gefunden: {snap_id}")
        snap = Snapshot.from_dict(self._load(row))
        self.require_live_object("thread", snap.thread_id)
        return snap

    def list_snapshots(self, thread_id: str, *, include_trashed: bool = False) -> list[Snapshot]:
        if not include_trashed:
            self.require_live_object("thread", thread_id)
        rows = self.connection.execute("SELECT payload FROM snapshots WHERE thread_id = ?", (thread_id,)).fetchall()
        items = [Snapshot.from_dict(self._load(row)) for row in rows]
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items

    def list_whiteboard(self, thread_id: str, *, include_trashed: bool = False) -> list[WhiteboardEntry]:
        self.get_thread(thread_id, include_trashed=include_trashed)
        rows = self.connection.execute(
            "SELECT payload FROM whiteboard_entries WHERE thread_id = ?",
            (thread_id,),
        ).fetchall()
        items = [WhiteboardEntry.from_dict(self._load(row)) for row in rows]
        items.sort(key=lambda item: (item.created_at, item.ordinal, item.id))
        return items

    def append_whiteboard_entry(self, entry: WhiteboardEntry) -> tuple[WhiteboardEntry, bool]:
        if not self._transaction_depth:
            with self.transaction():
                return self.append_whiteboard_entry(entry)
        self.get_thread(entry.thread_id)
        stored, duplicate = plan_whiteboard_append(self.list_whiteboard(entry.thread_id), entry)
        if duplicate:
            return stored, True
        self.connection.execute(
            "INSERT INTO whiteboard_entries(id,thread_id,created_at,ordinal,external_key,payload) VALUES (?,?,?,?,?,?)",
            (stored.id, stored.thread_id, stored.created_at, stored.ordinal, stored.external_key, self._dump(stored.to_dict())),
        )
        return stored, False

    def save_node(self, node: KnowledgeNode, *, include_trashed: bool = False) -> None:
        if not self._transaction_depth:
            with self.transaction():
                self.save_node(node, include_trashed=include_trashed)
            return
        if not include_trashed:
            self.require_live_object("node", node.id)
            if node.metadata.get("thread_id"):
                self.require_live_object("thread", node.metadata["thread_id"])
        self.connection.execute(
            "INSERT OR REPLACE INTO nodes(id,kind,status,updated_at,payload) VALUES (?,?,?,?,?)",
            (node.id, node.kind, node.status, node.updated_at, self._dump(node.to_dict())),
        )
        self._commit()

    def get_node(self, node_id: str, *, include_trashed: bool = False) -> KnowledgeNode:
        if not include_trashed:
            self.require_live_object("node", node_id)
        row = self.connection.execute("SELECT payload FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if row is None:
            raise NotFound(f"Knoten nicht gefunden: {node_id}")
        node = KnowledgeNode.from_dict(self._load(row))
        if not include_trashed and node.metadata.get("thread_id"):
            self.require_live_object("thread", node.metadata["thread_id"])
        return node

    def list_nodes(self, *, include_trashed: bool = False) -> list[KnowledgeNode]:
        items = [KnowledgeNode.from_dict(self._load(row)) for row in self.connection.execute("SELECT payload FROM nodes")]
        if not include_trashed:
            hidden = self.hidden_node_ids(items)
            items = [item for item in items if item.id not in hidden]
        items.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
        return items

    def save_relation(self, relation: Relation) -> None:
        if not self._transaction_depth:
            with self.transaction():
                self.save_relation(relation)
            return
        self.require_live_object("relation", relation.id)
        self.require_live_node_reference(relation.source_id)
        self.require_live_node_reference(relation.target_id)
        self.connection.execute(
            "INSERT OR REPLACE INTO relations(id,source_id,target_id,kind,created_at,payload) VALUES (?,?,?,?,?,?)",
            (relation.id, relation.source_id, relation.target_id, relation.kind, relation.created_at, self._dump(relation.to_dict())),
        )
        self._commit()

    def list_relations(self, *, include_trashed: bool = False) -> list[Relation]:
        items = [Relation.from_dict(self._load(row)) for row in self.connection.execute("SELECT payload FROM relations")]
        if not include_trashed:
            hidden = self.hidden_node_ids(self.list_nodes(include_trashed=True))
            items = [item for item in items if not self.object_in_trash("relation", item.id)
                     and item.source_id not in hidden and item.target_id not in hidden]
        items.sort(key=lambda item: (item.created_at, item.id))
        return items

    def append_graph_event(self, event: GraphEvent) -> None:
        self.connection.execute(
            "INSERT INTO graph_events(id,occurred_at,payload) VALUES (?,?,?)",
            (event.id, event.occurred_at, self._dump(event.to_dict())),
        )
        self._commit()

    def list_graph_events(self) -> list[GraphEvent]:
        items = [GraphEvent.from_dict(self._load(row)) for row in self.connection.execute("SELECT payload FROM graph_events")]
        items.sort(key=lambda item: (item.occurred_at, item.id))
        return items

    def save_import_batch(self, batch_id: str, data: Mapping[str, Any]) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO import_batches(id,payload) VALUES (?,?)",
            (batch_id, self._dump(data)),
        )
        self._commit()

    def get_import_batch(self, batch_id: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT payload FROM import_batches WHERE id = ?", (batch_id,)).fetchone()
        if row is None:
            raise NotFound(f"Import-Batch nicht gefunden: {batch_id}")
        return self._load(row)

    def list_import_batches(self) -> list[dict[str, Any]]:
        return [self._load(row) for row in self.connection.execute("SELECT payload FROM import_batches ORDER BY id")]

    def save_source_record(self, record: SourceRecord) -> None:
        self.connection.execute(
            """INSERT OR REPLACE INTO source_records(
                   source_system,source_id,target_id,payload
               ) VALUES (?,?,?,?)""",
            (
                record.source_system,
                record.source_id,
                record.target_id,
                self._dump(record.to_dict()),
            ),
        )
        self._commit()

    def get_source_record(self, source_system: str, source_id: str) -> SourceRecord:
        row = self.connection.execute(
            "SELECT payload FROM source_records WHERE source_system = ? AND source_id = ?",
            (source_system, source_id),
        ).fetchone()
        if row is None:
            raise NotFound(f"Quellbeleg nicht gefunden: {source_system}/{source_id}")
        return SourceRecord.from_dict(self._load(row))

    def list_source_records(self, source_system: str | None = None) -> list[SourceRecord]:
        if source_system is None:
            rows = self.connection.execute(
                "SELECT payload FROM source_records ORDER BY source_system, source_id"
            )
        else:
            rows = self.connection.execute(
                "SELECT payload FROM source_records WHERE source_system = ? ORDER BY source_id",
                (source_system,),
            )
        return [SourceRecord.from_dict(self._load(row)) for row in rows]

    def save_artifact(self, data: Mapping[str, Any]) -> None:
        self.connection.execute(
            """INSERT OR IGNORE INTO artifacts(
                   sha256,size,relative_path,payload
               ) VALUES (?,?,?,?)""",
            (
                data["sha256"],
                int(data["size"]),
                data["relative_path"],
                self._dump(data),
            ),
        )
        self._commit()

    def list_artifacts(self) -> list[dict[str, Any]]:
        return [
            self._load(row)
            for row in self.connection.execute(
                "SELECT payload FROM artifacts ORDER BY sha256"
            )
        ]

    def link_node_artifact(self, data: Mapping[str, Any]) -> None:
        self.connection.execute(
            """INSERT OR REPLACE INTO node_artifacts(
                   node_id,sha256,role,payload
               ) VALUES (?,?,?,?)""",
            (
                data["node_id"],
                data["sha256"],
                data["role"],
                self._dump(data),
            ),
        )
        self._commit()

    def replace_node_artifact(self, data: Mapping[str, Any]) -> None:
        self.connection.execute(
            "DELETE FROM node_artifacts WHERE node_id = ? AND role = ?",
            (data["node_id"], data["role"]),
        )
        self.link_node_artifact(data)

    def list_node_artifacts(self) -> list[dict[str, Any]]:
        return [
            self._load(row)
            for row in self.connection.execute(
                "SELECT payload FROM node_artifacts ORDER BY node_id, sha256, role"
            )
        ]
