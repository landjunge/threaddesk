"""Canonical JSON knowledge export and selection boundaries."""

from __future__ import annotations

import json
import hashlib
import csv
import io
from pathlib import Path
from zipfile import ZipFile

import pytest

from threaddesk.core.models import GraphEvent, KnowledgeNode, Relation
from threaddesk.core.provenance import SourceRecord
from threaddesk.services.knowledge_export import (
    KnowledgeExportError,
    KnowledgeExportService,
)
from threaddesk.storage.sqlite_store import SQLiteStore


def populated_store(tmp_path: Path) -> SQLiteStore:
    store = SQLiteStore(tmp_path / "workspace")
    for node in (
        KnowledgeNode("project", "project", "Project", visibility="shared"),
        KnowledgeNode("task", "task", "Task", visibility="public"),
        KnowledgeNode("private", "document", "Private", visibility="private"),
    ):
        store.save_node(node)
    for relation in (
        Relation("included", "project", "task", "contains"),
        Relation("private-link", "project", "private", "references"),
    ):
        store.save_relation(relation)
    store.append_graph_event(
        GraphEvent("event-project", "node.created", "project", "project", 1, "2026-09-15T10:00:00+00:00")
    )
    store.append_graph_event(
        GraphEvent("event-private", "node.created", "private", "document", 1, "2026-09-15T10:01:00+00:00")
    )
    store.save_source_record(
        SourceRecord("notion", "source-project", "project", "source-hash", "target-hash", "bundle", "2026-09-15T10:00:00+00:00", "rule")
    )
    store.save_artifact({"sha256": "a" * 64, "size": 4, "relative_path": "artifacts/a"})
    store.replace_node_artifact({"node_id": "project", "sha256": "a" * 64, "role": "content"})
    return store


def test_selection_exports_only_selected_nodes_and_internal_relations(tmp_path: Path) -> None:
    payload = KnowledgeExportService(populated_store(tmp_path)).build(
        node_ids=["project", "task"],
        generated_at="2026-09-15T11:00:00+00:00",
    )

    assert [node["id"] for node in payload["nodes"]] == ["project", "task"]
    assert [relation["id"] for relation in payload["relations"]] == ["included"]
    assert [event["id"] for event in payload["events"]] == ["event-project"]
    assert [record["source_id"] for record in payload["source_records"]] == ["source-project"]
    assert len(payload["artifacts"]) == 1
    assert len(payload["node_artifacts"]) == 1


def test_private_nodes_are_excluded_until_explicitly_requested(tmp_path: Path) -> None:
    service = KnowledgeExportService(populated_store(tmp_path))

    safe = service.build(node_ids=["private"], generated_at="2026-09-15T11:00:00+00:00")
    explicit = service.build(
        node_ids=["private"],
        include_private=True,
        generated_at="2026-09-15T11:00:00+00:00",
    )

    assert safe["nodes"] == []
    assert safe["selection"]["excluded_private"] == ["private"]
    assert [node["id"] for node in explicit["nodes"]] == ["private"]


def test_json_round_trip_is_lossless_and_checksum_protected(tmp_path: Path) -> None:
    service = KnowledgeExportService(populated_store(tmp_path))
    payload = service.build(
        include_private=True,
        generated_at="2026-09-15T11:00:00+00:00",
    )

    encoded = service.encode(payload)

    assert service.decode(encoded) == payload
    tampered = json.loads(encoded)
    tampered["nodes"][0]["title"] = "Changed after export"
    with pytest.raises(KnowledgeExportError, match="export_checksum"):
        service.decode(json.dumps(tampered))


def test_missing_selection_and_broken_relation_are_rejected(tmp_path: Path) -> None:
    service = KnowledgeExportService(populated_store(tmp_path))
    with pytest.raises(KnowledgeExportError, match="selection_missing"):
        service.build(node_ids=["missing"])

    payload = service.build(include_private=True)
    body = dict(payload)
    body["relations"] = [dict(payload["relations"][0], target_id="missing")]
    body["counts"] = dict(payload["counts"], relations=1)
    body.pop("sha256")
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    broken = {**body, "sha256": hashlib.sha256(encoded.encode()).hexdigest()}
    with pytest.raises(KnowledgeExportError, match="export_relation_target"):
        service.verify(broken)


def test_cli_can_emit_verified_canonical_export(monkeypatch, tmp_path: Path, capsys) -> None:
    from threaddesk.ui import cli

    store = populated_store(tmp_path)
    monkeypatch.setattr(cli, "_svc", lambda: type("Service", (), {"store": store})())

    assert cli.main(["graph", "--export", "--ids", "project", "task"]) == 0

    decoded = KnowledgeExportService.decode(capsys.readouterr().out)
    assert decoded["selection"]["included"] == ["project", "task"]
    assert [relation["id"] for relation in decoded["relations"]] == ["included"]


def test_markdown_export_is_readable_traceable_and_private_by_default(tmp_path: Path) -> None:
    service = KnowledgeExportService(populated_store(tmp_path))
    payload = service.build(generated_at="2026-09-15T11:00:00+00:00")

    rendered = service.encode_markdown(payload)

    assert rendered.startswith("# ThreadDesk-Wissensexport\n")
    assert "## Project" in rendered
    assert "## Task" in rendered
    assert "`project` | `contains` | `task`" in rendered
    assert "`notion` | `source-project` | `project` | `bundle`" in rendered
    assert "Private nodes excluded: `private`" not in rendered
    assert "Private Knoten ausgeschlossen: `private`" in rendered
    assert "## Private" not in rendered


def test_cli_can_emit_english_markdown_selection(monkeypatch, tmp_path: Path, capsys) -> None:
    from threaddesk.ui import cli

    store = populated_store(tmp_path)
    monkeypatch.setattr(cli, "_svc", lambda: type("Service", (), {"store": store})())

    assert cli.main([
        "--lang", "en", "graph", "--export", "--format", "markdown",
        "--ids", "project", "task",
    ]) == 0

    rendered = capsys.readouterr().out
    assert rendered.startswith("# ThreadDesk knowledge export\n")
    assert "## Project" in rendered
    assert "## Task" in rendered
    assert "## Private" not in rendered


def test_csv_is_normalized_safe_and_private_by_default(tmp_path: Path) -> None:
    store = populated_store(tmp_path)
    store.save_node(KnowledgeNode("formula", "task", "=2+2", visibility="public"))
    payload = KnowledgeExportService(store).build(generated_at="2026-09-15T11:00:00+00:00")

    rows = list(csv.DictReader(io.StringIO(KnowledgeExportService.encode_csv(payload))))

    assert {row["record_type"] for row in rows} == {"node", "relation", "source"}
    assert next(row for row in rows if row["id"] == "formula")["title"] == "'=2+2"
    assert not any(row["id"] == "private" for row in rows)
    assert next(row for row in rows if row["id"] == "included")["target_id"] == "task"


def test_xlsx_has_separate_valid_sheets_and_cli_writes_file(monkeypatch, tmp_path: Path) -> None:
    from threaddesk.ui import cli

    store = populated_store(tmp_path)
    monkeypatch.setattr(cli, "_svc", lambda: type("Service", (), {"store": store})())
    target = tmp_path / "knowledge.xlsx"

    assert cli.main(["graph", "--export", "--format", "xlsx", "--output", str(target)]) == 0

    with ZipFile(target) as workbook:
        names = set(workbook.namelist())
        assert "xl/worksheets/sheet1.xml" in names
        assert "xl/worksheets/sheet2.xml" in names
        assert "xl/worksheets/sheet3.xml" in names
        assert b"Private" not in workbook.read("xl/worksheets/sheet1.xml")
        assert b"Project" in workbook.read("xl/worksheets/sheet1.xml")


def test_xlsx_requires_output_path_in_both_languages(monkeypatch, tmp_path: Path, capsys) -> None:
    from threaddesk.ui import cli

    store = populated_store(tmp_path)
    monkeypatch.setattr(cli, "_svc", lambda: type("Service", (), {"store": store})())

    assert cli.main(["graph", "--export", "--format", "xlsx"]) == 2
    assert "--output wissen.xlsx" in capsys.readouterr().err
    assert cli.main(["--lang", "en", "graph", "--export", "--format", "xlsx"]) == 2
    assert "--output knowledge.xlsx" in capsys.readouterr().err
