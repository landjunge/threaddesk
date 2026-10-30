"""Non-destructive, idempotent migration from JsonStore to SQLiteStore."""

from __future__ import annotations

import json
from typing import Callable

from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.storage.owner_documents import read_owner_documents


class MigrationError(RuntimeError):
    pass


def _read(source: JsonStore) -> dict:
    threads = source.list_threads(include_archived=True, include_trashed=True)
    return {
        "threads": threads,
        "snapshots": [snap for thread in threads for snap in source.list_snapshots(thread.id, include_trashed=True)],
        "nodes": source.list_nodes(include_trashed=True),
        "relations": source.list_relations(include_trashed=True),
        "trash_entries": source.list_trash_entries(),
        "events": source.list_graph_events(),
        "source_records": source.list_source_records(),
        "whiteboard": [
            entry
            for thread in threads
            for entry in source.list_whiteboard(thread.id, include_trashed=True)
        ],
        "management_operations": source.list_management_operations(),
        "issued_handoffs": source.list_issued_handoffs(),
        "current_id": source.get_current_id(),
        "owner_documents": read_owner_documents(source),
    }


def _canonical(data: dict) -> str:
    serializable = {
        key: [item.to_dict() if hasattr(item, "to_dict") else item for item in value] if isinstance(value, list) else value
        for key, value in data.items()
    }
    return json.dumps(serializable, ensure_ascii=False, sort_keys=True)


def migrate_json_store(
    source: JsonStore,
    target: SQLiteStore,
    *,
    dry_run: bool = False,
    fault: Callable[[str], None] | None = None,
) -> dict:
    try:
        incoming = _read(source)
        existing = _read(target)  # type: ignore[arg-type]
    except Exception as exc:
        raise MigrationError(f"JSON-Bestand konnte nicht gelesen werden: {type(exc).__name__}") from exc

    counts = {key: len(value) for key, value in incoming.items() if isinstance(value, list)}
    if _canonical(incoming) == _canonical(existing):
        return {"status": "noop", "changed": False, "counts": counts, "dry_run": dry_run}
    if any(
        existing[key]
        for key in (
            "threads",
            "snapshots",
            "nodes",
            "relations",
            "events",
            "source_records",
            "whiteboard",
            "management_operations",
            "issued_handoffs",
            "trash_entries",
            "owner_documents",
        )
    ):
        raise MigrationError("SQLite-Ziel enthält bereits einen anderen Bestand.")
    if dry_run:
        return {"status": "preview", "changed": True, "counts": counts, "dry_run": True}

    try:
        with target.transaction():
            for thread in incoming["threads"]:
                target.save_thread(thread)
            for entry in incoming["whiteboard"]:
                target.append_whiteboard_entry(entry)
            if fault:
                fault("after_threads")
            for snapshot in incoming["snapshots"]:
                target.save_snapshot(snapshot)
            for node in incoming["nodes"]:
                target.save_node(node)
            for relation in incoming["relations"]:
                target.save_relation(relation)
            for event in incoming["events"]:
                target.append_graph_event(event)
            for record in incoming["source_records"]:
                target.save_source_record(record)
            for receipt in incoming["management_operations"]:
                target.save_management_operation(receipt.get("storage_operation_id") or receipt["result"]["operation_id"], receipt)
            for issued in incoming["issued_handoffs"]:
                target.save_issued_handoff(issued["handoff"]["handoff_id"], issued)
            # Import lifecycle last so hidden payloads can first retain their IDs.
            for entry in incoming["trash_entries"]:
                target.save_trash_entry(entry)
            target.save_migrated_owner_documents(incoming["owner_documents"])
            target.set_current_id(incoming["current_id"])
            if fault:
                fault("before_commit")
    except Exception as exc:
        raise MigrationError(f"Migration zurückgerollt: {type(exc).__name__}") from exc
    return {"status": "imported", "changed": True, "counts": counts, "dry_run": False}
