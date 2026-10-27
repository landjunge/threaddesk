"""Rebuildable file-node projection; library records own file identity."""
from __future__ import annotations

from threaddesk.core.errors import NotFound
from threaddesk.core.models import KnowledgeNode, Relation, now_iso
from threaddesk.services.library_import import LibraryImporter


def sync_file_nodes(store) -> dict:
    created = updated = 0
    for record in LibraryImporter(store)._read_records():
        record_id = record["id"]
        # Generated document identity stays stable across rename/move/restore.
        try:
            node = store.get_node(record_id, include_trashed=True)
        except NotFound:
            node = KnowledgeNode(id=record_id, kind="document", title=record["filename"],
                                 created_at=now_iso(), updated_at=now_iso(), source="library")
            created += 1
        else:
            if node.metadata.get("library_record_id") != record_id:
                raise ValueError("library_node_identity_conflict")
        metadata = {**node.metadata, "library_record_id": record_id,
                    "thread_id": record.get("thread_id"),
                    "attachment_node_id": record.get("node_id"),
                    "library_trashed": bool(record.get("trashed")),
                    "trashed": bool(record.get("trashed"))}
        if node.title != record["filename"] or node.metadata != metadata:
            node.title, node.metadata, node.updated_at = record["filename"], metadata, now_iso()
            store.save_node(node, include_trashed=True)
            updated += 1
    return {"created": created, "updated": updated}


def visible_library_nodes(store, nodes):
    """Use authoritative lifecycle even if a crash interrupted projection refresh."""
    rows = {r["id"]: r for r in LibraryImporter(store)._read_records()}
    visible = []
    for node in nodes:
        identity = node.metadata.get("library_record_id")
        if not identity:
            visible.append(node)
            continue
        record = rows.get(identity)
        if record and record.get("status") == "stored" and not record.get("trashed"):
            node.title = record["filename"]
            node.metadata = {**node.metadata, "thread_id": record.get("thread_id")}
            visible.append(node)
    return visible


def library_relations(store, nodes):
    """Deterministic edges reflect confirmed attachments, never semantic guesses."""
    import hashlib
    by_id = {node.id: node for node in nodes}
    result = []
    for record in LibraryImporter(store)._read_records():
        if record.get("trashed") or record["id"] not in by_id:
            continue
        targets = set(record.get("node_ids") or [])
        if record.get("node_id"):
            targets.add(record["node_id"])
        targets.update(node.id for node in nodes if record.get("thread_id") and node.kind == "project"
                       and node.metadata.get("thread_id") == record.get("thread_id"))
        for target in sorted(targets):
            if target not in by_id or target == record["id"]:
                continue
            identity = hashlib.sha256(("library:" + record["id"] + ":" + target).encode()).hexdigest()[:12]
            result.append(Relation(id=identity, source_id=target, target_id=record["id"],
                                   kind="contains", source="library",
                                   metadata={"library_record_id": record["id"], "derived": True}))
    return result
