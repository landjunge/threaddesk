"""Bridge-sized pages retain progress and traversability without exposing manifests."""
from __future__ import annotations

import copy
import json

import pytest

from threaddesk.services.library_batch.public_status import MAX_JSON_BYTES, public_status
from threaddesk.services.library_import import LibraryImportError


def job_with_files(count=275):
    return {
        "version": 1, "operation_id": "import-275", "manifest_hash": "a" * 64,
        "state": "partial", "complete": False,
        "created_at": "2026-10-26T08:00:00+00:00", "updated_at": "2026-10-26T08:01:00+00:00",
        "manifest": {"expected_count": count, "files": [{"path": "/private/original-secret.txt"}] * count},
        "counts": {"stored": count - 2, "missing": 1, "conflict": 1, "unavailable": 0},
        "projection": {"status": "ready", "created": count, "updated": 0},
        "index": {"status": "partial", "documents": count - 2, "failed": 2,
                  "error": "two_documents_failed", "errors": [{"id": "f" * 12, "error": "parse_failed"}] * 100},
        "files": [{"source_key": f"{i:064x}", "source_ref": "file-ref-" + str(i),
                   "original_path": f"Originale/Datei-{i}.txt", "status": "stored",
                   "record_id": f"{i:012x}", "sha256": "b" * 64, "size": 123,
                   "thread_id": "c" * 12} for i in range(count)],
    }


def test_default_summary_excludes_manifest_and_preserves_original():
    job = job_with_files()
    before = copy.deepcopy(job)
    result = public_status(job)
    assert result["operation_id"] == "import-275"
    assert result["total"] == result["expected_count"] == 275
    assert result["counts"] == job["counts"]
    assert result["returned"] == len(result["files"]) == 20
    assert result["next_offset"] == 20
    assert "manifest" not in result
    assert "/private/original-secret.txt" not in json.dumps(result)
    assert result["index"]["errors_count"] == 100
    assert result["index"]["errors_omitted"] == 97
    assert len(result["index"]["errors"]) == 3
    assert job == before


@pytest.mark.parametrize("limit", [1, 20, 50])
def test_all_275_files_traversable_under_json_budget(limit):
    job = job_with_files()
    offset, seen = 0, []
    while offset is not None:
        page = public_status(job, offset=offset, limit=limit)
        assert len(json.dumps(page, ensure_ascii=True, indent=2).encode()) <= MAX_JSON_BYTES < 32 * 1024
        assert len(page["files"]) <= limit
        seen.extend(row["file_index"] for row in page["files"])
        next_offset = page["next_offset"]
        assert next_offset is None or next_offset > offset
        offset = next_offset
    assert seen == list(range(275))


def test_long_unicode_paths_identifiers_and_errors_are_marked_and_paginated():
    job = job_with_files()
    for row in job["files"]:
        row.update(original_path="Ordner/" + "📄Ä\\\"" * 2000,
                   source_ref="Quelle-" + "ä" * 2000,
                   error="Fehler: " + "无法读取📄" * 3000)
    before = copy.deepcopy(job)
    offset, seen, byte_limited = 0, [], False
    while offset is not None:
        page = public_status(job, offset=offset, limit=50)
        assert len(json.dumps(page, ensure_ascii=True, indent=2).encode()) <= MAX_JSON_BYTES
        byte_limited |= page["page_limited_by_bytes"]
        for row in page["files"]:
            assert {"original_path", "source_ref", "error"} <= set(row["truncated_fields"])
            assert row["original_path"].endswith("…")
            assert len(row["error"].encode()) <= 192
            assert len(row["source_ref_sha256"]) == 64
            seen.append(row["file_index"])
        next_offset = page["next_offset"]
        assert next_offset is None or next_offset > offset
        offset = next_offset
    assert byte_limited
    assert seen == list(range(275))
    assert job == before


def test_running_job_reports_expected_and_remaining_before_counts_exist():
    job = job_with_files()
    del job["counts"]
    job["files"] = [{"status": "stored"}, {"status": "processing"}]
    job["state"] = "running"
    page = public_status(job)
    assert page["counts"] == {"stored": 1, "processing": 1}
    assert page["processed"] == 1
    assert page["remaining"] == 274
    assert page["expected_count"] == 275
    assert page["total"] == 2


def test_empty_and_out_of_range_pages_terminate():
    empty = public_status({"operation_id": "empty", "files": []})
    assert empty["files"] == [] and empty["next_offset"] is None
    beyond = public_status(job_with_files(), offset=999)
    assert beyond["files"] == [] and beyond["returned"] == 0 and beyond["next_offset"] is None


@pytest.mark.parametrize("kwargs", [{"offset": -1}, {"offset": True}, {"offset": "1"},
                                    {"limit": 0}, {"limit": 51}, {"limit": False}, {"limit": 1.5}])
def test_invalid_pagination_is_rejected(kwargs):
    with pytest.raises(LibraryImportError, match="invalid_batch_status_page"):
        public_status(job_with_files(), **kwargs)
