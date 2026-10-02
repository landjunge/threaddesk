from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from threaddesk.core.errors import InvalidState

STATUSES = ("idea", "active", "paused", "done", "archived")
NODE_KINDS = (
    "project",
    "decision",
    "task",
    "result",
    "person",
    "agent",
    "document",
    "tool",
    "source",
    "workflow",
)
NODE_STATUSES = (
    "idea",
    "candidate",
    "proposed",
    "confirmed",
    "active",
    "ready",
    "assigned",
    "in_progress",
    "waiting",
    "blocked",
    "delivered",
    "review",
    "unverified",
    "verified",
    "accepted",
    "rejected",
    "rework",
    "superseded",
    "done",
    "paused",
    "archived",
)
NODE_TRANSITIONS = {
    "decision": {
        "proposed": ("confirmed", "rejected"),
        "confirmed": ("superseded",),
    },
    "task": {
        "idea": ("ready",),
        "ready": ("assigned",),
        "assigned": ("in_progress",),
        "in_progress": ("blocked", "delivered"),
        "blocked": ("in_progress",),
        "delivered": ("review",),
        "review": ("accepted", "rejected"),
        "rejected": ("in_progress",),
    },
    "result": {
        "delivered": ("unverified",),
        "unverified": ("verified", "rejected", "rework"),
        "verified": ("accepted", "rejected", "rework"),
        "rework": ("delivered",),
    },
}
RELATION_KINDS = (
    "contains",
    "depends_on",
    "assigned_to",
    "produced",
    "supports",
    "references",
    "blocks",
    "follows",
    "related_to",
)
VISIBILITIES = ("private", "shared", "public")
ACTOR_TYPES = (
    "human",
    "grok",
    "claude",
    "codex",
    "chatgpt",
    "gnom-hub-v1",
    "local-assistant",
    "system",
)
AGENT_TYPES = tuple(item for item in ACTOR_TYPES if item not in {"human", "system"})
ENTRY_TYPES = (
    "note",
    "task",
    "claimed",
    "progress",
    "result",
    "decision",
    "problem",
    "question",
    "system",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid4().hex[:12]


@dataclass
class ThreadContext:
    notes: str = ""
    files: list[str] = field(default_factory=list)
    prompts: list[dict[str, Any]] = field(default_factory=list)
    agent_state: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ThreadContext:
        data = data or {}
        return cls(
            notes=data.get("notes") or "",
            files=list(data.get("files") or []),
            prompts=list(data.get("prompts") or []),
            agent_state=dict(data.get("agent_state") or {}),
            extra=dict(data.get("extra") or {}),
        )


@dataclass
class Snapshot:
    id: str
    thread_id: str
    created_at: str
    label: str
    context: ThreadContext

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "created_at": self.created_at,
            "label": self.label,
            "context": self.context.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Snapshot:
        return cls(
            id=data["id"],
            thread_id=data["thread_id"],
            created_at=data["created_at"],
            label=data.get("label") or "",
            context=ThreadContext.from_dict(data.get("context")),
        )


@dataclass
class Thread:
    id: str
    title: str
    description: str = ""
    status: str = "idea"
    created_at: str = ""
    updated_at: str = ""
    context: ThreadContext = field(default_factory=ThreadContext)
    current_snapshot_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "context": self.context.to_dict(),
            "current_snapshot_id": self.current_snapshot_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Thread:
        return cls(
            id=data["id"],
            title=data["title"],
            description=data.get("description") or "",
            status=data.get("status") or "idea",
            created_at=data.get("created_at") or "",
            updated_at=data.get("updated_at") or "",
            context=ThreadContext.from_dict(data.get("context")),
            current_snapshot_id=data.get("current_snapshot_id"),
        )


@dataclass
class KnowledgeNode:
    id: str
    kind: str
    title: str
    status: str = "idea"
    details: str = ""
    created_at: str = ""
    updated_at: str = ""
    revision: int = 1
    source: str = "local"
    visibility: str = "private"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KnowledgeNode:
        return cls(
            id=data["id"],
            kind=data["kind"],
            title=data["title"],
            status=data.get("status") or "idea",
            details=data.get("details") or "",
            created_at=data.get("created_at") or "",
            updated_at=data.get("updated_at") or "",
            revision=int(data.get("revision") or 1),
            source=data.get("source") or "local",
            visibility=data.get("visibility") or "private",
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class Relation:
    id: str
    source_id: str
    target_id: str
    kind: str
    created_at: str = ""
    revision: int = 1
    source: str = "local"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Relation:
        return cls(
            id=data["id"],
            source_id=data["source_id"],
            target_id=data["target_id"],
            kind=data["kind"],
            created_at=data.get("created_at") or "",
            revision=int(data.get("revision") or 1),
            source=data.get("source") or "local",
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class GraphEvent:
    id: str
    name: str
    entity_id: str
    entity_type: str
    revision: int
    occurred_at: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphEvent:
        return cls(
            id=data["id"],
            name=data["name"],
            entity_id=data["entity_id"],
            entity_type=data["entity_type"],
            revision=int(data["revision"]),
            occurred_at=data["occurred_at"],
            payload=dict(data.get("payload") or {}),
        )


@dataclass
class WhiteboardEntry:
    """One append-only contribution on a thread whiteboard.

    Corrections are new entries. Nothing here is edited in place.
    """

    id: str
    thread_id: str
    actor: str
    actor_type: str
    created_at: str
    entry_type: str
    content: str
    ordinal: int = 0
    task_id: str | None = None
    handoff_id: str | None = None
    run_id: str | None = None
    external_key: str | None = None
    actor_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WhiteboardEntry:
        return cls(
            id=data["id"],
            thread_id=data["thread_id"],
            actor=data["actor"],
            actor_type=data["actor_type"],
            created_at=data["created_at"],
            entry_type=data.get("entry_type") or "note",
            content=data["content"],
            ordinal=int(data.get("ordinal") or 0),
            task_id=data.get("task_id"),
            handoff_id=data.get("handoff_id"),
            run_id=data.get("run_id"),
            external_key=data.get("external_key"),
            actor_id=data.get("actor_id") or None,
            metadata=dict(data.get("metadata") or {}),
        )

    def same_body(self, other: WhiteboardEntry) -> bool:
        """Identity fields may differ. The contribution itself must not."""
        return (
            self.thread_id == other.thread_id
            and self.actor == other.actor
            and self.actor_type == other.actor_type
            and self.entry_type == other.entry_type
            and self.content == other.content
            and self.task_id == other.task_id
            and self.handoff_id == other.handoff_id
            and self.run_id == other.run_id
            and self.external_key == other.external_key
            and self.actor_id == other.actor_id
            and self.metadata == other.metadata
        )


def plan_whiteboard_append(
    existing: list[WhiteboardEntry], entry: WhiteboardEntry
) -> tuple[WhiteboardEntry, bool]:
    """Decide whether to keep an existing entry or append this one.

    Same external key or same id with the same body is a duplicate.
    A different body never replaces the stored entry.
    """
    if entry.external_key:
        for current in existing:
            if current.external_key == entry.external_key:
                if not current.same_body(entry):
                    raise InvalidState("whiteboard_conflict")
                return current, True
    for current in existing:
        if current.id == entry.id:
            if not current.same_body(entry):
                raise InvalidState("whiteboard_conflict")
            return current, True
    if entry.ordinal < 1:
        entry.ordinal = 1 + max((item.ordinal for item in existing), default=0)
    return entry, False


def new_thread(title: str, description: str = "") -> Thread:
    ts = now_iso()
    return Thread(
        id=new_id(),
        title=title.strip(),
        description=description.strip(),
        status="idea",
        created_at=ts,
        updated_at=ts,
    )
