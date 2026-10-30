"""One deterministic command catalogue, including module availability."""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache

from threaddesk.core.errors import ManagementError
from threaddesk.services.commands.validation import encode
from jsonschema import Draft202012Validator


@lru_cache(maxsize=512)
def _check_schema(encoded_schema):
    # Cache only immutable schema bytes. A changed schema has a different key;
    # live module availability, rights and records are never cached here.
    Draft202012Validator.check_schema(json.loads(encoded_schema))


class CommandRegistry:
    def __init__(self, store, specs=None):
        self._dynamic_modules = specs is None
        if specs is None:
            from threaddesk.services.commands.legacy import specifications as legacy
            from threaddesk.services.commands.domains import specifications as domains
            specs = [*legacy(), *domains()]
        self.store, self.specs, self.aliases = store, {}, {}
        self._module_command_ids = set()
        for spec in specs:
            if spec.id in self.specs or spec.id in self.aliases:
                raise ValueError("Duplicate command: " + spec.id)
            _check_schema(encode(spec.schema))
            self.specs[spec.id] = spec
            for alias in spec.aliases:
                if alias in self.specs or alias in self.aliases:
                    raise ValueError("Duplicate command alias: " + alias)
                self.aliases[alias] = spec.id

    def get(self, identity):
        self._refresh_modules()
        identity = self.aliases.get(identity, identity)
        try:
            return self.specs[identity]
        except KeyError as exc:
            raise ManagementError("command_not_found", "Command is not registered") from exc

    def availability(self, spec, scopes, transport="local"):
        if transport not in spec.allowed_transports:
            return "local_owner_cli_required"
        if scopes is not None and spec.scope not in scopes:
            return "permission_required"
        from threaddesk.storage.sqlite_store import SQLiteStore
        backend = "sqlite" if isinstance(self.store, SQLiteStore) else "json"
        if backend not in spec.backends:
            return "unsupported_backend"
        if spec.module_id:
            if spec.id.startswith("module." + spec.module_id + "."):
                from threaddesk.services.commands.module_commands import availability
                return availability(self.store, spec)
            from threaddesk.services.modules import ModuleRegistry
            try:
                module = ModuleRegistry(self.store).get(spec.module_id)
                if not module.enabled:
                    return "disabled"
                if not set(module.manifest.approvals) <= set(module.granted_approvals):
                    return "permission_required"
            except Exception as exc:
                from threaddesk.core.errors import ThreadDeskError
                if not isinstance(exc, ThreadDeskError):
                    raise
                return "unavailable"
        return "available"

    def records(self, scopes=None, transport="local"):
        self._refresh_modules()
        return [{**spec.public(), "availability": self.availability(spec, scopes, transport)}
                for spec in sorted(self.specs.values(), key=lambda value: value.id)]

    def revision(self, scopes=None, transport="local"):
        return hashlib.sha256(encode(self.records(scopes, transport)).encode()).hexdigest()

    def _refresh_modules(self):
        if not self._dynamic_modules:
            return
        from threaddesk.services.commands.module_commands import specifications
        for identity in self._module_command_ids:
            self.specs.pop(identity, None)
        self._module_command_ids = set()
        for spec in specifications(self.store):
            if spec.id in self.specs or spec.id in self.aliases:
                raise ManagementError("command_conflict", "Module command collides with an existing registration")
            self.specs[spec.id] = spec
            self._module_command_ids.add(spec.id)
