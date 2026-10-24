"""Index, local commands, and the KiraBridge boundary stay separate."""
from __future__ import annotations

from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.services.library_bridge import contract
from threaddesk.services.library_commands import execute
from threaddesk.services.library_import import LibraryImporter
from threaddesk.storage.json_store import JsonStore


def test_index_survives_restart_and_a_failed_blob(tmp_path: Path) -> None:
    store = JsonStore(tmp_path / "desk")
    importer = LibraryImporter(store)
    source = tmp_path / "library" / "Notes"
    source.mkdir(parents=True)
    (source / "plan.md").write_text("Brückenplan\n", encoding="utf-8")
    (source / "picture.png").write_bytes(b"\x89PNG\r\nnot-a-real-body")
    summary = importer.import_tree(source)
    assert summary["index"]["status"] == "ready"
    assert summary["index"]["documents"] == 2
    again = LibraryImporter(store)
    assert again.catalog()["index"]["documents"] == 2
    hits = again.rebuild_index()
    assert hits["documents"] == 2
    from threaddesk.services.library_index import LibraryIndex
    found = LibraryIndex(importer.root).search("Brückenplan")
    assert found[0]["filename"] == "plan.md"
    markdown = next(item for item in importer._read_records() if item["filename"] == "plan.md")
    (importer.blobs / markdown["sha256"]).unlink()
    rebuilt = LibraryIndex(importer.root).rebuild(importer._read_records(), importer.blobs)
    assert rebuilt["documents"] == 1
    assert rebuilt["failed"] == 1
    assert LibraryIndex(importer.root).search("picture")[0]["filename"] == "picture.png"


def test_commands_find_open_and_organize_without_touching_bytes(tmp_path: Path) -> None:
    store = JsonStore(tmp_path / "desk")
    service = ThreadService(store=store)
    service.create("4AllPass")
    importer = LibraryImporter(store)
    source = tmp_path / "library"
    (source / "Loose").mkdir(parents=True)
    file_path = source / "Loose" / "note.md"
    file_path.write_text("Alpha plan\n", encoding="utf-8")
    before = file_path.read_bytes()
    importer.import_tree(source)
    from threaddesk.services.library_index import LibraryIndex
    index = LibraryIndex(importer.root)

    def search(text: str):
        return index.search(text)

    found = execute("finde plan", search=search, reassign=importer.reassign)
    assert found["ok"] is True
    assert found["hits"][0]["filename"] == "note.md"
    opened = execute("öffne note.md", search=search, reassign=importer.reassign)
    assert opened["action"] == "open"
    record_id = opened["record_id"]
    blob_before = (importer.blobs / importer._record_by_id(record_id)["sha256"]).read_bytes()
    moved = execute("ordne note.md zu 4AllPass", search=search, reassign=importer.reassign)
    assert moved["ok"] is True
    assert moved["hits"][0]["thread_title"] == "4AllPass"
    assert file_path.read_bytes() == before
    assert (importer.blobs / importer._record_by_id(record_id)["sha256"]).read_bytes() == blob_before
    missing = execute("ordne note.md zu Unknown", search=search, reassign=importer.reassign)
    assert missing["error"] == "thread_missing"
    assert execute("löschen alles", search=search, reassign=importer.reassign)["error"] == "unknown_command"


def test_command_route_rebuilds_a_broken_index_and_opens_the_copy(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("fastapi")
    from http_ui_client import UIClient
    from threaddesk.ui.server import create_app

    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path / "desk"))
    source = tmp_path / "library" / "Notes"
    source.mkdir(parents=True)
    (source / "plan.md").write_text("Brueckenplan\n", encoding="utf-8")
    client = UIClient(create_app())
    imported = client.post("/library/folder", data={"source": str(source)})
    assert imported.status_code == 200
    assert "Index bereit" in imported.text
    index = tmp_path / "desk" / "library-files" / "index.json"
    index.write_text("{", encoding="utf-8")
    broken = client.get("/library")
    assert "Index unvollständig" in broken.text
    found = client.post("/library/command", data={"command": "finde Brueckenplan"})
    assert found.status_code == 200
    assert "plan.md" in found.text
    opened = client.post("/library/command", data={"command": "oeffne plan.md"}, follow_redirects=False)
    assert opened.status_code == 303
    assert opened.headers["location"].startswith("/library/files/")
    downloaded = client.get(opened.headers["location"])
    assert downloaded.status_code == 200
    assert downloaded.content == b"Brueckenplan\n"
    unknown = client.post("/library/command", data={"command": "loesche alles"})
    assert unknown.status_code == 200
    assert "unbekannt" in unknown.text
    assert "unknown_command" not in unknown.text


def test_open_and_organize_wait_when_several_files_match() -> None:
    hits = [
        {"id": "a" * 12, "filename": "plan-a.md"},
        {"id": "b" * 12, "filename": "plan-b.md"},
    ]
    moved: list[tuple[str, str]] = []

    def search(_text: str):
        return hits

    def reassign(record_id: str, title: str):
        moved.append((record_id, title))
        return {"id": record_id, "filename": "plan-a.md", "thread_title": title}

    opened = execute("öffne plan", search=search, reassign=reassign)
    assert opened["action"] == "choose"
    assert "record_id" not in opened
    assert len(opened["hits"]) == 2
    ambiguous = execute("ordne plan zu 4AllPass", search=search, reassign=reassign)
    assert ambiguous["action"] == "choose"
    assert moved == []
    exact = execute("open plan-a.md", search=search, reassign=reassign)
    assert exact["record_id"] == "a" * 12

    seen: dict[str, str] = {}

    def search_named(text: str):
        seen["query"] = text
        return [{"id": "c" * 12, "filename": "Bericht zu Q3.md"}]

    organized = execute("ordne Bericht zu Q3 zu 4AllPass", search=search_named, reassign=reassign)
    assert seen["query"] == "Bericht zu Q3"
    assert organized["action"] == "organize"
    assert moved == [("c" * 12, "4AllPass")]


def test_total_read_failure_keeps_a_ready_index(tmp_path: Path) -> None:
    store = JsonStore(tmp_path / "desk")
    importer = LibraryImporter(store)
    source = tmp_path / "library"
    source.mkdir()
    (source / "plan.md").write_text("eins\n", encoding="utf-8")
    (source / "note.md").write_text("zwei\n", encoding="utf-8")
    importer.import_tree(source)
    from threaddesk.services.library_index import LibraryIndex
    index = LibraryIndex(importer.root)
    before = index.path.read_text(encoding="utf-8")
    for record in importer._read_records():
        (importer.blobs / record["sha256"]).unlink()
    kept = index.rebuild(importer._read_records(), importer.blobs)
    assert kept["status"] == "failed"
    assert kept["error"] == "index_kept"
    assert index.path.read_text(encoding="utf-8") == before
    escaped = index.rebuild(
        [{"id": "d" * 12, "status": "stored", "filename": "x.md", "sha256": "/etc/passwd"}],
        importer.blobs,
    )
    assert escaped["documents"] == 2
    assert "/etc/passwd" not in index.path.read_text(encoding="utf-8")


def test_bridge_contract_has_no_speech_operation() -> None:
    described = contract()
    assert described["bridge_speech_operations"] == []
    assert described["executes_programs"] is False
    assert described["reads_originals"] is False
    assert described["local_commands"] == ["find", "open", "organize"]
