"""NetzwerkPunkt-Suite als sichtbarer Schreibtisch-Inhalt."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore

ROOT = Path(__file__).resolve().parents[1]


def load_seed():
    path = ROOT / "packaging" / "seed_netzwerkpunkt.py"
    spec = importlib.util.spec_from_file_location("seed_netzwerkpunkt", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_creates_suite_threads_knowledge_and_file_paths(tmp_path: Path) -> None:
    still = tmp_path / "05-4allpass-tresor.jpg"
    still.write_bytes(b"fake-jpg")
    landing = tmp_path / "4allpass.html"
    landing.write_text("<html>4AllPass</html>", encoding="utf-8")
    seed = load_seed()
    svc = ThreadService(store=JsonStore(tmp_path / "desk"))
    result = seed.seed_workspace(
        svc,
        files={
            "4AllPass": [still, landing],
            "NetzwerkPunkt": [landing],
        },
    )
    titles = [thread.title for thread in svc.list()]
    assert titles == [
        "NetzwerkPunkt",
        "4AllPass",
        "TollGate",
        "gnom-hub-v1",
        "ThreadDesk",
        "Agent-X-Files",
        "Workshop",
    ]
    assert result["created_threads"] == 7
    four = next(thread for thread in svc.list() if thread.title == "4AllPass")
    assert "Tresor" in four.context.notes
    assert str(still) in four.context.files
    assert four.status == "active"
    node_titles = {node.title: node for node in svc.list_nodes()}
    assert node_titles["NetzwerkPunkt"].kind == "project"
    assert node_titles["4AllPass"].kind == "tool"
    assert node_titles["Identität ist nicht Erlaubnis"].kind == "decision"
    relations = {(rel.source_id, rel.kind, rel.target_id) for rel in svc.list_relations()}
    hub_id = node_titles["NetzwerkPunkt"].id
    vault_id = node_titles["4AllPass"].id
    assert (hub_id, "contains", vault_id) in relations
    assert svc.current().title == "NetzwerkPunkt"


def test_seed_is_idempotent(tmp_path: Path) -> None:
    seed = load_seed()
    svc = ThreadService(store=JsonStore(tmp_path))
    first = seed.seed_workspace(svc)
    second = seed.seed_workspace(svc)
    assert first["created_threads"] == 7
    assert second["created_threads"] == 0
    assert second["skipped_threads"] == 7
    assert len(svc.list()) == 7
    assert len(svc.list_nodes()) == first["created_nodes"]
