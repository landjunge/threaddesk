"""Structured complete local CLI, including catalogue and durable readback."""
from __future__ import annotations

import json
from pathlib import Path

from threaddesk.core.errors import ThreadDeskError
from threaddesk.services.commands import CommandApplication
from threaddesk.services.commands.validation import MAX_REQUEST


def register_commands(subparsers, service_factory):
    parser = subparsers.add_parser("command", help="Versioned JSON command catalogue and invocation")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--catalog", action="store_true")
    mode.add_argument("--operation")
    mode.add_argument("--request")
    mode.add_argument("--request-file")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0)

    def run(args):
        svc = service_factory()
        try:
            app = CommandApplication(svc, transport="cli")
            if args.catalog:
                result = app.catalog(limit=args.limit, offset=args.offset)
            elif args.operation:
                request = {"version": 1, "workspace_id": app.workspace_id, "command": "command.operation",
                           "arguments": {"operation_id": args.operation}, "result_offset": args.offset}
                result = app.call(request)
            else:
                if args.request_file:
                    path = Path(args.request_file)
                    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_REQUEST:
                        raise ValueError("invalid_request_file")
                    incoming = path.read_text(encoding="utf-8")
                else:
                    incoming = args.request
                if len(incoming.encode()) > MAX_REQUEST:
                    raise ValueError("request_too_large")
                result = app.call(json.loads(incoming))
            print(json.dumps({"ok": True, **result}, ensure_ascii=False, allow_nan=False))
            return 0
        except (ThreadDeskError, ValueError, OSError, TypeError) as exc:
            print(json.dumps({"ok": False, "code": getattr(exc, "code", "invalid_request"),
                              "error": str(exc), "details": getattr(exc, "details", {})}, ensure_ascii=False))
            return 2
        finally:
            if hasattr(svc.store, "connection"):
                svc.store.connection.close()
    parser.set_defaults(func=run)
