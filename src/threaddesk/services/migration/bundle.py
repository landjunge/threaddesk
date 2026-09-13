"""Read and validate an untrusted local ThreadDesk Notion bundle.

The validator is intentionally file-only. It has no Notion dependency, does
not follow source URLs and never opens a network connection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
from types import MappingProxyType
from typing import Any, Iterator, Mapping, NoReturn
import unicodedata
import zipfile

from threaddesk.core.errors import SecretRejected
from threaddesk.core.secrets import reject_secrets


BUNDLE_FORMAT = "threaddesk-notion-bundle-v1"
SCHEMA_VERSION = 1
REQUIRED_FILES = frozenset(
    {"objects.ndjson", "relations.ndjson", "exclusions.json", "report.md"}
)
COUNT_KEYS = frozenset(
    {"objects", "relations", "content", "attachments", "exclusions"}
)
BLOCKED_SUFFIXES = frozenset(
    {
        ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar",
        ".exe", ".dll", ".com", ".bat", ".cmd", ".ps1", ".sh", ".app",
        ".dmg", ".pkg", ".msi", ".jar", ".py", ".pyc", ".js", ".html",
        ".htm", ".svgz",
    }
)
CONTENT_SUFFIXES = frozenset({".md", ".txt"})
TEXT_ATTACHMENT_SUFFIXES = frozenset({".txt", ".md", ".csv", ".json"})
ALLOWED_ATTACHMENT_SUFFIXES = frozenset(
    {
        ".txt", ".md", ".csv", ".json", ".pdf", ".png", ".jpg", ".jpeg",
        ".gif", ".webp", ".svg", ".docx", ".xlsx", ".pptx", ".odt",
        ".ods", ".odp", ".mp3", ".m4a", ".wav", ".ogg", ".mp4", ".mov",
    }
)
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


class BundleValidationError(ValueError):
    """Safe validation failure that never includes imported content."""

    def __init__(self, code: str, path: str = "") -> None:
        self.code = code
        self.path = path
        suffix = f": {path}" if path else ""
        super().__init__(f"{code}{suffix}")


@dataclass(frozen=True)
class BundleLimits:
    max_files: int = 10_000
    max_file_bytes: int = 100 * 1024 * 1024
    max_total_uncompressed: int = 1024 * 1024 * 1024
    max_compression_ratio: float = 100.0
    max_ndjson_line_bytes: int = 2 * 1024 * 1024

    def __post_init__(self) -> None:
        values = (
            self.max_files,
            self.max_file_bytes,
            self.max_total_uncompressed,
            self.max_compression_ratio,
            self.max_ndjson_line_bytes,
        )
        if any(value <= 0 for value in values):
            raise ValueError("Bundle-Limits müssen größer als null sein.")


@dataclass(frozen=True)
class ValidatedBundle:
    path: Path
    bundle_sha256: str
    manifest: Mapping[str, Any]
    counts: Mapping[str, int]
    files: tuple[str, ...]
    max_ndjson_line_bytes: int
    max_file_bytes: int

    def ensure_unchanged(self) -> None:
        if _hash_file(self.path) != self.bundle_sha256:
            _fail("bundle_changed", self.path.name)

    def iter_objects(self) -> Iterator[dict[str, Any]]:
        self.ensure_unchanged()
        yield from _iter_ndjson_path(
            self.path, "objects.ndjson", self.max_ndjson_line_bytes
        )

    def iter_relations(self) -> Iterator[dict[str, Any]]:
        self.ensure_unchanged()
        yield from _iter_ndjson_path(
            self.path, "relations.ndjson", self.max_ndjson_line_bytes
        )

    def iter_exclusions(self) -> Iterator[dict[str, Any]]:
        self.ensure_unchanged()
        with zipfile.ZipFile(self.path, "r") as archive:
            data = _json_object_or_list(
                _read_limited(
                    archive,
                    archive.getinfo("exclusions.json"),
                    self.max_file_bytes,
                ),
                "exclusions.json",
            )
        yield from data

    def read_text(self, name: str) -> str:
        if name not in self.files or not name.startswith("content/"):
            _fail("content_path", name)
        try:
            with zipfile.ZipFile(self.path, "r") as archive:
                info = archive.getinfo(name)
                data = _read_limited(archive, info, self.max_file_bytes)
        except (KeyError, OSError, zipfile.BadZipFile):
            _fail("bundle_changed", name)
        expected = self.manifest["files"][name]
        if (
            len(data) != expected["size"]
            or hashlib.sha256(data).hexdigest() != expected["sha256"]
        ):
            _fail("bundle_changed", name)
        return _decode_utf8(data, name)


def _fail(code: str, path: str = "") -> NoReturn:
    raise BundleValidationError(code, path)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    with archive.open(info, "r") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _aware_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.utcoffset() is not None


def _safe_path(name: str) -> bool:
    if (
        not name
        or "\\" in name
        or "\x00" in name
        or name.startswith("/")
        or unicodedata.normalize("NFC", name) != name
    ):
        return False
    raw_parts = name.rstrip("/").split("/")
    if any(
        part in {"", ".", ".."}
        or part.endswith((" ", "."))
        or ":" in part
        or any(ord(character) < 32 for character in part)
        for part in raw_parts
    ):
        return False
    path = PurePosixPath(name)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        return False
    return True


def _allowed_location_and_type(name: str) -> bool:
    if name in REQUIRED_FILES or name == "manifest.json":
        return True
    path = PurePosixPath(name)
    if len(path.parts) < 2:
        return False
    suffix = path.suffix.lower()
    if suffix in BLOCKED_SUFFIXES:
        return False
    if path.parts[0] == "content":
        return suffix in CONTENT_SUFFIXES
    if path.parts[0] == "attachments":
        return suffix in ALLOWED_ATTACHMENT_SUFFIXES
    return False


def _read_limited(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int
) -> bytes:
    if info.file_size > limit:
        _fail("file_size", info.filename)
    with archive.open(info, "r") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        _fail("file_size", info.filename)
    return data


def _decode_utf8(data: bytes, path: str) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        _fail("utf8", path)


def _scan_secrets(text: str, path: str) -> None:
    try:
        reject_secrets(text)
        # JSON commonly quotes property names. Removing quotes lets the existing
        # conservative scanner catch {"token": "..."} without echoing it.
        reject_secrets(text.replace('"', "").replace("'", ""))
    except SecretRejected:
        _fail("secret", path)


def _json_object(data: bytes, path: str) -> dict[str, Any]:
    text = _decode_utf8(data, path)
    _scan_secrets(text, path)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        _fail("json", path)
    if not isinstance(value, dict):
        _fail("json_object", path)
    return value


def _iter_ndjson_archive(
    archive: zipfile.ZipFile, name: str, line_limit: int
) -> Iterator[dict[str, Any]]:
    with archive.open(name, "r") as handle:
        line_number = 0
        while True:
            raw = handle.readline(line_limit + 1)
            if not raw:
                break
            line_number += 1
            if len(raw) > line_limit:
                _fail("line_size", f"{name}:{line_number}")
            if not raw.strip():
                continue
            text = _decode_utf8(raw, f"{name}:{line_number}")
            _scan_secrets(text, f"{name}:{line_number}")
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                _fail("ndjson", f"{name}:{line_number}")
            if not isinstance(value, dict):
                _fail("ndjson_object", f"{name}:{line_number}")
            yield value


def _iter_ndjson_path(
    path: Path, name: str, line_limit: int
) -> Iterator[dict[str, Any]]:
    with zipfile.ZipFile(path, "r") as archive:
        yield from _iter_ndjson_archive(archive, name, line_limit)


def _require_string(value: Any, code: str, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(code, path)
    return value


def _validate_manifest(manifest: dict[str, Any]) -> None:
    required = {
        "format", "schema_version", "export_id", "created_at",
        "source_workspace_id", "roots", "counts", "files",
    }
    if not required.issubset(manifest):
        _fail("manifest_fields", "manifest.json")
    if manifest.get("format") != BUNDLE_FORMAT:
        _fail("manifest_format", "manifest.json")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        _fail("manifest_schema", "manifest.json")
    for field in ("export_id", "source_workspace_id"):
        _require_string(manifest.get(field), "manifest_field", field)
    if not _aware_timestamp(manifest.get("created_at")):
        _fail("manifest_timestamp", "created_at")
    roots = manifest.get("roots")
    if not isinstance(roots, list) or not roots or not all(
        isinstance(root, str) and root.strip() for root in roots
    ):
        _fail("manifest_roots", "roots")
    counts = manifest.get("counts")
    if not isinstance(counts, dict) or set(counts) != COUNT_KEYS or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in counts.values()
    ):
        _fail("manifest_counts", "counts")
    files = manifest.get("files")
    if not isinstance(files, dict):
        _fail("manifest_files", "files")
    for name, record in files.items():
        if not isinstance(name, str) or not isinstance(record, dict):
            _fail("manifest_file", "files")
        if not _safe_path(name):
            _fail("path", name)
        digest = record.get("sha256")
        size = record.get("size")
        if not isinstance(digest, str) or not HEX_SHA256.fullmatch(digest):
            _fail("manifest_checksum", name)
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            _fail("manifest_size", name)


def _validate_object(
    item: dict[str, Any], source_ids: set[str], content_hashes: Mapping[str, str]
) -> str | None:
    required = {
        "source_id", "title", "source_path", "source_url", "source_type",
        "parent_id", "last_edited_at", "properties", "content_path",
        "content_sha256", "archived", "suggested_kind", "mapping_reason",
    }
    if not required.issubset(item):
        _fail("object_fields", "objects.ndjson")
    source_id = _require_string(item.get("source_id"), "source_id", "objects.ndjson")
    if source_id in source_ids:
        _fail("source_id_duplicate", source_id)
    source_ids.add(source_id)
    for field in ("title", "source_path", "source_url", "source_type", "suggested_kind", "mapping_reason"):
        _require_string(item.get(field), "object_field", field)
    if item.get("parent_id") is not None and not isinstance(item.get("parent_id"), str):
        _fail("object_parent", source_id)
    if not _aware_timestamp(item.get("last_edited_at")):
        _fail("object_timestamp", source_id)
    if not isinstance(item.get("properties"), dict):
        _fail("object_properties", source_id)
    if not isinstance(item.get("archived"), bool):
        _fail("object_archived", source_id)
    content_path = item.get("content_path")
    content_sha = item.get("content_sha256")
    if content_path is None and content_sha is None:
        return None
    if not isinstance(content_path, str) or not content_path.startswith("content/"):
        _fail("content_path", source_id)
    if content_path not in content_hashes:
        _fail("content_path", content_path)
    if not isinstance(content_sha, str) or content_sha != content_hashes[content_path]:
        _fail("content_checksum", content_path)
    return content_path


def validate_bundle(
    path: Path | str, *, limits: BundleLimits | None = None
) -> ValidatedBundle:
    """Validate an untrusted local bundle without changing ThreadDesk state."""

    bundle_path = Path(path)
    limits = limits or BundleLimits()
    if bundle_path.suffix.lower() != ".tdbundle" or not bundle_path.is_file():
        _fail("bundle_file", bundle_path.name)
    if not zipfile.is_zipfile(bundle_path):
        _fail("bundle_zip", bundle_path.name)

    with zipfile.ZipFile(bundle_path, "r") as archive:
        infos = archive.infolist()
        names: set[str] = set()
        canonical_names: set[str] = set()
        file_infos: dict[str, zipfile.ZipInfo] = {}
        total_size = 0
        for info in infos:
            name = info.filename
            if name in names:
                _fail("duplicate", name)
            names.add(name)
            canonical_name = unicodedata.normalize("NFC", name).casefold()
            if canonical_name in canonical_names:
                _fail("path_collision", name)
            canonical_names.add(canonical_name)
            if not _safe_path(name):
                _fail("path", name)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                _fail("symlink", name)
            if info.flag_bits & 0x1:
                _fail("encrypted", name)
            if info.is_dir():
                if name.rstrip("/") not in {"content", "attachments"}:
                    _fail("path", name)
                continue
            if not _allowed_location_and_type(name):
                _fail("file_type", name)
            file_infos[name] = info
            if len(file_infos) > limits.max_files:
                _fail("file_limit")
            if info.file_size > limits.max_file_bytes:
                _fail("file_size", name)
            total_size += info.file_size
            if total_size > limits.max_total_uncompressed:
                _fail("total_size")
            if info.file_size and info.file_size / max(1, info.compress_size) > limits.max_compression_ratio:
                _fail("compression_ratio", name)

        if "manifest.json" not in file_infos:
            _fail("required_file", "manifest.json")
        manifest = _json_object(
            _read_limited(archive, file_infos["manifest.json"], limits.max_file_bytes),
            "manifest.json",
        )
        _validate_manifest(manifest)

        actual_files = set(file_infos) - {"manifest.json"}
        declared_files = set(manifest["files"])
        missing_required = REQUIRED_FILES - actual_files
        if missing_required:
            _fail("required_file", sorted(missing_required)[0])
        if actual_files != declared_files:
            _fail("file_set")

        member_hashes: dict[str, str] = {}
        for name in sorted(actual_files):
            info = file_infos[name]
            expected = manifest["files"][name]
            if info.file_size != expected["size"]:
                _fail("size", name)
            digest = _hash_member(archive, info)
            member_hashes[name] = digest
            if digest != expected["sha256"]:
                _fail("checksum", name)

        for name in sorted(actual_files):
            suffix = PurePosixPath(name).suffix.lower()
            if (
                name.endswith((".json", ".md", ".txt", ".csv"))
                and (not name.startswith("attachments/") or suffix in TEXT_ATTACHMENT_SUFFIXES)
            ):
                text = _decode_utf8(
                    _read_limited(archive, file_infos[name], limits.max_file_bytes), name
                )
                _scan_secrets(text, name)

        source_ids: set[str] = set()
        referenced_content: set[str] = set()
        object_count = 0
        content_hashes = {
            name: digest for name, digest in member_hashes.items()
            if name.startswith("content/")
        }
        for item in _iter_ndjson_archive(
            archive, "objects.ndjson", limits.max_ndjson_line_bytes
        ):
            object_count += 1
            content_path = _validate_object(item, source_ids, content_hashes)
            if content_path:
                referenced_content.add(content_path)
        if referenced_content != set(content_hashes):
            _fail("content_orphan")

        relation_count = 0
        for item in _iter_ndjson_archive(
            archive, "relations.ndjson", limits.max_ndjson_line_bytes
        ):
            relation_count += 1
            source_id = _require_string(
                item.get("source_id"), "relation_source", "relations.ndjson"
            )
            target_id = _require_string(
                item.get("target_id"), "relation_target", "relations.ndjson"
            )
            _require_string(item.get("kind"), "relation_kind", "relations.ndjson")
            if source_id not in source_ids:
                _fail("relation_source", source_id)
            if target_id not in source_ids:
                _fail("relation_target", target_id)

        exclusions = _json_object_or_list(
            _read_limited(archive, file_infos["exclusions.json"], limits.max_file_bytes),
            "exclusions.json",
        )
        if not isinstance(exclusions, list):
            _fail("exclusions", "exclusions.json")
        for item in exclusions:
            if not isinstance(item, dict):
                _fail("exclusions", "exclusions.json")
            for field in ("source_id", "title", "reason"):
                _require_string(item.get(field), "exclusion_field", field)
            if item["source_id"] in source_ids:
                _fail("exclusion_overlap", item["source_id"])

        actual_counts = {
            "objects": object_count,
            "relations": relation_count,
            "content": len(content_hashes),
            "attachments": sum(name.startswith("attachments/") for name in actual_files),
            "exclusions": len(exclusions),
        }
        if actual_counts != manifest["counts"]:
            _fail("count")

    return ValidatedBundle(
        path=bundle_path,
        bundle_sha256=_hash_file(bundle_path),
        manifest=_freeze(manifest),
        counts=MappingProxyType(actual_counts),
        files=tuple(sorted(actual_files)),
        max_ndjson_line_bytes=limits.max_ndjson_line_bytes,
        max_file_bytes=limits.max_file_bytes,
    )


def _json_object_or_list(data: bytes, path: str) -> Any:
    text = _decode_utf8(data, path)
    _scan_secrets(text, path)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        _fail("json", path)
