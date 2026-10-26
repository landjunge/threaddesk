"""Local browser adapter for the shared library commands; existing CSRF applies."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from threaddesk.core.errors import ThreadDeskError
from threaddesk.services.library_api import LibraryApplication


def library_router(service_factory):
    router = APIRouter()

    def respond(action, args):
        store = service_factory().store
        try:
            return JSONResponse({"ok": True, "result": LibraryApplication(store).call({"action": action, **args})})
        except (ThreadDeskError, ValueError, TypeError, OSError) as exc:
            code = getattr(exc, "code", "library_error")
            status = 409 if "conflict" in code else 404 if code == "not_found" else 400
            return JSONResponse({"ok": False, "code": code, "error": str(exc)}, status_code=status)
        finally:
            if hasattr(store, "connection"):
                store.connection.close()

    @router.get("/api/library/query")
    def query(request: Request):
        args = dict(request.query_params)
        action = args.pop("action", "status")
        for key in ("limit", "offset"):
            if key in args:
                try:
                    args[key] = int(args[key])
                except ValueError:
                    return JSONResponse({"ok": False, "code": "validation_error"}, status_code=400)
        if "include_trashed" in args:
            if args["include_trashed"] not in {"true", "false"}:
                return JSONResponse({"ok": False, "code": "validation_error"}, status_code=400)
            args["include_trashed"] = args["include_trashed"] == "true"
        from threaddesk.services.library_api import READ_ACTIONS
        if action not in READ_ACTIONS:
            return JSONResponse({"ok": False, "code": "read_only_required"}, status_code=400)
        return respond(action, args)

    @router.post("/api/library/command")
    async def command(request: Request):
        import json
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 131072:
                return JSONResponse({"ok": False, "code": "request_too_large"}, status_code=413)
            body.extend(chunk)
        try:
            args = json.loads(body)
        except (ValueError, UnicodeError):
            return JSONResponse({"ok": False, "code": "validation_error"}, status_code=400)
        if not isinstance(args, dict):
            return JSONResponse({"ok": False, "code": "validation_error"}, status_code=400)
        return respond(args.pop("action", None), args)

    @router.get("/api/library/content/{record_id}")
    def content(record_id: str):
        from threaddesk.services.library_files import LibraryFileService
        store = service_factory().store
        try:
            files = LibraryFileService(store)
            preview = files.preview(record_id)
            record = preview["record"]
            if preview["kind"] not in {"image", "audio", "video"}:
                return JSONResponse({"ok": False, "code": "metadata_only"}, status_code=415)
            blob, _ = files.importer.open_record(record_id)
            return FileResponse(blob, media_type=record["media_type"], headers={
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
        except ThreadDeskError as exc:
            return JSONResponse({"ok": False, "code": getattr(exc, "code", "library_error")}, status_code=400)
        finally:
            if hasattr(store, "connection"):
                store.connection.close()

    return router
