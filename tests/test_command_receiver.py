"""The composed byte receiver contract survives command/HTTP adaptation."""
import base64
import hashlib

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.services.commands import CommandApplication
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.mark.parametrize("backend", [JsonStore, SQLiteStore])
def test_real_receiver_action_schema_commit_replay_and_unknown_fields(tmp_path, backend):
    store = backend(tmp_path / "workspace")
    try:
        svc = ThreadService(store)
        thread = svc.create("Received original")
        application = CommandApplication(svc)
        def call(command, args, operation=None):
            request = {"version": 1, "workspace_id": application.workspace_id, "command": command, "arguments": args}
            if operation:
                request["operation_id"] = operation
            return application.call(request)
        body = "An actual received original: Größe".encode()
        begin = {"action": "begin", "transfer_id": "receiver-original", "filename": "Original.txt",
                 "thread_id": thread.id, "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        assert call("library_receive", begin, "begin")["result"]["state"] == "receiving"
        with pytest.raises(ManagementError) as invalid:
            call("library_receive", {**begin, "unknown": True}, "invalid")
        assert invalid.value.code == "validation_error"
        assert not application.operation("invalid")["found"]
        call("library_receive", {"action": "append", "transfer_id": "receiver-original", "offset": 0,
             "data_base64": base64.b64encode(body).decode()}, "append")
        commit = {"action": "commit", "transfer_id": "receiver-original"}
        result = call("library_receive", commit, "commit")["result"]
        assert result["state"] == "committed"
        assert call("library_receive", commit, "commit")["duplicate"]
        assert call("library_receive_status", {"transfer_id": "receiver-original"})["result"]["state"] == "committed"
        from threaddesk.services.library_import import LibraryImporter
        importer = LibraryImporter(store)
        records = importer._read_records()
        assert len(records) == 1
        path, record = importer.open_record(records[0]["id"])
        assert path.read_bytes() == body and record["sha256"] == begin["sha256"]
    finally:
        if hasattr(store, "connection"):
            store.connection.close()
