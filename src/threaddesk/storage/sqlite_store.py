"""SQLite implementation of the local ThreadDesk store contract."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator, Mapping

from threaddesk.core.errors import NotFound
from threaddesk.core.models import GraphEvent, KnowledgeNode, Relation, Snapshot, Thread
from threaddesk.core.provenance import SourceRecord
from threaddesk.storage.schema import FTS_SQL, MIGRATIONS, SCHEMA_SQL, SCHEMA_VERSION


class SQLiteStore:
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

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._transaction_depth:
            raise RuntimeError("Verschachtelte Transaktionen werden nicht unterstützt.")
        self._transaction_depth = 1
        self.connection.execute("BEGIN")
        try:
            yield
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()
        finally:
            self._transaction_depth = 0

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

    def write_text_artifact(self, name: str, text: str) -> Path:
        path = self.artifact_path(name)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
        return path

    def list_threads(self, include_archived: bool = False) -> list[Thread]:
        sql = "SELECT payload FROM threads"
        values: tuple[str, ...] = ()
        if not include_archived:
            sql += " WHERE status != ?"
            values = ("archived",)
        rows = self.connection.execute(sql, values).fetchall()
        items = [Thread.from_dict(self._load(row)) for row in rows]
        items.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
        return items

    def get_thread(self, thread_id: str) -> Thread:
        row = self.connection.execute("SELECT payload FROM threads WHERE id = ?", (thread_id,)).fetchone()
        if row is None:
            raise NotFound(f"Thread nicht gefunden: {thread_id}")
        return Thread.from_dict(self._load(row))

    def save_thread(self, thread: Thread) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO threads(id,status,updated_at,payload) VALUES (?,?,?,?)",
            (thread.id, thread.status, thread.updated_at, self._dump(thread.to_dict())),
        )
        self._commit()

    def delete_thread(self, thread_id: str) -> None:
        cursor = self.connection.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
        if not cursor.rowcount:
            raise NotFound(f"Thread nicht gefunden: {thread_id}")
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
        self.connection.execute(
            "INSERT OR REPLACE INTO snapshots(id,thread_id,created_at,payload) VALUES (?,?,?,?)",
            (snap.id, snap.thread_id, snap.created_at, self._dump(snap.to_dict())),
        )
        self._commit()

    def get_snapshot(self, snap_id: str) -> Snapshot:
        row = self.connection.execute("SELECT payload FROM snapshots WHERE id = ?", (snap_id,)).fetchone()
        if row is None:
            raise NotFound(f"Snapshot nicht gefunden: {snap_id}")
        return Snapshot.from_dict(self._load(row))

    def list_snapshots(self, thread_id: str) -> list[Snapshot]:
        rows = self.connection.execute("SELECT payload FROM snapshots WHERE thread_id = ?", (thread_id,)).fetchall()
        items = [Snapshot.from_dict(self._load(row)) for row in rows]
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items

    def save_node(self, node: KnowledgeNode) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO nodes(id,kind,status,updated_at,payload) VALUES (?,?,?,?,?)",
            (node.id, node.kind, node.status, node.updated_at, self._dump(node.to_dict())),
        )
        self._commit()

    def get_node(self, node_id: str) -> KnowledgeNode:
        row = self.connection.execute("SELECT payload FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if row is None:
            raise NotFound(f"Knoten nicht gefunden: {node_id}")
        return KnowledgeNode.from_dict(self._load(row))

    def list_nodes(self) -> list[KnowledgeNode]:
        items = [KnowledgeNode.from_dict(self._load(row)) for row in self.connection.execute("SELECT payload FROM nodes")]
        items.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
        return items

    def save_relation(self, relation: Relation) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO relations(id,source_id,target_id,kind,created_at,payload) VALUES (?,?,?,?,?,?)",
            (relation.id, relation.source_id, relation.target_id, relation.kind, relation.created_at, self._dump(relation.to_dict())),
        )
        self._commit()

    def list_relations(self) -> list[Relation]:
        items = [Relation.from_dict(self._load(row)) for row in self.connection.execute("SELECT payload FROM relations")]
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
