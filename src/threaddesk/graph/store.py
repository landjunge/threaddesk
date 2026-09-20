"""In-memory Authority graph. Rebuildable from events. No renderer."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from threaddesk.core.authority_event import validate_event
from threaddesk.graph.model import AuthEdge, AuthNode, GraphSnapshot, Incident

SCHEMA = "threaddesk.authority-graph.v1"


def _nid(*parts: str) -> str:
    return ":".join(p.replace(" ", "_") for p in parts if p)


class AuthorityGraph:
    def __init__(self) -> None:
        self._events: dict[str, dict[str, Any]] = {}
        self._nodes: dict[str, AuthNode] = {}
        self._edges: dict[str, AuthEdge] = {}
        self._order: list[str] = []
        self._incidents: list[Incident] = []

    def ingest(self, events: list[dict[str, Any]]) -> int:
        """Validate and fold events. Duplicate event_id is skipped (idempotent)."""
        added = 0
        for raw in events:
            validate_event(raw)
            eid = raw["event_id"]
            if eid in self._events:
                continue
            self._events[eid] = dict(raw)
            self._order.append(eid)
            self._apply(raw)
            added += 1
            if raw.get("decision") in ("DENY", "FREEZE"):
                self.open_incident(
                    f"{raw['event_type']}:{raw.get('decision')}",
                    event_ids=[eid],
                )
        return added

    def ingest_payload(self, payload: dict[str, Any]) -> int:
        events = payload.get("events")
        if not isinstance(events, list):
            raise ValueError("payload.events must be a list")
        return self.ingest(events)

    def _node(self, node_id: str, kind: str, label: str, **attrs: Any) -> AuthNode:
        existing = self._nodes.get(node_id)
        if existing is None:
            node = AuthNode(id=node_id, kind=kind, label=label, attrs=dict(attrs))
            self._nodes[node_id] = node
            return node
        existing.attrs.update({k: v for k, v in attrs.items() if v is not None})
        if label and label != existing.label and not existing.label:
            existing.label = label
        return existing

    def _edge(
        self,
        kind: str,
        source_id: str,
        target_id: str,
        event: dict[str, Any],
        **attrs: Any,
    ) -> AuthEdge:
        eid = event["event_id"]
        edge_id = _nid("edge", eid, kind, source_id, target_id)
        edge = AuthEdge(
            id=edge_id,
            kind=kind,
            source_id=source_id,
            target_id=target_id,
            event_id=eid,
            timestamp=str(event.get("timestamp") or ""),
            decision=event.get("decision"),
            observed=True,
            attrs=dict(attrs),
        )
        self._edges[edge_id] = edge
        return edge

    def _apply(self, ev: dict[str, Any]) -> None:
        actor = ev.get("actor") if isinstance(ev.get("actor"), dict) else {}
        agent_id = str(actor.get("agent_id") or "").strip()
        role = str(actor.get("role") or "").strip()
        workflow = str(ev.get("workflow_id") or "").strip()
        project = str(ev.get("project_id") or "").strip()
        resource = str(ev.get("resource") or "").strip()
        action = str(ev.get("action") or "").strip()
        result_ref = str(ev.get("result_ref") or "").strip()
        budget_ref = str(ev.get("budget_ref") or "").strip()
        cap = str(ev.get("capability_id") or "").strip()
        et = ev["event_type"]

        if project:
            self._node(_nid("project", project), "project", project)
        if workflow:
            self._node(_nid("workflow", workflow), "workflow", workflow)
            if project:
                self._edge("belongs_to", _nid("workflow", workflow), _nid("project", project), ev)
        if agent_id:
            self._node(_nid("agent", agent_id), "agent", agent_id, role=role)
        if resource:
            kind = "task" if resource.startswith("issue:") else "resource"
            self._node(_nid("resource", resource), kind, resource)
        if result_ref:
            self._node(_nid("result", result_ref), "result", result_ref)
        if budget_ref:
            self._node(_nid("budget", budget_ref), "budget", budget_ref)
        if cap:
            self._node(_nid("capability", cap), "capability", cap)
        if action and et in ("tool.intent", "tool.result"):
            self._node(_nid("tool", action), "tool", action)

        if et == "work.started" and agent_id and workflow:
            self._edge("belongs_to", _nid("agent", agent_id), _nid("workflow", workflow), ev)
        elif et == "agent.invoked" and agent_id and workflow:
            self._edge("invoked", _nid("workflow", workflow), _nid("agent", agent_id), ev)
        elif et == "delegation.created" and agent_id and resource:
            self._edge("delegated_to", _nid("agent", agent_id), _nid("resource", resource), ev)
        elif et == "tool.intent" and agent_id and resource:
            self._edge("requested", _nid("agent", agent_id), _nid("resource", resource), ev)
            if action:
                self._edge("wrote_to", _nid("tool", action), _nid("resource", resource), ev)
        elif et == "tool.result" and result_ref and agent_id:
            self._edge("result_of", _nid("result", result_ref), _nid("agent", agent_id), ev)
        elif et == "work.finished" and workflow and result_ref:
            self._edge("result_of", _nid("workflow", workflow), _nid("result", result_ref), ev)
        elif et == "budget.checked" and budget_ref and workflow:
            kind = "authorized_by" if ev.get("decision") == "ALLOW" else "denied_by"
            self._edge(kind, _nid("workflow", workflow), _nid("budget", budget_ref), ev)
            if ev.get("decision") == "ALLOW":
                self._edge(
                    "cost_charged_to",
                    _nid("workflow", workflow),
                    _nid("budget", budget_ref),
                    ev,
                )
        elif et.startswith("capability.") and cap and agent_id:
            self._edge("used_capability", _nid("agent", agent_id), _nid("capability", cap), ev)
        elif et == "authority.freeze" and agent_id:
            self._node(_nid("incident", ev["event_id"]), "incident", "freeze")
            self._edge(
                "frozen_by",
                _nid("agent", agent_id),
                _nid("incident", ev["event_id"]),
                ev,
            )

    def snapshot(self) -> GraphSnapshot:
        traces = sorted({str(self._events[i].get("trace_id") or "") for i in self._order})
        return GraphSnapshot(
            schema=SCHEMA,
            nodes=sorted(self._nodes.values(), key=lambda n: n.id),
            edges=sorted(self._edges.values(), key=lambda e: e.id),
            event_ids=list(self._order),
            trace_ids=[t for t in traces if t],
        )

    def query(
        self,
        *,
        project_id: str | None = None,
        agent_id: str | None = None,
        decision: str | None = None,
        event_type: str | None = None,
        trace_id: str | None = None,
    ) -> GraphSnapshot:
        allowed_events: set[str] | None = None
        if any([project_id, agent_id, decision, event_type, trace_id]):
            allowed_events = set()
            for eid in self._order:
                ev = self._events[eid]
                if project_id and ev.get("project_id") != project_id:
                    continue
                actor = ev.get("actor") if isinstance(ev.get("actor"), dict) else {}
                if agent_id and actor.get("agent_id") != agent_id:
                    continue
                if decision and ev.get("decision") != decision:
                    continue
                if event_type and ev.get("event_type") != event_type:
                    continue
                if trace_id and ev.get("trace_id") != trace_id:
                    continue
                allowed_events.add(eid)
        snap = self.snapshot()
        if allowed_events is None:
            return snap
        edges = [e for e in snap.edges if e.event_id in allowed_events]
        node_ids = {e.source_id for e in edges} | {e.target_id for e in edges}
        nodes = [n for n in snap.nodes if n.id in node_ids]
        return GraphSnapshot(
            schema=SCHEMA,
            nodes=nodes,
            edges=edges,
            event_ids=[eid for eid in snap.event_ids if eid in allowed_events],
            trace_ids=sorted(
                {
                    str(self._events[eid].get("trace_id") or "")
                    for eid in allowed_events
                    if self._events[eid].get("trace_id")
                }
            ),
        )

    def open_incident(self, reason: str, *, event_ids: list[str] | None = None) -> Incident:
        ids = list(event_ids or self._order)
        incident = Incident(
            id=uuid4().hex[:12],
            reason=reason,
            created_at=datetime.now(timezone.utc).isoformat(),
            event_ids=ids,
            snapshot=self.snapshot(),
        )
        self._incidents.append(incident)
        return incident

    def incidents(self) -> list[Incident]:
        return list(self._incidents)
