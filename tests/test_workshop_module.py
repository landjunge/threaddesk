import pytest

from threaddesk.core.errors import InvalidState
from threaddesk.services.modules import ModuleRegistry, ModuleRuntime
from threaddesk.services.workshop_module import WORKSHOP_MANIFEST, WorkshopEvent, WorkshopService
from threaddesk.storage.json_store import JsonStore


def setup(tmp_path):
    store = JsonStore(tmp_path)
    registry = ModuleRegistry(store)
    service = WorkshopService(registry, ModuleRuntime(store, registry))
    service.install()
    return store, registry, service


def event(**changes):
    values = {
        "id": "autumn-lab",
        "title": "Autumn Lab",
        "audience": "Teenagers",
        "course_level": "Advanced",
        "schedule": "2026-10-12T09:00:00+02:00",
        "location": "Studio 2",
        "materials": ("Clay", "Wire"),
        "participant_ids": ("person-1",),
        "task_ids": ("task-1",),
        "feedback": ("More setup time",),
        "workflow_steps": ("Prepare", "Run", "Review"),
    }
    values.update(changes)
    return WorkshopEvent(**values)


def test_builtin_manifest_covers_real_workshop_capabilities():
    assert "workshop.event" in WORKSHOP_MANIFEST.node_kinds
    assert set(WORKSHOP_MANIFEST.approvals) == {"knowledge:link", "contact:link"}
    assert WORKSHOP_MANIFEST.uninstall == "retain-data"


def test_workshop_stays_off_until_both_link_permissions_are_granted(tmp_path):
    _, registry, service = setup(tmp_path)
    assert service.create_event(event()).error == "module_disabled"
    with pytest.raises(InvalidState, match="module_approval_required"):
        registry.set_enabled("workshop", True, ("knowledge:link",))
    registry.set_enabled("workshop", True, WORKSHOP_MANIFEST.approvals)
    assert service.create_event(event()).ok is True


def test_workshop_round_trip_and_reusable_workflow(tmp_path):
    store, registry, service = setup(tmp_path)
    registry.set_enabled("workshop", True, WORKSHOP_MANIFEST.approvals)
    assert service.create_event(event()).ok is True
    stored = store._read_json(tmp_path / "module-workshop-data.json")["records"]["autumn-lab"]
    assert stored["workflow_steps"] == ["Prepare", "Run", "Review"]
    assert stored["participant_ids"] == ["person-1"]


def test_workshop_updates_feedback_without_replacing_other_fields(tmp_path):
    store, registry, service = setup(tmp_path)
    registry.set_enabled("workshop", True, WORKSHOP_MANIFEST.approvals)
    service.create_event(event())
    result = service.update_event("autumn-lab", {"feedback": ["Excellent pacing"]})
    assert result.ok is True
    assert result.value["materials"] == ["Clay", "Wire"]
    assert result.value["feedback"] == ["Excellent pacing"]


def test_workshop_rejects_incomplete_or_unknown_fields(tmp_path):
    _, registry, service = setup(tmp_path)
    registry.set_enabled("workshop", True, WORKSHOP_MANIFEST.approvals)
    with pytest.raises(InvalidState, match="workshop_required_field"):
        service.create_event(event(location=""))
    service.create_event(event())
    assert service.update_event("autumn-lab", {"credential": "secret"}).error == "workshop_field"
