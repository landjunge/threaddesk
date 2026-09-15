"""Explicit, stale-safe decisions for migration conflicts."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
import hashlib
import json
from typing import Any, Iterable, Mapping

from threaddesk.core.import_models import DiffKind, DryRunResult, ImportProposal
from threaddesk.core.models import KnowledgeNode
from threaddesk.services.migration.diff import node_target_hash


KEEP_LOCAL = "keep_local"
TAKE_SOURCE = "take_source"


def allowed_actions(proposal: ImportProposal) -> tuple[str, ...]:
    """Return only decisions that make sense for this exact conflict."""
    if proposal.diff is not DiffKind.CONFLICT:
        return ()
    if proposal.reason == "target_missing":
        return (TAKE_SOURCE,)
    return (KEEP_LOCAL, TAKE_SOURCE)


def conflict_token(
    bundle_sha256: str,
    proposal: ImportProposal,
    nodes_by_id: Mapping[str, KnowledgeNode],
) -> str:
    """Bind a visible decision to both source and current local target state."""
    target = nodes_by_id.get(proposal.target_id or "")
    payload = {
        "bundle_sha256": bundle_sha256,
        "source_id": proposal.source_id,
        "source_hash": proposal.provenance.source_hash,
        "target_id": proposal.target_id,
        "target_hash": node_target_hash(target) if target is not None else "missing",
        "reason": proposal.reason,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolve_conflicts(
    plan: DryRunResult,
    *,
    existing_nodes: Iterable[KnowledgeNode],
    resolutions: Mapping[str, Any] | None,
) -> DryRunResult:
    """Apply explicit choices without mutating the reviewed bundle or store."""
    choices = resolutions or {}
    nodes_by_id = {node.id: node for node in existing_nodes}
    conflicts = {
        proposal.source_id: proposal
        for proposal in plan.proposals
        if proposal.diff is DiffKind.CONFLICT
    }
    if set(choices) - set(conflicts):
        raise ValueError("resolution_unknown")

    proposals: list[ImportProposal] = []
    for proposal in plan.proposals:
        if proposal.diff is not DiffKind.CONFLICT:
            proposals.append(proposal)
            continue
        choice = choices.get(proposal.source_id)
        if not isinstance(choice, Mapping):
            raise ValueError("resolution_missing")
        action = choice.get("action")
        token = choice.get("token")
        if action not in allowed_actions(proposal):
            raise ValueError("resolution_action")
        expected = conflict_token(plan.bundle_sha256, proposal, nodes_by_id)
        if token != expected:
            raise ValueError("resolution_stale")
        if action == KEEP_LOCAL:
            proposals.append(replace(
                proposal,
                diff=DiffKind.NOOP,
                reason="resolved_keep_local",
            ))
        else:
            proposals.append(replace(
                proposal,
                diff=(DiffKind.UPDATE if proposal.target_id else DiffKind.NEW),
                target_id=proposal.target_id if proposal.target_id else None,
                reason="resolved_take_source",
            ))

    counts = Counter({kind.value: 0 for kind in DiffKind})
    counts.update(proposal.diff.value for proposal in proposals)
    counts[DiffKind.EXCLUDED.value] = len(plan.exclusions)
    return DryRunResult.create(
        bundle_sha256=plan.bundle_sha256,
        proposals=tuple(proposals),
        relations=plan.relations,
        exclusions=plan.exclusions,
        counts=counts,
    )
