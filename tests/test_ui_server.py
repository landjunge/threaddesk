from __future__ import annotations

from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    return tmp_path


def test_index_lists_threads(home: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from threaddesk.ui.server import create_app

    svc = ThreadService(store=JsonStore(home))
    svc.create("Gnom-Hub Switcher", "erster Gedanke")
    client = TestClient(create_app())
    res = client.get("/")
    assert res.status_code == 200
    assert "ThreadDesk" in res.text
    assert "Gnom-Hub Switcher" in res.text
    assert "erster Gedanke" in res.text


def test_partial_threads_and_switch(home: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from threaddesk.ui.server import create_app

    svc = ThreadService(store=JsonStore(home))
    a = svc.create("Alpha")
    b = svc.create("Beta")
    client = TestClient(create_app())
    listed = client.get("/partials/threads")
    assert listed.status_code == 200
    assert "Alpha" in listed.text
    assert "Beta" in listed.text

    switched = client.post(f"/threads/{a.id}/switch")
    assert switched.status_code == 200
    assert "Alpha" in switched.text
    assert ThreadService(store=JsonStore(home)).current().id == a.id
    assert b.id != a.id


def test_write_note_status_snapshot_and_gate(home: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from threaddesk.ui.server import create_app

    client = TestClient(create_app())
    created = client.post("/threads", data={"title": "Gamma", "description": "d"})
    assert created.status_code == 200
    svc = ThreadService(store=JsonStore(home))
    thread = svc.current()
    assert thread is not None
    assert thread.title == "Gamma"

    note = client.post(f"/threads/{thread.id}/note", data={"text": "stand heute"})
    assert note.status_code == 200
    assert "stand heute" in note.text

    status = client.post(f"/threads/{thread.id}/status", data={"status": "active"})
    assert status.status_code == 200
    assert ThreadService(store=JsonStore(home)).current().status == "active"

    snap = client.post(f"/threads/{thread.id}/snapshot", data={"label": "vor-umbau"})
    assert snap.status_code == 200
    snaps = ThreadService(store=JsonStore(home)).snapshots(thread.id)
    assert snaps
    assert snaps[0].label == "vor-umbau"

    client.post(f"/threads/{thread.id}/note", data={"text": "anders"})
    restored = client.post(f"/snapshots/{snaps[0].id}/restore")
    assert restored.status_code == 200
    assert ThreadService(store=JsonStore(home)).current().context.notes == "stand heute"

    frozen = client.post("/gate/freeze", data={"frozen": "1"})
    assert frozen.status_code == 200
    assert ThreadService(store=JsonStore(home)).gate()["frozen"] is True
