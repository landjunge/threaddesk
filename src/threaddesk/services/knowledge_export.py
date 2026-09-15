"""Canonical, checksum-protected JSON exports of selected knowledge context."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Iterable, Mapping

from threaddesk.core.models import (
    NODE_KINDS,
    NODE_STATUSES,
    RELATION_KINDS,
    VISIBILITIES,
    now_iso,
)


FORMAT = "threaddesk.knowledge-export.v1"


class KnowledgeExportError(ValueError):
    """The requested selection or serialized export is not trustworthy."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _checksum(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _records(store: Any, method: str) -> list[Any]:
    reader = getattr(store, method, None)
    return list(reader()) if reader is not None else []


class KnowledgeExportService:
    """Build and verify one source-neutral export without mutating the store."""

    def __init__(self, store: Any) -> None:
        self.store = store

    def build(
        self,
        *,
        node_ids: Iterable[str] | None = None,
        include_private: bool = False,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        all_nodes = {node.id: node for node in self.store.list_nodes()}
        requested = None if node_ids is None else {str(node_id) for node_id in node_ids}
        if requested is not None:
            missing = requested - set(all_nodes)
            if missing:
                raise KnowledgeExportError("selection_missing")
            candidates = [all_nodes[node_id] for node_id in requested]
        else:
            candidates = list(all_nodes.values())

        excluded_private = sorted(
            node.id for node in candidates if node.visibility == "private" and not include_private
        )
        nodes = sorted(
            (
                node
                for node in candidates
                if include_private or node.visibility != "private"
            ),
            key=lambda node: node.id,
        )
        selected_ids = {node.id for node in nodes}
        relations = sorted(
            (
                relation
                for relation in self.store.list_relations()
                if relation.source_id in selected_ids
                and relation.target_id in selected_ids
            ),
            key=lambda relation: relation.id,
        )
        relation_ids = {relation.id for relation in relations}
        events = sorted(
            (
                event
                for event in self.store.list_graph_events()
                if event.entity_id in selected_ids or event.entity_id in relation_ids
            ),
            key=lambda event: (event.occurred_at, event.id),
        )
        source_records = sorted(
            (
                record
                for record in _records(self.store, "list_source_records")
                if record.target_id in selected_ids
            ),
            key=lambda record: (record.source_system, record.source_id),
        )
        node_artifacts = sorted(
            (
                dict(link)
                for link in _records(self.store, "list_node_artifacts")
                if link["node_id"] in selected_ids
            ),
            key=lambda link: (link["node_id"], link["role"], link["sha256"]),
        )
        artifact_hashes = {link["sha256"] for link in node_artifacts}
        artifacts = sorted(
            (
                dict(artifact)
                for artifact in _records(self.store, "list_artifacts")
                if artifact["sha256"] in artifact_hashes
            ),
            key=lambda artifact: artifact["sha256"],
        )

        body = {
            "format": FORMAT,
            "generated_at": generated_at or now_iso(),
            "selection": {
                "requested": None if requested is None else sorted(requested),
                "included": sorted(selected_ids),
                "excluded_private": excluded_private,
            },
            "counts": {
                "nodes": len(nodes),
                "relations": len(relations),
                "events": len(events),
                "source_records": len(source_records),
                "artifacts": len(artifacts),
                "node_artifacts": len(node_artifacts),
            },
            "nodes": [node.to_dict() for node in nodes],
            "relations": [relation.to_dict() for relation in relations],
            "events": [event.to_dict() for event in events],
            "source_records": [record.to_dict() for record in source_records],
            "artifacts": artifacts,
            "node_artifacts": node_artifacts,
        }
        return {**body, "sha256": _checksum(body)}

    @staticmethod
    def verify(payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise KnowledgeExportError("export_format")
        value = deepcopy(dict(payload))
        checksum = value.pop("sha256", None)
        if value.get("format") != FORMAT:
            raise KnowledgeExportError("export_format")
        if not isinstance(checksum, str) or checksum != _checksum(value):
            raise KnowledgeExportError("export_checksum")
        collections = (
            "nodes",
            "relations",
            "events",
            "source_records",
            "artifacts",
            "node_artifacts",
        )
        if any(not isinstance(value.get(name), list) for name in collections):
            raise KnowledgeExportError("export_shape")
        counts = value.get("counts")
        if not isinstance(counts, Mapping) or any(
            counts.get(name) != len(value[name]) for name in collections
        ):
            raise KnowledgeExportError("export_counts")
        node_ids = [item.get("id") for item in value["nodes"] if isinstance(item, Mapping)]
        relation_ids = [
            item.get("id") for item in value["relations"] if isinstance(item, Mapping)
        ]
        if len(node_ids) != len(value["nodes"]) or len(set(node_ids)) != len(node_ids):
            raise KnowledgeExportError("export_nodes")
        if len(relation_ids) != len(value["relations"]) or len(set(relation_ids)) != len(relation_ids):
            raise KnowledgeExportError("export_relations")
        node_id_set = set(node_ids)
        if any(
            node.get("kind") not in NODE_KINDS
            or node.get("status") not in NODE_STATUSES
            or node.get("visibility") not in VISIBILITIES
            or not isinstance(node.get("title"), str)
            or not node["title"].strip()
            for node in value["nodes"]
        ):
            raise KnowledgeExportError("export_nodes")
        if any(
            relation.get("source_id") not in node_id_set
            or relation.get("target_id") not in node_id_set
            or relation.get("kind") not in RELATION_KINDS
            for relation in value["relations"]
        ):
            raise KnowledgeExportError("export_relation_target")
        selection = value.get("selection")
        if not isinstance(selection, Mapping) or set(selection.get("included", ())) != node_id_set:
            raise KnowledgeExportError("export_selection")
        source_keys: list[tuple[Any, Any]] = []
        for record in value["source_records"]:
            if not isinstance(record, Mapping) or record.get("target_id") not in node_id_set:
                raise KnowledgeExportError("export_source_records")
            source_keys.append((record.get("source_system"), record.get("source_id")))
        if len(set(source_keys)) != len(source_keys):
            raise KnowledgeExportError("export_source_records")
        artifact_hashes = [
            item.get("sha256") for item in value["artifacts"] if isinstance(item, Mapping)
        ]
        if (
            len(artifact_hashes) != len(value["artifacts"])
            or len(set(artifact_hashes)) != len(artifact_hashes)
        ):
            raise KnowledgeExportError("export_artifacts")
        artifact_hash_set = set(artifact_hashes)
        if any(
            not isinstance(link, Mapping)
            or link.get("node_id") not in node_id_set
            or link.get("sha256") not in artifact_hash_set
            for link in value["node_artifacts"]
        ):
            raise KnowledgeExportError("export_artifact_links")
        return {**value, "sha256": checksum}

    @classmethod
    def encode(cls, payload: Mapping[str, Any]) -> str:
        checked = cls.verify(payload)
        return json.dumps(checked, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    @classmethod
    def decode(cls, raw: str | bytes) -> dict[str, Any]:
        try:
            text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            payload = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise KnowledgeExportError("export_json") from exc
        return cls.verify(payload)
