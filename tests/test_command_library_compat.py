"""Existing package and historical journal imports keep their actual semantics."""
import hashlib
from pathlib import Path
from zipfile import ZipFile

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.services.commands import CommandApplication
from threaddesk.services.library_import import LibraryImporter
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.mark.parametrize("backend", [JsonStore, SQLiteStore])
def test_package_and_historical_resume_use_original_import_services(tmp_path, backend):
    store = backend(tmp_path / "workspace")
    try:
        svc = ThreadService(store)
        thread = svc.create("Package project")
        app = CommandApplication(svc, transport="cli")
        def call(command, args, operation):
            return app.call({"version": 1, "workspace_id": app.workspace_id, "command": command,
                             "arguments": args, "operation_id": operation})
        package = tmp_path / "original.zip"
        with ZipFile(package, "w") as archive:
            archive.writestr("Package project/plan.txt", "Actual owned package original")
            archive.writestr("unassigned.txt", "Preserved unassigned original")
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        args = {"path": str(package.resolve()), "sha256": digest}
        result = call("library.package_import", args, "package")
        assert result["result"]["stored"] == 2
        records = LibraryImporter(store).catalog()["records"]
        assert next(row for row in records if row["origin_path"].endswith("plan.txt"))["thread_id"] == thread.id
        assert call("library.package_import", args, "package")["duplicate"]
        assert hashlib.sha256(package.read_bytes()).hexdigest() == digest
        with pytest.raises(ManagementError) as conflict:
            call("library.package_import", {**args, "sha256": "0" * 64}, "wrong-package")
        assert conflict.value.code == "artifact_conflict"
        # A historical persisted journal may name an existing original source.
        source = tmp_path / "historical-originals"
        source.mkdir()
        (source / "first.txt").write_text("Historical original")
        (source / "Unknown.key").write_bytes(b"not a Keynote document")
        imported = call("library.folder_import", {"path": str(source.resolve())}, "folder-import")
        assert imported["result"]["stored"] == 1 and imported["result"]["failed"] == 1
        journal = app.call({"version": 1, "workspace_id": app.workspace_id,
                           "command": "library.journal_status", "arguments": {"collection": "failures", "limit": 1}})["result"]
        assert journal["total"] == 1 and journal["counts"]["failed"] == 1 and len(journal["items"]) == 1
        (source / "second.txt").write_text("Original supplied after journal creation")
        resumed = call("library.journal_resume", {}, "journal-resume")
        assert resumed["result"]["stored"] == 1
        assert call("library.journal_resume", {}, "journal-resume")["duplicate"]
        assert (source / "first.txt").read_text() == "Historical original"
        assert len(LibraryImporter(store).catalog()["records"]) == 4
        selected = tmp_path / "selected-original.txt"
        selected.write_text("Selected owned original")
        digest = hashlib.sha256(selected.read_bytes()).hexdigest()
        args = {"files": [{"name": "Package project/selected.txt", "path": str(selected.resolve()), "sha256": digest}]}
        assert call("library.selected_import", args, "selected-import")["result"]["stored"] == 1
        assert call("library.selected_import", args, "selected-import")["duplicate"]
        assert hashlib.sha256(selected.read_bytes()).hexdigest() == digest
        records = LibraryImporter(store).catalog()["records"]
        assert len(records) == 5
        assert next(row for row in records if row["origin_path"].endswith("selected.txt"))["thread_id"] == thread.id
    finally:
        if hasattr(store, "connection"):
            store.connection.close()


@pytest.mark.parametrize("backend", [JsonStore, SQLiteStore])
def test_owner_reference_is_explicit_local_cli_only_and_independently_read_back(tmp_path, backend):
    store = backend(tmp_path / "workspace")
    try:
        svc = ThreadService(store)
        thread = svc.create("Owned source authority")
        root = tmp_path / "originals"
        root.mkdir()
        app = CommandApplication(svc, transport="cli")
        def request(command, args, operation):
            return {"version": 1, "workspace_id": app.workspace_id, "command": command, "arguments": args,
                    "operation_id": operation, "expected_revision": thread.revision}
        app.call(request("server_sync.configure", {"thread_id": thread.id, "url": "https://server.example",
                         "project_id": "", "root": str(root.resolve()), "token": "fixture-only-" + "x" * 32}, "configure"))
        original = root / "retained.txt"
        original.write_text("Retained original")
        args = {"thread_id": thread.id, "path": str(original), "allowed": True}
        for transport in ("mcp", "http"):
            remote = CommandApplication(svc, transport=transport)
            with pytest.raises(ManagementError) as denied:
                remote.call(request("server_sync.owner_reference", args, "denied-" + transport))
            assert denied.value.code == "local_owner_cli_required"
            assert not app.operation("denied-" + transport)["found"]
        app.call(request("server_sync.owner_reference", args, "grant"))
        from threaddesk.server_sync.desktop import BindingBook
        assert str(original) in BindingBook(svc).view(thread.id)["owner_references"]
        assert app.call(request("server_sync.owner_reference", args, "grant"))["duplicate"]
        app.call(request("server_sync.owner_reference", {**args, "allowed": False}, "revoke"))
        assert str(original) not in BindingBook(svc).view(thread.id)["owner_references"]
        assert original.read_text() == "Retained original"
    finally:
        if hasattr(store, "connection"):
            store.connection.close()
