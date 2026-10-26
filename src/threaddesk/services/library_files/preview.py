"""Bounded preview descriptions; never execute or inline active file contents."""
from __future__ import annotations

from pathlib import Path

MAX_PREVIEW_BYTES = 256 * 1024


def format_info(record):
    try:
        from threaddesk.services.file_formats import describe
        return describe(record["filename"])
    except ImportError:
        media = record.get("media_type", "application/octet-stream")
        kind = media.split("/", 1)[0]
        suffix = Path(record["filename"]).suffix.casefold()
        text = media.startswith("text/") and suffix not in {".html", ".htm", ".svg"}
        preview_kind = "text" if text else kind if kind in {"image", "audio", "video"} else "metadata"
        return {"manage": True, "preview": preview_kind != "metadata", "preview_kind": preview_kind,
                "external_open": suffix in {".txt", ".md", ".pdf", ".png", ".jpg", ".jpeg", ".mp3", ".mp4"}}


def preview(service, record_id):
    record = service.info(record_id, include_trashed=True)
    if record.get("trashed"):
        return {"record": record, "kind": "metadata", "formats": format_info(record),
                "can_open": False, "content_url": None, "text": "", "truncated": False,
                "integrity": "not_checked", "message": "Datei liegt im Papierkorb. Wiederherstellung ist möglich."}
    blob, _verified = service.importer.open_record(record_id)
    formats = format_info(record)
    kind = formats.get("preview_kind", "metadata")
    # SVG/HTML may carry active payloads; metadata is the shared service fallback.
    if Path(record["filename"]).suffix.casefold() in {".html", ".htm", ".svg"}:
        kind = "metadata"
    result = {"record": record, "kind": kind, "formats": formats,
              "can_open": bool(formats.get("external_open")),
              "content_url": "/api/library/content/" + record_id,
              "text": "", "truncated": False,
              "integrity": "verified", "message": ""}
    if kind in {"text", "pdf"}:
        from threaddesk.services.file_formats import extract
        extracted = extract(blob, record["filename"])
        result["extraction_status"] = extracted["status"]
        result["message"] = extracted.get("error", "")
        if extracted.get("text"):
            result["kind"] = "text"
            result["text"] = extracted["text"][:MAX_PREVIEW_BYTES]
            result["truncated"] = extracted.get("truncated", False) or len(extracted["text"]) > MAX_PREVIEW_BYTES
        else:
            result["kind"] = "metadata"
    elif kind not in {"pdf", "image", "audio", "video"}:
        result.update(kind="metadata", message="Keine sichere interne Vorschau verfügbar.")
    return result
