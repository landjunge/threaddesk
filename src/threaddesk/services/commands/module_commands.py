"""Declarative module commands over six existing, narrow ModuleContext methods.

Manifests select capabilities and may further restrict their source-owned input
schemas. They never select import paths, Python handlers or executable files.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json

from threaddesk.core.errors import ManagementError, NotFound
from threaddesk.services.module_contracts import LOCAL_ID, MAX_COMMANDS, validate_declarations
from threaddesk.services.commands.model import CommandSpec
from threaddesk.services.commands.schemas import ID, TEXT, REV, PAGE, obj, page, choice


@dataclass(frozen=True)
class ModuleCommandSpec(CommandSpec):
    module_contract: dict = field(default_factory=dict)

    def public(self):
        return {**super().public(), "module_contract": self.module_contract}


def _public_contract(installed, declaration):
    manifest = installed.manifest
    permissions = {"read_scopes": sorted(manifest.read_scopes), "write_actions": sorted(manifest.write_actions),
                   "required_approvals": sorted(set(manifest.approvals) | set(declaration.get("required_approvals", ()))),
                   "granted_approvals": sorted(installed.granted_approvals)}
    shown = {key: [value for value in values if len(value) <= 128][:16] for key, values in permissions.items()}
    return {"capability": declaration["capability"], "action": declaration.get("action"),
            "module_version": manifest.version, "manifest_version": manifest.manifest_version,
            **shown, "permissions_counts": {key: len(values) for key, values in permissions.items()},
            "permissions_truncated": any(len(shown[key]) != len(values) for key, values in permissions.items()),
            "permissions_digest": hashlib.sha256(json.dumps(permissions, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            "permissions_read_command": "modules.list"}


def _schema(capability):
    if capability == "read_nodes":
        return obj({"kind": TEXT, **PAGE}, ("kind",))
    if capability == "read_thread":
        return obj({"id": ID}, ("id",))
    if capability == "read_whiteboard":
        return obj({"id": ID, **PAGE}, ("id",))
    if capability == "read_own_data":
        return obj(PAGE)
    if capability == "write_own_record":
        return obj({"record_id": {"type": "string", "pattern": LOCAL_ID.pattern, "maxLength": 128},
                    "value": {"type": "object"}, "expected_revision": REV},
                   ("record_id", "value", "expected_revision"))
    return obj({"id": ID, "actor": TEXT,
                "actor_type": choice("human", "codex", "chatgpt", "grok", "claude", "gnom-hub-v1", "system"),
                "entry_type": TEXT, "content": {"type": "string", "minLength": 1, "maxLength": 8000},
                "metadata": {"type": "object", "maxProperties": 50},
                **{name: ID for name in ("task_id", "handoff_id", "run_id", "external_key", "actor_id", "instance_id", "room_id")}},
               ("id", "actor", "actor_type", "entry_type", "content"))


def _permitted(installed, declaration):
    manifest, capability = installed.manifest, declaration["capability"]
    if not installed.enabled:
        return "disabled"
    needed = set(manifest.approvals) | set(declaration.get("required_approvals", ()))
    if not needed <= set(installed.granted_approvals) or not needed <= set(manifest.approvals):
        return "permission_required"
    if capability == "read_nodes" and not any(scope.startswith("knowledge:") for scope in manifest.read_scopes):
        return "permission_required"
    if capability == "read_thread" and "thread:read" not in manifest.read_scopes:
        return "permission_required"
    if capability == "read_whiteboard" and "whiteboard:read" not in manifest.read_scopes:
        return "permission_required"
    action = "whiteboard:append" if capability == "append_whiteboard" else declaration.get("action")
    if action and action not in manifest.write_actions:
        return "permission_required"
    return "available"


def availability(store, spec):
    """Recheck live enablement/rights; a cached command never grants itself."""
    from threaddesk.services.modules import ModuleRegistry
    try:
        installed = ModuleRegistry(store).get(spec.module_id)
    except NotFound:
        return "unavailable"
    local_id = spec.id.removeprefix(f"module.{spec.module_id}.")
    declaration = next((item for item in installed.manifest.commands if item["id"] == local_id), None)
    if declaration is None:
        return "unavailable"
    return _permitted(installed, declaration)


def specifications(store):
    from threaddesk.services.modules import ModuleRegistry
    for installed in ModuleRegistry(store).list():
        manifest = installed.manifest
        for declaration in manifest.commands:
            declared = deepcopy(declaration)
            capability = declared["capability"]
            schema = _schema(capability)
            if "input_schema" in declared:
                schema["allOf"] = [deepcopy(declared["input_schema"])]
            effect = "data" if capability == "append_whiteboard" else "external" if capability == "write_own_record" else "read"
            yield ModuleCommandSpec(
                f"module.{manifest.id}.{declared['id']}", manifest.id,
                declared.get("description") or f"Module capability {capability}", schema,
                _handler(manifest.id, declared), effect=effect,
                scope="workspace.read" if effect == "read" else "workspace.write",
                revision_target="id" if capability == "append_whiteboard" else None,
                affects_index=capability == "append_whiteboard",
                native_contract=capability == "write_own_record", module_id=manifest.id,
                module_contract=_public_contract(installed, declared),
            )


def _handler(module_id, declared):
    def run(svc, args):
        from threaddesk.services.modules import ModuleContext, ModuleRegistry
        installed = ModuleRegistry(svc.store).get(module_id)
        current = next((value for value in installed.manifest.commands if value["id"] == declared["id"]), None)
        if current != declared:
            raise ManagementError("catalog_conflict", "Module command changed; refresh its catalogue")
        permitted = _permitted(installed, current)
        if permitted != "available":
            raise ManagementError(permitted, "Module command is not currently permitted")
        context = ModuleContext(svc.store, installed)
        capability = declared["capability"]
        if capability == "read_nodes":
            return page(context.read_nodes(args["kind"]), args)
        if capability == "read_thread":
            return context.read_thread(args["id"])
        if capability == "read_whiteboard":
            return page(context.read_whiteboard(args["id"]), args)
        if capability == "read_own_data":
            data = context.read_own_data()
            records = sorted(data["records"].items())
            result = page(records, args, name="records")
            result["records"] = dict(result["records"])
            return {**result, "revision": data.get("revision", 0), "schema_version": 1}
        if capability == "write_own_record":
            return context.write_own_record(declared["action"], args["record_id"], args["value"],
                                            expected_revision=args["expected_revision"])
        data = dict(args)
        identity = data.pop("id")
        result = context.append_whiteboard(identity, **data)
        if not result["duplicate"]:
            svc.bus.emit("whiteboard.appended", {"thread_id": identity, "id": result["entry"]["id"], "duplicate": False})
        return result
    return run
