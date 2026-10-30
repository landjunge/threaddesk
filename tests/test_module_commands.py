"""Live declarative discovery uses existing module grants and narrow contexts."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import InvalidState, ManagementError
from threaddesk.services.commands import CommandApplication
from threaddesk.services.commands.module_commands import MAX_COMMANDS
from threaddesk.services.modules import ModuleContext, ModuleManifest, ModuleRegistry
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore

COMMANDS = (
    {"id": "projects", "capability": "read_nodes"},
    {"id": "thread", "capability": "read_thread"},
    {"id": "board", "capability": "read_whiteboard"},
    {"id": "append", "capability": "append_whiteboard"},
    {"id": "records", "capability": "read_own_data"},
    {"id": "record", "capability": "write_own_record", "action": "probe:write",
     "required_approvals": ["probe:write"]},
)


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def setup(request, tmp_path):
    svc = ThreadService(request.param(tmp_path))
    manifest = ModuleManifest("probe", "Probe", "1.0", read_scopes=("knowledge:project", "thread:read", "whiteboard:read"),
                              write_actions=("whiteboard:append", "probe:write"), approvals=("probe:write",),
                              commands=deepcopy(COMMANDS))
    registry = ModuleRegistry(svc.store)
    registry.install(manifest)
    return svc, manifest, registry, CommandApplication(svc)


def invoke(app, name, args=None, *, operation=None, revision=None):
    request = {"version": 1, "workspace_id": app.workspace_id,
               "command": "module.probe." + name, "arguments": args or {}}
    if operation is not None:
        request["operation_id"] = operation
    if revision is not None:
        request["expected_revision"] = revision
    return app.call(request)


def rows(app):
    return {row["id"]: row for row in app.registry.records() if row["id"].startswith("module.probe.")}


def test_install_disabled_then_real_read_write_conflict_and_replay(setup):
    svc, manifest, registry, app = setup
    thread = svc.create("Module CAS source")
    project = svc.create_node("project", "Allowed project")
    svc.create_node("task", "Other kind")
    assert len(rows(app)) == 6
    assert {row["availability"] for row in rows(app).values()} == {"disabled"}
    with pytest.raises(ManagementError) as disabled:
        invoke(app, "thread", {"id": thread.id})
    assert disabled.value.code == "disabled"
    before = app.registry.revision()
    registry.set_enabled("probe", True, manifest.approvals)
    assert app.registry.revision() != before
    actual = invoke(app, "thread", {"id": thread.id})["result"]
    assert actual["revision"] == thread.revision and "files" not in actual
    assert [item["id"] for item in invoke(app, "projects", {"kind": "project"})["result"]["items"]] == [project.id]
    with pytest.raises(InvalidState, match="module_read_scope"):
        invoke(app, "projects", {"kind": "task"})
    args = {"id": thread.id, "actor": "Module probe", "actor_type": "system", "entry_type": "note", "content": "Retained entry"}
    first = invoke(app, "append", args, operation="module-append", revision=thread.revision)
    assert svc.get(thread.id).revision == thread.revision + 1
    assert invoke(app, "append", args, operation="module-append", revision=thread.revision)["duplicate"]
    with pytest.raises(ManagementError) as stale:
        invoke(app, "append", {**args, "content": "Stale append"}, operation="stale-append", revision=thread.revision)
    assert stale.value.code == "revision_conflict"
    assert len(invoke(app, "board", {"id": thread.id})["result"]["items"]) == 1
    assert first["result"]["entry"]["content"] == "Retained entry"


def test_owned_record_shared_legacy_revision_and_reopen(setup):
    svc, manifest, registry, app = setup
    registry.set_enabled("probe", True, manifest.approvals)
    assert invoke(app, "records")["result"]["revision"] == 0
    args = {"record_id": "sample", "value": {"title": "First"}}
    result = invoke(app, "record", args, operation="record-first", revision=0)
    assert result["result"] == {"record_id": "sample", "revision": 1}
    assert invoke(app, "record", args, operation="record-first", revision=0)["duplicate"]
    with pytest.raises(ManagementError) as conflict:
        invoke(app, "record", {**args, "value": {"title": "Wrong"}}, operation="record-stale", revision=0)
    assert conflict.value.code == "revision_conflict"
    # Existing runtime writers share the same lock/revision, rather than a
    # competing command-only data store.
    context = ModuleContext(svc.store, registry.get("probe"))
    assert context.write_own_record("probe:write", "legacy", {"kept": True}) is None
    actual = invoke(app, "records")["result"]
    assert actual["revision"] == 2 and actual["records"]["sample"] == {"title": "First"}
    reopened = CommandApplication(ThreadService(type(svc.store)(svc.store.root)))
    assert invoke(reopened, "record", args, operation="record-first", revision=0)["duplicate"]
    assert invoke(reopened, "records")["result"] == actual


def test_dynamic_schema_removal_and_rights_revoke_in_same_app(setup):
    svc, manifest, registry, app = setup
    thread = svc.create("Live grant source")
    registry.set_enabled("probe", True, manifest.approvals)
    before = app.registry.revision()
    declarations = deepcopy(manifest.commands)
    declarations[1]["input_schema"] = {"properties": {"id": {"maxLength": 1}}}
    registry.update(replace(manifest, commands=declarations))
    assert app.registry.revision() != before
    assert rows(app)["module.probe.thread"]["availability"] == "disabled"
    registry.set_enabled("probe", True, manifest.approvals)
    with pytest.raises(ManagementError) as schema:
        invoke(app, "thread", {"id": thread.id})
    assert schema.value.code == "validation_error"
    # Remove a capability without deleting its declaration: discovery and a
    # cached application must report the actual missing scope.
    registry.update(replace(manifest, read_scopes=("knowledge:project", "whiteboard:read")))
    registry.set_enabled("probe", True, manifest.approvals)
    assert rows(app)["module.probe.thread"]["availability"] == "permission_required"
    with pytest.raises(ManagementError) as denied:
        invoke(app, "thread", {"id": thread.id})
    assert denied.value.code == "permission_required"
    registry.uninstall("probe")
    assert rows(app) == {}
    with pytest.raises(ManagementError) as missing:
        invoke(app, "records")
    assert missing.value.code == "command_not_found"


def test_approvals_and_scope_revocation_block_cached_write(setup):
    _svc, manifest, registry, app = setup
    registry.set_enabled("probe", True, manifest.approvals)
    catalog = app.registry.revision()
    state = registry._load()
    state["modules"]["probe"]["granted_approvals"] = []
    registry._save(state)  # Simulated explicit grant revocation, not a new API.
    assert app.registry.revision() != catalog
    assert rows(app)["module.probe.record"]["availability"] == "permission_required"
    with pytest.raises(ManagementError) as denied:
        invoke(app, "record", {"record_id": "no-write", "value": {}}, operation="denied", revision=0)
    assert denied.value.code == "permission_required"
    assert not (_svc.store.root / "module-probe-data.json").exists()


def test_module_reads_are_inert_and_scope_changes_change_catalog(setup):
    svc, manifest, registry, app = setup
    thread = svc.create("Read only source")
    registry.set_enabled("probe", True, manifest.approvals)
    before = {str(path.relative_to(svc.store.root)): path.read_bytes()
              for path in svc.store.root.rglob("*") if path.is_file()}
    invoke(app, "thread", {"id": thread.id})
    invoke(app, "board", {"id": thread.id})
    invoke(app, "records")
    after = {str(path.relative_to(svc.store.root)): path.read_bytes()
             for path in svc.store.root.rglob("*") if path.is_file()}
    assert after == before
    initial_revision = app.registry.revision()
    # Both capabilities remain available after explicit re-enable, but their
    # actual permissible kinds changed. The catalog must still change.
    registry.update(replace(manifest, read_scopes=("knowledge:task", "thread:read", "whiteboard:read")))
    registry.set_enabled("probe", True, manifest.approvals)
    assert rows(app)["module.probe.projects"]["availability"] == "available"
    assert app.registry.revision() != initial_revision


def test_old_manifests_keep_empty_commands_without_activation(tmp_path):
    registry = ModuleRegistry(JsonStore(tmp_path))
    manifest = ModuleManifest.from_dict({"id": "old", "name": "Old", "version": "1", "manifest_version": 1})
    assert manifest.commands == ()
    assert registry.install(manifest).enabled is False
    assert not any(row["id"].startswith("module.old.") for row in CommandApplication(ThreadService(registry.store)).registry.records())


@pytest.mark.parametrize("patch", [
    {"capability": "os.system"}, {"handler": "evil.module:run"},
    {"input_schema": {"$ref": "https://untrusted.invalid/schema"}},
    {"input_schema": {"properties": {"id": {"pattern": "(a+)+$"}}}},
    {"input_schema": {"type": "not-a-type"}},
])
def test_untrusted_code_and_unbounded_schema_features_never_install(tmp_path, patch):
    declaration = {"id": "sample", "capability": "read_thread", **patch}
    registry = ModuleRegistry(JsonStore(tmp_path))
    with pytest.raises(InvalidState):
        registry.install(ModuleManifest("invalid", "Invalid", "1", commands=(declaration,)))
    assert registry.list() == []


def test_module_command_count_and_duplicate_budgets(tmp_path):
    registry = ModuleRegistry(JsonStore(tmp_path))
    many = tuple({"id": "read-" + str(index), "capability": "read_own_data"} for index in range(MAX_COMMANDS + 1))
    with pytest.raises(InvalidState, match="module_command_limit"):
        registry.install(ModuleManifest("large", "Large", "1", commands=many))
    with pytest.raises(InvalidState, match="module_command_identity"):
        registry.install(ModuleManifest("duplicate", "Duplicate", "1", commands=(COMMANDS[0], COMMANDS[0])))


def test_large_permission_metadata_keeps_each_catalog_record_bounded(tmp_path):
    import json
    store = JsonStore(tmp_path)
    registry = ModuleRegistry(store)
    manifest = ModuleManifest("bounded", "Bounded", "1",
                              read_scopes=tuple("scope-" + str(index) + ":" + "x" * 300 for index in range(80)),
                              commands=({"id": "read", "capability": "read_own_data",
                                         "input_schema": {"properties": {"unused": {"enum": ["x" * 7000]}}}},))
    registry.install(manifest)
    app = CommandApplication(ThreadService(store))
    row = app.registry.get("module.bounded.read").public()
    contract = row["module_contract"]
    assert contract["permissions_truncated"] and contract["permissions_counts"]["read_scopes"] == 80
    assert len(json.dumps(row, ensure_ascii=False).encode()) < 24000
    first = contract["permissions_digest"]
    registry.update(replace(manifest, read_scopes=(*manifest.read_scopes, "new:scope")))
    assert app.registry.get("module.bounded.read").public()["module_contract"]["permissions_digest"] != first


@pytest.mark.parametrize("store_type", [JsonStore, SQLiteStore])
def test_concurrent_legacy_owned_record_writers_do_not_lose_other_records(tmp_path, store_type):
    store = store_type(tmp_path)
    registry = ModuleRegistry(store)
    manifest = ModuleManifest("parallel", "Parallel", "1", write_actions=("own:write",))
    registry.install(manifest)
    registry.set_enabled("parallel", True)
    def write(index):
        local = store_type(tmp_path)
        context = ModuleContext(local, ModuleRegistry(local).get("parallel"))
        context.write_own_record("own:write", "record-" + str(index), {"index": index})
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write, range(12)))
    state = ModuleContext(store, registry.get("parallel")).read_own_data()
    assert len(state["records"]) == 12 and state["revision"] == 12
