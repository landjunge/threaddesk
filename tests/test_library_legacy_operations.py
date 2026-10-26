"""Legacy owner receipts cannot be poisoned when the public boundary adopts them."""
from types import SimpleNamespace

import pytest

from test_library_api import library as library  # Explicit fixture re-export.
from threaddesk.core.errors import ManagementError
from threaddesk.services.library_files import LibraryFileService
from threaddesk.services.library_files.state import state_path
from threaddesk.services.library_operation import LibraryOperationBinding


def test_readonly_verification_uses_original_owner_hash(library):
    _app, svc, identity, _node, _original, _root = library
    files = LibraryFileService(svc.store)
    request = {"action": "rename", "id": identity, "operation_id": "legacy-owner-rename",
               "expected_revision": 1, "data": {"filename": "OriginalReceipt.txt"}}
    saved = files.manage(request)
    before = state_path(files.root).read_bytes()
    assert files.verify_recorded_request(request)["result"] == {**saved, "duplicate": True}
    with pytest.raises(ManagementError) as wrong:
        files.verify_recorded_request({**request, "data": {"filename": "WrongPayload.txt"}})
    assert wrong.value.code == "operation_conflict"
    assert state_path(files.root).read_bytes() == before
    assert LibraryOperationBinding(svc.store).read(request["operation_id"]) is None
    unknown = files.verify_recorded_request({**request, "operation_id": "not-recorded"})
    assert unknown["found"] is False and unknown["result"] is None


def test_public_wrong_legacy_replay_does_not_poison_correct_replay(library):
    app, svc, identity, _node, _original, _root = library
    files = LibraryFileService(svc.store)
    request = {"action": "rename", "id": identity, "operation_id": "legacy-public-adoption",
               "expected_revision": 1, "data": {"filename": "CorrectReceipt.txt"}}
    saved = files.manage(request)
    with pytest.raises(ManagementError) as wrong:
        app.call({**request, "data": {"filename": "WrongReceipt.txt"}})
    assert wrong.value.code == "operation_conflict"
    assert LibraryOperationBinding(svc.store).read(request["operation_id"]) is None
    correct = app.call(request)
    assert correct["duplicate"] and correct["record"] == saved["record"]
    assert app.call(request)["record"] == saved["record"]


def test_open_verification_never_launches_or_rechecks_handler(library):
    _app, svc, identity, _node, _original, _root = library
    launches = []
    files = LibraryFileService(svc.store,
        opener=lambda *args, **kwargs: (launches.append(args), SimpleNamespace(returncode=0))[1],
        handler_resolver=lambda _path: "/System/Applications/TextEdit.app")
    saved = files.open(identity, operation_id="legacy-open-owner", expected_revision=1)
    request = {"action": "open", "id": identity, "operation_id": "legacy-open-owner", "expected_revision": 1}
    before = state_path(files.root).read_bytes()
    verified = LibraryFileService(svc.store).verify_recorded_request(request)
    assert verified["result"] == {**saved, "duplicate": True}
    with pytest.raises(ManagementError) as wrong:
        LibraryFileService(svc.store).verify_recorded_request({**request, "expected_revision": 2})
    assert wrong.value.code == "operation_conflict"
    with pytest.raises(ManagementError) as invalid:
        files.verify_recorded_request({**request, "data": {}})
    assert invalid.value.code == "validation_error"
    assert len(launches) == 1
    assert state_path(files.root).read_bytes() == before


def test_long_public_reindex_identity_has_a_readback(library):
    app, _svc, _identity, _node, _original, _root = library
    identity = "index-" + "a" * 105  # Valid public bound (128), above import-job bound (100).
    result = app.call({"action": "reindex", "operation_id": identity})
    assert result["index"]["status"] == "ready"
    observed = app.call({"action": "operation", "operation_id": identity})
    assert observed["found"] and observed["result"]["operation_id"] == identity
