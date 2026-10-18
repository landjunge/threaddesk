"""Exact return reads stay local, bounded in scope and side-effect free."""
from pathlib import Path
import json

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.services.mcp import McpBridge
from threaddesk.services.return_contract import build
from threaddesk.services.return_inbox import ReturnInbox
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def service(request, tmp_path):
    svc = ThreadService(request.param(tmp_path))
    yield svc
    if isinstance(svc.store, SQLiteStore):
        svc.store.connection.close()


def payload(identity, text="Synthetic result"):
    return build(return_id=identity, handoff_id="issued-1", handoff_revision=1,
                 thread_id="thread-1", task_id="thread-1:task", worker="codex",
                 run_id="run-1", result=text)


def test_exact_read_keeps_item_decision_and_unrelated_results_local(service, monkeypatch):
    wanted = payload("return-1")
    service.receive_return(wanted)
    service.receive_return(payload("return-10", "Unrelated content must stay local"))
    service.decide_return("return-1", "rework", "Synthetic missing check")
    old_list = service.returns()
    artifact = service.store.artifact_path("return-inbox.json")
    before = artifact.read_bytes()
    monkeypatch.setattr(ReturnInbox, "list", lambda self: pytest.fail("exact read must not list"))
    response = McpBridge(service).call("get_return", {"return_id": "return-1"})
    assert response["ok"] and response["result"] == {"found": True, "item": old_list[0]}
    assert response["result"]["item"]["decision"]["choice"] == "rework"
    assert "Unrelated content" not in json.dumps(response)
    assert artifact.read_bytes() == before
    assert len(old_list) == 2


def test_missing_exact_id_is_not_prefix_or_path_lookup(service, tmp_path):
    service.receive_return(payload("ExactID"))
    outside = tmp_path / "outside-sensitive.txt"
    outside.write_text("not an inbox return")
    for identity in ("exactid", "Exact", " ExactID", "ExactID ", "absent", str(outside), "../outside-sensitive.txt"):
        response = McpBridge(service).call("get_return", {"return_id": identity})
        assert response == {"ok": True, "isError": False, "result": {"found": False, "item": None}}
    assert outside.read_text() == "not an inbox return"


@pytest.mark.parametrize("arguments", [{}, {"return_id": ""}, {"return_id": " "},
    {"return_id": None}, {"return_id": 1}, {"return_id": "x" * 257},
    {"return_id": "a", "principal": "other"}, {"return_id": "a", "path": "/tmp/store"},
    {"return_id": "a", "choice": "accepted"}])
def test_invalid_or_authority_fields_are_rejected(service, arguments):
    answer = McpBridge(service).call("get_return", arguments)
    assert answer["isError"] and answer["code"] == "validation_error"
    assert service.returns() == []


def test_new_read_rejects_secrets_in_id_or_legacy_selected_artifact(service):
    secret = "sk-" + "A" * 32
    response = McpBridge(service).call("get_return", {"return_id": secret})
    assert response["isError"] and secret not in json.dumps(response)
    safe = service.receive_return(payload("safe"))
    # Simulate an old/manual artifact without passing current receive validation.
    altered = {key: value for key, value in safe.items() if key != "duplicate"}
    altered["return"]["result"] = secret
    service.store.write_json_artifact("return-inbox.json", {"version": 1, "items": [altered]})
    response = McpBridge(service).call("get_return", {"return_id": "safe"})
    assert response["isError"] and secret not in json.dumps(response)
    assert McpBridge(service).call("get_return", {"return_id": "not-safe"})["result"] == {"found": False, "item": None}


def test_mcp_tool_contract_is_additive(service):
    tools = {tool["name"]: tool for tool in McpBridge(service).list_tools()}
    assert tools["get_return"]["inputSchema"] == {
        "type": "object", "additionalProperties": False, "required": ["return_id"],
        "properties": {"return_id": {"type": "string", "minLength": 1, "maxLength": 256}},
    }
    assert McpBridge(service).call("list_returns", {}) == {"ok": True, "isError": False, "result": []}
