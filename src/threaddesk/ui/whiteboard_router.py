"""Local UI forms delegate to the same whiteboard command registry as MCP."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import RedirectResponse

from threaddesk.core.errors import ManagementError
from threaddesk.services.commands import CommandApplication


def install(app, service_factory, workspace, language, page):
    @app.get("/whiteboards")
    def boards(request: Request):
        return page(request)

    def endpoint(action):
        async def submit(request: Request):
            form = await request.form()
            names = {"create": {"title", "description"}, "rename": {"title"},
                     "edit": {"entry_id", "content", "actor"}}.get(action, set())
            if set(form) - names - {"csrf_token", "operation_id", "expected_revision"}:
                raise ManagementError("validation_error", "Unbekannte Whiteboardfelder.")
            try:
                revision = int(form["expected_revision"])
                operation = str(form["operation_id"])
            except (KeyError, TypeError, ValueError):
                raise ManagementError("precondition_required", "Whiteboard vor dem Ändern neu laden.") from None
            args = {key: str(form[key]) for key in names if key in form}
            if action != "create":
                args["id"] = request.path_params["thread_id"]
            # A creation result contains at most 20k Unicode input characters.
            # Keep that proved ID-bearing receipt intact for the redirect; MCP
            # and CLI retain their separate 24k transport result budget.
            application = CommandApplication(service_factory(), transport="http", result_budget=256 * 1024)
            result = application.call({"version": 1, "workspace_id": application.workspace_id,
                "command": "whiteboard." + action, "arguments": args,
                "expected_revision": revision, "operation_id": operation})
            thread = result.get("result", {}).get("thread")
            identity = thread["id"] if thread else args["id"]
            if request.headers.get("hx-request") == "true":
                response = workspace(request)
                response.headers["X-ThreadDesk-Operation"] = operation
                response.headers["X-ThreadDesk-Duplicate"] = str(result.get("duplicate", False)).lower()
                return response
            destination = "/whiteboards" if action in {"archive", "unarchive"} else "/?thread=" + identity + "#notes"
            return RedirectResponse(destination, status_code=303,
                headers={"X-ThreadDesk-Operation": operation, "X-ThreadDesk-Duplicate": str(result.get("duplicate", False)).lower()})
        return submit

    app.add_api_route("/whiteboards", endpoint("create"), methods=["POST"])
    for action in ("open", "close", "rename", "archive", "unarchive", "edit"):
        app.add_api_route("/threads/{thread_id}/whiteboard/" + action, endpoint(action), methods=["POST"])
