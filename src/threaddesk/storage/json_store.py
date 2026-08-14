from __future__ import annotations

import json
from pathlib import Path

from threaddesk.core.errors import NotFound
from threaddesk.core.models import Snapshot, Thread

DEFAULT_ROOT = Path.home() / ".threaddesk"


class JsonStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or DEFAULT_ROOT)
        self.threads_dir = self.root / "threads"
        self.snaps_dir = self.root / "snapshots"
        self.state_path = self.root / "state.json"
        self.threads_dir.mkdir(parents=True, exist_ok=True)
        self.snaps_dir.mkdir(parents=True, exist_ok=True)

    def _thread_path(self, thread_id: str) -> Path:
        return self.threads_dir / f"{thread_id}.json"

    def _read_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)

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
