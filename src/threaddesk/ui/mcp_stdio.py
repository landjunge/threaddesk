"""Minimal MCP JSON-RPC over stdin/stdout. No extra dependency."""

from __future__ import annotations

import json
import sys
from typing import Any

from threaddesk.api.service import ThreadService
from threaddesk.services.mcp import McpBridge


def _package_version():
    from threaddesk import __version__
    return __version__


def _msg(id_: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _err(id_: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def handle(bridge: McpBridge, req: dict[str, Any]) -> dict[str, Any] | None:
    method = req.get("method")
    rid = req.get("id")
    params = req.get("params") or {}
    if method == "initialize":
        return _msg(
            rid,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "threaddesk", "version": _package_version()},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _msg(rid, {"tools": bridge.list_tools()})
    if method == "tools/call":
        name = str(params.get("name") or "")
        raw = bridge.call(name, params.get("arguments") or {})
        if raw.get("ok"):
            text = json.dumps(raw.get("result"), ensure_ascii=False, indent=2)
            return _msg(rid, {"content": [{"type": "text", "text": text}], "isError": False})
        return _msg(
            rid,
            {
                "content": [{"type": "text", "text": json.dumps({"error": raw.get("error"), "code": raw.get("code", "tool_error"), "details": raw.get("details", {})}, ensure_ascii=False)}],
                "isError": True,
            },
        )
    if rid is None:
        return None
    return _err(rid, -32601, f"unknown method: {method}")


def serve(svc: ThreadService | None = None) -> None:
    bridge = McpBridge(svc or ThreadService())
    from threaddesk.services.library_runtime import LibraryRuntime
    runtime = LibraryRuntime(lambda: type(bridge.svc.store)(bridge.svc.store.workspace_path))
    runtime.start()
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                sys.stdout.write(json.dumps(_err(None, -32700, "parse error")) + "\n")
                sys.stdout.flush()
                continue
            out = handle(bridge, req)
            if out is not None:
                sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
                sys.stdout.flush()
    finally:
        runtime.stop()


def main() -> None:
    serve()


if __name__ == "__main__":
    main()
