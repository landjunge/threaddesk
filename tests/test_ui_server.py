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
