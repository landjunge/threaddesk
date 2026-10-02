"""Local people and agents. The id stays. The label can change.

No secrets, no team rooms, and no cryptographic keys live here.
"""

from __future__ import annotations

import json
from typing import Any

from threaddesk.core.errors import InvalidState, NotFound
from threaddesk.core.models import AGENT_TYPES, new_id
from threaddesk.core.secrets import reject_secrets

COLOR_TOKENS = ("ink", "moss", "clay", "sea", "plum", "sand")
HUMAN = "human"
AGENT = "agent"
ARTIFACT = "actors.json"


class ActorRegistry:
    def __init__(self, store: Any) -> None:
        self.store = store
        self.path = store.artifact_path(ARTIFACT)

    def instance_id(self) -> str:
        state = self._read()
        if not state.get("instance_id"):
            state["instance_id"] = new_id()
            self._write(state)
        return str(state["instance_id"])

    def list(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._read()["actors"]]

    def get(self, actor_id: str) -> dict[str, Any]:
        for actor in self.list():
            if actor["id"] == actor_id:
                return actor
        raise NotFound(f"Akteur nicht gefunden: {actor_id}")

    def add_human(self, name: str, color_token: str) -> dict[str, Any]:
        actor = {
            "id": new_id(),
            "kind": HUMAN,
            "name": _label(name),
            "color_token": _color(color_token),
            "person_id": None,
            "agent_type": None,
            "model": None,
            "provider": None,
        }
        state = self._read()
        state["actors"].append(actor)
        self._write(state)
        return actor

    def add_agent(
        self,
        name: str,
        person_id: str,
        agent_type: str,
        model: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        agent_type = _agent_type(agent_type)
        person = self._assigned_person(person_id)
        actor = {
            "id": new_id(),
            "kind": AGENT,
            "name": _label(name),
            "color_token": None,
            "person_id": person["id"],
            "agent_type": agent_type,
            "model": _optional(model),
            "provider": _optional(provider),
        }
        state = self._read()
        state["actors"].append(actor)
        self._write(state)
        return actor

    def rename(self, actor_id: str, name: str) -> dict[str, Any]:
        return self._update(actor_id, name=_label(name))

    def recolor(self, actor_id: str, color_token: str) -> dict[str, Any]:
        actor = self.get(actor_id)
        if actor["kind"] != HUMAN:
            raise InvalidState("actor_color")
        return self._update(actor_id, color_token=_color(color_token))

    def appearance(self, actor_id: str) -> dict[str, Any]:
        actor = self.get(actor_id)
        if actor["kind"] == AGENT:
            person = self._assigned_person(actor.get("person_id"))
            return {
                "actor_id": actor["id"],
                "kind": AGENT,
                "name": actor["name"],
                "color_token": person["color_token"],
                "ai": True,
                "agent_type": actor["agent_type"],
                "person_id": person["id"],
            }
        if actor["kind"] != HUMAN:
            raise InvalidState("actor_unknown")
        return {
            "actor_id": actor["id"],
            "kind": HUMAN,
            "name": actor["name"],
            "color_token": actor["color_token"],
            "ai": False,
            "agent_type": None,
            "person_id": None,
        }

    def marks(self) -> dict[str, dict[str, Any]]:
        found = {}
        for actor in self.list():
            try:
                found[actor["id"]] = self.appearance(actor["id"])
            except InvalidState:
                continue
        return found

    def _assigned_person(self, person_id: str | None) -> dict[str, Any]:
        if not person_id:
            raise InvalidState("actor_unassigned")
        try:
            person = self.get(person_id)
        except NotFound as exc:
            raise InvalidState("actor_unassigned") from exc
        if person["kind"] != HUMAN:
            raise InvalidState("actor_unassigned")
        return person

    def _update(self, actor_id: str, **changes: Any) -> dict[str, Any]:
        state = self._read()
        for actor in state["actors"]:
            if actor["id"] != actor_id:
                continue
            actor.update(changes)
            actor["id"] = actor_id
            self._write(state)
            return dict(actor)
        raise NotFound(f"Akteur nicht gefunden: {actor_id}")

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "instance_id": None, "actors": []}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("version") != 1 or not isinstance(value.get("actors"), list):
            raise InvalidState("actors")
        value.setdefault("instance_id", None)
        return value

    def _write(self, state: dict[str, Any]) -> None:
        if not state.get("instance_id"):
            state["instance_id"] = new_id()
        self.store.write_json_artifact(ARTIFACT, state)


def require_entry_actor(store: Any, actor_id: str | None, actor_type: str) -> str | None:
    """Bind an entry to a real actor. Never recast an agent as human or system."""
    if actor_id is None or actor_id == "":
        return None
    if not isinstance(actor_id, str):
        raise InvalidState("whiteboard_actor_id")
    registry = ActorRegistry(store)
    try:
        actor = registry.get(actor_id)
    except NotFound as exc:
        raise InvalidState("actor_unknown") from exc
    if actor["kind"] == AGENT:
        registry._assigned_person(actor.get("person_id"))
        if actor_type != actor.get("agent_type"):
            raise InvalidState("actor_kind_mismatch")
        return actor["id"]
    if actor["kind"] == HUMAN:
        if actor_type != HUMAN:
            raise InvalidState("actor_kind_mismatch")
        return actor["id"]
    raise InvalidState("actor_unknown")


def _label(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidState("actor_name")
    value = reject_secrets(value).strip()
    if not value or len(value) > 80:
        raise InvalidState("actor_name")
    return value


def _optional(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return _label(value)


def _color(value: str) -> str:
    if value not in COLOR_TOKENS:
        raise InvalidState("actor_color")
    return value


def _agent_type(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidState("actor_agent_type")
    value = value.strip().lower()
    if value not in AGENT_TYPES:
        raise InvalidState("actor_agent_type")
    return value
