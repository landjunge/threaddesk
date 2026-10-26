"""Source-owned library/thread/graph documents, separate from query transport."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from threaddesk.core.secrets import reject_secrets
from threaddesk.services.file_formats import describe, extract
from threaddesk.storage.search_source import document as thread_document

from .normalize import searchable

DIGEST = re.compile(r"^[0-9a-f]{64}$")


def finish(doc):
    doc["normalized"] = searchable(
        [
            doc.get(name)
            for name in (
                "filename",
                "logical_path",
                "origin_path",
                "thread_title",
                "title",
                "project_title",
                "format",
                "excerpt",
            )
        ]
    )
    doc["fingerprint"] = hashlib.sha256(
        json.dumps(doc, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return doc


def file_document(record, blobs, cached=None):
    digest = record.get("sha256", "")
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        raise OSError("bad_digest")
    root = Path(blobs)
    blob = root / digest
    if root.is_symlink() or blob.is_symlink() or not blob.is_file():
        raise OSError("blob_unavailable")
    info = blob.stat()
    if "size" in record and info.st_size != record["size"]:
        raise OSError("blob_size_mismatch")
    filename = str(record.get("filename", ""))
    descriptor = describe(filename)
    stamp = [info.st_ino, info.st_size, info.st_mtime_ns]
    reusable = (
        cached
        and cached.get("sha256") == digest
        and cached.get("blob_stamp") == stamp
        and cached.get("suffix") == descriptor["suffix"]
        and cached.get("extraction_status") not in {"unsupported", "failed"}
    )
    outcome = (
        {
            "text": cached.get("excerpt", ""),
            "status": cached["extraction_status"],
            "error": cached.get("extraction_error", ""),
            "truncated": cached.get("truncated", False),
        }
        if reusable
        else extract(blob, filename)
    )
    node_ids = record.get("node_ids") or []
    node = record.get("node_id") or (node_ids[0] if node_ids else "")
    doc = {
        name: record.get(name, "")
        for name in (
            "filename",
            "origin_path",
            "thread_id",
            "thread_title",
            "format",
            "assignment",
            "project_id",
        )
    }
    doc.update(
        key="file:" + record["id"],
        id=record["id"],
        entity_type="file",
        record_id=record["id"],
        file_node_id=record["id"],
        node_id=node,
        node_ids=node_ids,
        project_ids=record.get("project_ids", []),
        project_title=record.get("project_title", ""),
        title=record.get("filename", ""),
        version=record.get("version", 1), current_version=record.get("current_version", True),
        logical_path=record.get("logical_path") or record.get("origin_path", ""),
        updated_at=record.get("updated_at")
        or record.get("imported_at")
        or record.get("created_at", ""),
        trashed=int(bool(record.get("trashed"))),
        sha256=digest,
        excerpt=outcome["text"],
        extraction_status=outcome["status"],
        extraction_error=outcome["error"],
        truncated=outcome["truncated"],
    )
    doc.update(
        suffix=descriptor["suffix"], family=descriptor["format"], blob_stamp=stamp
    )
    return finish(doc)


def _thread_projection(thread):
    data = thread.to_dict()
    projected = thread_document(data, len(json.dumps(data).encode()))
    extra = thread.context.extra or {}
    return {
        "key": "thread:" + thread.id,
        "id": thread.id,
        "entity_type": "thread",
        "record_id": "",
        "thread_id": thread.id,
        "node_id": extra.get("node_id", ""),
        "project_id": projected.project_id or "",
        "filename": "",
        "title": projected.title,
        "thread_title": projected.title,
        "format": "thread",
        "assignment": "matched",
        "updated_at": thread.updated_at,
        "trashed": int(bool(extra.get("trashed"))),
        "excerpt": projected.description + "\n" + projected.notes,
    }


def _node_projection(node):
    meta = node.metadata or {}
    return {
        "key": "node:" + node.id,
        "id": node.id,
        "entity_type": "node",
        "record_id": meta.get("library_record_id") or meta.get("record_id", ""),
        "thread_id": meta.get("thread_id", ""),
        "node_id": node.id,
        "project_id": node.id if node.kind == "project" else meta.get("project_id", ""),
        "filename": "",
        "title": node.title,
        "thread_title": "",
        "format": node.kind,
        "assignment": "matched",
        "updated_at": node.updated_at,
        "trashed": int(bool(meta.get("trashed"))),
        "excerpt": node.details,
    }


def workspace_documents(store, errors=None):
    """Reuse canonical thread projections; isolate bad/oversized neighbors."""
    errors = errors if errors is not None else []
    for values, project in (
        (store.list_threads(include_archived=True), _thread_projection),
        (store.list_nodes(), _node_projection),
    ):
        for value in values:
            try:
                doc = project(value)
                if len(doc["excerpt"]) > 1024 * 1024:
                    doc["excerpt"] = doc["excerpt"][: 1024 * 1024]
                    doc["truncated"] = True
                    errors.append({"id": value.id, "error": "projection_limited"})
                reject_secrets(doc["excerpt"])
                yield finish(doc)
            except Exception as exc:  # noqa: BLE001 -- a malformed object must not hide its neighbors
                errors.append(
                    {"id": getattr(value, "id", ""), "error": type(exc).__name__}
                )
