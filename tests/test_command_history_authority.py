"""Previously CLI-only/internally readable data uses the authorized command boundary."""
import json
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.services.commands import CommandApplication
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore])
def application(tmp_path, request):
    store = request.param(tmp_path / "workspace")
    app = CommandApplication(ThreadService(store), transport="mcp")
    yield app
    if hasattr(store, "connection"):
        store.connection.close()


def call(app, command, arguments):
    return app.call({"version": 1, "workspace_id": app.workspace_id,
                     "command": command, "arguments": arguments}, read_only=True)


def test_prompt_history_is_thread_bound_paginated_and_inert(application):
    svc = application.service
    first, other = svc.create("Prompt history"), svc.create("Other")
    svc.prompt("generic", "detailed", first.id, save=True)
    svc.prompt("generic", "short", first.id, save=True)
    before = svc.get(first.id).to_dict()
    one = call(application, "prompts.list", {"id": first.id, "limit": 1})
    two = call(application, "prompts.list", {"id": first.id, "offset": one["result"]["next_offset"]})
    assert one["result"]["total"] == 2
    assert one["result"]["items"][0]["id"] != two["result"]["items"][0]["id"]
    assert call(application, "prompts.list", {"id": other.id})["result"]["items"] == []
    assert svc.get(first.id).to_dict() == before
    restricted = CommandApplication(svc, transport="mcp", allowed_scopes=[])
    with pytest.raises(ManagementError) as denied:
        call(restricted, "prompts.list", {"id": first.id})
    assert denied.value.code == "permission_required"


def test_authority_import_reuses_validation_without_persisting_or_executing(application):
    fixture = Path(__file__).resolve().parents[1] / "docs/authority/fixtures/example-trace.json"
    events = json.loads(fixture.read_text())["events"]
    before = application.service.graph()
    first = call(application, "authority.import", {"events": events})
    second = call(application, "authority.import", {"events": events})
    assert first["result"] == second["result"]
    assert first["result_digest"] == second["result_digest"]
    assert first["result"]["imported"] == 5
    assert application.service.graph() == before
    assert not application.store.list_management_operation_records()
    with pytest.raises(ManagementError) as bad_hash:
        call(application, "authority.import", {"events": [{**events[0], "event_hash": "invalid"}]})
    assert bad_hash.value.code == "validation_error"
    with pytest.raises(ManagementError) as path:
        call(application, "authority.import", {"events": events, "output": "/tmp/unapproved.json"})
    assert path.value.code == "validation_error"
