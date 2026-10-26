"""Content search uses stored bytes and canonical IDs across restarts."""

import hashlib
import json
import zipfile

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.models import KnowledgeNode
from threaddesk.services.file_formats import describe, extract, supported_formats
from threaddesk.services.library_index import LibraryIndex, LibrarySearchError
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


def test_registry_distinguishes_each_operation_and_never_runs_source():
    expected = [
        "pdf",
        "doc",
        "docx",
        "odt",
        "rtf",
        "txt",
        "epub",
        "html",
        "md",
        "xls",
        "xlsx",
        "ods",
        "csv",
        "tsv",
        "ppt",
        "pptx",
        "odp",
        "key",
        "jpg",
        "png",
        "gif",
        "webp",
        "tiff",
        "heic",
        "svg",
        "mp3",
        "wav",
        "flac",
        "aac",
        "m4a",
        "ogg",
        "mp4",
        "mov",
        "webm",
        "mkv",
        "avi",
        "py",
        "js",
        "ts",
        "json",
        "xml",
        "yaml",
        "toml",
        "sql",
        "log",
        "zip",
        "tar",
        "gz",
        "7z",
    ]
    assert all(describe("name." + suffix)["manage"] for suffix in expected)
    assert describe("name.doc")["index"] is False
    assert describe("name.doc")["preview"] is False
    assert describe("name.doc")["external_open"] is True
    for suffix in ["py", "js", "ts", "sh", "exe", "unknown"]:
        assert describe("name." + suffix)["external_open"] is False
    assert describe("page.html")["preview_kind"] == "metadata"
    assert describe("image.svg")["preview_kind"] == "metadata"
    assert len(supported_formats()) >= len(expected)


def test_safe_container_adapters_and_bad_neighbor(tmp_path):
    doc = tmp_path / "plan.docx"
    with zipfile.ZipFile(doc, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="x"><w:t>Brückenstrategie</w:t></w:document>',
        )
        archive.writestr("word/vbaProject.bin", b"should never run")
    assert "Brückenstrategie" in extract(doc, doc.name)["text"]
    odf = tmp_path / "sheet.ods"
    with zipfile.ZipFile(odf, "w") as archive:
        archive.writestr(
            "content.xml", "<document><cell>Quartalsumsatz</cell></document>"
        )
    assert "Quartalsumsatz" in extract(odf, odf.name)["text"]
    bad = tmp_path / "broken.docx"
    bad.write_bytes(b"not a zip")
    assert extract(bad, bad.name)["status"] == "failed"
    entity = tmp_path / "entity.odt"
    with zipfile.ZipFile(entity, "w") as archive:
        archive.writestr("content.xml", '<!DOCTYPE a [<!ENTITY b "boom">]><a>&b;</a>')
    assert extract(entity, entity.name)["status"] == "failed"
    page = tmp_path / "page.html"
    page.write_text("<p>Ergebnis</p><script>secret_search_marker</script>")
    assert extract(page, page.name)["text"] == "Ergebnis"


def _record(root, name, content, *, record_id="a" * 12, **fields):
    blobs = root / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(content).hexdigest()
    (blobs / digest).write_bytes(content)
    return dict(
        id=record_id,
        filename=name,
        sha256=digest,
        size=len(content),
        status="stored",
        format="document",
        origin_path="Original/" + name,
        logical_path="Inbox/" + name,
        thread_id="t" * 12,
        thread_title="Projekt Brücke",
        node_id="n" * 12,
        project_id="p" * 12,
        assignment="matched",
        updated_at="2026-10-26T10:00:00Z",
        **fields,
    )


def test_fts_finds_content_beyond_old_excerpt_and_spelling_variants(tmp_path):
    root = tmp_path / "library-files"
    record = _record(
        root,
        "Übersicht.md",
        ("x " * 20000 + "Brückenstrategie Jahresabschluss").encode(),
    )
    index = LibraryIndex(root)
    status = index.rebuild([record], root / "blobs")
    assert status["status"] == "ready"
    assert status["mode"] in {"fts5_trigram", "fts5_tokens", "bounded_scan"}
    assert LibraryIndex(root).search("strategie")[0]["record_id"] == record["id"]
    for term in [
        "brueckenstrategie",
        "brückenstrategie",
        "bruckenstrategie",
        "uebersicht",
        "ubersicht",
    ]:
        assert index.search(term)[0]["node_id"] == "n" * 12
    hit = index.search("Jahresabschluss")[0]
    assert hit["open_path"].endswith(record["id"])
    assert hit["graph_path"].endswith("n" * 12)
    assert len(hit["snippet"]) <= 240


def test_filters_and_literal_query_semantics(tmp_path):
    root = tmp_path / "library-files"
    record = _record(root, "Plan.md", b"Alpha beta gamma")
    index = LibraryIndex(root)
    index.rebuild([record], root / "blobs")
    assert index.search(
        "beta",
        kind="md",
        project_id="p" * 12,
        date_from="2026-10-25",
        date_to="2026-10-27",
        assignment="matched",
    )
    assert not index.search("beta", project_id="other")
    assert not index.search("beta", kind="pdf")
    assert not index.search("beta", date_from="2027-01-01")
    assert index.search("beta", thread_id="t" * 12)
    assert not index.search('" OR *')
    with pytest.raises(LibrarySearchError):
        index.search("beta", date_from="not-a-date")
    with pytest.raises(LibrarySearchError):
        index.search("beta", limit=100000)


def test_corrupt_file_does_not_block_remaining_results(tmp_path):
    root = tmp_path / "library-files"
    good = _record(root, "good.md", b"find_the_good_result")
    bad = _record(root, "broken.docx", b"broken", record_id="b" * 12)
    index = LibraryIndex(root)
    state = index.rebuild([good, bad], root / "blobs")
    assert state["status"] == "partial"
    assert state["failed"] == 1
    assert index.search("good_result")[0]["id"] == good["id"]
    assert index.search("broken")[0]["extraction_status"] == "failed"


def test_state_generation_hides_stale_deleted_files_then_restore(tmp_path):
    root = tmp_path / "library-files"
    record = _record(root, "restorable.md", b"restore_search_marker")
    index = LibraryIndex(root)
    index.rebuild([record], root / "blobs")
    (tmp_path / "library-file-state.json").write_text(json.dumps({"generation": 1}))
    assert index.status()["status"] == "stale"
    with pytest.raises(LibrarySearchError, match="index_stale"):
        index.search("restore_search_marker")
    record["trashed"] = True
    index.rebuild([record], root / "blobs")
    assert not index.search("restore_search_marker")
    assert index.search("restore_search_marker", include_trashed=True)
    record["trashed"] = False
    record["filename"] = "renamed.md"
    record["logical_path"] = "NewFolder/renamed.md"
    index.rebuild([record], root / "blobs")
    assert index.search("NewFolder")[0]["filename"] == "renamed.md"
    assert (
        index.search("restorable.md")[0]["filename"] == "renamed.md"
    )  # original provenance remains searchable


@pytest.mark.parametrize("backend", [JsonStore, SQLiteStore])
def test_unified_thread_and_graph_projection_keeps_canonical_ids(tmp_path, backend):
    store = backend(tmp_path / "desk")
    service = ThreadService(store=store)
    thread = service.create("Sichtbares Projekt")
    service.set_note("Arbeitsgedächtnis Markergruppe", thread.id)
    node = KnowledgeNode(
        id="f" * 12,
        kind="idea",
        title="Graphentwurf",
        details="Markergruppe",
        metadata={"thread_id": thread.id},
    )
    store.save_node(node)
    index = LibraryIndex(store.workspace_path / "library-files")
    index.rebuild([], index.root / "blobs", store=store)
    hits = index.search("Markergruppe", entity_type="all")
    assert {item["entity_type"] for item in hits} == {"thread", "node"}
    assert (
        next(item for item in hits if item["entity_type"] == "node")["node_id"]
        == node.id
    )
    assert (
        next(item for item in hits if item["entity_type"] == "thread")["thread_id"]
        == thread.id
    )
    assert not index.search("Markergruppe")  # legacy file commands remain file-only
    service.set_note("Neuer Arbeitsstand", thread.id)
    index.sync_workspace(store)
    assert not index.search("Arbeitsgedächtnis", entity_type="all")
    if isinstance(store, SQLiteStore):
        store.connection.close()


def test_unchanged_content_is_not_parsed_again_on_metadata_update(
    tmp_path, monkeypatch
):
    root = tmp_path / "library-files"
    record = _record(root, "once.md", b"cache_marker")
    index = LibraryIndex(root)
    index.rebuild([record], root / "blobs")

    def forbidden(*args, **kwargs):
        raise AssertionError("unchanged blob parsed twice")

    monkeypatch.setattr(
        "threaddesk.services.library_search.projections.extract", forbidden
    )
    record["logical_path"] = "Moved/once.md"
    index.rebuild([record], root / "blobs")
    assert index.search("Moved")[0]["logical_path"] == "Moved/once.md"


def test_large_text_is_explicitly_limited_without_blocking_metadata(tmp_path):
    file = tmp_path / "large.txt"
    file.write_text("a" * (1024 * 1024 + 10))
    outcome = extract(file, file.name)
    assert outcome["status"] == "limited"
    assert outcome["truncated"]
    assert len(outcome["text"]) == 1024 * 1024


def test_parser_rejects_symlink_without_reading_target(tmp_path):
    target = tmp_path / "outside.txt"
    target.write_text("outside_marker")
    link = tmp_path / "inside.txt"
    link.symlink_to(target)
    outcome = extract(link, link.name)
    assert outcome["status"] == "failed"
    assert outcome["text"] == ""


def test_real_pdf_worker_extracts_bounded_text_and_reports_no_text(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 10 100 Td (PDF search marker) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    pdf = tmp_path / "example.pdf"
    with pdf.open("wb") as stream:
        writer.write(stream)
    outcome = extract(pdf, pdf.name)
    assert outcome["status"] == "indexed", outcome
    assert "PDF search marker" in outcome["text"]
    blank = tmp_path / "blank.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with blank.open("wb") as stream:
        writer.write(stream)
    assert extract(blank, blank.name)["error"] == "no_extractable_text"


def test_pdf_timeout_is_per_file_and_explicit(tmp_path, monkeypatch):
    import subprocess

    pdf = tmp_path / "slow.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("bounded-pdf-worker", 5)

    monkeypatch.setattr(
        "threaddesk.services.file_formats.extraction.subprocess.run", timeout
    )
    outcome = extract(pdf, pdf.name)
    assert outcome["status"] == "limited"
    assert outcome["error"] == "time_limit"
    assert outcome["truncated"]


def test_search_database_never_follows_a_link(tmp_path):
    root = tmp_path / "library-files"
    record = _record(root, "local.md", b"local")
    outside = tmp_path / "outside.sqlite3"
    outside.write_bytes(b"unchanged")
    (root / "content-search.sqlite3").symlink_to(outside)
    with pytest.raises(OSError):
        LibraryIndex(root).rebuild([record], root / "blobs")
    assert outside.read_bytes() == b"unchanged"


def test_frozen_pdf_uses_its_packaged_worker_frontdoor(tmp_path, monkeypatch):
    import subprocess
    import sys

    pdf = tmp_path / "packaged.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    observed = []

    def completed(argv, **kwargs):
        observed.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps(
                {
                    "text": "packaged marker",
                    "status": "indexed",
                    "error": "",
                    "truncated": False,
                }
            ),
            "",
        )

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        "threaddesk.services.file_formats.extraction.subprocess.run", completed
    )
    assert extract(pdf, pdf.name)["text"] == "packaged marker"
    assert observed == [[sys.executable, "--file-format-pdf-worker", str(pdf)]]
