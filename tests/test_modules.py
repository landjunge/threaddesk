import json

import pytest

from threaddesk.core.errors import InvalidState, NotFound
from threaddesk.services.modules import ModuleManifest, ModuleRegistry
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
