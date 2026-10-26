"""Resource-bounded optional PDF parser. Invoked only by the format adapter."""

from __future__ import annotations

import json
import logging
import os
import stat
import sys

MAX_BYTES = 16 * 1024 * 1024
MAX_TEXT = 1024 * 1024
MAX_PAGES = 200


def main(path=None):
    try:
        import resource

        for name, limit in (
            ("RLIMIT_AS", 512 * 1024 * 1024),
            ("RLIMIT_DATA", 512 * 1024 * 1024),
            ("RLIMIT_CPU", 3),
        ):
            if hasattr(resource, name):
                resource.setrlimit(getattr(resource, name), (limit, limit))
    except (ImportError, OSError, ValueError):
        # Parent timeout and bounded input/output remain active where a limit
        # is unavailable. No PDF process is used for a metadata-only fallback.
        pass
    logging.disable(logging.CRITICAL)
    result = {
        "text": "",
        "status": "failed",
        "error": "pdf_parse",
        "truncated": False,
        "adapter": "pdf",
    }
    try:
        try:
            from pypdf import PdfReader
        except ImportError:
            result.update(status="unsupported", error="dependency_missing:pypdf")
        else:
            from io import BytesIO

            descriptor = os.open(
                path or sys.argv[1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            )
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                    raise ValueError("pdf_input_limit")
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("pdf_input_limit")
            reader = PdfReader(BytesIO(raw))
            if reader.is_encrypted:
                result.update(status="unsupported", error="encrypted")
            else:
                values, remaining = [], MAX_TEXT
                limited = len(reader.pages) > MAX_PAGES
                for page in reader.pages[:MAX_PAGES]:
                    contents = page.get_contents()
                    if (
                        contents is not None
                        and len(contents.get_data()) > 4 * 1024 * 1024
                    ):
                        limited = True
                        continue
                    value = page.extract_text() or ""
                    values.append(value[:remaining])
                    remaining -= len(values[-1])
                    if not remaining:
                        limited = True
                        break
                result.update(
                    text="\n".join(values)[:MAX_TEXT],
                    status="limited" if limited else "indexed",
                    error="",
                    truncated=limited,
                )
                if not result["text"].strip() and not limited:
                    result.update(status="metadata_only", error="no_extractable_text")
    except MemoryError:
        result.update(status="limited", error="resource_limit", truncated=True)
    except Exception as exc:  # noqa: BLE001 -- isolate third-party/parser failures per file
        result.update(error=type(exc).__name__)
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
