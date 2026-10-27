"""Protected HTTP adapters for the shared commands and graph read contract."""
from __future__ import annotations

import json
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from threaddesk.core.errors import ThreadDeskError
from threaddesk.services.commands import CommandApplication
from threaddesk.services.commands.validation import MAX_REQUEST


def command_router(service_factory):
    router = APIRouter()

    def run(callback, *, graph=False):
        svc = service_factory()
        try:
            application = CommandApplication(svc, result_budget=2 * 1024 * 1024 if graph else 24000, transport="http")
            return JSONResponse(callback(application), headers={"Cache-Control": "no-store"})
        except (ThreadDeskError, OSError, ValueError, TypeError) as exc:
            code = getattr(exc, "code", "invalid_state")
            status = (409 if "conflict" in code or code in {"object_in_trash", "operation_unconfirmed"}
                      else 404 if code in {"not_found", "command_not_found"}
                      else 403 if code in {"permission_required", "disabled"} else 400)
            return JSONResponse({"ok": False, "code": code, "error": str(exc),
                                 "details": getattr(exc, "details", {})}, status_code=status)
        finally:
            if hasattr(svc.store, "connection"):
                svc.store.connection.close()

    @router.get("/api/commands/catalog")
    def catalog(limit: int = 10, offset: int = 0):
        return run(lambda app: app.catalog(limit=limit, offset=offset))

    async def body(request):
        incoming = bytearray()
        async for chunk in request.stream():
            if len(incoming) + len(chunk) > MAX_REQUEST:
                return None
            incoming.extend(chunk)
        try:
            args = json.loads(incoming)
            return args if isinstance(args, dict) else None
        except (ValueError, UnicodeError):
            return None

    @router.post("/api/commands")
    async def invoke(request: Request):
        args = await body(request)
        if args is None:
            return JSONResponse({"ok": False, "code": "validation_error"}, status_code=400)
        return await run_in_threadpool(run, lambda app: {"ok": True, **app.call(args)})

    def read_command(app, identity, args):
        response = app.call({"version": 1, "workspace_id": app.workspace_id,
                             "command": identity, "arguments": args}, read_only=True)
        if "result" not in response:
            from threaddesk.core.errors import ManagementError
            raise ManagementError("page_too_large", "Narrow the graph query or reduce the page limit")
        return response["result"]

    @router.get("/api/command-artifacts/{name}")
    def artifact(name: str):
        import re
        if not re.fullmatch(r"command-(?:export|backup)-[a-f0-9]{64}\.(?:json|md|csv|xlsx|svg|pdf|zip)", name):
            return JSONResponse({"ok": False, "code": "not_found"}, status_code=404)
        svc = service_factory()
        try:
            path = svc.store.artifact_path(name)
            digest = name.rsplit("-", 1)[1].split(".")[0]
            from threaddesk.services.commands.artifacts import read_verified_file
            body = read_verified_file(path, sha256=digest)
            return Response(body, media_type="application/octet-stream", headers={"Cache-Control": "no-store",
                "Content-Disposition": 'attachment; filename="' + name + '"',
                "Content-Security-Policy": "default-src 'none'; sandbox"})
        except ThreadDeskError as exc:
            return JSONResponse({"ok": False, "code": getattr(exc, "code", "artifact_unavailable")}, status_code=409)
        finally:
            if hasattr(svc.store, "connection"):
                svc.store.connection.close()

    @router.get("/api/graph/v2")
    def graph(request: Request):
        args = dict(request.query_params)
        for key in ("limit", "offset", "hops"):
            if key in args:
                try:
                    args[key] = int(args[key])
                except ValueError:
                    return JSONResponse({"ok": False, "code": "validation_error"}, status_code=400)
        return run(lambda app: read_command(app, "graph.query", args), graph=True)

    @router.get("/api/graph/change-status")
    def change_status():
        return run(lambda app: read_command(app, "graph.change_status", {}), graph=True)

    @router.post("/api/graph/v2")
    async def graph_selection(request: Request):
        args = await body(request)
        if args is None:
            return JSONResponse({"ok": False, "code": "validation_error"}, status_code=400)
        return await run_in_threadpool(run, lambda app: read_command(app, "graph.query", args), graph=True)

    @router.get("/api/graph/views")
    def views(limit: int = 100, offset: int = 0):
        return run(lambda app: read_command(app, "graph_view.list", {"limit": limit, "offset": offset}), graph=True)

    @router.get("/api/graph/views/{identity}")
    def view(identity: str):
        return run(lambda app: read_command(app, "graph_view.get", {"id": identity}), graph=True)

    @router.post("/api/graph/views")
    async def manage_view(request: Request):
        args = await body(request)
        if args is None:
            return JSONResponse({"ok": False, "code": "validation_error"}, status_code=400)
        def perform(app):
            response = app.call({"version": 1, "workspace_id": app.workspace_id,
                                 "command": "graph_view.manage", "arguments": args,
                                 "operation_id": args.get("operation_id"),
                                 "expected_revision": args.get("expected_revision")})
            return {"ok": True, "result": response["result"]}
        return await run_in_threadpool(run, perform)

    return router
