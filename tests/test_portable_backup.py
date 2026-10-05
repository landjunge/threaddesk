"""A desk backup survives the activity file changing while it is written."""

from __future__ import annotations

import json
import threading
import time
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.models import new_thread
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.portable_backup import BackupError, download_backup, restore_backup
from threaddesk.storage.workspace_backup import BackupError as WorkspaceBackupError


def test_activity_writes_do_not_abort_the_backup(tmp_path: Path) -> None:
    store = JsonStore(tmp_path / "home")
    thread = new_thread("Sicherung")
    thread.context.notes = "bleibt"
    store.save_thread(thread)
    store.write_json_artifact("hausmeister-activity.json", {"seen": 1, "kind": "page"})
    (store.whiteboard_dir / thread.id).mkdir(parents=True)
    (store.whiteboard_dir / thread.id / "eintrag.json").write_text(
        json.dumps({"id": "eintrag", "thread_id": thread.id, "content": "Plan"}),
        encoding="utf-8",
    )
    activity = store.artifact_path("hausmeister-activity.json")
    stop = False

    def churn() -> None:
        seen = 0
        while not stop:
            seen += 1
            activity.write_text(json.dumps({"seen": seen, "kind": "pointer"}), encoding="utf-8")

    worker = threading.Thread(target=churn)
    worker.start()
    try:
        body = download_backup(store)
    finally:
        stop = True
        worker.join()
    archive = zipfile.ZipFile(BytesIO(body))
    names = set(archive.namelist())
    assert "workspace/threads/" + thread.id + ".json" in names
    assert "workspace/whiteboard/" + thread.id + "/eintrag.json" in names
    assert "workspace/hausmeister-activity.json" not in names
    restored = restore_backup(body, tmp_path / "restored-root")
    assert json.loads((restored / "threads" / f"{thread.id}.json").read_text())["context"]["notes"] == "bleibt"
    assert (tmp_path / "home" / "threads" / f"{thread.id}.json").exists()


def test_a_changed_thread_still_stops_the_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = JsonStore(tmp_path / "home")
    store.save_thread(new_thread("A"))
    original = Path.read_bytes
    calls = {"n": 0}

    def changing(self: Path) -> bytes:
        calls["n"] += 1
        body = original(self)
        if self.name.endswith(".json") and self.parent.name == "threads" and calls["n"] > 1:
            return body + b" "
        return body

    monkeypatch.setattr(Path, "read_bytes", changing)
    with pytest.raises(WorkspaceBackupError, match="changed during backup"):
        download_backup(store)
