"""Thin form adapters for the revision-bound thread management contract."""
from __future__ import annotations

from html import escape
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

from threaddesk.core import i18n
from threaddesk.core.errors import ManagementError
from threaddesk.services.thread_management import manage
from threaddesk.server_sync.desktop import record_owner_reference


# Existing public form paths remain stable; only their write preconditions change.
ROUTES = (
    ("/threads", "create", "ui.created", {"title": "title", "description": "description"}),
    ("/threads/{thread_id}/switch", "switch", None, {}),
    ("/threads/{thread_id}/note", "set_note", "ui.note_saved", {"text": "text", "append": "append"}),
    ("/threads/{thread_id}/describe", "update", "ui.description_saved", {"description": "text"}),
    ("/threads/{thread_id}/status", "update", "ui.status_saved", {"status": "status"}),
    ("/threads/{thread_id}/rename", "update", "ui.renamed", {"title": "title"}),
    ("/threads/{thread_id}/files", "add_file", "ui.file_added", {"path": "path"}),
    ("/threads/{thread_id}/files/remove", "remove_file", "ui.file_removed", {"path": "path"}),
    ("/threads/{thread_id}/archive", "archive", "ui.archived", {}),
    ("/threads/{thread_id}/snapshot", "snapshot", "ui.snapshot_saved", {"label": "label"}),
    ("/snapshots/{snap_id}/restore", "restore_snapshot", "ui.snapshot_loaded", {}),
)


def rejection_response(request, exc, language):
    code = exc.code
    conflict = code in {"revision_conflict", "operation_conflict", "object_in_trash"}
    status = 409 if conflict else 428 if code == "precondition_required" else 404 if code == "not_found" else 400
    if request.url.path.startswith("/api/"):
        return JSONResponse({"ok": False, "code": code, "error": code,
                             "details": exc.details}, status_code=status)
    key = "ui.mutation_conflict" if conflict else "ui.mutation_precondition" if status == 428 else "ui.mutation_failed"
    # HTMX keeps the original form on a rejected write; no stale draft is
    # replaced by the fresh server state. The header selects a localized alert.
    return HTMLResponse('<p role="alert">' + escape(i18n.translate(key, language)) + '</p>',
                        status_code=status, headers={"X-ThreadDesk-Mutation-Error": key,
                                                     "X-ThreadDesk-Error-Code": code})


def install(app, service_factory, workspace, language):
    """Use the same durable operation/expected-revision contract as MCP/CLI."""
    def endpoint(action, notice_key, fields):
        async def submit(request: Request):
            form = await request.form()
            operation_id = form.get("operation_id")
            revision = form.get("expected_revision")
            if not operation_id or revision is None:
                raise ManagementError("precondition_required", "Die Ansicht muss vor dem Ändern aktualisiert werden.")
            try:
                expected_revision = int(revision)
            except (ValueError, TypeError):
                raise ManagementError("validation_error", "Ungültige erwartete Revision.") from None
            allowed = {*fields.values(), "operation_id", "expected_revision", "csrf_token"}
            if set(form) - allowed:
                raise ManagementError("validation_error", "Unbekannte Änderungsfelder.")
            data = {name: str(form.get(source, "")) for name, source in fields.items()}
            if "append" in data:
                data["append"] = data["append"] in {"1", "on", "true"}
            svc = service_factory()
            args = {"operation_id": operation_id, "action": action,
                    "expected_revision": expected_revision, "data": data}
            if action == "restore_snapshot":
                snapshot = svc.store.get_snapshot(request.path_params["snap_id"])
                args["id"] = snapshot.thread_id
                data["snapshot_id"] = snapshot.id
            elif action != "create":
                args["id"] = request.path_params["thread_id"]
            result = manage(svc, args)
            if not result["duplicate"] and action in {"add_file", "remove_file"}:
                record_owner_reference(svc, result["thread_id"], data["path"],
                                       allowed=action == "add_file")
            extra = {}
            if notice_key:
                thread = result["thread"] or {}
                snapshot = result.get("snapshot") or {}
                extra["notice"] = i18n.translate(
                    notice_key, language(request), title=thread.get("title", ""),
                    status=thread.get("status", ""), path=data.get("path", "").strip(),
                    id=snapshot.get("id", result["thread_id"]),
                )
            response = workspace(request, extra)
            response.headers["X-ThreadDesk-Operation"] = result["operation_id"]
            response.headers["X-ThreadDesk-Duplicate"] = str(result["duplicate"]).lower()
            return response
        return submit

    for path, action, notice, fields in ROUTES:
        app.add_api_route(path, endpoint(action, notice, fields), methods=["POST"])
