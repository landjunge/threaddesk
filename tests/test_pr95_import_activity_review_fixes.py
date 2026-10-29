"""Published source observations survive interrupted mapping and later versions."""
import os
from datetime import datetime, timezone

import pytest

from threaddesk.core.errors import ManagementError
from threaddesk.services.activity import ActivityService
from threaddesk.services.library_batch import LibraryBatchImporter
from threaddesk.services.library_batch.jobs import JobStore
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def profile(tmp_path, request):
    store = request.param(tmp_path / "workspace")
    yield store
    if hasattr(store, "connection"):
        store.connection.close()


def _source(tmp_path):
    folder = tmp_path / "source"
    folder.mkdir()
    path = folder / "document.txt"
    path.write_text("Original verified bytes")
    return folder, path


def _version(path, text, day):
    path.write_text(text)
    stamp = datetime(2026, 10, day, 12, tzinfo=timezone.utc).timestamp()
    os.utime(path, (stamp, stamp))


@pytest.mark.parametrize("failure", [OSError, RuntimeError], ids=["transient", "interruption"])
def test_resume_preserves_checkpointed_change_identity_and_original_time(profile, tmp_path, monkeypatch, failure):
    folder, path = _source(tmp_path)
    batch = LibraryBatchImporter(profile)
    batch.run(batch.manifest_for_folder(folder), operation_id="original")
    _version(path, "A genuinely changed source version", 20)
    manifest = batch.manifest_for_folder(folder)
    with monkeypatch.context() as patch:
        def unavailable(*args, **kwargs):
            raise failure("metadata mapping temporarily unavailable")
        patch.setattr(batch, "_metadata", unavailable)
        if failure is RuntimeError:
            with pytest.raises(RuntimeError):
                batch.run(manifest, operation_id="interrupted-change")
        else:
            result = batch.run(manifest, operation_id="interrupted-change")
            assert not result["complete"]
    sources = JobStore(profile).read("library-batch-sources.json")["sources"]
    receipt = next(iter(sources.values()))
    assert receipt["state"] == "record_published"
    evidence = receipt["activity_evidence"]
    assert evidence["source_modified_at"] == "2026-10-20T12:00:00+00:00"
    assert ActivityService(profile).files([receipt["record_id"]])["revision"] == 0
    # A later timestamp on unchanged bytes cannot rewrite the original evidence.
    _version(path, path.read_text(), 21)
    resumed = LibraryBatchImporter(profile).resume("interrupted-change")
    assert resumed["complete"]
    sources = JobStore(profile).read("library-batch-sources.json")["sources"]
    after = next(iter(sources.values()))
    assert after["activity_evidence"] == evidence
    assert after["activity_evidence_history"] == [evidence]
    event = ActivityService(profile).files([receipt["record_id"]])["files"][receipt["record_id"]]["modified"]
    assert event["occurred_at"] == evidence["source_modified_at"]
    assert event["event_id"] == "file-change:" + evidence["operation_id"]
    path.unlink()
    assert ActivityService(profile).reconcile()["duplicates"] == 1
    assert LibraryBatchImporter(profile).resume("interrupted-change") == resumed


@pytest.mark.parametrize("legacy_receipt", [False, True], ids=["history", "legacy-single-evidence"])
def test_all_pending_source_versions_survive_until_paginated_reconciliation(profile, tmp_path, monkeypatch, legacy_receipt):
    folder, path = _source(tmp_path)
    batch = LibraryBatchImporter(profile)
    batch.run(batch.manifest_for_folder(folder), operation_id="initial")
    identities = []
    with monkeypatch.context() as patch:
        def unavailable(*args, **kwargs):
            raise ManagementError("activity_unavailable", "Projection temporarily unavailable")
        patch.setattr(ActivityService, "record_content_change", unavailable)
        for index, day in enumerate([20, 21]):
            _version(path, f"Verified changed version {index}", day)
            result = batch.run(batch.manifest_for_folder(folder), operation_id=f"changed-{index}")
            assert result["complete"] and result["files"][0]["activity"]["status"] == "pending"
            identities.append(result["files"][0]["record_id"])
            if index == 0 and legacy_receipt:
                jobs = JobStore(profile)
                data = jobs.read("library-batch-sources.json")
                for receipt in data["sources"].values():
                    receipt.pop("activity_evidence_history")
                jobs.write("library-batch-sources.json", data)
    path.unlink()  # No original or fresh stat is needed to replay observations.
    service = ActivityService(profile)
    first = service.reconcile(limit=1)
    assert (first["total"], first["recorded"], first["next_offset"]) == (2, 1, 1)
    second = service.reconcile(limit=1, offset=first["next_offset"])
    assert (second["recorded"], second["failed"], second["next_offset"]) == (1, 0, None)
    events = service.files(identities)["files"]
    assert [events[identity]["modified"]["occurred_at"] for identity in identities] == [
        "2026-10-20T12:00:00+00:00", "2026-10-21T12:00:00+00:00"]
    again = service.reconcile()
    assert (again["total"], again["recorded"], again["duplicates"]) == (2, 0, 2)


def test_failed_source_verification_does_not_invent_activity(profile, tmp_path, monkeypatch):
    folder, path = _source(tmp_path)
    batch = LibraryBatchImporter(profile)
    batch.run(batch.manifest_for_folder(folder), operation_id="initial")
    _version(path, "Unstable changed source", 20)
    monkeypatch.setattr(batch, "_post_copy_check", lambda *args: "source_changed_after_copy")
    result = batch.run(batch.manifest_for_folder(folder), operation_id="unverified")
    assert not result["complete"] and result["files"][0]["error"] == "source_changed_after_copy"
    assert ActivityService(profile).reconcile()["total"] == 0


def test_repeated_bytes_and_original_timestamp_keep_distinct_predecessor_observations(profile, tmp_path):
    folder, path = _source(tmp_path)
    batch = LibraryBatchImporter(profile)
    batch.run(batch.manifest_for_folder(folder), operation_id="initial")
    for index, (text, day) in enumerate([
        ("Version B", 20), ("Version C", 21), ("Version B", 20), ("Version D", 22),
    ]):
        _version(path, text, day)
        result = batch.run(batch.manifest_for_folder(folder), operation_id=f"transition-{index}")
        assert result["complete"]
        assert result["files"][0]["activity"]["recorded"]
    result = ActivityService(profile).reconcile()
    assert (result["total"], result["failed"], result["duplicates"]) == (4, 0, 4)


def test_remapped_origin_with_same_hashes_and_timestamps_preserves_all_record_identities(profile, tmp_path):
    _folder, path = _source(tmp_path)
    batch = LibraryBatchImporter(profile)
    identities = []
    for index, (origin, text, day) in enumerate([
        ("before/document.txt", "Version A", 19), ("before/document.txt", "Version B", 20),
        ("after/document.txt", "Version A", 19), ("after/document.txt", "Version B", 20),
    ]):
        _version(path, text, day)
        row = {"path": str(path), "original_path": origin, "source_ref": "stable-source"}
        result = batch.run({"files": [row]}, operation_id=f"mapping-{index}")
        assert result["complete"]
        identities.append(result["files"][0]["record_id"])
        if index:
            assert result["files"][0]["activity"]["recorded"]
    assert identities[1] != identities[3]
    result = ActivityService(profile).reconcile()
    assert (result["total"], result["failed"], result["duplicates"]) == (3, 0, 3)
