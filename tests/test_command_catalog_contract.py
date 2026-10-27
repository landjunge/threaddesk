"""Published transport and workspace bindings remain true across adapters."""
import hashlib
from dataclasses import replace

import pytest
from jsonschema.exceptions import SchemaError

from http_ui_client import UIClient
from threaddesk.api.service import ThreadService
from threaddesk.services.commands import CommandApplication
from threaddesk.services.commands.model import workspace_identity
from threaddesk.services.commands.registry import CommandRegistry
from threaddesk.services.commands.validation import command_request_digest, encode
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.ui.server import create_app


@pytest.mark.parametrize("backend", [JsonStore, SQLiteStore])
def test_change_status_http_and_command_share_inert_workspace_binding(tmp_path, monkeypatch, backend):
    home = tmp_path / "workspace"
    monkeypatch.setenv("THREADDESK_HOME", str(home))
    monkeypatch.setenv("THREADDESK_STORAGE", "sqlite" if backend is SQLiteStore else "json")
    store = backend(home)
    try:
        application = CommandApplication(ThreadService(store))
        identity = workspace_identity(store)
        request = {"version": 1, "workspace_id": identity, "command": "graph.change_status", "arguments": {}}
        first = application.call(request, read_only=True)["result"]
        with UIClient(create_app()) as client:
            response = client.get("/api/graph/change-status")
        assert response.status_code == 200
        actual = response.json()
        assert actual["workspace_id"] == identity == application.workspace_id
        assert actual["status"] == first["status"] == "ready"
        assert actual["fingerprint"] == first["fingerprint"]
        assert not store.list_management_operation_records()
        assert str(home) not in encode(actual)
    finally:
        if hasattr(store, "connection"):
            store.connection.close()


def test_catalogue_does_not_offer_owner_search_to_remote_transports(tmp_path):
    registry = CommandRegistry(JsonStore(tmp_path / "workspace"))
    row = registry.get("search.query").public()
    assert row["allowed_transports"] == ["local", "cli"]
    assert row["transports"]["http"] == row["transports"]["mcp"] == "not_allowed"
    assert row["transports"]["cli"] == "local_authorized"


def test_digest_helper_preserves_canonical_dispatch_identity(tmp_path):
    application = CommandApplication(ThreadService(JsonStore(tmp_path / "workspace")))
    spec = application.registry.get("trash.purge")
    arguments = {"trash_id": "trash-test", "generation": 1, "expected_revision": 2,
                 "operation_id": "permanent-test", "reference_digest": "a" * 64, "confirmation": "DELETE test"}
    request = {"operation_id": "permanent-test", "expected_revision": 2}
    canonical = {"version": 1, "workspace_id": application.workspace_id, "command": spec.id,
                 "arguments": arguments, "operation_id": "permanent-test", "expected_revision": 2}
    digest = command_request_digest(application.workspace_id, spec.id, arguments, "permanent-test", 2)
    assert digest == application._digest(request, spec, arguments)
    assert digest == hashlib.sha256(encode(canonical).encode()).hexdigest()
    assert digest != command_request_digest(application.workspace_id, spec.id, arguments, "permanent-test")


def test_schema_cache_revalidates_changed_content(tmp_path):
    store = JsonStore(tmp_path / "workspace")
    spec = CommandRegistry(store).get("graph.change_status")
    CommandRegistry(store, [spec])
    with pytest.raises(SchemaError):
        CommandRegistry(store, [replace(spec, schema={"type": "definitely-not-a-json-type"})])
