"""Minimal MCP JSON-RPC over stdin/stdout. No extra dependency."""

from __future__ import annotations

import json
import sys
from queue import Empty, Queue
from threading import Thread
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
    if not isinstance(req, dict):
        return _err(None, -32600, "request must be an object")
    method = req.get("method")
    rid = req.get("id")
    params = req.get("params", {})
    if not isinstance(params, dict):
        return _err(rid, -32602, "params must be an object")
    if method == "initialize":
        return _msg(
            rid,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "threaddesk", "version": _package_version()},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _msg(rid, {"tools": bridge.list_tools()})
    if method == "tools/call":
        name = str(params.get("name") or "")
        raw = bridge.call(name, params.get("arguments", {}))
        if raw.get("ok"):
            result = raw.get("result")
            text = json.dumps(result, ensure_ascii=False, indent=2)
            response = {"content": [{"type": "text", "text": text}], "isError": False}
            if isinstance(result, dict):
                response["structuredContent"] = result
            return _msg(rid, response)
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
    # Only the main thread touches the bridge/store (SQLite connections are
    # thread-bound). A bounded reader queue allows live catalogue checks while
    # stdin is idle, including module changes made by the desktop application.
    incoming = Queue(maxsize=16)

    def read_lines():
        try:
            for line in sys.stdin:
                incoming.put(line)
        finally:
            incoming.put(None)

    reader = Thread(target=read_lines, name="threaddesk-mcp-input", daemon=True)
    reader.start()

    def write(message):
        sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    try:
        revision = bridge.tools_revision()
    except Exception:
        revision = None
    ready = False
    try:
        while True:
            try:
                line = incoming.get(timeout=1.0)
            except Empty:
                line = ""
            if line is None:
                break
            line = line.strip()
            if line:
                try:
                    req = json.loads(line)
                except json.JSONDecodeError:
                    write(_err(None, -32700, "parse error"))
                    continue
                try:
                    out = handle(bridge, req)
                except Exception:
                    # Domain errors are already tool results. Discovery errors
                    # remain protocol errors, without leaking local paths/data.
                    out = _err(req.get("id") if isinstance(req, dict) else None,
                               -32603, "MCP request could not be processed")
                if out is not None:
                    write(out)
                if isinstance(req, dict) and req.get("method") == "notifications/initialized":
                    ready = True
            if not ready:
                continue
            try:
                current = bridge.tools_revision()
            except Exception:
                # A failed optional observation neither fabricates a revision
                # nor stops ordinary request processing. tools/list will expose
                # its error explicitly if the current catalogue cannot be read.
                continue
            if current != revision:
                revision = current
                write({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
    finally:
        runtime.stop()


def main() -> None:
    serve()


if __name__ == "__main__":
    main()
