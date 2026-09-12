from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Mapping

from threaddesk.core.errors import NotFound
from threaddesk.core.models import GraphEvent, KnowledgeNode, Relation, Snapshot, Thread
from threaddesk.core.provenance import SourceRecord

DEFAULT_ROOT = Path.home() / ".threaddesk"


class JsonStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or DEFAULT_ROOT)
        self.threads_dir = self.root / "threads"
        self.snaps_dir = self.root / "snapshots"
        self.nodes_dir = self.root / "nodes"
        self.relations_dir = self.root / "relations"
        self.events_dir = self.root / "graph-events"
        self.source_records_dir = self.root / "source-records"
        self.state_path = self.root / "state.json"
        self.threads_dir.mkdir(parents=True, exist_ok=True)
        self.snaps_dir.mkdir(parents=True, exist_ok=True)
        self.nodes_dir.mkdir(parents=True, exist_ok=True)
        self.relations_dir.mkdir(parents=True, exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.source_records_dir.mkdir(parents=True, exist_ok=True)

    def _thread_path(self, thread_id: str) -> Path:
        return self.threads_dir / f"{thread_id}.json"

    def _read_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)

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
        items: list[Thread] = []
        for path in sorted(self.threads_dir.glob("*.json")):
            thread = Thread.from_dict(self._read_json(path))
            if include_archived or thread.status != "archived":
                items.append(thread)
        items.sort(key=lambda t: (t.updated_at, t.id), reverse=True)
        return items

    def get_thread(self, thread_id: str) -> Thread:
        path = self._thread_path(thread_id)
        if not path.exists():
            raise NotFound(f"Thread nicht gefunden: {thread_id}")
        return Thread.from_dict(self._read_json(path))

    def save_thread(self, thread: Thread) -> None:
        self._write_json(self._thread_path(thread.id), thread.to_dict())

    def delete_thread(self, thread_id: str) -> None:
        path = self._thread_path(thread_id)
        if not path.exists():
            raise NotFound(f"Thread nicht gefunden: {thread_id}")
        path.unlink()
        snap_dir = self.snaps_dir / thread_id
        if snap_dir.exists():
            for p in snap_dir.glob("*.json"):
                p.unlink()
            snap_dir.rmdir()

    def get_current_id(self) -> str | None:
        if not self.state_path.exists():
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
        if not path.exists():
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
