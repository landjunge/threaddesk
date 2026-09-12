"""Immutable proposals produced before an import is confirmed."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from threaddesk.core.models import KnowledgeNode, Relation
from threaddesk.core.provenance import Provenance


class DiffKind(str, Enum):
    NEW = "new"
    NOOP = "noop"
    UPDATE = "update"
    CONFLICT = "conflict"
    POSSIBLE_DUPLICATE = "possible_duplicate"
    EXCLUDED = "excluded"
    OPEN = "open"
    ARCHIVE = "archive"


@dataclass(frozen=True)
class NodeDraft:
    id: str
    kind: str
    title: str
    status: str
    details: str
    source: str
    visibility: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_node(self) -> KnowledgeNode:
        return KnowledgeNode(
            id=self.id,
            kind=self.kind,
            title=self.title,
            status=self.status,
            details=self.details,
            source=self.source,
            visibility=self.visibility,
            metadata=dict(self.metadata),
        )


@dataclass(frozen=True)
class RelationDraft:
    id: str
    source_id: str
    target_id: str
    kind: str
    source: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_relation(self) -> Relation:
        return Relation(
            id=self.id,
            source_id=self.source_id,
            target_id=self.target_id,
            kind=self.kind,
            source=self.source,
            metadata=dict(self.metadata),
        )


@dataclass(frozen=True)
class MappedObject:
    source_id: str
    source_hash: str
    draft: NodeDraft
    provenance: Provenance
    mapping_state: str
    mapping_reason: str
    archived: bool = False


@dataclass(frozen=True)
class MappedRelation:
    source_id: str
    target_id: str
    source_kind: str
    draft: RelationDraft
    mapping_state: str


@dataclass(frozen=True)
class MappedBundle:
    objects: tuple[MappedObject, ...]
    relations: tuple[MappedRelation, ...]
    exclusions: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class ImportProposal:
    source_id: str
    diff: DiffKind
    draft: NodeDraft
    target_id: str | None
    reason: str
    provenance: Provenance


@dataclass(frozen=True)
class ExclusionProposal:
    source_id: str
    title: str
    reason: str


@dataclass(frozen=True)
class DryRunResult:
    bundle_sha256: str
    proposals: tuple[ImportProposal, ...]
    relations: tuple[MappedRelation, ...]
    exclusions: tuple[ExclusionProposal, ...]
    counts: Mapping[str, int]

    @classmethod
    def create(
        cls,
        *,
        bundle_sha256: str,
        proposals: tuple[ImportProposal, ...],
        relations: tuple[MappedRelation, ...],
        exclusions: tuple[ExclusionProposal, ...],
        counts: Mapping[str, int],
    ) -> "DryRunResult":
        return cls(
            bundle_sha256=bundle_sha256,
            proposals=proposals,
            relations=relations,
            exclusions=exclusions,
            counts=MappingProxyType(dict(counts)),
        )
