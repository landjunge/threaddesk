"""Content adapters with bounded input/output and explicit failure results."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from threaddesk.core.errors import SecretRejected
from threaddesk.core.secrets import reject_secrets

from .containers import archive_text, zip_text
from .registry import descriptor
from .text import decode, html_text, rtf_text

MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_TEXT_CHARS = 1024 * 1024


def extract_file(path: Path, filename: str) -> dict:
    info = descriptor(filename)
    result = {
        "text": "",
        "status": "metadata_only",
        "error": "",
        "truncated": False,
        "adapter": info["adapter"],
    }
    try:
        file_info = path.lstat()
        if not stat.S_ISREG(file_info.st_mode) or path.is_symlink():
            raise OSError("unsafe_file")
        adapter = info["adapter"]
        if adapter == "metadata":
            return result
        if (
            adapter in {"office", "epub", "pdf", "archive"}
            and file_info.st_size > MAX_INPUT_BYTES
        ):
            return {
                **result,
                "status": "limited",
                "truncated": True,
                "error": "input_limit",
            }
        file_descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(file_descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (file_info.st_dev, file_info.st_ino):
                raise OSError("source_changed")
            raw = stream.read(MAX_INPUT_BYTES + 1)
        raw, truncated = raw[:MAX_INPUT_BYTES], len(raw) > MAX_INPUT_BYTES
        if adapter == "text":
            text = decode(raw)
        elif adapter == "html":
            text = html_text(raw)
        elif adapter == "rtf":
            text = rtf_text(raw)
        elif adapter in {"office", "epub"}:
            text, bounded = zip_text(raw, epub=adapter == "epub")
            truncated |= bounded
        elif adapter == "archive":
            text, bounded = archive_text(raw, filename)
            truncated |= bounded
        elif adapter == "pdf":
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "threaddesk.services.file_formats.pdf_worker",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if completed.returncode != 0:
                return {
                    **result,
                    "status": "limited",
                    "error": "resource_limit",
                    "truncated": True,
                }
            parsed = json.loads(completed.stdout)
            text = str(parsed.get("text", ""))[:MAX_TEXT_CHARS]
            reject_secrets(text)
            return {**result, **parsed, "text": text}
        else:
            return result
        truncated |= len(text) > MAX_TEXT_CHARS
        text = text[:MAX_TEXT_CHARS]
        reject_secrets(text)
        return {
            **result,
            "text": text,
            "status": "limited" if truncated else "indexed",
            "truncated": truncated,
        }
    except SecretRejected:
        return {**result, "status": "failed", "error": "content_rejected"}
    except subprocess.TimeoutExpired:
        return {**result, "status": "limited", "error": "time_limit", "truncated": True}
    except Exception as exc:  # noqa: BLE001 -- isolate third-party/parser failures per file
        # A bad file cannot abort the remaining index. Do not expose parser text
        # or document contents through an exception message.
        return {**result, "status": "failed", "error": type(exc).__name__}
