"""Versioned, least-privilege module manifests and local lifecycle state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Callable, Mapping

from threaddesk.core.errors import InvalidState, NotFound
from threaddesk.storage.protocols import ArtifactStore


MANIFEST_VERSION = 1
MODULE_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
CAPABILITIES = frozenset({"read", "write", "connector", "view", "migration"})


@dataclass(frozen=True)
class ModuleManifest:
    id: str
    name: str
    version: str
    node_kinds: tuple[str, ...] = ()
    relation_kinds: tuple[str, ...] = ()
    read_scopes: tuple[str, ...] = ()
    write_actions: tuple[str, ...] = ()
    connectors: tuple[str, ...] = ()
    approvals: tuple[str, ...] = ()
    views: tuple[str, ...] = ()
    migrations: tuple[str, ...] = ()
    uninstall: str = "retain-data"
    manifest_version: int = MANIFEST_VERSION

    def validate(self) -> None:
        if self.manifest_version != MANIFEST_VERSION:
            raise InvalidState("module_manifest_version")
        if not MODULE_ID.fullmatch(self.id):
            raise InvalidState("module_id")
        if not self.name.strip() or not self.version.strip():
            raise InvalidState("module_identity")
        if self.uninstall not in {"retain-data", "export-and-remove"}:
            raise InvalidState("module_uninstall_policy")
        for values in (
            self.node_kinds,
            self.relation_kinds,
            self.read_scopes,
            self.write_actions,
            self.connectors,
            self.approvals,
            self.views,
            self.migrations,
        ):
            if len(values) != len(set(values)) or any(not item.strip() for item in values):
                raise InvalidState("module_manifest_values")

    @property
    def capabilities(self) -> tuple[str, ...]:
        values = set()
        if self.read_scopes:
            values.add("read")
        if self.write_actions:
            values.add("write")
        if self.connectors:
            values.add("connector")
        if self.views:
            values.add("view")
        if self.migrations:
            values.add("migration")
        return tuple(sorted(values))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModuleManifest":
        manifest = cls(
            id=str(value.get("id", "")),
            name=str(value.get("name", "")),
            version=str(value.get("version", "")),
            node_kinds=tuple(value.get("node_kinds") or ()),
            relation_kinds=tuple(value.get("relation_kinds") or ()),
            read_scopes=tuple(value.get("read_scopes") or ()),
            write_actions=tuple(value.get("write_actions") or ()),
            connectors=tuple(value.get("connectors") or ()),
            approvals=tuple(value.get("approvals") or ()),
            views=tuple(value.get("views") or ()),
            migrations=tuple(value.get("migrations") or ()),
            uninstall=str(value.get("uninstall", "retain-data")),
            manifest_version=int(value.get("manifest_version", 0)),
        )
        manifest.validate()
        return manifest


@dataclass
class InstalledModule:
    manifest: ModuleManifest
    enabled: bool = False
    granted_approvals: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_dict(),
            "enabled": self.enabled,
            "granted_approvals": list(self.granted_approvals),
        }


class ModuleRegistry:
    """Persists declarations and grants; installation never enables a module."""

    ARTIFACT = "modules.json"

    def __init__(self, store: ArtifactStore) -> None:
        self.store = store

    def _load(self) -> dict[str, Any]:
        path = self.store.artifact_path(self.ARTIFACT)
        if not path.exists():
            return {"schema_version": 1, "modules": {}}
        import json

        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema_version") != 1 or not isinstance(value.get("modules"), dict):
            raise InvalidState("module_registry")
        return value

    def _save(self, state: Mapping[str, Any]) -> None:
        self.store.write_json_artifact(self.ARTIFACT, state)

    def list(self) -> list[InstalledModule]:
        result = []
        for value in self._load()["modules"].values():
            result.append(
                InstalledModule(
                    manifest=ModuleManifest.from_dict(value["manifest"]),
                    enabled=bool(value.get("enabled", False)),
                    granted_approvals=tuple(value.get("granted_approvals") or ()),
                )
            )
        return sorted(result, key=lambda item: item.manifest.id)

    def get(self, module_id: str) -> InstalledModule:
        return next((item for item in self.list() if item.manifest.id == module_id), None) or self._missing(module_id)

    @staticmethod
    def _missing(module_id: str) -> InstalledModule:
        raise NotFound(f"Modul nicht gefunden: {module_id}")

    def install(self, manifest: ModuleManifest) -> InstalledModule:
        manifest.validate()
        state = self._load()
        if manifest.id in state["modules"]:
            raise InvalidState("module_already_installed")
        installed = InstalledModule(manifest=manifest)
        state["modules"][manifest.id] = installed.to_dict()
        self._save(state)
        return installed

    def update(self, manifest: ModuleManifest) -> InstalledModule:
        manifest.validate()
        state = self._load()
        current = state["modules"].get(manifest.id)
        if current is None:
            raise NotFound(f"Modul nicht gefunden: {manifest.id}")
        old = ModuleManifest.from_dict(current["manifest"])
        new_approvals = set(manifest.approvals) - set(old.approvals)
        installed = InstalledModule(
            manifest=manifest,
            enabled=bool(current.get("enabled")) and not new_approvals,
            granted_approvals=tuple(
                item for item in current.get("granted_approvals", ()) if item in manifest.approvals
            ),
        )
        state["modules"][manifest.id] = installed.to_dict()
        self._save(state)
        return installed

    def set_enabled(self, module_id: str, enabled: bool, approvals: tuple[str, ...] = ()) -> InstalledModule:
        state = self._load()
        value = state["modules"].get(module_id)
        if value is None:
            raise NotFound(f"Modul nicht gefunden: {module_id}")
        manifest = ModuleManifest.from_dict(value["manifest"])
        granted = set(value.get("granted_approvals") or ()) | set(approvals)
        if not set(approvals).issubset(manifest.approvals) or (enabled and not set(manifest.approvals).issubset(granted)):
            raise InvalidState("module_approval_required")
        value["enabled"] = enabled
        value["granted_approvals"] = sorted(granted)
        self._save(state)
        return self.get(module_id)

    def uninstall(self, module_id: str) -> ModuleManifest:
        state = self._load()
        value = state["modules"].pop(module_id, None)
        if value is None:
            raise NotFound(f"Modul nicht gefunden: {module_id}")
        self._save(state)
        return ModuleManifest.from_dict(value["manifest"])


@dataclass(frozen=True)
class ModuleRunResult:
    ok: bool
    value: Any = None
    error: str | None = None


class ModuleContext:
    """Narrow facade: modules never receive the application store itself."""

    def __init__(self, store: Any, installed: InstalledModule) -> None:
        self.__store = store
        self.module_id = installed.manifest.id
        self.manifest = installed.manifest

    def read_nodes(self, kind: str) -> list[dict[str, Any]]:
        scope = f"knowledge:{kind}"
        if scope not in self.manifest.read_scopes and "knowledge:*" not in self.manifest.read_scopes:
            raise InvalidState("module_read_scope")
        return [node.to_dict() for node in self.__store.list_nodes() if node.kind == kind]

    def read_own_data(self) -> dict[str, Any]:
        path = self.__store.artifact_path(f"module-{self.module_id}-data.json")
        if not path.exists():
            return {"schema_version": 1, "records": {}}
        import json

        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema_version") != 1 or not isinstance(value.get("records"), dict):
            raise InvalidState("module_data")
        return value

    def write_own_record(self, action: str, record_id: str, value: Mapping[str, Any]) -> None:
        if action not in self.manifest.write_actions:
            raise InvalidState("module_write_action")
        if not MODULE_ID.fullmatch(record_id):
            raise InvalidState("module_record_id")
        state = self.read_own_data()
        state["records"][record_id] = dict(value)
        self.__store.write_json_artifact(f"module-{self.module_id}-data.json", state)


class ModuleRuntime:
    def __init__(self, store: Any, registry: ModuleRegistry) -> None:
        self.store = store
        self.registry = registry

    def run(
        self,
        module_id: str,
        action: str,
        handler: Callable[[ModuleContext], Any],
    ) -> ModuleRunResult:
        try:
            installed = self.registry.get(module_id)
            if not installed.enabled:
                raise InvalidState("module_disabled")
            if action not in installed.manifest.write_actions:
                raise InvalidState("module_write_action")
            value = handler(ModuleContext(self.store, installed))
            return ModuleRunResult(ok=True, value=value)
        except Exception as exc:  # isolation boundary: a module cannot crash the core
            return ModuleRunResult(ok=False, error=str(exc) or exc.__class__.__name__)
