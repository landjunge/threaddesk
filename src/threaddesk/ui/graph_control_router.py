"""Capability-bound browser delivery; all mutations retain the local CSRF gate."""
import json
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from threaddesk.core.errors import ManagementError
from threaddesk.services.commands.errors import normalized
from threaddesk.services.commands.validation import MAX_REQUEST
from threaddesk.services.graph_view_control import GraphViewControlService


def graph_control_router(service_factory):
    router = APIRouter()

    def invoke(action, client_id, token, arguments):
        service = service_factory()
        try:
            control = GraphViewControlService(service.store)
            if action == "connect":
                if arguments:
                    raise ManagementError("validation_error", "No client identity is accepted on registration")
                result = control.register()
            else:
                allowed = {"heartbeat": set(), "pending": set(), "claim": {"operation_id"},
                           "ack": {"operation_id", "status", "observed_state", "error_code"}}[action]
                if set(arguments) - allowed:
                    raise ManagementError("validation_error", "Unknown view-client field")
                if action == "heartbeat":
                    result = control.heartbeat(client_id, token)
                elif action == "pending":
                    result = control.pending(client_id, token)
                elif action == "claim":
                    result = control.claim(client_id, token, arguments.get("operation_id"))
                else:
                    result = control.acknowledge(client_id, token, **arguments)
            return JSONResponse({"ok": True, "result": result}, headers={"Cache-Control": "no-store"})
        except Exception as exc:
            error = normalized(exc)
            status = 403 if error.code == "view_client_denied" else 409 if "conflict" in error.code else 400
            return JSONResponse({"ok": False, "code": error.code, "error": str(error)}, status_code=status)
        finally:
            if hasattr(service.store, "connection"):
                service.store.connection.close()

    async def request_body(request):
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_REQUEST:
                return None
            body.extend(chunk)
        try:
            value = json.loads(body)
            return value if isinstance(value, dict) else None
        except (ValueError, UnicodeError):
            return None

    @router.post("/api/graph/view-control/connect")
    async def connect(request: Request):
        args = await request_body(request)
        if args is None:
            return JSONResponse({"ok": False, "code": "validation_error"}, status_code=400)
        return await run_in_threadpool(invoke, "connect", None, None, args)

    @router.get("/api/graph/view-control/{client_id}/pending")
    def pending(client_id: str, request: Request):
        return invoke("pending", client_id, request.headers.get("X-ThreadDesk-View-Client"), {})

    @router.post("/api/graph/view-control/{client_id}/{action}")
    async def write(client_id: str, action: str, request: Request):
        if action not in {"heartbeat", "claim", "ack"}:
            return JSONResponse({"ok": False, "code": "not_found"}, status_code=404)
        args = await request_body(request)
        if args is None:
            return JSONResponse({"ok": False, "code": "validation_error"}, status_code=400)
        return await run_in_threadpool(invoke, action, client_id, request.headers.get("X-ThreadDesk-View-Client"), args)

    return router
