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


def test_node_records_revision_source_and_visibility(svc: ThreadService) -> None:
    node = svc.create_node(
        "decision",
        "Local-first bleibt verbindlich",
        status="confirmed",
        source="user-confirmed",
        visibility="shared",
    )

    assert node.revision == 1
    assert node.source == "user-confirmed"
    assert node.visibility == "shared"
    assert svc.get_node(node.id).to_dict() == node.to_dict()


def test_old_node_data_gets_safe_field_defaults() -> None:
    from threaddesk.core.models import KnowledgeNode

    node = KnowledgeNode.from_dict(
        {"id": "legacy", "kind": "project", "title": "Altbestand"}
    )

    assert node.revision == 1
    assert node.source == "local"
    assert node.visibility == "private"


def test_node_rejects_invalid_provenance_fields(svc: ThreadService) -> None:
    with pytest.raises(InvalidState):
        svc.create_node("task", "Ohne Herkunft", source="")
    with pytest.raises(InvalidState):
        svc.create_node("task", "Falsche Sichtbarkeit", visibility="world")
    with pytest.raises(SecretRejected):
        svc.create_node("task", "Geheimnis", source="sk-abcdefghijklmnop")


@pytest.mark.parametrize(
    ("kind", "start", "target"),
    [
        ("decision", "proposed", "confirmed"),
        ("task", "ready", "assigned"),
        ("result", "unverified", "verified"),
    ],
)
def test_guarded_node_status_transition(
    svc: ThreadService, kind: str, start: str, target: str
) -> None:
    node = svc.create_node(kind, "Prüfobjekt", status=start)

    changed = svc.transition_node(node.id, target, expected_revision=1)

    assert changed.status == target
    assert changed.revision == 2
    assert changed.updated_at >= node.updated_at
    assert svc.get_node(node.id).to_dict() == changed.to_dict()


def test_node_transition_rejects_invalid_path_without_writing(
    svc: ThreadService,
) -> None:
    task = svc.create_node("task", "Arbeitspaket", status="ready")

    with pytest.raises(InvalidState, match="Ungültiger Statuswechsel"):
        svc.transition_node(task.id, "accepted", expected_revision=1)

    unchanged = svc.get_node(task.id)
    assert unchanged.status == "ready"
    assert unchanged.revision == 1


def test_node_transition_rejects_stale_revision_without_writing(
    svc: ThreadService,
) -> None:
    decision = svc.create_node("decision", "Local-first", status="proposed")

    with pytest.raises(InvalidState, match="Veraltete Revision"):
        svc.transition_node(decision.id, "confirmed", expected_revision=0)

    unchanged = svc.get_node(decision.id)
    assert unchanged.status == "proposed"
    assert unchanged.revision == 1


def test_node_transition_is_limited_to_first_three_workflow_types(
    svc: ThreadService,
) -> None:
    project = svc.create_node("project", "ThreadDesk", status="active")

    with pytest.raises(InvalidState, match="noch nicht unterstützt"):
        svc.transition_node(project.id, "paused", expected_revision=1)


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


def test_relation_records_revision_and_source(svc: ThreadService) -> None:
    project = svc.create_node("project", "ThreadDesk")
    task = svc.create_node("task", "Beziehungen", status="ready")

    relation = svc.connect(
        project.id, task.id, "contains", source="user-confirmed"
    )

    assert relation.revision == 1
    assert relation.source == "user-confirmed"
    assert svc.list_relations()[0].to_dict() == relation.to_dict()


def test_old_relation_data_gets_safe_field_defaults() -> None:
    from threaddesk.core.models import Relation

    relation = Relation.from_dict(
        {
            "id": "legacy",
            "source_id": "a",
            "target_id": "b",
            "kind": "contains",
        }
    )

    assert relation.revision == 1
    assert relation.source == "local"


def test_relation_rejects_empty_or_secret_source_without_writing(
    svc: ThreadService,
) -> None:
    project = svc.create_node("project", "ThreadDesk")
    task = svc.create_node("task", "Beziehungen", status="ready")

    with pytest.raises(InvalidState, match="Herkunft fehlt"):
        svc.connect(project.id, task.id, "contains", source="")
    with pytest.raises(SecretRejected):
        svc.connect(
            project.id,
            task.id,
            "contains",
            source="sk-abcdefghijklmnop",
        )

    assert svc.list_relations() == []


def test_graph_writes_create_persistent_append_only_events(tmp_path: Path) -> None:
    first = ThreadService(store=JsonStore(tmp_path))
    decision = first.create_node("decision", "Local-first", status="proposed")
    task = first.create_node("task", "Ereignisse", status="ready")
    relation = first.connect(decision.id, task.id, "supports")
    changed = first.transition_node(
        decision.id, "confirmed", expected_revision=decision.revision
    )

    events = ThreadService(store=JsonStore(tmp_path)).list_graph_events()

    assert [event.name for event in events] == [
        "node.created",
        "node.created",
        "relation.created",
        "node.transitioned",
    ]
    assert events[2].entity_id == relation.id
    assert events[3].revision == changed.revision
    assert events[3].payload == {"from": "proposed", "to": "confirmed"}
    assert len({event.id for event in events}) == 4


def test_rejected_graph_write_does_not_create_event(svc: ThreadService) -> None:
    task = svc.create_node("task", "Ereignisse", status="ready")
    before = svc.list_graph_events()

    with pytest.raises(InvalidState):
        svc.transition_node(task.id, "accepted", expected_revision=task.revision)

    assert svc.list_graph_events() == before
