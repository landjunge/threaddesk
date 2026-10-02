"""The existing map stays the graph. Threads and nodes point at each other."""

from __future__ import annotations

from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore

MAP_JS = Path(__file__).resolve().parents[1] / "src" / "threaddesk" / "ui" / "static" / "map.js"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    monkeypatch.delenv("THREADDESK_STORAGE", raising=False)
    return tmp_path


def test_graph_schema_stays_and_threads_are_not_nodes(home: Path) -> None:
    svc = ThreadService(store=JsonStore(home))
    thread = svc.create("Nur ein Thread")
    project = svc.create_node("project", "Sichtbarer Knoten", metadata={"thread_id": thread.id})
    person = svc.register_human("Ada", "plum")
    agent = svc.register_agent("Assistent", person["id"], "local-assistant")
    svc.create_node(
        "person", "Ada", metadata={"thread_id": thread.id, "actor_id": person["id"]}
    )
    svc.create_node(
        "agent", "Assistent", metadata={"thread_id": thread.id, "actor_id": agent["id"]}
    )

    graph = svc.graph()

    assert set(graph) == {"schema", "nodes", "relations", "counts", "filters"}
    assert graph["schema"] == "threaddesk.graph.v1"
    titles = [node["title"] for node in graph["nodes"]]
    assert "Nur ein Thread" not in titles
    assert "Sichtbarer Knoten" in titles
    linked = next(node for node in graph["nodes"] if node["id"] == project.id)
    assert linked["metadata"]["thread_id"] == thread.id


def test_thread_and_map_link_both_ways(home: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from threaddesk.ui.server import create_app

    svc = ThreadService(store=JsonStore(home))
    other = svc.create("Daneben")
    thread = svc.create("Akte")
    node = svc.create_node("task", "Verknüpft", metadata={"thread_id": thread.id})
    svc.create_node("task", "Fremd", metadata={"thread_id": other.id})
    client = TestClient(create_app())

    desk = client.get(f"/?thread={thread.id}&node={node.id}")
    assert desk.status_code == 200
    assert "Verknüpft" in desk.text
    assert "Fremd" not in desk.text
    assert f'data-linked-node="{node.id}"' in desk.text
    assert "is-selected" in desk.text
    assert f"/map?thread={thread.id}&amp;node={node.id}" in desk.text
    assert ThreadService(store=JsonStore(home)).current().id == thread.id

    missing = client.get("/?thread=missing-thread")
    assert missing.status_code == 200

    page = client.get("/map")
    assert 'data-graph-endpoint="/api/graph"' in page.text
    assert "data-actor-marks=" in page.text


def test_focus_respects_reduced_motion() -> None:
    source = MAP_JS.read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in source
    body = source.split("const focusOn", 1)[1]
    early, later = body.split('root.classList.add("is-focusing")', 1)
    assert "effects-off" in early and "return" in early
    assert "is-focusing" in later
