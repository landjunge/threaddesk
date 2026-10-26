"""Full-file library import. Originals stay put. The store is a temp directory."""
from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import NotFound
from threaddesk.services.library_import import (
    LibraryImportError,
    LibraryImporter,
    MAX_FILE_BYTES,
)
from threaddesk.storage.json_store import JsonStore


PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x00\x03\x00\x01\x00\x05\xfe\xd4\xef\x00\x00\x00\x00IEND\xaeB`\x82"
)
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _store(tmp_path: Path) -> tuple[JsonStore, ThreadService, LibraryImporter]:
    store = JsonStore(tmp_path / "desk")
    service = ThreadService(store=store)
    return store, service, LibraryImporter(store)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_imports_bytes_assigns_projects_and_leaves_originals(tmp_path: Path) -> None:
    store, service, importer = _store(tmp_path)
    project = service.create("4AllPass", "bestehend")
    current = store.get_current_id()
    source = tmp_path / "library"
    (source / "4AllPass").mkdir(parents=True)
    (source / "Loose").mkdir()
    note = source / "4AllPass" / "note.md"
    note.write_text("# Plan\n", encoding="utf-8")
    text = source / "4AllPass" / "plain.txt"
    text.write_text("nur text\n", encoding="utf-8")
    pdf = source / "4AllPass" / "brief.pdf"
    pdf.write_bytes(PDF)
    image = source / "Loose" / "dot.png"
    image.write_bytes(PNG)
    sheet = source / "4AllPass" / "numbers.xlsx"
    sheet.write_bytes(b"PK\x03\x04xlsx-bytes")
    audio = source / "Loose" / "clip.mp3"
    audio.write_bytes(b"ID3" + b"\x00" * 16)
    video = source / "Loose" / "clip.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 8)
    archive = source / "4AllPass" / "pack.zip"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive_file:
        archive_file.writestr("inside.txt", "inside")
    archive.write_bytes(buffer.getvalue())
    before = {path: (_sha(path), path.stat().st_mtime_ns) for path in (
        note, text, pdf, image, sheet, audio, video, archive)}

    summary = importer.import_tree(source)

    assert summary["stored"] == 8
    assert summary["failed"] == 0
    assert summary["verified"] is True
    for path, (digest, mtime) in before.items():
        assert _sha(path) == digest
        assert path.stat().st_mtime_ns == mtime
    records = importer.catalog()["records"]
    assert len(records) == 8
    assigned = [item for item in records if item["origin_path"].startswith("4AllPass/")]
    assert assigned
    assert {item["thread_id"] for item in assigned} == {project.id}
    loose = [item for item in records if item["origin_path"].startswith("Loose/")]
    assert {item["thread_title"] for item in loose} == {"Nicht zugeordnet"}
    assert store.get_current_id() == current
    blob = importer.blobs / _sha(note)
    assert blob.read_text(encoding="utf-8") == "# Plan\n"
    opened, record = importer.open_record(assigned[0]["id"])
    assert opened.read_bytes() == (source / record["origin_path"]).read_bytes()


def test_duplicate_checksum_keeps_one_blob_and_a_new_version(tmp_path: Path) -> None:
    _store_tuple = _store(tmp_path)
    importer = _store_tuple[2]
    source = tmp_path / "library"
    target = source / "notes"
    target.mkdir(parents=True)
    file_path = target / "note.md"
    file_path.write_text("eins\n", encoding="utf-8")
    first = importer.import_tree(source)
    assert first["stored"] == 1
    blobs = list(importer.blobs.glob("*"))
    assert len([path for path in blobs if not path.name.startswith(".")]) == 1
    again = importer.import_tree(source)
    assert again["duplicate"] == 1
    assert again["stored"] == 0
    assert len(list(importer.records.glob("*.json"))) == 1
    file_path.write_text("zwei\n", encoding="utf-8")
    revised = importer.import_tree(source)
    assert revised["stored"] == 1
    assert len(list(importer.records.glob("*.json"))) == 2
    versions = sorted(item["version"] for item in importer._read_records())
    assert versions == [1, 2]
    assert len([path for path in importer.blobs.iterdir() if not path.name.startswith(".")]) == 2


def test_resume_finishes_a_pending_file_without_a_second_copy(tmp_path: Path) -> None:
    importer = _store(tmp_path)[2]
    source = tmp_path / "library"
    source.mkdir()
    file_path = source / "note.md"
    file_path.write_text("weiter\n", encoding="utf-8")
    importer.import_tree(source)
    digest = _sha(file_path)
    journal = importer._read_journal()
    journal["items"]["note.md"]["status"] = "pending"
    importer._write_json(importer.journal_path, journal)
    blob = importer.blobs / digest
    assert blob.is_file()
    resumed = importer.resume()
    assert resumed["duplicate"] == 1
    assert blob.read_bytes() == b"weiter\n"
    assert importer.catalog()["complete"] is True


def test_rejects_secrets_symlinks_traversal_and_executables(tmp_path: Path) -> None:
    importer = _store(tmp_path)[2]
    source = tmp_path / "library"
    source.mkdir()
    (source / "note.md").write_text("api_key=sk-abcdefghijklmnopqrstuvwxyz\n", encoding="utf-8")
    (source / "module.py").write_text("api_key=sk-abcdefghijklmnopqrstuvwxyz\n", encoding="utf-8")
    (source / "settings.toml").write_text("api_key=sk-abcdefghijklmnopqrstuvwxyz\n", encoding="utf-8")
    (source / ".env").write_text("TOKEN=abc\n", encoding="utf-8")
    (source / "run.exe").write_bytes(b"MZ")
    outside = tmp_path / "outside.txt"
    outside.write_text("geheim\n", encoding="utf-8")
    link = source / "link.md"
    link.symlink_to(outside)
    summary = importer.import_tree(source)
    assert summary["stored"] == 0
    assert not any(importer.blobs.iterdir()) if importer.blobs.exists() else True
    assert outside.read_text(encoding="utf-8") == "geheim\n"
    package = tmp_path / "slip.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("../evil.txt", "nope")
    with pytest.raises(LibraryImportError) as caught:
        importer.import_zip_package(package)
    assert caught.value.code == "unsafe_path"
    assert not list(importer.records.glob("*.json"))


def test_zip_package_assigns_and_blocks_a_broad_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _store(tmp_path)[1]
    importer = LibraryImporter(service.store)
    service.create("TollGate")
    package = tmp_path / "export.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("TollGate/plan.md", "# Toll\n")
        archive.writestr("other.txt", "lose\n")
    summary = importer.import_zip_package(package)
    assert summary["stored"] == 2
    by_origin = {item["origin_path"]: item for item in importer.catalog()["records"]}
    assert by_origin["TollGate/plan.md"]["thread_title"] == "TollGate"
    assert by_origin["other.txt"]["thread_title"] == "Nicht zugeordnet"
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with pytest.raises(LibraryImportError) as caught:
        importer.import_tree(tmp_path)
    assert caught.value.code == "source_too_broad"


def test_many_small_files_survive_a_new_importer(tmp_path: Path) -> None:
    importer = _store(tmp_path)[2]
    source = tmp_path / "library"
    for folder in ("Alpha", "Beta", "Gamma"):
        (source / folder).mkdir(parents=True)
        for index in range(40):
            (source / folder / f"file-{index}.txt").write_text(f"{folder}-{index}\n", encoding="utf-8")
    summary = importer.import_tree(source)
    assert summary["stored"] == 120
    assert summary["verified"] is True
    reopened = LibraryImporter(importer.store)
    catalog = reopened.catalog()
    assert catalog["counts"]["stored"] == 120
    assert catalog["complete"] is True
    sample = catalog["records"][0]
    path, record = reopened.open_record(sample["id"])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_does_not_replace_a_blob_with_different_bytes(tmp_path: Path) -> None:
    importer = _store(tmp_path)[2]
    source = tmp_path / "library"
    source.mkdir()
    (source / "note.md").write_text("stabil\n", encoding="utf-8")
    importer.import_tree(source)
    digest = _sha(source / "note.md")
    blob = importer.blobs / digest
    blob.write_bytes(b"tampered\n")
    (source / "other.md").write_text("stabil\n", encoding="utf-8")
    summary = importer.import_tree(source)
    failed = [item for item in summary["results"] if item["relative_path"] == "other.md"]
    assert failed[0]["status"] == "failed"
    assert failed[0]["error"] == "existing_checksum"
    assert blob.read_bytes() == b"tampered\n"


def test_ui_imports_opens_and_rejects_a_missing_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    from http_ui_client import UIClient

    from threaddesk.ui.server import create_app

    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path / "desk"))
    source = tmp_path / "library" / "4AllPass"
    source.mkdir(parents=True)
    (source / "note.md").write_text("# UI\n", encoding="utf-8")
    (source.parent / "picture.png").write_bytes(PNG)
    client = UIClient(create_app())
    page = client.get("/library")
    assert page.status_code == 200
    assert "Bibliothek importieren" in page.text
    imported = client.post("/library/folder", data={"source": str(source.parent)})
    assert imported.status_code == 200
    assert "note.md" in imported.text
    assert "4AllPass" in imported.text or "Nicht zugeordnet" in imported.text
    record_id = imported.text.split("/library/files/")[1].split('"')[0]
    downloaded = client.get(f"/library/files/{record_id}")
    assert downloaded.status_code == 200
    assert downloaded.content in {b"# UI\n", PNG}
    missing = client.get("/library/files/not-a-record")
    assert missing.status_code == 404
    with pytest.raises(NotFound):
        LibraryImporter(JsonStore(tmp_path / "desk")).open_record("../secrets")
    assert MAX_FILE_BYTES >= 1024 * 1024


def test_upload_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    from http_ui_client import UIClient

    from threaddesk.ui.server import create_app

    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path / "desk"))
    client = UIClient(create_app())
    response = client.post(
        "/library/files",
        files=[("files", ("Alpha/note.md", b"# Hoch\n", "text/markdown"))],
    )
    assert response.status_code == 200
    assert "note.md" in response.text
    package = io.BytesIO()
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("Beta/sheet.csv", "a,b\n")
    packed = client.post(
        "/library/package",
        files={"package": ("export.zip", package.getvalue(), "application/zip")},
    )
    assert packed.status_code == 200
    assert "sheet.csv" in packed.text
