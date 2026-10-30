"""Registry-owned MCP schemas, live grants and real stdio discovery/calls."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
import subprocess
import sys
from threading import Thread

from jsonschema import Draft202012Validator
from referencing import Registry
import pytest

from threaddesk.api.service import ThreadService
from threaddesk.services.commands import CommandApplication
from threaddesk.services.commands.model import CommandSpec
from threaddesk.services.commands.registry import CommandRegistry
from threaddesk.services.commands.schemas import obj
from threaddesk.services.mcp import McpBridge, TOOLS
from threaddesk.services.mcp_commands import tool_name
from threaddesk.services.modules import ModuleManifest, ModuleRegistry
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.ui.mcp_stdio import handle


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def service(tmp_path, request):
    store = request.param(tmp_path / "workspace")
    yield ThreadService(store)
    if hasattr(store, "connection"):
        store.connection.close()


def invoke(bridge, command, arguments=None, **fields):
    return bridge.call(tool_name(command), {"workspace_id": bridge.commands.application.workspace_id,
                                           "arguments": arguments or {}, **fields})


def test_every_authorized_registry_command_has_its_own_concrete_tool(service):
    bridge = McpBridge(service)
    listing = bridge.list_tools()
    assert {tool["name"] for tool in TOOLS} <= {tool["name"] for tool in listing}
    dynamic = {tool["_meta"]["threaddesk"]["id"]: tool for tool in listing if tool["name"].startswith("td_")}
    app = bridge.commands.application
    permitted = {row["id"]: row for row in app.registry.records(transport="mcp") if row["availability"] == "available"}
    assert set(dynamic) == set(permitted)
    assert len(listing) == len({tool["name"] for tool in listing})
    for identity, tool in dynamic.items():
        Draft202012Validator.check_schema(tool["inputSchema"])
        assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", tool["name"])
        metadata = tool["_meta"]["threaddesk"]
        assert metadata["input_schema"] == permitted[identity]["input_schema"]
        assert metadata["scope"] == permitted[identity]["scope"]
        assert metadata["workspace_id"] == app.workspace_id
        assert tool["annotations"]["readOnlyHint"] == (metadata["effect"] == "read")
        assert "arguments" in tool["inputSchema"]["properties"]
    assert "search.status" not in dynamic
    assert "server_sync.owner_reference" not in dynamic
    assert ("migration.stage" in dynamic) == isinstance(service.store, SQLiteStore)


def test_names_preserve_distinct_ids_and_fit_the_existing_bridge_contract():
    ids = ["a.b", "a_b", "a__b", "a-b", "module." + "long-" * 30 + ".read", "future/ü-command"]
    names = [tool_name(identity) for identity in ids]
    assert len(set(names)) == len(ids)
    for identity, name in zip(ids, names):
        assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name)
        assert tool_name(identity) == name
    assert tool_name("whiteboard.create") == "td_whiteboard__create"


def test_future_registration_appears_in_same_bridge_and_reuses_the_dispatcher(service):
    registry = CommandRegistry(service.store)
    bridge = McpBridge(service, registry=registry)
    before = bridge.tools_revision()
    spec = CommandSpec("future.feature", "future", "Source-owned future read", obj({"token": {"const": "known"}}, ("token",)),
                       lambda svc, args: {"received": args["token"]})
    registry.specs[spec.id] = spec
    assert bridge.tools_revision() != before
    assert tool_name(spec.id) in {tool["name"] for tool in bridge.list_tools()}
    result = invoke(bridge, spec.id, {"token": "known"})
    assert result["result"]["result"] == {"received": "known"}
    assert result["result"]["result_digest"]
    assert invoke(bridge, spec.id, {"token": "other"})["code"] == "validation_error"


_REF_SCHEMA = {"type": "object", "properties": {"value": {"$ref": "#/$defs/text"}},
               "required": ["value"], "additionalProperties": False,
               "$defs": {"text": {"type": "string", "const": "ok"}}}


@pytest.mark.parametrize("identifier", [None, "", "#", "own.json", "https://schema.example.test/own.json", "https://schema.example.test/own.json#"])
def test_domain_fragment_refs_keep_their_resource_root_and_source_identity(service, identifier):
    schema = deepcopy(_REF_SCHEMA)
    if identifier is not None:
        schema["$id"] = identifier
    _assert_resource_schema(service, schema, {"value": "ok"}, {"value": "wrong"})


@pytest.mark.parametrize("reference", ["root", "anchor", "dynamic_anchor", "nested_resource"])
def test_recursive_anchor_and_nested_resource_refs_keep_domain_scope(service, reference):
    if reference == "root":
        schema = obj({"value": {"const": "ok"}, "next": {"$ref": "#"}}, ("value",))
        valid, invalid = {"value": "ok", "next": {"value": "ok"}}, {"value": "ok", "next": {"value": "wrong"}}
    elif reference == "anchor":
        schema = deepcopy(_REF_SCHEMA)
        schema["$defs"]["text"]["$anchor"] = "text"
        schema["properties"]["value"] = {"$ref": "#text"}
        valid, invalid = {"value": "ok"}, {"value": "wrong"}
    elif reference == "dynamic_anchor":
        schema = {"$dynamicAnchor": "node", **obj({"value": {"const": "ok"}, "next": {"$dynamicRef": "#node"}}, ("value",))}
        valid, invalid = {"value": "ok", "next": {"value": "ok"}}, {"value": "ok", "next": {"value": "wrong"}}
    else:
        schema = {"$id": "https://schema.example.test/outer.json", **obj({"item": {"$ref": "inner.json"}}, ("item",)),
                  "$defs": {"inner": {"$id": "inner.json", **deepcopy(_REF_SCHEMA)}}}
        valid, invalid = {"item": {"value": "ok"}}, {"item": {"value": "wrong"}}
    _assert_resource_schema(service, schema, valid, invalid)


def _assert_resource_schema(service, schema, valid, invalid):
    source = deepcopy(schema)
    calls = []
    spec = CommandSpec("future.ref", "future", "Resource references", schema,
                       lambda svc, args: calls.append(args) or args)
    registry = CommandRegistry(service.store, [spec])
    direct = CommandApplication(service, registry=registry, transport="mcp")
    assert direct.call({"version": 1, "workspace_id": direct.workspace_id, "command": spec.id, "arguments": valid})["result"] == valid
    calls.clear()
    bridge = McpBridge(service, registry=registry)
    tool = next(tool for tool in bridge.list_tools() if tool["name"] == tool_name(spec.id))
    public = tool["inputSchema"]
    Draft202012Validator.check_schema(public)
    validator = Draft202012Validator(public, registry=Registry())
    validator.validate({"workspace_id": direct.workspace_id, "arguments": valid})
    assert list(validator.iter_errors({"workspace_id": direct.workspace_id, "arguments": invalid}))
    assert invoke(bridge, spec.id, valid)["result"]["result"] == valid
    assert invoke(bridge, spec.id, invalid)["code"] == "validation_error"
    assert calls == [valid]
    assert spec.schema == source and tool["_meta"]["threaddesk"]["input_schema"] == source
    assert bridge.list_tools()[-1]["inputSchema"] == public
    if source.get("$id") not in (None, "", "#"):
        assert public["properties"]["arguments"]["$id"] == source["$id"]


@pytest.mark.parametrize("identifier", [None, "https://schema.example.test/native.json"])
def test_lifted_native_bindings_resolve_refs_in_the_same_domain_resource(service, identifier):
    schema = deepcopy(_REF_SCHEMA)
    schema["properties"].update(operation_id={"$ref": "#/$defs/operation"}, expected_revision={"$ref": "#/$defs/revision"})
    schema["$defs"].update(operation={"const": "native-ref-operation"}, revision={"const": 0})
    schema["required"].extend(["operation_id", "expected_revision"])
    if identifier is not None:
        schema["$id"] = identifier
    source = deepcopy(schema)
    spec = CommandSpec("future.native", "future", "Native resource references", schema, lambda svc, args: args,
                       effect="domain", native_contract=True)
    bridge = McpBridge(service, registry=CommandRegistry(service.store, [spec]))
    tool = bridge.list_tools()[-1]
    payload = {"workspace_id": bridge.commands.application.workspace_id, "arguments": {"value": "ok"},
               "operation_id": "native-ref-operation", "expected_revision": 0}
    Draft202012Validator(tool["inputSchema"], registry=Registry()).validate(payload)
    assert bridge.call(tool_name(spec.id), payload)["result"]["result"] == {
        "value": "ok", "operation_id": "native-ref-operation", "expected_revision": 0}
    assert bridge.call(tool_name(spec.id), {**payload, "operation_id": "wrong"})["code"] == "validation_error"
    assert bridge.call(tool_name(spec.id), {**payload, "expected_revision": 1})["code"] == "validation_error"
    assert spec.schema == source


def test_external_schema_refs_are_rejected_without_network_or_handler_execution(service, monkeypatch):
    def refuse_network(*args, **kwargs):
        pytest.fail("Schema validation attempted network access")
    monkeypatch.setattr("socket.socket.connect", refuse_network)
    calls = []
    spec = CommandSpec("future.external", "future", "External ref must fail", obj({
        "value": {"$ref": "https://schema.example.test/must-not-be-fetched.json"}}, ("value",)),
        lambda svc, args: calls.append(args))
    bridge = McpBridge(service, registry=CommandRegistry(service.store, [spec]))
    result = invoke(bridge, spec.id, {"value": "ok"})
    assert result["isError"] and not result["ok"]
    assert calls == []


def test_native_create_then_whiteboard_write_replay_conflict_and_independent_readback(service):
    bridge = McpBridge(service)
    created = invoke(bridge, "thread_manage", {"action": "create", "data": {"title": "MCP fixture"}},
                     operation_id="mcp-create", expected_revision=0)
    assert created["ok"], created
    thread = created["result"]["result"]["thread"]
    fields = {"id": thread["id"], "actor": "MCP test", "actor_type": "system", "entry_type": "note", "content": "Persistent MCP entry"}
    written = invoke(bridge, "whiteboard.append", fields, operation_id="mcp-append", expected_revision=thread["revision"])
    assert written["ok"] and not written["result"]["duplicate"]
    reopened = McpBridge(ThreadService(type(service.store)(service.store.workspace_path)))
    try:
        replay = invoke(reopened, "whiteboard.append", fields, operation_id="mcp-append", expected_revision=thread["revision"])
        assert replay["result"]["duplicate"]
        assert replay["result"]["result_digest"] == written["result"]["result_digest"]
        assert invoke(reopened, "whiteboard.append", {**fields, "content": "Changed"}, operation_id="mcp-append", expected_revision=thread["revision"])["code"] == "operation_conflict"
        assert invoke(reopened, "whiteboard.append", fields, operation_id="mcp-stale", expected_revision=thread["revision"])["code"] == "revision_conflict"
        read = invoke(reopened, "whiteboard.list", {"id": thread["id"]})["result"]["result"]
        assert len(read["items"]) == 1 and read["items"][0]["content"] == fields["content"]
        receipt = invoke(reopened, "command.operation", {"operation_id": "mcp-append"})["result"]["result"]
        assert receipt["state"] == "complete" and receipt["result"] == written["result"]["result"]
    finally:
        if hasattr(reopened.svc.store, "connection"):
            reopened.svc.store.connection.close()
    bad = bridge.call(tool_name("get_thread"), {"workspace_id": "ws-wrong", "arguments": {"id": thread["id"]}})
    assert bad["code"] == "workspace_mismatch"
    mismatch = invoke(bridge, "thread_manage", {"operation_id": "other", "action": "create", "data": {"title": "Rejected"}}, operation_id="mismatch", expected_revision=0)
    assert mismatch["code"] == "validation_error"


def test_read_scopes_cannot_be_bypassed_by_legacy_gateway_or_request_fields(service):
    thread = service.create("Permission fixture")
    bridge = McpBridge(service, allowed_scopes={"workspace.read"})
    names = {tool["name"] for tool in bridge.list_tools()}
    assert "add_note" not in names and tool_name("whiteboard.append") not in names
    assert bridge.call("add_note", {"id": thread.id, "text": "Denied"})["code"] == "permission_required"
    assert bridge.call("command_invoke", {"version": 1, "workspace_id": bridge.commands.application.workspace_id,
        "command": "add_note", "arguments": {"id": thread.id, "text": "Denied"},
        "operation_id": "scope-denied", "expected_revision": thread.revision})["code"] == "permission_required"
    assert invoke(bridge, "whiteboard.append", {"id": thread.id, "actor": "Test", "actor_type": "human", "entry_type": "note", "content": "Denied"}, operation_id="scope-board", expected_revision=thread.revision)["code"] == "permission_required"
    assert bridge.call(tool_name("get_thread"), {"workspace_id": bridge.commands.application.workspace_id, "arguments": {"id": thread.id}, "allowed_scopes": ["workspace.write"]})["code"] == "validation_error"
    assert invoke(bridge, "search.status")["code"] == "local_owner_cli_required"
    assert service.get(thread.id).context.notes == "" and service.whiteboard(thread.id) == []


def test_dynamic_reads_never_refresh_the_index_and_invalid_wrappers_never_dispatch(service, monkeypatch):
    bridge = McpBridge(service)
    thread = service.create("Read only")
    def fail(_store):
        pytest.fail("read command attempted an index refresh")
    monkeypatch.setattr("threaddesk.services.library_refresh.refresh_existing", fail)
    assert invoke(bridge, "get_thread", {"id": thread.id})["ok"]
    assert bridge.call(tool_name("get_thread"), [thread.id])["code"] == "validation_error"
    assert bridge.call(tool_name("get_thread"), False)["code"] == "validation_error"
    assert invoke(bridge, "get_thread", {"id": thread.id, "unknown": True})["code"] == "validation_error"


def test_module_enable_schema_update_grant_revoke_disable_uninstall_are_live(service):
    bridge = McpBridge(service)
    thread = service.create("Module source")
    registry = ModuleRegistry(service.store)
    manifest = ModuleManifest("mcp-probe", "MCP probe", "1", read_scopes=("thread:read",),
        write_actions=("probe:write",), approvals=("probe:write",), commands=(
            {"id": "read", "capability": "read_thread"},
            {"id": "write", "capability": "write_own_record", "action": "probe:write", "required_approvals": ["probe:write"]}))
    identity = "module.mcp-probe.read"
    def names():
        return {tool["name"] for tool in bridge.list_tools()}
    revision = bridge.tools_revision()
    registry.install(manifest)
    assert bridge.tools_revision() != revision
    assert tool_name(identity) not in names()
    assert invoke(bridge, identity, {"id": thread.id})["code"] == "disabled"
    registry.set_enabled(manifest.id, True, manifest.approvals)
    assert tool_name(identity) in names()
    assert invoke(bridge, identity, {"id": thread.id})["ok"]
    written = invoke(bridge, "module.mcp-probe.write", {"record_id": "sample", "value": {"kept": True}}, operation_id="module-mcp-write", expected_revision=0)
    assert written["ok"], written
    state = registry._load()
    state["modules"][manifest.id]["granted_approvals"] = []
    registry._save(state)
    assert tool_name(identity) not in names()
    denied = invoke(bridge, "module.mcp-probe.write", {"record_id": "sample", "value": {"kept": False}}, operation_id="module-mcp-revoked", expected_revision=1)
    assert denied["code"] == "permission_required"
    declarations = deepcopy(manifest.commands)
    declarations[0]["input_schema"] = {"properties": {"id": {"maxLength": 1}}}
    registry.update(replace(manifest, commands=declarations))
    registry.set_enabled(manifest.id, True, manifest.approvals)
    schema = next(tool for tool in bridge.list_tools() if tool["name"] == tool_name(identity))["inputSchema"]["properties"]["arguments"]
    assert schema["allOf"][0]["properties"]["id"]["maxLength"] == 1
    assert invoke(bridge, identity, {"id": thread.id})["code"] == "validation_error"
    registry.set_enabled(manifest.id, False)
    assert tool_name(identity) not in names()
    registry.uninstall(manifest.id)
    assert invoke(bridge, identity, {"id": thread.id})["code"] == "command_not_found"


def test_real_stdio_discovery_call_and_idle_list_changed(tmp_path):
    service = ThreadService(JsonStore(tmp_path))
    thread = service.create("Actual stdio source")
    modules = ModuleRegistry(service.store)
    manifest = ModuleManifest("wire-probe", "Wire probe", "1", read_scopes=("thread:read",),
                              commands=({"id": "read", "capability": "read_thread"},))
    modules.install(manifest)
    root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, "PYTHONPATH": str(root / "src"), "THREADDESK_HOME": str(tmp_path), "THREADDESK_STORAGE": "json"}
    process = subprocess.Popen([sys.executable, "-m", "threaddesk.ui.mcp_stdio"], cwd=root, env=environment,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    output = Queue()
    def read_output():
        for line in process.stdout:
            output.put(json.loads(line))
    reader = Thread(target=read_output, daemon=True)
    reader.start()
    def send(payload):
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()
    def receive():
        try:
            return output.get(timeout=12)
        except Empty:
            pytest.fail("stdio peer did not return its expected message")
    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert receive()["result"]["capabilities"]["tools"]["listChanged"] is True
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = receive()["result"]["tools"]
        assert tool_name("module.wire-probe.read") not in {tool["name"] for tool in tools}
        workspace_id = next(tool for tool in tools if tool["name"] == tool_name("get_thread"))["_meta"]["threaddesk"]["workspace_id"]
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": tool_name("get_thread"), "arguments": {"workspace_id": workspace_id, "arguments": {"id": thread.id}}}})
        called = receive()["result"]
        assert called["structuredContent"]["result"]["title"] == thread.title
        assert json.loads(called["content"][0]["text"]) == called["structuredContent"]
        modules.set_enabled(manifest.id, True)
        assert receive() == {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}
        send({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})
        tools = receive()["result"]["tools"]
        assert tool_name("module.wire-probe.read") in {tool["name"] for tool in tools}
        send({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": tool_name("module.wire-probe.read"), "arguments": {"workspace_id": workspace_id, "arguments": {"id": thread.id}}}})
        assert receive()["result"]["structuredContent"]["result"]["id"] == thread.id
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
    assert process.returncode == 0, process.stderr.read()
