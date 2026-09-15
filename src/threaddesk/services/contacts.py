"""Local contact model with explicit private/export boundaries."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any, Mapping

from threaddesk.core.errors import InvalidState, NotFound
from threaddesk.core.secrets import reject_secrets
from threaddesk.storage.protocols import ArtifactStore


@dataclass(frozen=True)
class Contact:
    id: str
    name: str
    kind: str = "person"
    roles: tuple[str, ...] = ()
    channels: Mapping[str, str] = field(default_factory=dict)
    project_ids: tuple[str, ...] = ()
    task_ids: tuple[str, ...] = ()
    marked: bool = False
    private: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.id.strip() or not self.name.strip() or self.kind not in {"person", "organization"}:
            raise InvalidState("contact_identity")
        reject_secrets(json.dumps(asdict(self), ensure_ascii=False))

    def to_dict(self, include_private: bool = True) -> dict[str, Any]:
        self.validate()
        value = asdict(self)
        if not include_private:
            value.pop("private", None)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Contact":
        contact = cls(
            id=str(value.get("id", "")),
            name=str(value.get("name", "")),
            kind=str(value.get("kind", "person")),
            roles=tuple(value.get("roles") or ()),
            channels=dict(value.get("channels") or {}),
            project_ids=tuple(value.get("project_ids") or ()),
            task_ids=tuple(value.get("task_ids") or ()),
            marked=bool(value.get("marked", False)),
            private=dict(value.get("private") or {}),
        )
        contact.validate()
        return contact


class ContactBook:
    ARTIFACT = "contacts.json"

    def __init__(self, store: ArtifactStore) -> None:
        self.store = store

    def _load(self) -> dict[str, Any]:
        path = self.store.artifact_path(self.ARTIFACT)
        if not path.exists():
            return {"schema_version": 1, "contacts": {}}
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema_version") != 1 or not isinstance(value.get("contacts"), dict):
            raise InvalidState("contacts_state")
        return value

    def save(self, contact: Contact) -> Contact:
        contact.validate()
        state = self._load()
        state["contacts"][contact.id] = contact.to_dict()
        self.store.write_json_artifact(self.ARTIFACT, state)
        return contact

    def get(self, contact_id: str) -> Contact:
        value = self._load()["contacts"].get(contact_id)
        if value is None:
            raise NotFound(f"Kontakt nicht gefunden: {contact_id}")
        return Contact.from_dict(value)

    def list(self) -> list[Contact]:
        return sorted((Contact.from_dict(item) for item in self._load()["contacts"].values()), key=lambda c: c.id)

    def find_channel(self, channel: str, address: str) -> Contact | None:
        address = address.strip().casefold()
        return next((c for c in self.list() if c.channels.get(channel, "").strip().casefold() == address), None)

    def export(self, contact_ids: tuple[str, ...] | None = None) -> dict[str, Any]:
        selected = self.list()
        if contact_ids is not None:
            wanted = set(contact_ids)
            selected = [contact for contact in selected if contact.id in wanted]
        return {"schema_version": 1, "contacts": [contact.to_dict(include_private=False) for contact in selected]}
