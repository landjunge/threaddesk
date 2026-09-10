from __future__ import annotations

from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import InvalidState, NotFound, SecretRejected
from threaddesk.storage.json_store import JsonStore


@pytest.fixture
def svc(tmp_path: Path) -> ThreadService:
    return ThreadService(store=JsonStore(tmp_path))


def test_create_nodes_and_connect_them(svc: ThreadService) -> None:
    project = svc.create_node("project", "ThreadDesk", status="active")
    task = svc.create_node("task", "Datenmodell bauen", status="active")

    relation = svc.connect(project.id, task.id, "contains")

    assert svc.get_node(project.id).title == "ThreadDesk"
    assert svc.get_node(task.id).status == "active"
    assert relation.source_id == project.id
    assert relation.target_id == task.id
    assert svc.relations_for(project.id) == [relation]


def test_graph_survives_a_fresh_service_instance(tmp_path: Path) -> None:
    first = ThreadService(store=JsonStore(tmp_path))
    decision = first.create_node(
        "decision",
        "Notion ist nur die Übergangslösung",
        status="confirmed",
        details="ThreadDesk wird das gemeinsame Projektgedächtnis.",
        metadata={"source": "brainstorming"},
    )

    second = ThreadService(store=JsonStore(tmp_path))
    loaded = second.get_node(decision.id)

    assert loaded.to_dict() == decision.to_dict()


def test_connect_rejects_unknown_nodes_without_writing(svc: ThreadService) -> None:
    project = svc.create_node("project", "ThreadDesk")

    with pytest.raises(NotFound):
        svc.connect(project.id, "missing", "contains")

    assert svc.list_relations() == []


def test_node_input_is_validated(svc: ThreadService) -> None:
    with pytest.raises(InvalidState):
        svc.create_node("unknown", "Etwas")
    with pytest.raises(InvalidState):
        svc.create_node("task", "")
    with pytest.raises(InvalidState):
        svc.create_node("task", "Etwas", status="not-a-status")
    with pytest.raises(SecretRejected):
        svc.create_node("task", "Etwas", metadata={"api_key": "sk-abcdefghijklmnop"})


def test_existing_thread_files_remain_compatible(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    thread = ThreadService(store=store).create("Alter Thread")

    project = ThreadService(store=JsonStore(tmp_path)).create_node(
        "project", "Neues Projekt"
    )

    reopened = ThreadService(store=JsonStore(tmp_path))
    assert reopened.get(thread.id).title == "Alter Thread"
    assert reopened.get_node(project.id).title == "Neues Projekt"


def test_graph_payload_is_read_only_and_filterable(svc: ThreadService) -> None:
    project = svc.create_node("project", "ThreadDesk", status="active")
    task = svc.create_node("task", "Karte bauen", status="blocked")
    decision = svc.create_node("decision", "Local-first", status="confirmed")
    svc.connect(project.id, task.id, "contains")
    svc.connect(decision.id, project.id, "supports")

    graph = svc.graph(status="active")

    assert graph["counts"] == {"nodes": 1, "relations": 0}
    assert graph["nodes"][0]["id"] == project.id
    assert graph["relations"] == []


def test_graph_endpoint_returns_map_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from threaddesk.ui.server import create_app

    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    svc = ThreadService(store=JsonStore(tmp_path))
    project = svc.create_node("project", "ThreadDesk", status="active")

    response = TestClient(create_app()).get("/api/graph?kind=project")

    assert response.status_code == 200
    assert response.json()["nodes"][0]["id"] == project.id
    assert response.json()["counts"]["nodes"] == 1


def test_knowledge_list_can_create_nodes_and_relations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from threaddesk.ui.server import create_app

    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    client = TestClient(create_app())

    created = client.post(
        "/knowledge/nodes",
        data={"kind": "project", "title": "ThreadDesk", "status": "active"},
        follow_redirects=False,
    )
    assert created.status_code == 303

    svc = ThreadService(store=JsonStore(tmp_path))
    project = svc.list_nodes()[0]
    task = svc.create_node("task", "Listenansicht", status="active")
    connected = client.post(
        "/knowledge/relations",
        data={
            "source_id": project.id,
            "target_id": task.id,
            "kind": "contains",
        },
        follow_redirects=False,
    )
    assert connected.status_code == 303

    page = client.get("/knowledge")
    assert page.status_code == 200
    assert "Wissenspool" in page.text
    assert "ThreadDesk" in page.text
    assert "Listenansicht" in page.text
    assert "contains" in page.text
