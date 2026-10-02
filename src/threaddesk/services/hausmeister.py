"""Local housekeeper. It appends its own notes and never touches originals."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import time
from typing import Any, Callable

from threaddesk.core.errors import InvalidState, NotFound, SecretRejected
from threaddesk.core.models import new_id, now_iso
from threaddesk.core.secrets import reject_secrets
from threaddesk.services.actors import ActorRegistry
from threaddesk.services.modules import ModuleManifest, ModuleRegistry, ModuleRuntime
from threaddesk.services.ollama_local import OllamaError, complete, list_models

MANIFEST = ModuleManifest(
    id="local-assistant",
    name="Hausmeister",
    version="1.0.0",
    read_scopes=("thread:read", "whiteboard:read"),
    write_actions=("whiteboard:append",),
    connectors=("ollama:127.0.0.1",),
    views=("hausmeister:desk",),
    uninstall="retain-data",
)
SETTINGS = "hausmeister.json"
QUEUE = "hausmeister-queue.json"
ACTIVITY = "hausmeister-activity.json"
AGENT_TYPE = "local-assistant"
ACTOR_NAME = "Hausmeister"
IDLE_AFTER_SECONDS = 600
LOAD_LIMIT = 1.5
ACTIVITY_GAP_SECONDS = 15
SURFACE_KINDS = frozenset({"pointer", "click", "key", "scroll", "touch"})
OPEN = frozenset({"waiting", "paused", "running"})


@dataclass(frozen=True)
class IdleSnapshot:
    idle_seconds: float
    user_active: bool
    load: float
    heavy_job: bool = False
    desk_busy: bool = False


def machine_is_quiet(snapshot: IdleSnapshot) -> bool:
    """True only after a long quiet stretch and a light machine."""
    return (
        snapshot.idle_seconds >= IDLE_AFTER_SECONDS
        and not snapshot.user_active
        and snapshot.load < LOAD_LIMIT
        and not snapshot.heavy_job
        and not snapshot.desk_busy
    )


def activity_is_due(previous: float | None, now: float, gap: float = ACTIVITY_GAP_SECONDS) -> bool:
    """True when the last accepted ping is old enough for another one."""
    if previous is None:
        return True
    return now - previous >= gap


def note_activity(store: Any, now: float | None = None, kind: str = "page") -> bool:
    """Remember that someone used the desk.

    Live surface pings are dropped inside the gap. An explicit timestamp
    is a test clock and is stored as given, so tests never wait.
    """
    if kind != "page" and kind not in SURFACE_KINDS:
        raise InvalidState("activity_kind")
    stamp = time.time() if now is None else float(now)
    current = _read_activity(store)
    previous = current.get("seen")
    previous_seen = float(previous) if isinstance(previous, (int, float)) else None
    if now is None and kind != "page" and not activity_is_due(previous_seen, stamp):
        return False
    store.write_json_artifact(ACTIVITY, {"seen": stamp, "kind": kind})
    return True


def live_snapshot(store: Any) -> IdleSnapshot:
    value = _read_activity(store)
    seen = time.time()
    if isinstance(value.get("seen"), (int, float)):
        seen = float(value["seen"])
    idle = max(0.0, time.time() - seen)
    try:
        load = float(os.getloadavg()[0])
    except (AttributeError, OSError):
        load = 0.0
    return IdleSnapshot(idle_seconds=idle, user_active=idle < IDLE_AFTER_SECONDS, load=load)


class Hausmeister:
    def __init__(self, store: Any, transport: Any = None, snapshot_fn: Callable[[], IdleSnapshot] | None = None) -> None:
        self.store = store
        self.transport = transport
        self.snapshot_fn = snapshot_fn
        self.registry = ModuleRegistry(store)
        self.runtime = ModuleRuntime(store, self.registry)

    def install(self) -> None:
        try:
            self.registry.get(MANIFEST.id)
        except NotFound:
            self.registry.install(MANIFEST)

    def status(self) -> dict[str, Any]:
        self.install()
        installed = self.registry.get(MANIFEST.id)
        models: list[str] = []
        ollama_ok = False
        try:
            models = list_models(self.transport, timeout=0.4)
            ollama_ok = True
        except OllamaError:
            ollama_ok = False
        actor = _find_agent(ActorRegistry(self.store))
        return {
            "enabled": installed.enabled,
            "model": self._stored_model(),
            "models": models,
            "ollama_ok": ollama_ok,
            "actor_id": actor["id"] if actor else "",
            "agent_type": AGENT_TYPE if actor else "",
            "kind": actor["kind"] if actor else "",
            "phase": self._phase(installed.enabled, ollama_ok, self._stored_model()),
        }

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        self.install()
        if enabled:
            self.ensure_actor()
        self.registry.set_enabled(MANIFEST.id, enabled)
        return self.status()

    def set_model(self, model: str) -> dict[str, Any]:
        self.install()
        model = _model_name(model)
        try:
            available = list_models(self.transport, timeout=0.4)
        except OllamaError as exc:
            raise OllamaError("ollama_unavailable") from exc
        if model not in available:
            raise OllamaError("ollama_model_missing")
        self.store.write_json_artifact(SETTINGS, {"version": 1, "model": model})
        return self.status()

    def ensure_actor(self) -> dict[str, Any]:
        registry = ActorRegistry(self.store)
        found = _find_agent(registry)
        if found is not None:
            return found
        humans = [item for item in registry.list() if item["kind"] == "human"]
        person = humans[0] if humans else registry.add_human("Lokal", "sea")
        return registry.add_agent(ACTOR_NAME, person["id"], AGENT_TYPE, provider="ollama")

    def run(self, thread_id: str, order: str) -> dict[str, Any]:
        """Read, ask local Ollama, then append the housekeeper's own notes."""
        self.install()
        order = _order(order)
        installed = self.registry.get(MANIFEST.id)
        if not installed.enabled:
            return {"ok": False, "error": "module_disabled", "entries": []}
        model = self._stored_model()
        if not model:
            return {"ok": False, "error": "ollama_model_missing", "entries": []}
        try:
            available = list_models(self.transport, timeout=0.4)
        except OllamaError:
            return {"ok": False, "error": "ollama_unavailable", "entries": []}
        if model not in available:
            return {"ok": False, "error": "ollama_model_missing", "entries": []}
        actor = self.ensure_actor()
        if actor["kind"] != "agent" or actor["agent_type"] != AGENT_TYPE:
            return {"ok": False, "error": "actor_kind_mismatch", "entries": []}
        result = self.runtime.run(
            MANIFEST.id,
            "whiteboard:append",
            lambda context: self._work(context, thread_id, order, model, actor),
        )
        if not result.ok:
            return {"ok": False, "error": _safe_error(result.error), "entries": []}
        return {"ok": True, "error": "", "entries": result.value["entries"], "actor_id": actor["id"]}

    def enqueue(self, thread_id: str, order: str, task_id: str | None = None) -> dict[str, Any]:
        self.install()
        if not self.registry.get(MANIFEST.id).enabled:
            return {"ok": False, "error": "module_disabled", "job": None}
        order = _order(order)
        existing = self._open_match(thread_id, order)
        if existing is not None:
            return {"ok": True, "error": "", "job": existing, "duplicate": True}
        job = _job(thread_id, order, task_id)
        jobs = self.jobs()
        jobs.append(job)
        self._write_jobs(jobs)
        return {"ok": True, "error": "", "job": job, "duplicate": False}

    def run_now(self, thread_id: str, order: str, task_id: str | None = None) -> dict[str, Any]:
        """Start at once. Idle time is not required."""
        self.install()
        if not self.registry.get(MANIFEST.id).enabled:
            return {"ok": False, "error": "module_disabled", "entries": []}
        order = _order(order)
        job = self._open_match(thread_id, order) or _job(thread_id, order, task_id)
        if job not in self.jobs():
            jobs = self.jobs()
            jobs.append(job)
            self._write_jobs(jobs)
        self._mark(job["id"], "running")
        result = self.run(thread_id, order)
        self._mark(job["id"], "done" if result["ok"] else "error", result.get("error", ""))
        result["job_id"] = job["id"]
        return result

    def tick(self, snapshot: IdleSnapshot) -> dict[str, Any]:
        """Start the next open job only while the machine is quiet."""
        self.install()
        if not self.registry.get(MANIFEST.id).enabled:
            return {"ok": False, "error": "module_disabled", "started": False, "phase": "off"}
        job = self._next_open()
        if job is None:
            return {"ok": True, "error": "", "started": False, "phase": "waiting_for_order"}
        if not machine_is_quiet(snapshot):
            if job["status"] == "running":
                self._mark(job["id"], "paused")
            phase = "paused" if job["status"] in {"running", "paused"} else "waiting_for_quiet"
            return {"ok": True, "error": "", "started": False, "phase": phase}
        if not self._stored_model():
            return {"ok": False, "error": "ollama_model_missing", "started": False, "phase": "no_model"}
        self._mark(job["id"], "running")
        current = self.snapshot_fn() if self.snapshot_fn else snapshot
        if not machine_is_quiet(current):
            self._mark(job["id"], "paused")
            return {"ok": True, "error": "", "started": False, "phase": "paused"}
        result = self.run(job["thread_id"], job["order"])
        self._mark(job["id"], "done" if result["ok"] else "error", result.get("error", ""))
        return {
            "ok": result["ok"],
            "error": result.get("error", ""),
            "started": bool(result["ok"]),
            "phase": "waiting_for_order" if result["ok"] else "error",
            "job_id": job["id"],
            "entries": result.get("entries", []),
        }

    def jobs(self) -> list[dict[str, Any]]:
        path = self.store.artifact_path(QUEUE)
        if not path.exists():
            return []
        value = json.loads(path.read_text(encoding="utf-8"))
        jobs = value.get("jobs") if isinstance(value, dict) else None
        return [dict(item) for item in jobs] if isinstance(jobs, list) else []

    def _work(self, context: Any, thread_id: str, order: str, model: str, actor: dict[str, Any]) -> dict[str, Any]:
        thread = context.read_thread(thread_id)
        board = context.read_whiteboard(thread_id)
        reply = complete(model, _prompt(thread, board, order), self.transport, timeout=90.0)
        pieces = _pieces(reply, len(board))
        if not pieces:
            raise InvalidState("hausmeister_empty")
        task_id = _task_id(board)
        written = []
        for piece in pieces:
            item = context.append_whiteboard(
                thread_id,
                actor=ACTOR_NAME,
                actor_type=AGENT_TYPE,
                entry_type="note",
                content=piece["content"],
                actor_id=actor["id"],
                task_id=task_id,
                metadata={"role": piece["role"], "source": AGENT_TYPE},
            )
            written.append(item["entry"])
        return {"entries": written}

    def _phase(self, enabled: bool, ollama_ok: bool, model: str) -> str:
        if not enabled:
            return "off"
        if not ollama_ok:
            return "ollama_down"
        if not model:
            return "no_model"
        jobs = self.jobs()
        if any(item["status"] == "running" for item in jobs):
            return "working"
        if any(item["status"] == "paused" for item in jobs):
            return "paused"
        if any(item["status"] == "waiting" for item in jobs):
            return "waiting_for_quiet"
        return "waiting_for_order"

    def _next_open(self) -> dict[str, Any] | None:
        open_jobs = [item for item in self.jobs() if item.get("status") in {"waiting", "paused"}]
        open_jobs.sort(key=lambda item: (item.get("created_at", ""), item.get("id", "")))
        return open_jobs[0] if open_jobs else None

    def _open_match(self, thread_id: str, order: str) -> dict[str, Any] | None:
        for item in self.jobs():
            if item.get("thread_id") == thread_id and item.get("order") == order and item.get("status") in OPEN:
                return item
        return None

    def _mark(self, job_id: str, status: str, error: str = "") -> None:
        jobs = self.jobs()
        for item in jobs:
            if item["id"] != job_id:
                continue
            item["status"] = status
            item["updated_at"] = now_iso()
            item["error"] = error
        self._write_jobs(jobs)

    def _write_jobs(self, jobs: list[dict[str, Any]]) -> None:
        self.store.write_json_artifact(QUEUE, {"version": 1, "jobs": jobs})

    def _stored_model(self) -> str:
        path = self.store.artifact_path(SETTINGS)
        if not path.exists():
            return ""
        value = json.loads(path.read_text(encoding="utf-8"))
        model = value.get("model") if isinstance(value, dict) else ""
        return model if isinstance(model, str) else ""


def _job(thread_id: str, order: str, task_id: str | None) -> dict[str, Any]:
    stamp = now_iso()
    return {
        "id": new_id(),
        "thread_id": thread_id,
        "order": order,
        "status": "waiting",
        "created_at": stamp,
        "updated_at": stamp,
        "task_id": task_id or "",
        "error": "",
    }


def _read_activity(store: Any) -> dict[str, Any]:
    path = store.artifact_path(ACTIVITY)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _find_agent(registry: ActorRegistry) -> dict[str, Any] | None:
    for actor in registry.list():
        if actor.get("kind") == "agent" and actor.get("agent_type") == AGENT_TYPE:
            return actor
    return None


def _prompt(thread: dict[str, Any], board: list[dict[str, Any]], order: str) -> str:
    lines = [
        "Du bist der lokale Hausmeister. Antworte nur mit JSON "
        '{"summary":"...","suggestions":["..."]}.',
        "Fasse den Thread zusammen und nenne höchstens drei nächste Schritte.",
        "Lösche nichts und fordere keine Schlüssel an.",
        f"Auftrag: {order}",
        f"Titel: {thread.get('title', '')}",
        f"Notizen: {thread.get('notes', '')}",
    ]
    for entry in board[-12:]:
        lines.append(f"- {entry.get('actor', '')}: {entry.get('content', '')}")
    return "\n".join(lines)


def _pieces(reply: str, earlier: int) -> list[dict[str, str]]:
    summary, suggestions = _parsed(reply)
    pieces = []
    if summary:
        pieces.append({"role": "summary", "content": summary})
    for suggestion in suggestions[:3]:
        pieces.append({"role": "suggestion", "content": suggestion})
    pieces.append({
        "role": "note",
        "content": f"Auftrag abgeschlossen. Vorherige Beiträge: {earlier}.",
    })
    safe = []
    for piece in pieces:
        try:
            safe.append({"role": piece["role"], "content": reject_secrets(piece["content"])})
        except SecretRejected:
            continue
    return safe


def _parsed(reply: str) -> tuple[str, list[str]]:
    start = reply.find("{")
    end = reply.rfind("}")
    if start < 0 or end <= start:
        text = reply.strip()
        return (text[:800], []) if text else ("", [])
    try:
        value = json.loads(reply[start:end + 1])
    except json.JSONDecodeError:
        return (reply.strip()[:800], [])
    summary = value.get("summary") if isinstance(value, dict) else ""
    raw = value.get("suggestions") if isinstance(value, dict) else []
    suggestions = [item.strip() for item in raw if isinstance(item, str) and item.strip()]
    if not isinstance(summary, str):
        summary = ""
    return (summary.strip()[:800], [item[:800] for item in suggestions])


def _task_id(board: list[dict[str, Any]]) -> str | None:
    for entry in reversed(board):
        task_id = entry.get("task_id")
        if isinstance(task_id, str) and task_id.strip():
            return task_id
    return None


def _order(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidState("hausmeister_order")
    value = reject_secrets(value).strip()
    if not value or len(value) > 500:
        raise InvalidState("hausmeister_order")
    return value


def _model_name(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidState("ollama_model_missing")
    value = reject_secrets(value).strip()
    if not value or len(value) > 80 or any(char in value for char in "\n\r\x00/\\"):
        raise InvalidState("ollama_model_missing")
    return value


def _safe_error(value: str | None) -> str:
    if value in {
        "module_disabled",
        "ollama_unavailable",
        "ollama_model_missing",
        "ollama_forbidden",
        "hausmeister_empty",
        "actor_kind_mismatch",
    }:
        return value
    if value and "API-Keys" in value:
        return "hausmeister_rejected"
    return "hausmeister_failed"
