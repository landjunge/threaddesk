"""Declarative command contract; handlers remain in their owning domains."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import Any, Callable


def workspace_identity(store):
    """Opaque binding to the selected local workspace, without exposing paths."""
    path = str(Path(store.workspace_path).resolve())
    return "ws-" + hashlib.sha256(path.encode()).hexdigest()[:32]


@dataclass(frozen=True)
class CommandSpec:
    id: str
    module: str
    description: str
    schema: dict
    handler: Callable[[Any, dict], Any] = field(repr=False, compare=False)
    effect: str = "read"
    scope: str = "workspace.read"
    revision_target: str | None = None
    native_contract: bool = False
    aliases: tuple[str, ...] = ()
    module_id: str | None = None
    backends: tuple[str, ...] = ("json", "sqlite")
    affects_index: bool = False
    allowed_transports: tuple[str, ...] = ("local", "cli", "http", "mcp")

    def public(self):
        return {"id": self.id, "module": self.module, "version": 1,
                "description": self.description, "input_schema": self.schema,
                "effect": self.effect, "scope": self.scope,
                "revision_target": self.revision_target,
                "operation_id_required": self.effect != "read",
                "aliases": list(self.aliases), "module_id": self.module_id,
                "affects_index": self.affects_index,
                "allowed_transports": list(self.allowed_transports),
                "backends": list(self.backends),
                "transports": {"http": "local_authorized" if "http" in self.allowed_transports else "not_allowed",
                               "cli": "local_authorized" if "cli" in self.allowed_transports else "not_allowed",
                               "mcp": "command_invoke" if "mcp" in self.allowed_transports else "not_allowed",
                               "kirabridge_native_write": "external_contract",
                               "kirabridge_visible_cli": "available_requires_actual_client_proof" if "cli" in self.allowed_transports else "not_allowed"}}
