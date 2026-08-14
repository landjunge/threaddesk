from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

STATUSES = ("idea", "active", "paused", "done", "archived")


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
