"""Security and contract tests for ``threaddesk-notion-bundle-v1``."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import socket
import stat
import zipfile

import pytest

from threaddesk.services.migration.bundle import (
    BundleLimits,
    BundleValidationError,
    validate_bundle,
)


def _json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()


def _ndjson_bytes(values: list[dict]) -> bytes:
    return b"".join(_json_bytes(value) for value in values)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def valid_parts() -> tuple[dict, dict[str, bytes]]:
    content = b"# ThreadDesk\n\nBestaetigter Projektstand.\n"
    objects = [
        {
            "source_id": "notion-page-1",
            "title": "ThreadDesk",
            "source_path": "NetzwerkPunkt/ThreadDesk",
            "source_url": "https://www.notion.so/notion-page-1",
            "source_type": "page",
            "parent_id": None,
            "last_edited_at": "2026-09-12T20:00:00+00:00",
            "properties": {"status": "active"},
            "content_path": "content/notion-page-1.md",
            "content_sha256": _sha256(content),
            "archived": False,
            "suggested_kind": "project",
            "mapping_reason": "Aktive Produktseite",
        }
    ]
    relations: list[dict] = []
    exclusions = [{"source_id": "private-1", "title": "Privat", "reason": "private"}]
    files = {
        "objects.ndjson": _ndjson_bytes(objects),
        "relations.ndjson": _ndjson_bytes(relations),
        "content/notion-page-1.md": content,
        "exclusions.json": _json_bytes(exclusions),
        "report.md": b"# Export report\n\nOne project, one exclusion.\n",
    }
    manifest = {
        "format": "threaddesk-notion-bundle-v1",
        "schema_version": 1,
        "export_id": "export-1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_workspace_id": "workspace-redacted",
        "roots": ["root-1"],
        "counts": {
            "objects": 1,
            "relations": 0,
            "content": 1,
            "attachments": 0,
            "exclusions": 1,
        },
        "files": {
            name: {"sha256": _sha256(data), "size": len(data)}
            for name, data in files.items()
        },
    }
    return manifest, files


def write_bundle(
    path: Path,
    *,
    manifest: dict | None = None,
    files: dict[str, bytes] | None = None,
    extra_infos: list[tuple[zipfile.ZipInfo, bytes]] | None = None,
) -> Path:
    default_manifest, default_files = valid_parts()
    manifest = deepcopy(manifest if manifest is not None else default_manifest)
    files = dict(files if files is not None else default_files)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", _json_bytes(manifest))
        for name, data in files.items():
            archive.writestr(name, data)
        for info, data in extra_infos or []:
            archive.writestr(info, data)
    return path


def rebuilt_manifest(files: dict[str, bytes], **updates) -> dict:
    manifest, _ = valid_parts()
    manifest["files"] = {
        name: {"sha256": _sha256(data), "size": len(data)}
        for name, data in files.items()
    }
    manifest.update(updates)
    return manifest


def test_valid_bundle_is_verified_and_remains_streamable(tmp_path: Path) -> None:
    path = write_bundle(tmp_path / "notion.tdbundle")

    checked = validate_bundle(path)

    assert checked.bundle_sha256 == _sha256(path.read_bytes())
    assert checked.manifest["export_id"] == "export-1"
    assert checked.counts == {
        "objects": 1,
        "relations": 0,
        "content": 1,
        "attachments": 0,
        "exclusions": 1,
    }
    assert [item["source_id"] for item in checked.iter_objects()] == ["notion-page-1"]
    assert list(checked.iter_relations()) == []


def test_validation_never_opens_a_network_connection(tmp_path: Path, monkeypatch) -> None:
    path = write_bundle(tmp_path / "offline.tdbundle")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    assert validate_bundle(path).counts["objects"] == 1


@pytest.mark.parametrize("missing", [
    "objects.ndjson", "relations.ndjson", "exclusions.json", "report.md",
])
def test_required_file_must_exist_and_be_listed(tmp_path: Path, missing: str) -> None:
    manifest, files = valid_parts()
    files.pop(missing)
    manifest["files"].pop(missing)

    with pytest.raises(BundleValidationError, match="required_file"):
        validate_bundle(write_bundle(tmp_path / "missing.tdbundle", manifest=manifest, files=files))


def test_unlisted_and_unknown_files_are_rejected(tmp_path: Path) -> None:
    manifest, files = valid_parts()
    files["content/surprise.md"] = b"not in manifest"

    with pytest.raises(BundleValidationError, match="file_set"):
        validate_bundle(write_bundle(tmp_path / "extra.tdbundle", manifest=manifest, files=files))


@pytest.mark.parametrize("field,value", [
    ("format", "other-format"),
    ("schema_version", 2),
    ("created_at", "2026-09-12T20:00:00"),
])
def test_unknown_format_schema_and_naive_timestamp_are_rejected(
    tmp_path: Path, field: str, value,
) -> None:
    manifest, files = valid_parts()
    manifest[field] = value

    with pytest.raises(BundleValidationError, match="manifest"):
        validate_bundle(write_bundle(tmp_path / "version.tdbundle", manifest=manifest, files=files))


def test_checksum_size_and_count_mismatches_are_rejected(tmp_path: Path) -> None:
    manifest, files = valid_parts()
    manifest["files"]["report.md"]["sha256"] = "0" * 64
    with pytest.raises(BundleValidationError, match="checksum"):
        validate_bundle(write_bundle(tmp_path / "hash.tdbundle", manifest=manifest, files=files))

    manifest, files = valid_parts()
    manifest["files"]["report.md"]["size"] += 1
    with pytest.raises(BundleValidationError, match="size"):
        validate_bundle(write_bundle(tmp_path / "size.tdbundle", manifest=manifest, files=files))

    manifest, files = valid_parts()
    manifest["counts"]["objects"] = 2
    with pytest.raises(BundleValidationError, match="count"):
        validate_bundle(write_bundle(tmp_path / "count.tdbundle", manifest=manifest, files=files))


@pytest.mark.parametrize("bad_path", [
    "../outside.md", "/absolute.md", "content/../../outside.md", "content\\evil.md",
    "C:/windows.md", "content/name:stream.md", "content/trailing .md ",
    "content/cafe\u0301.md",
])
def test_unsafe_archive_paths_are_rejected(tmp_path: Path, bad_path: str) -> None:
    manifest, files = valid_parts()
    files[bad_path] = b"unsafe"
    manifest["files"][bad_path] = {"sha256": _sha256(b"unsafe"), "size": 6}

    with pytest.raises(BundleValidationError, match="path"):
        validate_bundle(write_bundle(tmp_path / "path.tdbundle", manifest=manifest, files=files))


def test_symlinks_encrypted_entries_and_duplicate_names_are_rejected(tmp_path: Path) -> None:
    manifest, files = valid_parts()
    link = zipfile.ZipInfo("attachments/link.txt")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    manifest["files"][link.filename] = {"sha256": _sha256(b"target"), "size": 6}
    with pytest.raises(BundleValidationError, match="symlink"):
        validate_bundle(write_bundle(tmp_path / "link.tdbundle", manifest=manifest, files=files, extra_infos=[(link, b"target")]))

    manifest, files = valid_parts()
    duplicate = zipfile.ZipInfo("report.md")
    with pytest.warns(UserWarning):
        duplicate_path = write_bundle(
            tmp_path / "duplicate.tdbundle", manifest=manifest, files=files,
            extra_infos=[(duplicate, files["report.md"])],
        )
    with pytest.raises(BundleValidationError, match="duplicate"):
        validate_bundle(duplicate_path)


def test_case_insensitive_archive_path_collisions_are_rejected(tmp_path: Path) -> None:
    manifest, files = valid_parts()
    files["attachments/File.txt"] = b"first"
    files["attachments/file.txt"] = b"second"
    manifest = rebuilt_manifest(files)
    manifest["counts"]["attachments"] = 2

    with pytest.raises(BundleValidationError, match="path_collision"):
        validate_bundle(write_bundle(tmp_path / "collision.tdbundle", manifest=manifest, files=files))


@pytest.mark.parametrize("name", [
    "attachments/archive.zip", "attachments/run.sh", "attachments/app.exe",
    "content/page.html",
])
def test_nested_archives_and_executable_content_are_rejected(tmp_path: Path, name: str) -> None:
    manifest, files = valid_parts()
    files[name] = b"opaque"
    manifest["files"][name] = {"sha256": _sha256(b"opaque"), "size": 6}

    with pytest.raises(BundleValidationError, match="file_type"):
        validate_bundle(write_bundle(tmp_path / "type.tdbundle", manifest=manifest, files=files))


def test_file_total_line_and_compression_limits_are_enforced(tmp_path: Path) -> None:
    path = write_bundle(tmp_path / "limits.tdbundle")
    with pytest.raises(BundleValidationError, match="file_limit"):
        validate_bundle(path, limits=BundleLimits(max_files=2))
    with pytest.raises(BundleValidationError, match="total_size"):
        validate_bundle(path, limits=BundleLimits(max_total_uncompressed=10))

    manifest, files = valid_parts()
    huge = b"A" * 50_000
    files["report.md"] = huge
    manifest = rebuilt_manifest(files)
    with pytest.raises(BundleValidationError, match="compression_ratio"):
        validate_bundle(
            write_bundle(tmp_path / "ratio.tdbundle", manifest=manifest, files=files),
            limits=BundleLimits(max_compression_ratio=2),
        )

    manifest, files = valid_parts()
    objects = json.loads(files["objects.ndjson"])
    objects["properties"] = {"long": "x" * 2_000}
    files["objects.ndjson"] = _ndjson_bytes([objects])
    manifest = rebuilt_manifest(files)
    with pytest.raises(BundleValidationError, match="line_size"):
        validate_bundle(
            write_bundle(tmp_path / "line.tdbundle", manifest=manifest, files=files),
            limits=BundleLimits(max_ndjson_line_bytes=500),
        )


def test_duplicate_source_ids_and_unresolved_relations_are_rejected(tmp_path: Path) -> None:
    manifest, files = valid_parts()
    item = json.loads(files["objects.ndjson"])
    files["objects.ndjson"] = _ndjson_bytes([item, item])
    manifest = rebuilt_manifest(files)
    manifest["counts"]["objects"] = 2
    with pytest.raises(BundleValidationError, match="source_id"):
        validate_bundle(write_bundle(tmp_path / "duplicate-id.tdbundle", manifest=manifest, files=files))

    manifest, files = valid_parts()
    files["relations.ndjson"] = _ndjson_bytes([
        {"source_id": "notion-page-1", "target_id": "missing", "kind": "related_to"}
    ])
    manifest = rebuilt_manifest(files)
    manifest["counts"]["relations"] = 1
    with pytest.raises(BundleValidationError, match="relation_target"):
        validate_bundle(write_bundle(tmp_path / "relation.tdbundle", manifest=manifest, files=files))


def test_content_reference_and_hash_must_match(tmp_path: Path) -> None:
    manifest, files = valid_parts()
    item = json.loads(files["objects.ndjson"])
    item["content_sha256"] = "0" * 64
    files["objects.ndjson"] = _ndjson_bytes([item])
    manifest = rebuilt_manifest(files)

    with pytest.raises(BundleValidationError, match="content_checksum"):
        validate_bundle(write_bundle(tmp_path / "content.tdbundle", manifest=manifest, files=files))


@pytest.mark.parametrize("secret", [
    "api_key=sk-abcdefghijklmnopqrst",
    "AKIAABCDEFGHIJKLMNOP",
    "-----BEGIN PRIVATE KEY-----",
    "glpat-abcdefghijklmnopqrstuvwxyz",
    "ntn_abcdefghijklmnopqrstuvwxyz",
    "Bearer abcdefghijklmnop",
])
def test_secret_is_blocked_without_echoing_its_value(
    tmp_path: Path, secret: str,
) -> None:
    manifest, files = valid_parts()
    files["content/notion-page-1.md"] = secret.encode()
    item = json.loads(files["objects.ndjson"])
    item["content_sha256"] = _sha256(files["content/notion-page-1.md"])
    files["objects.ndjson"] = _ndjson_bytes([item])
    manifest = rebuilt_manifest(files)

    with pytest.raises(BundleValidationError) as caught:
        validate_bundle(write_bundle(tmp_path / "secret.tdbundle", manifest=manifest, files=files))

    assert "secret" in str(caught.value)
    assert secret not in str(caught.value)


def test_migration_runtime_has_no_notion_or_network_client_dependency() -> None:
    root = Path(__file__).parents[1]
    migration = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (root / "src" / "threaddesk" / "services" / "migration").rglob("*.py")
    )
    project = (root / "pyproject.toml").read_text(encoding="utf-8")

    for forbidden in ("import requests", "import httpx", "import urllib", "notion_client"):
        assert forbidden not in migration
    assert "notion-client" not in project.lower()


def test_published_bundle_schemas_are_valid_json_with_unique_ids() -> None:
    schema_root = Path(__file__).parents[1] / "docs" / "schemas"
    schemas = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(schema_root.glob("notion-*-v1.schema.json"))
    ]

    assert len(schemas) == 4
    assert len({schema["$id"] for schema in schemas}) == 4
    assert all(schema["$schema"].endswith("2020-12/schema") for schema in schemas)


def test_malformed_ndjson_is_reported_without_partial_result(tmp_path: Path) -> None:
    manifest, files = valid_parts()
    files["objects.ndjson"] = b'{"source_id":\n'
    manifest = rebuilt_manifest(files)

    with pytest.raises(BundleValidationError, match="ndjson"):
        validate_bundle(write_bundle(tmp_path / "broken.tdbundle", manifest=manifest, files=files))
