"""Map validated Notion source records to source-neutral import proposals."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from types import MappingProxyType
from typing import Any

from threaddesk.core.import_models import (
    MappedBundle,
    MappedObject,
    MappedRelation,
    NodeDraft,
    RelationDraft,
)
from threaddesk.core.models import NODE_KINDS, NODE_STATUSES, RELATION_KINDS
from threaddesk.core.provenance import Provenance


DEFAULT_STATUS = {
    "project": "active",
    "decision": "proposed",
    "task": "idea",
    "result": "unverified",
    "document": "unverified",
}


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{_stable_hash(list(parts))[:16]}"


class NotionMapper:
    """A deterministic mapper. It creates drafts, never confirmed facts."""

    source_system = "notion"

    def map(self, bundle) -> MappedBundle:
        workspace_id = str(bundle.manifest["source_workspace_id"])
        bundle_id = str(bundle.manifest["export_id"])
        mapped_objects = tuple(
            self._map_object(bundle, record, workspace_id, bundle_id)
            for record in bundle.iter_objects()
        )
        targets = {item.source_id: item.draft.id for item in mapped_objects}
        relations = tuple(
            self._map_relation(record, targets, workspace_id)
            for record in bundle.iter_relations()
        )
        exclusions = tuple(
            MappingProxyType(deepcopy(dict(record)))
            for record in bundle.iter_exclusions()
        )
        return MappedBundle(mapped_objects, relations, exclusions)

    def _map_object(
        self, bundle, record: dict[str, Any], workspace_id: str, bundle_id: str
    ) -> MappedObject:
        content_path = record.get("content_path")
        content = bundle.read_text(content_path) if content_path else ""
        source_hash = _stable_hash({"record": record, "content": content})
        suggested_kind = str(record["suggested_kind"])
        if suggested_kind in NODE_KINDS:
            kind = suggested_kind
            mapping_state = "mapped"
            mapping_rule = "notion.v1.suggested_kind"
        else:
            kind = "document"
            mapping_state = "open"
            mapping_rule = "notion.v1.unknown_kind_as_document"

        raw_status = record["properties"].get("status")
        if record["archived"]:
            status = "archived"
        elif (
            mapping_state == "mapped"
            and isinstance(raw_status, str)
            and raw_status in NODE_STATUSES
        ):
            status = raw_status
        else:
            status = DEFAULT_STATUS.get(kind, "idea")

        provenance = Provenance(
            source_system=self.source_system,
            source_id=str(record["source_id"]),
            source_url=str(record["source_url"]),
            source_path=str(record["source_path"]),
            source_type=str(record["source_type"]),
            source_last_edited_at=str(record["last_edited_at"]),
            source_hash=source_hash,
            bundle_id=bundle_id,
            mapping_rule=mapping_rule,
        )
        metadata = MappingProxyType(
            {
                "provenance": provenance.to_dict(),
                "source_properties": deepcopy(record["properties"]),
                "suggested_kind": suggested_kind,
                "mapping_reason": str(record["mapping_reason"]),
                "mapping_state": mapping_state,
            }
        )
        draft = NodeDraft(
            id=_stable_id("notion", workspace_id, str(record["source_id"])),
            kind=kind,
            title=str(record["title"]),
            status=status,
            details=content,
            source="notion-import",
            visibility="private",
            metadata=metadata,
        )
        return MappedObject(
            source_id=str(record["source_id"]),
            source_hash=source_hash,
            draft=draft,
            provenance=provenance,
            mapping_state=mapping_state,
            mapping_reason=str(record["mapping_reason"]),
            archived=bool(record["archived"]),
        )

    def _map_relation(
        self, record: dict[str, Any], targets: dict[str, str], workspace_id: str
    ) -> MappedRelation:
        source_kind = str(record["kind"])
        if source_kind in RELATION_KINDS:
            kind = source_kind
            mapping_state = "mapped"
        else:
            kind = "related_to"
            mapping_state = "open"
        source_id = str(record["source_id"])
        target_id = str(record["target_id"])
        metadata = MappingProxyType(
            {"source_kind": source_kind, "mapping_state": mapping_state}
        )
        draft = RelationDraft(
            id=_stable_id("notion-rel", workspace_id, source_id, target_id, source_kind),
            source_id=targets[source_id],
            target_id=targets[target_id],
            kind=kind,
            source="notion-import",
            metadata=metadata,
        )
        return MappedRelation(
            source_id=source_id,
            target_id=target_id,
            source_kind=source_kind,
            draft=draft,
            mapping_state=mapping_state,
        )
