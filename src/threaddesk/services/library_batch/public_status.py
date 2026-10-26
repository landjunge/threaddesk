"""Bounded, paginated job views for bridge transports; source manifests stay private."""
from __future__ import annotations

from collections import Counter
import hashlib
import json

from threaddesk.services.library_import import LibraryImportError

MAX_PAGE_FILES = 50
MAX_JSON_BYTES = 30 * 1024
_FILE_TEXT = {
    "source_key": 64, "source_ref": 160, "original_path": 256, "status": 32,
    "error": 192, "record_id": 100, "sha256": 64, "thread_id": 100,
    "node_id": 100, "assignment": 32, "historical_identity": 96,
    "predecessor_record_id": 100, "actual_sha256": 64,
}


def _text(value, limit):
    raw = str(value).encode("utf-8", errors="replace")
    if len(raw) <= limit:
        return raw.decode("utf-8"), False
    return raw[:limit - 3].decode("utf-8", errors="ignore") + "…", True


def _number(value):
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


def _strings(source, bounds):
    result, truncated = {}, []
    for key, limit in bounds.items():
        if key not in source or source[key] is None:
            continue
        result[key], cut = _text(source[key], limit)
        if cut:
            truncated.append(key)
    if truncated:
        result["truncated_fields"] = truncated
    return result


def projection_status(value):
    if not isinstance(value, dict):
        return {}
    result = _strings(value, {"status": 32, "mode": 48, "generation": 80, "error": 192})
    for key in ("created", "updated", "removed", "skipped", "documents", "failed",
                "state_generation", "entity_documents"):
        number = _number(value.get(key))
        if number is not None:
            result[key] = number
    for key in ("errors", "projection_errors"):
        errors = value.get(key)
        if isinstance(errors, list):
            result[key + "_count"] = len(errors)
            result[key + "_omitted"] = max(0, len(errors) - 3)
            samples = []
            for error in errors[:3]:
                if isinstance(error, dict):
                    samples.append(_strings(error, {"id": 100, "record_id": 100, "error": 192,
                                                    "status": 32, "path": 160}))
                else:
                    text, cut = _text(error, 192)
                    samples.append({"error": text, "truncated_fields": ["error"] if cut else []})
            result[key] = samples
    return result


def _file(row, position):
    if not isinstance(row, dict):
        return {"file_index": position, "status": "invalid", "error": "invalid_job_file"}
    result = {"file_index": position, **_strings(row, _FILE_TEXT)}
    for key in ("size", "actual_size"):
        number = _number(row.get(key))
        if number is not None:
            result[key] = number
    # file_index remains an exact locator even if a display identifier is long.
    if "source_ref" in result.get("truncated_fields", []):
        result["source_ref_sha256"] = hashlib.sha256(str(row["source_ref"]).encode()).hexdigest()
    return result


def _size(value):
    # Escaped, indented JSON is larger than the ordinary compact UTF-8 response.
    return len(json.dumps(value, ensure_ascii=True, indent=2).encode("utf-8"))


def public_status(job, *, offset=0, limit=20):
    """Return one bounded page without changing the canonical job or manifest.

    A byte-limited page may contain fewer than ``limit`` rows; always follow its
    actual ``next_offset`` rather than adding the requested limit yourself.
    """
    if (not isinstance(job, dict) or type(offset) is not int or offset < 0
            or type(limit) is not int or not 1 <= limit <= MAX_PAGE_FILES):
        raise LibraryImportError("invalid_batch_status_page")
    files = job.get("files", [])
    if not isinstance(files, list):
        raise LibraryImportError("invalid_batch_status_job")
    result = _strings(job, {"operation_id": 100, "manifest_hash": 64, "state": 32,
                            "created_at": 80, "updated_at": 80, "error": 192})
    observed = Counter(str(row.get("status", "unknown"))[:32]
                       if isinstance(row, dict) else "invalid" for row in files)
    counts = job.get("counts") if isinstance(job.get("counts"), dict) else dict(observed)
    result["counts"] = {str(key)[:48]: value for key, value in list(counts.items())[:64]
                        if _number(value) is not None}
    if len(counts) > 64:
        result["counts_omitted"] = len(counts) - 64
    manifest = job.get("manifest") if isinstance(job.get("manifest"), dict) else {}
    expected = _number(manifest.get("expected_count"))
    if expected is None:
        manifest_files = manifest.get("files")
        expected = len(manifest_files) if isinstance(manifest_files, list) else len(files)
    processed = sum(amount for status, amount in observed.items() if status not in {"processing", "pending"})
    result.update(complete=job.get("complete") is True, total=len(files), expected_count=expected,
                  processed=processed, remaining=max(0, expected - processed), offset=offset,
                  limit=limit, returned=0, next_offset=None, page_limited_by_bytes=False,
                  projection=projection_status(job.get("projection")), index=projection_status(job.get("index")), files=[])
    version = _number(job.get("version"))
    if version is not None:
        result["version"] = version
    if _size(result) > MAX_JSON_BYTES - 4096:
        raise LibraryImportError("batch_status_summary_limit")
    stop = min(len(files), offset + limit)
    for position in range(offset, stop):
        result["files"].append(_file(files[position], position))
        result["returned"] = len(result["files"])
        result["next_offset"] = position + 1 if position + 1 < len(files) else None
        if _size(result) > MAX_JSON_BYTES:
            result["files"].pop()
            result["returned"] = len(result["files"])
            result["next_offset"] = position
            result["page_limited_by_bytes"] = True
            break
    if offset >= len(files):
        result["next_offset"] = None
    return result
