from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from threaddesk.core.errors import InvalidState

STATUSES = ("idea", "active", "paused", "done", "archived")


def _require_str(data: dict[str, Any], key: str, what: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise InvalidState(f"{what}: Feld '{key}' fehlt oder ist kein Text.")
    return value


def _opt_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    return value if isinstance(value, str) else ""


def _clean_status(value: Any) -> str:
    return value if isinstance(value, str) and value in STATUSES else "idea"


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
        data = data if isinstance(data, dict) else {}
        files = data.get("files")
        prompts = data.get("prompts")
        return cls(
            notes=_opt_str(data, "notes"),
            files=[p for p in files if isinstance(p, str)] if isinstance(files, list) else [],
            prompts=[p for p in prompts if isinstance(p, dict)] if isinstance(prompts, list) else [],
            agent_state=dict(data.get("agent_state") or {}) if isinstance(data.get("agent_state"), dict) else {},
            extra=dict(data.get("extra") or {}) if isinstance(data.get("extra"), dict) else {},
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
        if not isinstance(data, dict):
            raise InvalidState("Snapshot-Datei ist kein Objekt.")
        return cls(
            id=_require_str(data, "id", "Snapshot-Datei"),
            thread_id=_require_str(data, "thread_id", "Snapshot-Datei"),
            created_at=_opt_str(data, "created_at"),
            label=_opt_str(data, "label"),
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
        if not isinstance(data, dict):
            raise InvalidState("Thread-Datei ist kein Objekt.")
        snap = data.get("current_snapshot_id")
        return cls(
            id=_require_str(data, "id", "Thread-Datei"),
            title=_require_str(data, "title", "Thread-Datei"),
            description=_opt_str(data, "description"),
            status=_clean_status(data.get("status")),
            created_at=_opt_str(data, "created_at"),
            updated_at=_opt_str(data, "updated_at"),
            context=ThreadContext.from_dict(data.get("context")),
            current_snapshot_id=snap if isinstance(snap, str) and snap else None,
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
