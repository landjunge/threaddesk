"""Existing knowledge forms use the versioned graph mutation contracts."""
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from threaddesk.services.commands import CommandApplication
from threaddesk.core.errors import ThreadDeskError


def install_knowledge_mutations(app, service_factory):
    def perform(form, command, arguments):
        if not form.get("operation_id") or "expected_revision" not in form:
            return JSONResponse({"ok": False, "code": "revision_contract_required"}, status_code=428)
        svc = service_factory()
        try:
            application = CommandApplication(svc)
            application.call({"version": 1, "workspace_id": application.workspace_id,
                              "command": command, "arguments": arguments,
                              "operation_id": str(form["operation_id"]),
                              "expected_revision": int(form["expected_revision"])})
            return RedirectResponse("/knowledge", status_code=303)
        except (ThreadDeskError, ValueError, TypeError) as exc:
            code = getattr(exc, "code", "validation_error")
            return JSONResponse({"ok": False, "code": code, "error": str(exc)},
                                status_code=409 if "conflict" in code else 400)
        finally:
            if hasattr(svc.store, "connection"):
                svc.store.connection.close()

    async def create(request: Request):
        form = dict(await request.form())
        args = {key: str(form[key]) for key in ("kind", "title", "status", "details") if key in form}
        return await run_in_threadpool(perform, form, "graph.node.create", args)

    async def connect(request: Request):
        form = dict(await request.form())
        args = {key: str(form[key]) for key in ("source_id", "target_id", "kind") if key in form}
        try:
            args["expected_target_revision"] = int(form.get("expected_target_revision", ""))
        except ValueError:
            return JSONResponse({"ok": False, "code": "revision_contract_required"}, status_code=428)
        return await run_in_threadpool(perform, form, "graph.relation.create", args)

    async def transition(node_id: str, request: Request):
        form = dict(await request.form())
        return await run_in_threadpool(perform, form, "graph.node.transition", {"id": node_id, "status": str(form.get("status", ""))})

    app.add_api_route("/knowledge/nodes", create, methods=["POST"])
    app.add_api_route("/knowledge/relations", connect, methods=["POST"])
    app.add_api_route("/knowledge/nodes/{node_id}/transition", transition, methods=["POST"])
