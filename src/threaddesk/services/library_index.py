"""Metadata and bounded text index for stored library copies.

The index is rebuilt from records and blobs. A failed rebuild leaves the
previous index in place. Search never reads the original library.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_DIGEST = re.compile(r"^[0-9a-f]{64}$")

TEXT_SUFFIXES = {
    ".md", ".markdown", ".txt", ".rst", ".csv", ".tsv", ".json",
    ".yaml", ".yml", ".html", ".htm", ".xml",
}
MAX_EXCERPT = 32 * 1024


class LibraryIndex:
    def __init__(self, library_root: Path) -> None:
        self.root = Path(library_root)
        self.path = self.root / "index.json"

    def status(self) -> dict:
        document = self._read()
        if document is None:
            return {"status": "missing", "documents": 0, "failed": 0, "error": ""}
        return {
            "status": document.get("status") or "ready",
            "documents": len(document.get("documents") or []),
            "failed": int(document.get("failed") or 0),
            "error": document.get("error") or "",
        }

    def rebuild(self, records: list[dict], blobs: Path) -> dict:
        documents = []
        failed = 0
        errors: list[dict] = []
        stored = 0
        for record in records:
            if record.get("status") != "stored":
                continue
            stored += 1
            try:
                documents.append(self._document(record, blobs))
            except OSError as exc:
                failed += 1
                errors.append({"id": record.get("id", ""), "error": exc.__class__.__name__})
        if stored and not documents and self._has_ready_index():
            return {"status": "failed", "documents": self.status()["documents"], "failed": failed, "error": "index_kept"}
        payload = {
            "version": 1,
            "status": "failed" if stored and not documents else "ready",
            "failed": failed,
            "errors": errors[:20],
            "documents": documents,
        }
        self._replace(payload)
        return self.status()

    def search(self, text: str, *, limit: int = 20, thread_id: str | None = None) -> list[dict]:
        query = " ".join(text.casefold().split())
        if not query:
            return []
        document = self._read()
        if not document:
            return []
        hits = []
        for item in document.get("documents") or []:
            if thread_id is not None and item.get("thread_id") != thread_id:
                continue
            haystack = " ".join([
                str(item.get("filename") or ""),
                str(item.get("origin_path") or ""),
                str(item.get("thread_title") or ""),
                str(item.get("format") or ""),
                str(item.get("excerpt") or ""),
            ]).casefold()
            if query in haystack or all(part in haystack for part in query.split()):
                hits.append({
                    "id": item.get("id"),
                    "filename": item.get("filename"),
                    "origin_path": item.get("origin_path"),
                    "thread_title": item.get("thread_title"),
                    "thread_id": item.get("thread_id"),
                    "format": item.get("format"),
                })
            if len(hits) >= limit:
                break
        return hits

    def _document(self, record: dict, blobs: Path) -> dict:
        suffix = Path(str(record.get("filename") or "")).suffix.casefold()
        excerpt = ""
        if suffix in TEXT_SUFFIXES:
            excerpt = self._excerpt(record, blobs)
        return {
            "id": record.get("id"),
            "filename": record.get("filename"),
            "origin_path": record.get("origin_path"),
            "thread_id": record.get("thread_id"),
            "thread_title": record.get("thread_title"),
            "format": record.get("format"),
            "sha256": record.get("sha256"),
            "excerpt": excerpt,
        }

    def _has_ready_index(self) -> bool:
        current = self._read()
        return bool(current and current.get("status") == "ready" and current.get("documents"))

    def _excerpt(self, record: dict, blobs: Path) -> str:
        digest = str(record.get("sha256") or "")
        if not _DIGEST.fullmatch(digest):
            raise OSError("bad digest")
        root = Path(blobs).resolve()
        blob = (root / digest).resolve()
        if not blob.is_relative_to(root):
            raise OSError("blob escape")
        with blob.open("rb") as handle:
            return handle.read(MAX_EXCERPT).decode("utf-8", errors="replace")

    def _read(self) -> dict | None:
        if not self.path.is_file():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"status": "failed", "failed": 0, "error": "index_unreadable", "documents": []}
        if not isinstance(data, dict):
            return {"status": "failed", "failed": 0, "error": "index_unreadable", "documents": []}
        return data

    def _replace(self, payload: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_name("index.json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(self.path)
