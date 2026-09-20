from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


NODE_KINDS = frozenset(
    {
        "human",
        "agent",
        "workflow",
        "task",
        "tool",
        "resource",
        "result",
        "project",
        "capability",
        "budget",
        "policy",
        "decision",
        "incident",
    }
)

EDGE_KINDS = frozenset(
    {
        "delegated_to",
        "invoked",
        "requested",
        "authorized_by",
        "denied_by",
        "used_capability",
        "derived_from",
        "created_under",
        "read_from",
        "wrote_to",
        "cost_charged_to",
        "frozen_by",
        "belongs_to",
        "result_of",
        "supersedes",
    }
)


@dataclass
class AuthNode:
    id: str
    kind: str
    label: str
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuthEdge:
    id: str
    kind: str
    source_id: str
    target_id: str
    event_id: str
    timestamp: str
    decision: str | None = None
    observed: bool = True
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GraphSnapshot:
    schema: str
    nodes: list[AuthNode]
    edges: list[AuthEdge]
    event_ids: list[str]
    trace_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "event_ids": list(self.event_ids),
            "trace_ids": list(self.trace_ids),
            "counts": {"nodes": len(self.nodes), "edges": len(self.edges)},
        }

    def as_list(self) -> list[dict[str, Any]]:
        """Same objects as the graph, as a list (G1 list view)."""
        rows = [{"object": "node", **n.to_dict()} for n in self.nodes]
        rows.extend({"object": "edge", **e.to_dict()} for e in self.edges)
        return rows


@dataclass
class Incident:
    id: str
    reason: str
    created_at: str
    event_ids: list[str]
    snapshot: GraphSnapshot

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "reason": self.reason,
            "created_at": self.created_at,
            "event_ids": list(self.event_ids),
            "snapshot": self.snapshot.to_dict(),
        }
