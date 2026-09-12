"""Read-only diff and dry-run planning for mapped source records."""

from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
import hashlib
import json
import re
import unicodedata
from typing import Iterable

from threaddesk.core.import_models import (
    DiffKind,
    DryRunResult,
    ExclusionProposal,
    ImportProposal,
    MappedObject,
    MappedRelation,
)
from threaddesk.core.models import KnowledgeNode
from threaddesk.core.provenance import SourceRecord
from threaddesk.services.migration.mapper import NotionMapper


def node_target_hash(node: KnowledgeNode) -> str:
    """Hash the user-visible and provenance-bearing logical target state."""

    payload = {
        "kind": node.kind,
        "title": node.title,
        "status": node.status,
        "details": node.details,
        "source": node.source,
        "visibility": node.visibility,
        "metadata": node.metadata,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"\w+", normalized))


def _possible_duplicate(mapped: MappedObject, nodes: Iterable[KnowledgeNode]):
    source_title = _normalized_title(mapped.draft.title)
    if not source_title:
        return None
    candidates = []
    for node in nodes:
        target_title = _normalized_title(node.title)
        if not target_title:
            continue
        ratio = SequenceMatcher(None, source_title, target_title).ratio()
        if source_title == target_title or ratio >= 0.9:
            candidates.append((ratio, node.id, node))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


class DryRunPlanner:
    """Compare proposals with local state without writing either one."""

    def __init__(self, mapper: NotionMapper | None = None) -> None:
        self.mapper = mapper or NotionMapper()

    def plan(
        self,
        bundle,
        *,
        existing_nodes: Iterable[KnowledgeNode],
        source_records: Iterable[SourceRecord],
    ) -> DryRunResult:
        mapped = self.mapper.map(bundle)
        return self.plan_mapped(
            objects=mapped.objects,
            relations=mapped.relations,
            exclusions=mapped.exclusions,
            existing_nodes=existing_nodes,
            source_records=source_records,
            bundle_sha256=bundle.bundle_sha256,
        )

    def plan_mapped(
        self,
        *,
        objects: Iterable[MappedObject],
        relations: Iterable[MappedRelation],
        exclusions: Iterable[dict],
        existing_nodes: Iterable[KnowledgeNode],
        source_records: Iterable[SourceRecord],
        bundle_sha256: str = "",
    ) -> DryRunResult:
        objects = tuple(objects)
        relations = tuple(relations)
        nodes = tuple(existing_nodes)
        nodes_by_id = {node.id: node for node in nodes}
        records = {
            record.key: record
            for record in source_records
            if record.source_system == "notion"
        }
        proposals = tuple(
            self._proposal(mapped, nodes, nodes_by_id, records)
            for mapped in objects
        )
        excluded = tuple(
            ExclusionProposal(
                source_id=str(item["source_id"]),
                title=str(item["title"]),
                reason=str(item["reason"]),
            )
            for item in exclusions
        )
        counts = Counter({kind.value: 0 for kind in DiffKind})
        counts.update(proposal.diff.value for proposal in proposals)
        counts[DiffKind.EXCLUDED.value] = len(excluded)
        return DryRunResult.create(
            bundle_sha256=bundle_sha256,
            proposals=proposals,
            relations=relations,
            exclusions=excluded,
            counts=counts,
        )

    @staticmethod
    def _proposal(mapped, nodes, nodes_by_id, records) -> ImportProposal:
        record = records.get(("notion", mapped.source_id))
        target_id = None
        reason = "new_source"
        if mapped.mapping_state == "open":
            diff = DiffKind.OPEN
            reason = "mapping_open"
        elif record is not None:
            target_id = record.target_id
            target = nodes_by_id.get(record.target_id)
            if target is None:
                diff = DiffKind.CONFLICT
                reason = "target_missing"
            elif mapped.source_hash == record.source_hash:
                diff = DiffKind.NOOP
                reason = "same_source_hash"
            elif node_target_hash(target) != record.target_hash:
                diff = DiffKind.CONFLICT
                reason = "source_and_target_changed"
            elif mapped.archived:
                diff = DiffKind.ARCHIVE
                reason = "source_archived"
            else:
                diff = DiffKind.UPDATE
                reason = "source_changed"
        elif mapped.archived:
            diff = DiffKind.ARCHIVE
            reason = "archived_source_without_target"
        else:
            duplicate = _possible_duplicate(mapped, nodes)
            if duplicate is None:
                diff = DiffKind.NEW
            else:
                diff = DiffKind.POSSIBLE_DUPLICATE
                target_id = duplicate.id
                reason = "similar_title"
        return ImportProposal(
            source_id=mapped.source_id,
            diff=diff,
            draft=mapped.draft,
            target_id=target_id,
            reason=reason,
            provenance=mapped.provenance,
        )
