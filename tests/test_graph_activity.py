"""Activity evidence, inert reads and revision-bound views on both profiles."""
from datetime import datetime, timezone
import json

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.services.activity import ActivityService, activity_band
from threaddesk.services.graph_read import GraphReadService
from threaddesk.services.graph_views import GraphViewService
from threaddesk.services.library_batch import LibraryBatchImporter
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore

STAMP = "2026-10-27T12:00:00+00:00"


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def profile(tmp_path, request):
    store = request.param(tmp_path / "workspace")
    yield store
    if hasattr(store, "close"):
        store.close()


def test_activity_reads_are_inert_and_initial_import_is_unknown(profile, tmp_path):
    svc = ThreadService(store=profile)
    node = svc.create_node("project", "Project")
    source = tmp_path / "source"
    source.mkdir()
    (source / "work.txt").write_text("original")
    importer = LibraryBatchImporter(profile)
    imported = importer.run(importer.manifest_for_folder(source.resolve(), node_id=node.id), operation_id="first")
    identity = imported["files"][0]["record_id"]
    before = {str(path): path.read_bytes() for path in profile.workspace_path.rglob("*") if path.is_file()}
    query = GraphReadService(profile).query(svc.graph(), mode="work", as_of=STAMP)
    assert query["schema"] == "threaddesk.graph.v2"
    assert all(row["activity"]["band"] == "unknown" for row in query["nodes"])
    assert ActivityService(profile).files([identity], as_of=STAMP)["files"][identity] == {}
    assert not (profile.workspace_path / "file-activity.json").exists()
    after = {str(path): path.read_bytes() for path in profile.workspace_path.rglob("*") if path.is_file()}
    assert before == after


def test_open_requires_successful_launch_and_replay_does_not_add_activity(profile):
    activity = ActivityService(profile)
    receipt = {"action": "open", "operation_id": "open-one", "record_id": "record",
               "status": "unknown", "sha256": "a" * 64, "launch_requested_at": STAMP}
    assert not activity.record_open_receipt(receipt)["recorded"]
    assert not activity.document.path.exists()
    receipt["status"] = "launch_requested"
    result = activity.record_open_receipt(receipt)
    assert result["revision"] == 1 and not result["duplicate"]
    assert activity.record_open_receipt(receipt)["duplicate"]
    event = activity.files(["record"], as_of=STAMP)["files"]["record"]["accessed"]
    assert event["kind"] == "open_requested"
    assert event["human_read_confirmed"] is False
    receipt["sha256"] = "b" * 64
    with pytest.raises(ManagementError) as error:
        activity.record_open_receipt(receipt)
    assert error.value.code == "operation_conflict"


def test_content_evidence_and_channels_aggregate_only_visible_files(profile):
    activity = ActivityService(profile)
    old = {"id": "old", "sha256": "a" * 64}
    current = {"id": "new", "sha256": "b" * 64, "status": "stored", "node_ids": ["project"],
               "filename": "Newest.txt"}
    assert not activity.record_content_change(current, None, source_modified_at=STAMP, operation_id="first")["recorded"]
    changed = activity.record_content_change(current, old, source_modified_at="2026-10-20T12:00:00Z", operation_id="change")
    assert changed["recorded"]
    receipt = {"action": "open", "operation_id": "open", "record_id": "new", "status": "launch_requested",
               "sha256": current["sha256"], "launch_requested_at": "2026-10-27T11:00:00+00:00"}
    activity.record_open_receipt(receipt)
    both = activity.node_activities([current], ["project", "new", "other"], as_of=STAMP, mode="work")
    assert both["nodes"]["project"]["band"] == "24h"
    assert both["nodes"]["project"]["selected"]["filename"] == "Newest.txt"
    assert both["nodes"]["project"]["selected"]["aggregation"] == "attached_file"
    assert both["nodes"]["other"]["band"] == "unknown"
    modified = activity.node_activities([current], ["project"], as_of=STAMP, mode="modified")
    assert modified["nodes"]["project"]["band"] == "7d"
    current["trashed"] = True
    assert activity.node_activities([current], ["project"], as_of=STAMP)["nodes"]["project"]["band"] == "unknown"


@pytest.mark.parametrize("occurred,band", [
    ("2026-10-26T12:00:00Z", "24h"),
    ("2026-10-26T11:59:59Z", "7d"),
    ("2026-10-20T12:00:00Z", "7d"),
    ("2026-09-27T12:00:00Z", "30d"),
    ("2026-07-29T12:00:00Z", "90d"),
    ("2026-07-28T12:00:00Z", "older"),
    (None, "unknown"),
    ("2026-10-28T12:00:00Z", "unknown"),
])
def test_fixed_rolling_intervals(occurred, band):
    assert activity_band(occurred, STAMP)["band"] == band


def test_dst_offset_and_future_are_explicit():
    # Last European DST transition is a 25-hour local day, not a 24-hour band.
    result = activity_band("2026-10-24T13:00:00+02:00", "2026-10-25T13:00:00+01:00")
    assert result["age_seconds"] == 25 * 3600
    assert result["band"] == "7d"
    assert activity_band("2026-10-28T12:00:00Z", STAMP)["clock_warning"] == "future_timestamp"
    with pytest.raises(ManagementError):
        activity_band("2026-10-25T13:00:00", STAMP)


def test_saved_view_revision_replay_conflict_delete_and_restart(profile):
    views = GraphViewService(profile)
    request = {"action": "save", "id": "daily", "operation_id": "save-daily", "expected_revision": 0,
               "data": {"title": "Daily", "state": {"camera": {"x": 9, "y": -1, "scale": .8},
                         "positions": {"abc": {"x": 10, "y": 20, "fixed": True}},
                         "filters": {"mode": "work", "band": "24h"}, "selection": ["abc"]}}}
    assert views.list()["views"] == []
    assert not views.document.path.exists()
    assert views.manage(request)["view"]["revision"] == 1
    assert GraphViewService(profile).manage(request)["duplicate"]
    assert views.get("daily")["state"]["positions"]["abc"]["fixed"] is True
    changed = json.loads(json.dumps(request));changed["data"]["title"] = "Different"
    with pytest.raises(ManagementError) as error:
        views.manage(changed)
    assert error.value.code == "operation_conflict"
    changed["operation_id"] = "stale"
    with pytest.raises(ManagementError) as error:
        views.manage(changed)
    assert error.value.code == "revision_conflict"
    deleted = views.manage({"action": "delete", "id": "daily", "expected_revision": 1,
                            "operation_id": "delete-daily"})
    assert deleted["view"]["revision"] == 2
    assert views.list()["total"] == 0
    assert views.operation_status("delete-daily")["result"]["view"]["deleted"]
    with pytest.raises(ManagementError) as error:
        views.get("daily")
    assert error.value.code == "not_found"


def test_graph_v2_bounded_neighborhood_and_v1_unchanged(profile):
    svc = ThreadService(store=profile)
    first = svc.create_node("project", "First")
    second = svc.create_node("task", "Second")
    third = svc.create_node("task", "Third")
    svc.connect(first.id, second.id, "contains")
    svc.connect(second.id, third.id, "contains")
    v1 = svc.graph()
    read = GraphReadService(profile)
    one = read.query(v1, center=first.id, hops=1, as_of=STAMP)
    assert {node["id"] for node in one["nodes"]} == {first.id, second.id}
    page = read.query(v1, limit=1, as_of=STAMP)
    assert page["total"] == 3 and page["next_offset"] == 1
    assert svc.graph() == v1 and v1["schema"] == "threaddesk.graph.v1"
    assert read.query(v1, band="24h", mode="work", as_of=STAMP)["nodes"] == []


def test_real_source_refresh_records_content_time_but_metadata_and_restore_do_not(profile, tmp_path):
    import os
    from threaddesk.services.library_files import LibraryFileService
    source = tmp_path / "source";source.mkdir()
    path = source / "work.txt";path.write_text("original")
    batch = LibraryBatchImporter(profile)
    first = batch.run(batch.manifest_for_folder(source.resolve()), operation_id="first-import")
    identity = first["files"][0]["record_id"]
    assert ActivityService(profile).files([identity])["revision"] == 0
    path.write_text("Actual changed source content")
    modified = datetime(2026, 10, 20, 12, tzinfo=timezone.utc).timestamp()
    os.utime(path, (modified, modified))
    second = batch.run(batch.manifest_for_folder(source.resolve()), operation_id="second-import")
    new_id = second["files"][0]["record_id"]
    assert new_id != identity
    activity = ActivityService(profile).files([new_id], as_of=STAMP)
    assert activity["revision"] == 1
    assert activity["files"][new_id]["modified"]["occurred_at"] == "2026-10-20T12:00:00+00:00"
    files = LibraryFileService(profile)
    for number, (action, data) in enumerate([
        ("rename", {"filename": "Renamed.txt"}), ("move", {"folder": "New folder"}),
        ("trash", {}), ("restore", {"trash_generation": 1})
    ]):
        record = files.info(new_id, include_trashed=True)
        files.manage({"action": action, "id": new_id, "expected_revision": record["revision"],
                      "operation_id": "metadata-" + str(number), "data": data})
    assert ActivityService(profile).files([new_id], as_of=STAMP)["revision"] == 1
    # Unchanged replay/refresh is technical processing, not another work event.
    batch.run(batch.manifest_for_folder(source.resolve()), operation_id="third-import")
    assert ActivityService(profile).files([new_id], as_of=STAMP)["revision"] == 1


def test_real_open_adapter_projects_success_but_no_second_launch_on_replay(profile, tmp_path):
    from types import SimpleNamespace
    from threaddesk.services.library_files import LibraryFileService
    source = tmp_path / "source";source.mkdir();(source / "view.txt").write_text("open fixture")
    batch = LibraryBatchImporter(profile)
    imported = batch.run(batch.manifest_for_folder(source.resolve()), operation_id="fixture-import")
    identity = imported["files"][0]["record_id"]
    launches = []
    files = LibraryFileService(profile, handler_resolver=lambda _path: "/Applications/TextEdit.app",
                               opener=lambda argv, **kwargs: (launches.append(argv) or SimpleNamespace(returncode=0)))
    first = files.open(identity, expected_revision=1, operation_id="first-open")
    assert first["status"] == "launch_requested" and first["activity"]["recorded"]
    assert files.open(identity, expected_revision=1, operation_id="first-open")["duplicate"]
    assert len(launches) == 1
    assert ActivityService(profile).files([identity])["revision"] == 1


def test_unassigned_file_does_not_mark_unassigned_projects_active(profile, monkeypatch):
    svc = ThreadService(store=profile)
    first = svc.create_node("project", "Unassigned first")
    second = svc.create_node("project", "Unassigned second")
    record = {"id": "abcdef123456", "status": "stored", "sha256": "a" * 64,
              "filename": "Unassigned.txt", "thread_id": None, "node_ids": []}
    monkeypatch.setattr("threaddesk.services.library_import.LibraryImporter._read_records", lambda self: [record])
    ActivityService(profile).record_open_receipt({"action": "open", "status": "launch_requested", "operation_id": "unassigned-open",
                                                "record_id": record["id"], "sha256": record["sha256"], "launch_requested_at": STAMP})
    graph = GraphReadService(profile).query(svc.graph(), mode="work", as_of=STAMP)
    assert {row["id"] for row in graph["nodes"]} == {first.id, second.id}
    assert all(row["activity"]["band"] == "unknown" for row in graph["nodes"])


def test_reconciliation_recovers_committed_open_without_launching_again(profile, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from threaddesk.services.library_files import LibraryFileService
    source = tmp_path / "source";source.mkdir();(source / "view.txt").write_text("open fixture")
    batch = LibraryBatchImporter(profile)
    imported = batch.run(batch.manifest_for_folder(source.resolve()), operation_id="fixture-import")
    identity = imported["files"][0]["record_id"]
    launches = []
    files = LibraryFileService(profile, handler_resolver=lambda _path: "/Applications/TextEdit.app",
                               opener=lambda argv, **kwargs: (launches.append(argv) or SimpleNamespace(returncode=0)))
    original = ActivityService.record_open_receipt
    def unavailable(self, receipt):
        raise ManagementError("activity_unavailable", "Fixture storage failure")
    monkeypatch.setattr(ActivityService, "record_open_receipt", unavailable)
    launched = files.open(identity, expected_revision=1, operation_id="recover-open")
    assert launched["status"] == "launch_requested" and not launched["activity"]["recorded"]
    monkeypatch.setattr(ActivityService, "record_open_receipt", original)
    recovered = ActivityService(profile).reconcile(limit=1)
    assert recovered["recorded"] == 1 and recovered["failed"] == 0
    evidence = ActivityService(profile).files([identity])["files"][identity]["accessed"]
    assert evidence["occurred_at"] == launched["launch_requested_at"]
    assert len(launches) == 1
    assert ActivityService(profile).reconcile(limit=1)["duplicates"] == 1
    assert len(launches) == 1


def test_reconciliation_uses_saved_source_evidence_without_current_original(profile, tmp_path, monkeypatch):
    import os
    source = tmp_path / "source";source.mkdir();path = source / "work.txt";path.write_text("old")
    batch = LibraryBatchImporter(profile)
    batch.run(batch.manifest_for_folder(source.resolve()), operation_id="before")
    path.write_text("Changed original")
    modified = datetime(2026, 10, 20, 12, tzinfo=timezone.utc).timestamp()
    os.utime(path, (modified, modified))
    original = ActivityService.record_content_change
    def unavailable(self, *args, **kwargs):
        raise ManagementError("activity_unavailable", "Fixture storage failure")
    monkeypatch.setattr(ActivityService, "record_content_change", unavailable)
    changed = batch.run(batch.manifest_for_folder(source.resolve()), operation_id="after")
    assert changed["complete"]
    identity = changed["files"][0]["record_id"]
    path.unlink()  # Reconciliation must use the committed evidence, not stat().
    monkeypatch.setattr(ActivityService, "record_content_change", original)
    recovered = ActivityService(profile).reconcile(limit=1)
    assert recovered["recorded"] == 1 and recovered["failed"] == 0
    evidence = ActivityService(profile).files([identity])["files"][identity]["modified"]
    assert evidence["occurred_at"] == "2026-10-20T12:00:00+00:00"


def test_bad_activity_does_not_block_graph_and_evidence_is_preserved(profile):
    svc = ThreadService(store=profile)
    node = svc.create_node("project", "Still navigable")
    path = profile.workspace_path / "file-activity.json"
    path.write_text("{ damaged fixture evidence")
    graph = GraphReadService(profile).query(svc.graph(), as_of=STAMP)
    assert graph["activity_status"] == "unavailable"
    assert graph["activity_revision"] is None
    assert graph["nodes"][0]["id"] == node.id
    assert graph["nodes"][0]["activity"]["band"] == "unknown"
    assert path.read_text() == "{ damaged fixture evidence"


def test_reconciliation_batch_reads_once_and_writes_only_new_events(profile, monkeypatch):
    from threaddesk.services.library_files import state
    receipts = {}
    for number in range(20):
        receipt = {"action": "open", "status": "launch_requested", "operation_id": "open-" + str(number),
                   "record_id": str(number), "sha256": "a" * 64, "launch_requested_at": STAMP}
        receipts[str(number)] = {"result": receipt}
    state.write_state(profile.workspace_path / "library-files", {
        "schema_version": 1, "generation": 0, "records": {}, "operations": receipts})
    service = ActivityService(profile)
    reads = writes = 0
    original_read, original_write = service.document.read, service.document.write
    def read():
        nonlocal reads
        reads += 1
        return original_read()
    def write(data):
        nonlocal writes
        writes += 1
        return original_write(data)
    monkeypatch.setattr(service.document, "read", read)
    monkeypatch.setattr(service.document, "write", write)
    assert service.reconcile(limit=50)["recorded"] == 20
    assert (reads, writes) == (1, 1)
    reads = writes = 0
    assert service.reconcile(limit=50)["duplicates"] == 20
    assert (reads, writes) == (1, 0)
