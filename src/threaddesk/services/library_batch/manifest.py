"""Bounded manifest validation, without reading or discovering source files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from threaddesk.services.library_import import LibraryImportError, MAX_FILES, _safe_relative

IDENTITY = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = {"path", "original_path", "source_ref", "source_version", "sha256", "size",
           "thread_id", "node_id", "historical_identity"}


def operation_id(value):
    if not isinstance(value, str) or not IDENTITY.fullmatch(value):
        raise LibraryImportError("invalid_operation_id")
    return value


def validate(manifest):
    if (not isinstance(manifest, dict) or set(manifest) - {"files", "expected_count", "protected_exclusions"}
            or not isinstance(manifest.get("files"), list) or len(manifest["files"]) > MAX_FILES):
        raise LibraryImportError("invalid_manifest")
    try:
        encoded_size = len(json.dumps(manifest, ensure_ascii=False).encode())
    except (TypeError, ValueError, UnicodeError) as exc:
        raise LibraryImportError("invalid_manifest") from exc
    if encoded_size > 4 * 1024 * 1024:
        raise LibraryImportError("manifest_too_large")
    expected = manifest.get("expected_count", len(manifest["files"]))
    if type(expected) is not int or not len(manifest["files"]) <= expected <= MAX_FILES:
        raise LibraryImportError("invalid_expected_count")
    protected = manifest.get("protected_exclusions", [])
    if not isinstance(protected, list) or len(protected) > MAX_FILES:
        raise LibraryImportError("invalid_exclusions")
    exclusions = []
    for entry in protected:
        ref = entry.get("source_ref") if isinstance(entry, dict) else entry
        if not isinstance(ref, str) or not 1 <= len(ref) <= 256:
            raise LibraryImportError("invalid_exclusions")
        exclusions.append(ref)
    rows, seen = [], set()
    for entry in manifest["files"]:
        if not isinstance(entry, dict) or set(entry) - _FIELDS:
            raise LibraryImportError("invalid_manifest_entry")
        row = dict(entry)
        for key in ("path", "original_path", "source_ref"):
            value = row.get(key)
            if (not isinstance(value, str) or not value or len(value) > 4096
                    or any(ord(c) < 32 for c in value)):
                raise LibraryImportError("invalid_manifest_entry")
        if not Path(row["path"]).is_absolute() or len(row["source_ref"]) > 256:
            raise LibraryImportError("invalid_manifest_entry")
        row["relative_path"] = _safe_relative(row["original_path"].lstrip("/"))
        for key in ("thread_id", "node_id"):
            if row.get(key) is not None and (not isinstance(row[key], str) or not IDENTITY.fullmatch(row[key])):
                raise LibraryImportError("invalid_assignment")
        for key in ("source_version", "historical_identity"):
            if row.get(key) is not None and (not isinstance(row[key], str) or len(row[key]) > 256):
                raise LibraryImportError("invalid_manifest_entry")
        if row.get("sha256") is not None and (not isinstance(row["sha256"], str) or not DIGEST.fullmatch(row["sha256"])):
            raise LibraryImportError("invalid_checksum")
        if row.get("size") is not None and (type(row["size"]) is not int or row["size"] < 0):
            raise LibraryImportError("invalid_size")
        if row.get("source_version") == "":
            row["source_version"] = None
        key = (row["source_ref"], row.get("source_version") or "")
        if key in seen:
            raise LibraryImportError("duplicate_source_ref")
        seen.add(key)
        rows.append(row)
    normalized = {"files": rows, "expected_count": expected, "protected_exclusions": sorted(set(exclusions))}
    encoded = json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return normalized, hashlib.sha256(encoded.encode()).hexdigest()


def source_key(row):
    text = json.dumps([row["source_ref"], row.get("source_version") or ""], separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()
