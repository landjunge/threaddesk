import json

import pytest

from threaddesk.core.errors import InvalidState, NotFound
from threaddesk.core.models import KnowledgeNode
from threaddesk.services.modules import ModuleManifest, ModuleRegistry, ModuleRuntime
from threaddesk.storage.json_store import JsonStore


def manifest(**changes):
    values = {
        "id": "workshop",
        "name": "Workshop",
        "version": "1.0.0",
        "node_kinds": ("workshop.event",),
        "read_scopes": ("knowledge:project",),
        "write_actions": ("workshop:create",),
        "approvals": ("knowledge:link",),
        "views": ("workshop:list",),
        "uninstall": "retain-data",
    }
    values.update(changes)
    return ModuleManifest(**values)


def test_install_is_disabled_and_manifest_exposes_capabilities(tmp_path):
    registry = ModuleRegistry(JsonStore(tmp_path))
    installed = registry.install(manifest())
    assert installed.enabled is False
    assert installed.manifest.capabilities == ("read", "view", "write")
    assert registry.get("workshop").manifest.version == "1.0.0"


def test_enable_requires_every_declared_approval(tmp_path):
    registry = ModuleRegistry(JsonStore(tmp_path))
    registry.install(manifest())
    with pytest.raises(InvalidState, match="module_approval_required"):
        registry.set_enabled("workshop", True)
    assert registry.set_enabled("workshop", True, ("knowledge:link",)).enabled is True


def test_update_with_new_permission_disables_module_until_reapproved(tmp_path):
    registry = ModuleRegistry(JsonStore(tmp_path))
    registry.install(manifest())
    registry.set_enabled("workshop", True, ("knowledge:link",))
    updated = registry.update(manifest(version="1.1.0", approvals=("knowledge:link", "contact:read")))
    assert updated.enabled is False
    assert updated.granted_approvals == ("knowledge:link",)


def test_uninstall_removes_registry_entry_without_touching_module_data(tmp_path):
    store = JsonStore(tmp_path)
    registry = ModuleRegistry(store)
    registry.install(manifest())
    data = tmp_path / "module-workshop-data.json"
    data.write_text('{"kept": true}', encoding="utf-8")
    assert registry.uninstall("workshop").uninstall == "retain-data"
    assert json.loads(data.read_text(encoding="utf-8")) == {"kept": True}
    with pytest.raises(NotFound):
        registry.get("workshop")


@pytest.mark.parametrize("bad_id", ["Workshop", "../workshop", "work_shop", ""])
def test_invalid_module_ids_are_rejected_without_writing(tmp_path, bad_id):
    registry = ModuleRegistry(JsonStore(tmp_path))
    with pytest.raises(InvalidState, match="module_id"):
        registry.install(manifest(id=bad_id))
    assert not (tmp_path / "modules.json").exists()


def enabled_runtime(tmp_path):
    store = JsonStore(tmp_path)
    registry = ModuleRegistry(store)
    registry.install(manifest())
    registry.set_enabled("workshop", True, ("knowledge:link",))
    return store, ModuleRuntime(store, registry)


def test_runtime_only_exposes_declared_read_scopes_and_own_data(tmp_path):
    store, runtime = enabled_runtime(tmp_path)
    store.save_node(KnowledgeNode(id="p1", kind="project", title="Allowed"))
    store.save_node(KnowledgeNode(id="t1", kind="task", title="Foreign"))

    def handler(context):
        projects = context.read_nodes("project")
        context.write_own_record("workshop:create", "event-1", {"title": "Planning"})
        return projects

    result = runtime.run("workshop", "workshop:create", handler)
    assert result.ok is True
    assert [item["id"] for item in result.value] == ["p1"]
    assert store.get_node("t1").title == "Foreign"


def test_runtime_denies_undeclared_scope_and_action_without_writing(tmp_path):
    _, runtime = enabled_runtime(tmp_path)
    denied_read = runtime.run("workshop", "workshop:create", lambda context: context.read_nodes("task"))
    denied_write = runtime.run("workshop", "admin:delete", lambda context: None)
    assert denied_read.ok is False and denied_read.error == "module_read_scope"
    assert denied_write.ok is False and denied_write.error == "module_write_action"


def test_module_failure_is_contained_and_core_remains_usable(tmp_path):
    store, runtime = enabled_runtime(tmp_path)
    result = runtime.run("workshop", "workshop:create", lambda context: 1 / 0)
    store.save_node(KnowledgeNode(id="p1", kind="project", title="Still alive"))
    assert result.ok is False
    assert result.error == "division by zero"
    assert store.get_node("p1").title == "Still alive"


def test_disabled_module_never_calls_handler(tmp_path):
    store = JsonStore(tmp_path)
    registry = ModuleRegistry(store)
    registry.install(manifest())
    called = []
    result = ModuleRuntime(store, registry).run("workshop", "workshop:create", lambda context: called.append(True))
    assert result.ok is False and result.error == "module_disabled"
    assert called == []
