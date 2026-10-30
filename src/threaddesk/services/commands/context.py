"""Context, whiteboard, actor and module command adapters."""
from __future__ import annotations

from threaddesk.services.commands.model import CommandSpec
from threaddesk.services.commands.schemas import ID, TEXT, BOOL, PAGE, obj, array, page, choice
from threaddesk.core.models import ACTOR_TYPES, ENTRY_TYPES


def specifications():
    def command(identity, schema, handler, *, module="context", effect="read", target=None):
        return CommandSpec(identity, module, identity.replace(".", " "), schema, handler,
                           effect=effect, scope="workspace.read" if effect == "read" else "workspace.write",
                           revision_target=target, affects_index=identity == "whiteboard.append")
    yield command("command.operation", obj({"operation_id": ID}, ("operation_id",)), _operation)
    yield command("command.catalog", obj({"limit": {"type": "integer", "minimum": 1, "maximum": 25},
                                           "offset": PAGE["offset"]}), _catalog)
    yield command("command.reconcile", obj({"request": {"type": "object"}}, ("request",)),
                  _reconcile, effect="external")
    yield command("whiteboard.list", obj({"id": ID, **PAGE}, ("id",)),
                  lambda svc, args: page([row.to_dict() for row in svc.whiteboard(args["id"])], args))
    yield command("whiteboard.stand", obj({"id": ID}, ("id",)), lambda svc, a: svc.working_stand(a["id"]))
    fields = {"id": ID, "actor": TEXT,
              "actor_type": choice(*ACTOR_TYPES),
              "entry_type": choice(*ENTRY_TYPES),
              "content": {"type": "string", "minLength": 1, "maxLength": 8000},
              **{key: ID for key in ("task_id", "handoff_id", "run_id", "actor_id", "instance_id", "room_id")},
              "metadata": {"type": "object", "maxProperties": 50}, "external_key": TEXT}
    def append(svc, args):
        args = dict(args)
        identity = args.pop("id")
        return svc.append_whiteboard(identity, **args)
    yield command("whiteboard.append", obj(fields, ("id", "actor", "actor_type", "entry_type", "content")),
                  append, effect="data", target="id")
    yield command("actors.list", obj(PAGE), lambda svc, a: page(svc.actors(), a), module="actors")
    yield command("actors.appearance", obj({"actor_id": ID}, ("actor_id",)),
                  lambda svc, a: svc.actor_appearance(a["actor_id"]), module="actors")
    for action, fields, required, method in (
        ("human", {"name": TEXT, "color_token": TEXT}, ("name", "color_token"), "register_human"),
        ("agent", {"name": TEXT, "person_id": ID, "agent_type": TEXT, "model": TEXT, "provider": TEXT},
         ("name", "person_id", "agent_type"), "register_agent"),
        ("rename", {"actor_id": ID, "name": TEXT}, ("actor_id", "name"), "rename_actor"),
        ("recolor", {"actor_id": ID, "color_token": TEXT}, ("actor_id", "color_token"), "recolor_actor"),
    ):
        yield command("actors." + action, obj(fields, required),
                      lambda svc, a, selected=method: getattr(svc, selected)(**a), module="actors", effect="external")
    yield command("modules.list", obj(PAGE), _modules, module="modules")
    for action, fields, required in (
        ("install", {"manifest": {"type": "object"}}, ("manifest",)),
        ("update", {"manifest": {"type": "object"}}, ("manifest",)),
        ("enable", {"id": ID, "enabled": BOOL, "approvals": array(TEXT)}, ("id", "enabled")),
        ("uninstall", {"id": ID}, ("id",)),
    ):
        yield command("modules." + action, obj(fields, required),
                      lambda svc, a, selected=action: _module_manage(svc, selected, a),
                      module="modules", effect="external")
    from threaddesk.services.tollgate import POLICY_INTS
    yield command("gate.status", obj(), lambda svc, a: svc.gate(), module="gate")
    yield command("gate.set", obj({"frozen": BOOL, **{key: {"type": "integer", "minimum": 0} for key in POLICY_INTS}}), lambda svc, a: svc.gate_set(**a),
                  module="gate", effect="external")
    yield command("gate.freeze", obj({"frozen": BOOL}, ("frozen",)), lambda svc, a: svc.gate_freeze(a["frozen"]),
                  module="gate", effect="external")
    yield command("prompt.preview", obj({"id": ID, "target": TEXT, "variant": TEXT}, ("id",)),
                  lambda svc, a: {"text": svc.prompt(a.get("target", "generic"), a.get("variant", "detailed"), a["id"], save=False)})


def _modules(svc, args):
    from threaddesk.services.modules import ModuleRegistry
    return page([value.to_dict() for value in ModuleRegistry(svc.store).list()], args)


def _operation(svc, args):
    from threaddesk.services.commands import CommandApplication
    return CommandApplication(svc).operation(args["operation_id"])


def _catalog(svc, args):
    from threaddesk.services.commands import CommandApplication
    return CommandApplication(svc).catalog(**args)


def _reconcile(svc, args):
    from threaddesk.services.commands import CommandApplication
    return CommandApplication(svc).reconcile(args["request"])


def _module_manage(svc, action, args):
    from threaddesk.services.modules import ModuleRegistry, ModuleManifest
    registry = ModuleRegistry(svc.store)
    if action in {"install", "update"}:
        return getattr(registry, action)(ModuleManifest.from_dict(args["manifest"])).to_dict()
    if action == "enable":
        return registry.set_enabled(args["id"], args["enabled"], tuple(args.get("approvals", ()))).to_dict()
    return registry.uninstall(args["id"]).to_dict()
