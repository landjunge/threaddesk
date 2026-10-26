"""Structured public CLI adapter, usable through an authorized visible terminal."""
from __future__ import annotations

import json
from pathlib import Path

from threaddesk.core.errors import ThreadDeskError
from threaddesk.services.library_api import LibraryApplication


def register_library(subparsers, language, service_factory):
    parser = subparsers.add_parser("library", help="Bibliothek / library: structured JSON commands")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--request", help="JSON command")
    source.add_argument("--request-file", help="UTF-8 JSON command file, at most 128 KiB")

    def run(args):
        store = None
        try:
            if args.request_file:
                path = Path(args.request_file)
                if path.is_symlink() or not path.is_file() or path.stat().st_size > 131072:
                    raise ValueError("invalid_request_file")
                body = path.read_text(encoding="utf-8")
            else:
                body = args.request
            if len(body.encode()) > 131072:
                raise ValueError("request_too_large")
            store = service_factory().store
            result = LibraryApplication(store).call(json.loads(body))
            print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
            return 0
        except (ThreadDeskError, ValueError, OSError, TypeError) as exc:
            print(json.dumps({"ok": False, "code": getattr(exc, "code", "invalid_request"),
                              "error": str(exc)}, ensure_ascii=False))
            return 2
        finally:
            if store is not None and hasattr(store, "connection"):
                store.connection.close()
    parser.set_defaults(func=run)
