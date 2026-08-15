from __future__ import annotations

import json
from pathlib import Path

from threaddesk.core.errors import InvalidState, NotFound, StoreCorrupt
from threaddesk.core.models import Snapshot, Thread, is_valid_id

DEFAULT_ROOT = Path.home() / ".threaddesk"


class JsonStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or DEFAULT_ROOT)
        self.threads_dir = self.root / "threads"
        self.snaps_dir = self.root / "snapshots"
        self.state_path = self.root / "state.json"
        self.threads_dir.mkdir(parents=True, exist_ok=True)
        self.snaps_dir.mkdir(parents=True, exist_ok=True)
        # Names of files the last listing could not read. UI may warn about them.
        self.last_skipped: list[str] = []

    def _thread_path(self, thread_id: str) -> Path:
        # Guard here, not only in the service: every caller gets the same floor.
        # Same message as a missing thread, so nothing leaks about the filesystem.
        if not is_valid_id(thread_id):
            raise NotFound(f"Thread nicht gefunden: {thread_id}")
        return self.threads_dir / f"{thread_id}.json"

    def _snap_dir(self, thread_id: str) -> Path:
        if not is_valid_id(thread_id):
            raise NotFound(f"Thread nicht gefunden: {thread_id}")
        return self.snaps_dir / thread_id

    def _read_json(self, path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StoreCorrupt(f"Datei unlesbar: {path.name}") from exc

    def _write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)

    def list_threads(self, include_archived: bool = False) -> list[Thread]:
        items: list[Thread] = []
        skipped: list[str] = []
        for path in sorted(self.threads_dir.glob("*.json")):
            try:
                thread = Thread.from_dict(self._read_json(path))
            except (StoreCorrupt, InvalidState):
                # One broken file must never take down the whole listing.
                skipped.append(path.name)
                continue
            if include_archived or thread.status != "archived":
                items.append(thread)
        self.last_skipped = skipped
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
        snap_dir = self._snap_dir(thread_id)
        if snap_dir.exists():
            for p in snap_dir.glob("*.json"):
                p.unlink()
            snap_dir.rmdir()

    def get_current_id(self) -> str | None:
        if not self.state_path.exists():
            return None
        try:
            data = self._read_json(self.state_path)
        except StoreCorrupt:
            # state.json is disposable: a broken pointer must not block the store.
            return None
        if not isinstance(data, dict):
            return None
        current = data.get("current_id")
        return current if isinstance(current, str) and current else None

    def set_current_id(self, thread_id: str | None) -> None:
        self._write_json(self.state_path, {"current_id": thread_id})

    def save_snapshot(self, snap: Snapshot) -> None:
        if not is_valid_id(snap.id):
            raise InvalidState(f"Snapshot-ID unzulässig: {snap.id}")
        path = self._snap_dir(snap.thread_id) / f"{snap.id}.json"
        self._write_json(path, snap.to_dict())

    def get_snapshot(self, snap_id: str) -> Snapshot:
        # Unvalidated ids would let '*' or '..' loose inside the glob pattern.
        if not is_valid_id(snap_id):
            raise NotFound(f"Snapshot nicht gefunden: {snap_id}")
        for path in self.snaps_dir.glob(f"*/{snap_id}.json"):
            return Snapshot.from_dict(self._read_json(path))
        raise NotFound(f"Snapshot nicht gefunden: {snap_id}")

    def list_snapshots(self, thread_id: str) -> list[Snapshot]:
        folder = self._snap_dir(thread_id)
        if not folder.exists():
            return []
        snaps: list[Snapshot] = []
        skipped: list[str] = []
        for path in folder.glob("*.json"):
            try:
                snaps.append(Snapshot.from_dict(self._read_json(path)))
            except (StoreCorrupt, InvalidState):
                skipped.append(path.name)
        self.last_skipped = skipped
        snaps.sort(key=lambda s: s.created_at, reverse=True)
        return snaps
