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


def test_packet_and_archive(home: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from threaddesk.ui.server import create_app

    client = TestClient(create_app())
    client.post("/threads", data={"title": "Delta", "description": "paket"})
    svc = ThreadService(store=JsonStore(home))
    thread = svc.current()
    assert thread is not None

    handoff = client.post(f"/threads/{thread.id}/handoff")
    assert handoff.status_code == 200
    assert "nicht ausgeführt" in handoff.text
    assert (home / "handoff.json").exists()

    gnom = client.post(f"/threads/{thread.id}/gnom")
    assert gnom.status_code == 200
    assert "threaddesk.gnom" in gnom.text
    assert "nicht gestartet" in gnom.text
    assert (home / "gnom.json").exists()
    assert (home / "gnom-chat.json").exists()

    archived = client.post(f"/threads/{thread.id}/archive")
    assert archived.status_code == 200
    assert ThreadService(store=JsonStore(home)).get(thread.id).status == "archived"
    assert "Archivieren" not in archived.text or "Delta" not in archived.text


def test_index_has_shortcuts_help(home: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from threaddesk.ui.server import create_app

    ThreadService(store=JsonStore(home)).create("Hilfe")
    res = TestClient(create_app()).get("/")
    assert res.status_code == 200
    assert "Tastatur" in res.text
    assert "data-thread-index" in res.text
    assert "Gnom-Brainstorm" in res.text


def test_rename_files_and_prompt_preview(home: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from threaddesk.ui.server import create_app

    client = TestClient(create_app())
    client.post("/threads", data={"title": "Alt", "description": ""})
    thread = ThreadService(store=JsonStore(home)).current()
    assert thread is not None

    renamed = client.post(f"/threads/{thread.id}/rename", data={"title": "Neu"})
    assert renamed.status_code == 200
    assert ThreadService(store=JsonStore(home)).current().title == "Neu"

    added = client.post(f"/threads/{thread.id}/files", data={"path": "src/app.py"})
    assert added.status_code == 200
    assert "src/app.py" in added.text
    assert "src/app.py" in ThreadService(store=JsonStore(home)).current().context.files

    preview = client.post(
        f"/threads/{thread.id}/prompt",
        data={"target": "gnom", "variant": "short"},
    )
    assert preview.status_code == 200
    assert "Prompt-Vorschau" in preview.text
    assert "prompt-text" in preview.text
    saved = client.post(
        f"/threads/{thread.id}/prompt",
        data={"target": "gnom", "variant": "short", "save": "1"},
    )
    assert saved.status_code == 200
    assert ThreadService(store=JsonStore(home)).current().context.prompts

    removed = client.post(
        f"/threads/{thread.id}/files/remove", data={"path": "src/app.py"}
    )
    assert removed.status_code == 200
    assert "src/app.py" not in ThreadService(store=JsonStore(home)).current().context.files


def test_map_page_is_a_read_only_api_graph_view(home: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from threaddesk.ui.server import create_app

    svc = ThreadService(store=JsonStore(home))
    project = svc.create_node("project", "ThreadDesk", status="active")
    task = svc.create_node("task", "Karte", status="ready")
    svc.connect(project.id, task.id, "contains")

    client = TestClient(create_app())
    page = client.get("/map")

    assert page.status_code == 200
    assert 'data-graph-endpoint="/api/graph"' in page.text
    assert 'src="/static/map.js"' in page.text
    assert "Hineinzoomen" in page.text
    assert "Herauszoomen" in page.text

    graph = client.get("/api/graph").json()
    assert graph["counts"] == {"nodes": 2, "relations": 1}


def test_knowledge_page_applies_guarded_node_transition(home: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from threaddesk.ui.server import create_app

    svc = ThreadService(store=JsonStore(home))
    task = svc.create_node("task", "UI-Ablauf", status="ready")
    client = TestClient(create_app())

    page = client.get("/knowledge")
    assert 'value="assigned"' in page.text
    assert f'value="{task.revision}"' in page.text

    changed = client.post(
        f"/knowledge/nodes/{task.id}/transition",
        data={"status": "assigned", "expected_revision": task.revision},
        follow_redirects=False,
    )

    assert changed.status_code == 303
    stored = ThreadService(store=JsonStore(home)).get_node(task.id)
    assert stored.status == "assigned"
    assert stored.revision == 2


def test_knowledge_page_filters_nodes_and_relations(home: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from threaddesk.ui.server import create_app

    svc = ThreadService(store=JsonStore(home))
    project = svc.create_node("project", "ThreadDesk", status="active")
    task = svc.create_node("task", "Unsichtbare Aufgabe", status="blocked")
    svc.connect(project.id, task.id, "contains")

    page = TestClient(create_app()).get("/knowledge?kind=project&status=active")

    assert page.status_code == 200
    assert "ThreadDesk" in page.text
    assert "Unsichtbare Aufgabe" not in page.text
    assert "contains" not in page.text
    assert 'option value="project" selected' in page.text
    assert 'option value="active" selected' in page.text
