"""Verified retry recovers only missing source-version change evidence."""
from copy import deepcopy

import pytest
from test_pr95_import_activity_review_fixes import _source, _version

from threaddesk.services.activity import ActivityService
from threaddesk.services.library_batch import LibraryBatchImporter
from threaddesk.services.library_batch.jobs import JobStore
from threaddesk.services.library_import import LibraryImporter
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=['json', 'sqlite'])
def profile(tmp_path, request):
    store = request.param(tmp_path / 'workspace')
    yield store
    if isinstance(store, SQLiteStore): store.connection.close()


def source_receipt(store):
    return next(iter(JobStore(store).read('library-batch-sources.json')['sources'].values()))


def unstable_first_verification(store, folder, path, monkeypatch):
    batch = LibraryBatchImporter(store)
    initial = batch.run(batch.manifest_for_folder(folder), operation_id='initial-verified-version')
    _version(path, 'Changed bytes B published to CAS', 20)
    published = path.read_bytes()
    manifest = batch.manifest_for_folder(folder)
    original_check = batch._post_copy_check
    observations = []
    def changed_before_first_check(source, digest, size):
        if not observations:
            _version(path, 'Concurrent source version C during first check', 21)
        result = original_check(source, digest, size)
        observations.append(result)
        return result
    with monkeypatch.context() as patch:
        patch.setattr(batch, '_post_copy_check', changed_before_first_check)
        unstable = batch.run(manifest, operation_id='source-verification-conflict')
    assert observations == ['source_changed_after_copy']
    assert unstable['files'][0]['error'] == 'source_changed_after_copy'
    assert not unstable['complete']
    receipt = source_receipt(store)
    assert receipt['state'] == 'complete'  # Metadata mapping did complete.
    assert receipt.get('activity_evidence') is None
    assert receipt['predecessor_record_id'] == initial['files'][0]['record_id']
    record_path, _record = LibraryImporter(store).open_record(receipt['record_id'])
    assert record_path.read_bytes() == published
    assert ActivityService(store).reconcile()['total'] == 0
    return manifest, published, unstable


@pytest.mark.parametrize('retry', ['resume', 'new-operation'])
def test_settled_source_retry_recovers_missing_evidence_after_real_first_check_conflict(profile, tmp_path, monkeypatch, retry):
    folder, path = _source(tmp_path)
    manifest, published, unstable = unstable_first_verification(profile, folder, path, monkeypatch)
    _version(path, published.decode(), 22)
    before = path.read_bytes(), path.stat().st_mtime_ns
    batch = LibraryBatchImporter(profile)
    recovered = (batch.resume('source-verification-conflict') if retry == 'resume'
                 else batch.run(manifest, operation_id='settled-fresh-operation'))
    assert recovered['complete'] and recovered['files'][0]['status'] == 'duplicate'
    assert recovered['files'][0]['record_id'] == unstable['files'][0]['record_id']
    receipt = source_receipt(profile)
    assert len(receipt['activity_evidence_history']) == 1
    evidence = deepcopy(receipt['activity_evidence'])
    assert evidence['source_modified_at'] == '2026-10-22T12:00:00+00:00'
    activity = ActivityService(profile).files([receipt['record_id']])
    assert activity['revision'] == 1
    assert activity['files'][receipt['record_id']]['modified']['event_id'] == 'file-change:' + evidence['operation_id']
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    _version(path, published.decode(), 23)
    repeat = batch.run(manifest, operation_id='later-unchanged-operation')
    assert repeat['complete']
    assert source_receipt(profile)['activity_evidence'] == evidence
    assert source_receipt(profile)['activity_evidence_history'] == [evidence]
    assert ActivityService(profile).files([receipt['record_id']])['revision'] == 1
    assert ActivityService(profile).reconcile()['duplicates'] == 1


@pytest.mark.parametrize('projection_pending', [False, True], ids=['already-projected', 'pending-projection'])
def test_history_only_current_evidence_keeps_verified_time_and_identity(profile, tmp_path, monkeypatch, projection_pending):
    from threaddesk.core.errors import ManagementError

    folder, path = _source(tmp_path)
    batch = LibraryBatchImporter(profile)
    batch.run(batch.manifest_for_folder(folder), operation_id='history-only-original')
    _version(path, 'Verified source B with existing evidence', 20)
    with monkeypatch.context() as patch:
        if projection_pending:
            def pending(*args, **kwargs): raise ManagementError('activity_unavailable', 'Private fixture projection pending')
            patch.setattr(ActivityService, 'record_content_change', pending)
        changed = batch.run(batch.manifest_for_folder(folder), operation_id='history-only-verified-change')
    assert changed['complete']
    jobs = JobStore(profile); document = jobs.read('library-batch-sources.json')
    receipt = next(iter(document['sources'].values()))
    evidence = deepcopy(receipt.pop('activity_evidence'))
    jobs.write('library-batch-sources.json', document)
    _version(path, path.read_text(), 23)
    retry = batch.run(batch.manifest_for_folder(folder), operation_id='history-only-settled-retry')
    assert retry['complete']
    assert source_receipt(profile)['activity_evidence'] == evidence
    assert source_receipt(profile)['activity_evidence_history'] == [evidence]
    activity = ActivityService(profile).files([receipt['record_id']])
    assert activity['revision'] == 1
    assert activity['files'][receipt['record_id']]['modified']['occurred_at'] == '2026-10-20T12:00:00+00:00'


def test_older_version_history_is_not_reused_as_the_missing_current_observation(profile, tmp_path, monkeypatch):
    folder, path = _source(tmp_path)
    batch = LibraryBatchImporter(profile)
    batch.run(batch.manifest_for_folder(folder), operation_id='older-history-original')
    _version(path, 'Verified earlier version B', 20)
    batch.run(batch.manifest_for_folder(folder), operation_id='older-history-b')
    previous = deepcopy(source_receipt(profile)['activity_evidence'])
    _version(path, 'Current version C with first verification conflict', 21)
    published = path.read_bytes(); manifest = batch.manifest_for_folder(folder)
    original_check = batch._post_copy_check
    def unstable(source, digest, size):
        _version(path, 'Concurrent later D before verification', 22)
        return original_check(source, digest, size)
    with monkeypatch.context() as patch:
        patch.setattr(batch, '_post_copy_check', unstable)
        conflict = batch.run(manifest, operation_id='older-history-current-conflict')
    assert conflict['files'][0]['error'] == 'source_changed_after_copy'
    assert source_receipt(profile).get('activity_evidence') is None
    assert source_receipt(profile)['activity_evidence_history'] == [previous]
    _version(path, published.decode(), 23)
    assert batch.resume('older-history-current-conflict')['complete']
    after = source_receipt(profile)
    assert after['activity_evidence_history'][0] == previous
    assert len(after['activity_evidence_history']) == 2
    current = after['activity_evidence']
    assert current['record']['id'] == after['record_id']
    assert current['previous_record'] == previous['record']
    assert current['source_modified_at'] == '2026-10-23T12:00:00+00:00'
    assert current['operation_id'] != previous['operation_id']
    assert ActivityService(profile).files([after['record_id']])['revision'] == 2


def test_second_check_failure_keeps_first_verified_evidence_for_reconcile_and_retry(profile, tmp_path, monkeypatch):
    folder, path = _source(tmp_path)
    batch = LibraryBatchImporter(profile)
    batch.run(batch.manifest_for_folder(folder), operation_id='second-check-original')
    _version(path, 'Published B verified before metadata', 20)
    published = path.read_bytes(); manifest = batch.manifest_for_folder(folder)
    original_metadata = batch._metadata
    def changed_during_metadata(*args, **kwargs):
        result = original_metadata(*args, **kwargs)
        _version(path, 'Later source C after successful first verification', 21)
        return result
    with monkeypatch.context() as patch:
        patch.setattr(batch, '_metadata', changed_during_metadata)
        conflicted = batch.run(manifest, operation_id='second-check-conflict')
    assert not conflicted['complete'] and conflicted['files'][0]['error'] == 'source_changed_after_copy'
    evidence = deepcopy(source_receipt(profile)['activity_evidence'])
    assert evidence['source_modified_at'] == '2026-10-20T12:00:00+00:00'
    assert ActivityService(profile).files([evidence['record']['id']])['revision'] == 0
    path.unlink()
    assert ActivityService(profile).reconcile()['recorded'] == 1
    _version(path, published.decode(), 23)
    assert batch.resume('second-check-conflict')['complete']
    assert source_receipt(profile)['activity_evidence'] == evidence
    assert source_receipt(profile)['activity_evidence_history'] == [evidence]
    assert ActivityService(profile).files([evidence['record']['id']])['revision'] == 1


def test_metadata_assignment_and_filename_edits_survive_verified_recovery(profile, tmp_path, monkeypatch):
    from threaddesk.api.service import ThreadService
    from threaddesk.services.library_files import LibraryFileService

    folder, path = _source(tmp_path)
    _manifest, published, unstable = unstable_first_verification(profile, folder, path, monkeypatch)
    identity = unstable['files'][0]['record_id']
    owner_target = ThreadService(profile).create('Explicit owner assignment after conflicted observation')
    files = LibraryFileService(profile)
    current = files.info(identity)
    files.manage({'operation_id': 'owner-assign-during-conflict', 'action': 'assign', 'id': identity,
                  'expected_revision': current['revision'], 'data': {'thread_id': owner_target.id}})
    current = files.info(identity)
    files.manage({'operation_id': 'owner-rename-during-conflict', 'action': 'rename', 'id': identity,
                  'expected_revision': current['revision'], 'data': {'filename': 'owner-kept-filename.txt'}})
    before = files.info(identity)
    _version(path, published.decode(), 22)
    recovered = LibraryBatchImporter(profile).resume('source-verification-conflict')
    assert recovered['complete']
    after = files.info(identity)
    assert recovered['files'][0]['thread_id'] == owner_target.id
    for key in ('filename', 'logical_path', 'thread_id', 'revision', 'assignment'):
        assert after[key] == before[key]
    assert ActivityService(profile).files([identity])['revision'] == 1


def test_first_unchanged_same_bytes_rename_and_mapping_do_not_create_content_change(profile, tmp_path):
    from threaddesk.services.library_files import LibraryFileService

    folder, path = _source(tmp_path)
    batch = LibraryBatchImporter(profile)
    manifest = batch.manifest_for_folder(folder)
    first = batch.run(manifest, operation_id='nonchange-original')
    identity = first['files'][0]['record_id']
    files = LibraryFileService(profile)
    before = files.info(identity)
    files.manage({'operation_id': 'nonchange-owner-rename', 'action': 'rename', 'id': identity,
                  'expected_revision': before['revision'], 'data': {'filename': 'same-bytes-renamed.txt'}})
    _version(path, path.read_text(), 23)
    unchanged = batch.run(batch.manifest_for_folder(folder), operation_id='nonchange-new-time')
    assert unchanged['complete'] and unchanged['files'][0]['status'] == 'duplicate'
    mapped = deepcopy(manifest)
    mapped['files'][0]['original_path'] = 'different-supplied-mapping/document.txt'
    remapped = batch.run(mapped, operation_id='nonchange-remap')
    assert remapped['complete'] and remapped['files'][0]['record_id'] == identity
    assert files.info(identity)['filename'] == 'same-bytes-renamed.txt'
    assert source_receipt(profile).get('activity_evidence') is None
    assert source_receipt(profile)['activity_evidence_history'] == []
    assert ActivityService(profile).files([identity])['revision'] == 0
    assert ActivityService(profile).reconcile()['total'] == 0


def test_actual_missing_source_during_first_verification_recovers_only_after_source_returns(profile, tmp_path, monkeypatch):
    folder, path = _source(tmp_path)
    batch = LibraryBatchImporter(profile)
    batch.run(batch.manifest_for_folder(folder), operation_id='missing-source-original')
    _version(path, 'Changed source B lost during first verification', 20)
    published = path.read_bytes(); manifest = batch.manifest_for_folder(folder)
    original_check = batch._post_copy_check
    def gone(source, digest, size):
        path.unlink()
        return original_check(source, digest, size)
    with monkeypatch.context() as patch:
        patch.setattr(batch, '_post_copy_check', gone)
        conflict = batch.run(manifest, operation_id='missing-source-conflict')
    assert conflict['files'][0]['error'] == 'source_unavailable_after_copy'
    assert source_receipt(profile).get('activity_evidence') is None
    assert ActivityService(profile).reconcile()['total'] == 0
    assert batch.resume('missing-source-conflict')['files'][0]['status'] == 'missing'
    assert ActivityService(profile).reconcile()['total'] == 0
    _version(path, published.decode(), 22)
    assert batch.resume('missing-source-conflict')['complete']
    receipt = source_receipt(profile)
    assert len(receipt['activity_evidence_history']) == 1
    assert ActivityService(profile).files([receipt['record_id']])['revision'] == 1
