"""Inert Authority Envelope import, without caller-selected file access."""
from threaddesk.core.authority_event import EVENT_TYPES, REQUIRED, SOURCE_TOOLS
from threaddesk.graph import AuthorityGraph
from threaddesk.services.commands.model import CommandSpec
from threaddesk.services.commands.schemas import TEXT, array, choice, obj


def specifications():
    nullable = {"type": ["string", "null"], "maxLength": 10000}
    event = obj({
        "schema_version": {"const": "1"},
        **{key: TEXT for key in ("event_id", "timestamp", "trace_id", "span_id", "action", "resource", "event_hash")},
        **{key: nullable for key in ("parent_span_id", "workflow_id", "project_id", "capability_id",
                                    "reason_code", "budget_ref", "result_ref", "previous_event_hash")},
        "actor": obj({key: TEXT for key in ("agent_id", "workload_id", "role")}),
        "source_tool": choice(*sorted(SOURCE_TOOLS)),
        "event_type": choice(*sorted(EVENT_TYPES)),
        "decision": {"enum": ["ALLOW", "DENY", "FREEZE", None]},
        "data_labels": array(TEXT, 100),
    }, REQUIRED)
    yield CommandSpec(
        "authority.import", "authority",
        "Validate supplied Authority Envelope v1 events and return an inert graph snapshot. Verifies event hashes; does not grant authority, persist events, execute, or read/write caller-selected paths.",
        obj({"events": array(event, 1000)}, ("events",)), _import,
    )


def _import(_service, args):
    graph = AuthorityGraph()
    added = graph.ingest(args["events"])
    return {**graph.snapshot().to_dict(), "imported": added}
