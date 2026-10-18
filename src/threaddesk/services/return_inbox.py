"""Local review inbox for untrusted worker returns."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from threaddesk.core.errors import InvalidState, NotFound
from threaddesk.core.models import now_iso
from threaddesk.core.secrets import reject_secrets
from threaddesk.services.return_contract import validate

CHOICES = ("accepted", "rejected", "rework")


class ReturnInbox:
    def __init__(self, store: Any, service=None) -> None:
        self.store = store
        self.service = service
        self.path = store.artifact_path("return-inbox.json")

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "items": []}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("version") != 1 or not isinstance(value.get("items"), list):
            raise InvalidState("return_inbox")
        return value

    def list(self) -> list[dict[str, Any]]:
        return list(self._read()["items"])

    def receive(self, value: Mapping[str, Any], *, strict_binding: bool = False) -> dict[str, Any]:
        with self.store.transaction():
            return self._receive(value, strict_binding=strict_binding)

    def _receive(self, value: Mapping[str, Any], *, strict_binding: bool = False) -> dict[str, Any]:
        payload = validate(value)
        reject_secrets(json.dumps(payload, ensure_ascii=False))
        state = self._read()
        for item in state["items"]:
            if item["return"]["return_id"] == payload["return_id"]:
                if item["return"] != payload:
                    raise InvalidState("return_id_conflict")
                if strict_binding and item.get("binding_status") != "issued_bound":
                    raise InvalidState("return_not_strictly_bound")
                return {**item, "duplicate": True}
        provenance = {"binding_status": "legacy_unbound", "source_verification": "unknown"}
        if self.service is not None:
            from threaddesk.services.issued_handoffs import IssuedHandoffs
            provenance = IssuedHandoffs(self.service).check_return(payload, strict=strict_binding)
        elif strict_binding:
            raise InvalidState("return_binding_service_required")
        revisions = [
            item["return"]["handoff_revision"] for item in state["items"]
            if item["return"]["handoff_id"] == payload["handoff_id"]
        ]
        if revisions and payload["handoff_revision"] < max(revisions):
            raise InvalidState("return_stale")
        item = {"return": payload, "decision": None, "received_at": now_iso(), **provenance}
        state["items"].append(item)
        self.store.write_json_artifact("return-inbox.json", state)
        return {**item, "duplicate": False}

    def decide(self, return_id: str, choice: str, note: str = "") -> dict[str, Any]:
        with self.store.transaction():
            return self._decide(return_id, choice, note)

    def _decide(self, return_id: str, choice: str, note: str = "") -> dict[str, Any]:
        choice = choice.strip().lower()
        if choice not in CHOICES:
            raise InvalidState(f"return_decision: {', '.join(CHOICES)}")
        note = reject_secrets(note).strip()
        state = self._read()
        for item in state["items"]:
            if item["return"]["return_id"] != return_id:
                continue
            existing = item["decision"]
            if existing:
                if existing["choice"] == choice and existing["note"] == note:
                    return item
                raise InvalidState("return_already_decided")
            item["decision"] = {"choice": choice, "note": note, "decided_at": now_iso()}
            self.store.write_json_artifact("return-inbox.json", state)
            return item
        raise NotFound(f"Rückgabe nicht gefunden: {return_id}")
