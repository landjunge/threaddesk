"""Graph, activity, saved-view and trash adapters over domain services."""
from __future__ import annotations

from threaddesk.services.commands.model import CommandSpec, workspace_identity
from threaddesk.services.commands.schemas import ID, TEXT, REV, BOOL, PAGE, obj, choice, array, page


def specifications():
    def spec(identity, schema, handler, *, effect="read", native=False, target=None):
        return CommandSpec(identity, identity.split(".")[0], identity.replace(".", " "), schema, handler,
                           effect=effect, scope="workspace.read" if effect == "read" else "workspace.write",
                           native_contract=native, revision_target=target, affects_index=effect == "data")
    filters = {"query": TEXT, "kind": TEXT, "status": TEXT, "project_id": TEXT,
               "mode": choice("status", "modified", "accessed", "work"),
               "band": choice("", "24h", "7d", "30d", "90d", "older", "unknown"),
               "center": ID, "hops": {"type": "integer", "minimum": 0, "maximum": 2},
               "as_of": {"type": "string", "maxLength": 64},
               "node_ids": {**array(ID, 1000), "minItems": 1, "uniqueItems": True},
               "limit": {"type": "integer", "minimum": 1, "maximum": 1000}, "offset": PAGE["offset"]}
    yield spec("graph.query", obj(filters), _graph)
    yield spec("graph.change_status", obj(), _change_status)
    yield spec("graph.node", obj({"id": ID}, ("id",)), lambda svc, a: svc.get_node(a["id"]).to_dict())
    yield spec("graph.node.transitions", obj({"id": ID}, ("id",)),
               lambda svc, a: {"id": a["id"], "transitions": svc.allowed_node_transitions(a["id"])})
    from threaddesk.core.models import NODE_KINDS, NODE_STATUSES, RELATION_KINDS, VISIBILITIES
    create = {"kind": choice(*NODE_KINDS), "title": {**TEXT, "minLength": 1},
              "status": choice(*NODE_STATUSES), "details": TEXT, "source": TEXT,
              "visibility": choice(*VISIBILITIES), "metadata": {"type": "object"}}
    yield spec("graph.node.create", obj(create, ("kind", "title")),
               lambda svc, a: svc.create_node(**a).to_dict(), effect="data", target="create")
    yield spec("graph.node.transition", obj({"id": ID, "status": choice(*NODE_STATUSES)}, ("id", "status")),
               lambda svc, a: svc.transition_node(a["id"], a["status"], expected_revision=svc.get_node(a["id"]).revision).to_dict(),
               effect="data", target="node:id")
    relation = {"source_id": ID, "target_id": ID, "kind": choice(*RELATION_KINDS),
                "expected_target_revision": REV, "source": TEXT, "metadata": {"type": "object"}}
    yield spec("graph.relation.create", obj(relation, ("source_id", "target_id", "kind", "expected_target_revision")),
               _connect, effect="data", target="node:source_id")
    yield spec("graph.relations", obj({"id": ID, **PAGE}),
               lambda svc, a: page([r.to_dict() for r in (svc.relations_for(a["id"]) if a.get("id") else svc.list_relations())], a))
    yield spec("graph.events", obj(PAGE), lambda svc, a: page([r.to_dict() for r in svc.list_graph_events()], a))
    yield spec("activity.files", obj({"record_ids": array(ID, 10000), "as_of": TEXT}, ("record_ids",)), _activity)
    yield spec("activity.reconcile", obj(PAGE), _reconcile, effect="external")
    yield spec("graph_view.list", obj({**PAGE, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}),
               lambda svc, a: _views(svc).list(**a))
    yield spec("graph_view.get", obj({"id": TEXT}, ("id",)), lambda svc, a: _views(svc).get(a["id"]))
    yield spec("graph_view.operation", obj({"operation_id": TEXT}, ("operation_id",)),
               lambda svc, a: _views(svc).operation_status(a["operation_id"]))
    yield spec("graph_view.clients", obj(), lambda svc, a: _control(svc).clients())
    yield spec("graph_view.apply_status", obj({"operation_id": ID}, ("operation_id",)),
               lambda svc, a: _control(svc).apply_status(a["operation_id"]))
    apply = {"id": TEXT, "expected_revision": REV, "operation_id": ID, "client_id": ID}
    yield spec("graph_view.apply", obj(apply, ("id", "expected_revision", "operation_id")),
               lambda svc, a: _control(svc).apply(a), effect="domain", native=True)
    view = obj({"action": choice("save", "delete"), "id": TEXT, "operation_id": ID,
                "expected_revision": REV, "data": {"type": "object"}},
               ("action", "id", "operation_id", "expected_revision"))
    yield spec("graph_view.manage", view, lambda svc, a: _views(svc).manage(a), effect="domain", native=True)
    kind = choice("thread", "node", "relation")
    yield spec("trash.list", obj({"state": choice("trashed", "restored", "purged", "all"), "kind": kind, **PAGE}),
               lambda svc, a: _trash(svc).list(**a))
    yield spec("trash.get", obj({"trash_id": TEXT}, ("trash_id",)), lambda svc, a: _trash(svc).get(a["trash_id"]))
    yield spec("trash.preview", obj({"kind": kind, "object_id": ID}, ("kind", "object_id")),
               lambda svc, a: _trash(svc).preview(**a))
    yield spec("trash.purge_preview", obj({"trash_id": TEXT}, ("trash_id",)),
               lambda svc, a: _trash(svc).purge_preview(a["trash_id"]))
    yield spec("trash.operation", obj({"operation_id": ID}, ("operation_id",)),
               lambda svc, a: _trash(svc).operation_status(a["operation_id"]))
    yield spec("trash.sync_conflicts", obj(PAGE), lambda svc, a: page(_trash(svc).sync_conflicts(), a))
    resolve = {"conflict_id": ID, "expected_object_digest": TEXT,
               "choice": choice("keep_local", "adopt_incoming"), "operation_id": ID}
    yield spec("trash.resolve_sync_conflict", obj(resolve, tuple(resolve)),
               lambda svc, a: _trash(svc).resolve_sync_conflict(**a), effect="domain", native=True)
    shared = {"operation_id": ID, "expected_revision": REV}
    yield spec("trash.move", obj({**shared, "kind": kind, "object_id": ID},
                                 ("operation_id", "expected_revision", "kind", "object_id")),
               lambda svc, a: _trash(svc).move(**a), effect="domain", native=True)
    restore = {**shared, "trash_id": TEXT, "generation": {"type": "integer", "minimum": 1}}
    yield spec("trash.restore", obj(restore, tuple(restore)),
               lambda svc, a: _trash(svc).restore(**a), effect="domain", native=True)
    purge = {**restore, "reference_digest": TEXT, "confirmation": TEXT}
    yield spec("trash.purge", obj(purge, tuple(purge)),
               lambda svc, a: _trash(svc).purge(**a), effect="domain", native=True)


def _graph(svc, arguments):
    from threaddesk.services.graph_read import GraphReadService
    return GraphReadService(svc.store).query(svc.graph(), **arguments)


def _change_status(svc, _arguments):
    from threaddesk.services.graph_read import GraphReadService
    return GraphReadService(svc.store).change_status(workspace_id=workspace_identity(svc.store))


def _connect(svc, arguments):
    from threaddesk.core.errors import ManagementError
    args = dict(arguments)
    expected = args.pop("expected_target_revision")
    actual = svc.get_node(args["target_id"]).revision
    if expected != actual:
        raise ManagementError("revision_conflict", "Relation target changed", actual_revision=actual)
    return svc.connect(**args).to_dict()


def _activity(svc, args):
    from threaddesk.services.activity import ActivityService
    return ActivityService(svc.store).files(args["record_ids"], as_of=args.get("as_of"))


def _reconcile(svc, args):
    from threaddesk.services.activity import ActivityService
    return ActivityService(svc.store).reconcile(**args)


def _views(svc):
    from threaddesk.services.graph_views import GraphViewService
    return GraphViewService(svc.store)


def _control(svc):
    from threaddesk.services.graph_view_control import GraphViewControlService
    return GraphViewControlService(svc.store)


def _trash(svc):
    from threaddesk.services.trash import TrashService
    return TrashService(svc.store)
