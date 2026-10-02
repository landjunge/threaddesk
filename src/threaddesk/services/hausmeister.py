"""Local housekeeper. It appends its own notes and never touches originals."""

from __future__ import annotations

import json
from typing import Any

from threaddesk.core.errors import InvalidState, NotFound, SecretRejected
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
AGENT_TYPE = "local-assistant"
ACTOR_NAME = "Hausmeister"


class Hausmeister:
    def __init__(self, store: Any, transport: Any = None) -> None:
        self.store = store
        self.transport = transport
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

    def _stored_model(self) -> str:
        path = self.store.artifact_path(SETTINGS)
        if not path.exists():
            return ""
        value = json.loads(path.read_text(encoding="utf-8"))
        model = value.get("model") if isinstance(value, dict) else ""
        return model if isinstance(model, str) else ""


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
