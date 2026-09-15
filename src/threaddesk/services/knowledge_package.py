"""Auditable ZIP package for a verified knowledge selection."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping
from zipfile import ZIP_DEFLATED, ZipFile

from threaddesk.services.knowledge_export import KnowledgeExportService

PACKAGE_FORMAT = "threaddesk.export-package.v1"


class KnowledgePackageService:
    def __init__(self, store: Any) -> None:
        self.store = store

    def preview(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        checked = KnowledgeExportService.verify(payload)
        return {
            "format": PACKAGE_FORMAT,
            "generated_at": checked["generated_at"],
            "selection": checked["selection"],
            "counts": {
                "nodes": checked["counts"]["nodes"],
                "relations": checked["counts"]["relations"],
                "artifacts_requested": checked["counts"]["artifacts"],
            },
            "files": ["manifest.json", "data/knowledge.json", "documents/preview.md", "export-log.json"],
        }

    def encode(self, payload: Mapping[str, Any], *, language: str = "de") -> bytes:
        checked = KnowledgeExportService.verify(payload)
        preview = self.preview(checked)
        included, skipped = [], []
        artifact_files: list[tuple[str, bytes]] = []
        root = Path(self.store.workspace_path).resolve()
        for artifact in checked["artifacts"]:
            path = (root / str(artifact["relative_path"])).resolve()
            if root not in path.parents or not path.is_file():
                skipped.append({"sha256": artifact["sha256"], "reason": "missing_or_unsafe"})
                continue
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != artifact["sha256"]:
                skipped.append({"sha256": artifact["sha256"], "reason": "checksum"})
                continue
            name = f"artifacts/{artifact['sha256']}/{path.name}"
            artifact_files.append((name, content)); included.append(name)
        manifest = {**preview, "artifacts_included": included, "artifacts_skipped": skipped}
        log = {
            "format": PACKAGE_FORMAT,
            "generated_at": checked["generated_at"],
            "source_sha256": checked["sha256"],
            "private_included": any(node["visibility"] == "private" for node in checked["nodes"]),
            "written_files": preview["files"] + included,
        }
        output = io.BytesIO()
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            archive.writestr("data/knowledge.json", KnowledgeExportService.encode(checked))
            archive.writestr("documents/preview.md", KnowledgeExportService.encode_markdown(checked, language=language))
            archive.writestr("export-log.json", json.dumps(log, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            for name, content in artifact_files:
                archive.writestr(name, content)
        return output.getvalue()
