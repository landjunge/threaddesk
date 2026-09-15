"""First built-in module: reusable workshop planning without core schema changes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from threaddesk.core.errors import InvalidState
from threaddesk.services.modules import ModuleManifest, ModuleRegistry, ModuleRunResult, ModuleRuntime


WORKSHOP_MANIFEST = ModuleManifest(
    id="workshop",
    name="Workshop",
    version="1.0.0",
    node_kinds=(
        "workshop.event",
        "workshop.audience",
        "workshop.material",
        "workshop.feedback",
        "workshop.workflow",
    ),
    relation_kinds=("workshop.participant", "workshop.task", "workshop.uses"),
    read_scopes=("knowledge:project", "knowledge:task", "knowledge:person"),
    write_actions=("workshop:create", "workshop:update"),
    approvals=("knowledge:link", "contact:link"),
    views=("workshop:list", "workshop:detail"),
    migrations=("workshop:v1",),
    uninstall="retain-data",
)


@dataclass(frozen=True)
class WorkshopEvent:
    id: str
    title: str
    audience: str
    course_level: str
    schedule: str
    location: str
    materials: tuple[str, ...] = ()
    participant_ids: tuple[str, ...] = ()
    task_ids: tuple[str, ...] = ()
    feedback: tuple[str, ...] = ()
    workflow_steps: tuple[str, ...] = ()

    def validate(self) -> None:
        required = (self.id, self.title, self.audience, self.course_level, self.schedule, self.location)
        if any(not value.strip() for value in required):
            raise InvalidState("workshop_required_field")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "type": "workshop.event",
            "id": self.id,
            "title": self.title,
            "audience": self.audience,
            "course_level": self.course_level,
            "schedule": self.schedule,
            "location": self.location,
            "materials": list(self.materials),
            "participant_ids": list(self.participant_ids),
            "task_ids": list(self.task_ids),
            "feedback": list(self.feedback),
            "workflow_steps": list(self.workflow_steps),
        }


class WorkshopService:
    def __init__(self, registry: ModuleRegistry, runtime: ModuleRuntime) -> None:
        self.registry = registry
        self.runtime = runtime

    def install(self) -> None:
        self.registry.install(WORKSHOP_MANIFEST)

    def create_event(self, event: WorkshopEvent) -> ModuleRunResult:
        event.validate()
        return self.runtime.run(
            "workshop",
            "workshop:create",
            lambda context: context.write_own_record("workshop:create", event.id, event.to_dict()),
        )

    def update_event(self, event_id: str, changes: Mapping[str, Any]) -> ModuleRunResult:
        def update(context):
            state = context.read_own_data()
            current = state["records"].get(event_id)
            if current is None:
                raise InvalidState("workshop_event_missing")
            allowed = {
                "title", "audience", "course_level", "schedule", "location", "materials",
                "participant_ids", "task_ids", "feedback", "workflow_steps",
            }
            if not set(changes).issubset(allowed):
                raise InvalidState("workshop_field")
            value = dict(current)
            value.update(changes)
            event = WorkshopEvent(
                id=event_id,
                title=str(value["title"]),
                audience=str(value["audience"]),
                course_level=str(value["course_level"]),
                schedule=str(value["schedule"]),
                location=str(value["location"]),
                materials=tuple(value.get("materials") or ()),
                participant_ids=tuple(value.get("participant_ids") or ()),
                task_ids=tuple(value.get("task_ids") or ()),
                feedback=tuple(value.get("feedback") or ()),
                workflow_steps=tuple(value.get("workflow_steps") or ()),
            )
            context.write_own_record("workshop:update", event_id, event.to_dict())
            return event.to_dict()

        return self.runtime.run("workshop", "workshop:update", update)
