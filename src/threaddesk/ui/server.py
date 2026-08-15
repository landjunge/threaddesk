"""Local ThreadDesk UI. Talks only to ThreadService. Never executes."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ThreadDeskError
from threaddesk.core.models import STATUSES
from threaddesk.storage.json_store import JsonStore

HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = HERE / "templates"
STATIC_DIR = HERE / "static"
WRITE_STATUSES = tuple(s for s in STATUSES if s != "archived")


def _svc() -> ThreadService:
    home = os.environ.get("THREADDESK_HOME")
    if home:
        return ThreadService(store=JsonStore(Path(home)))
    return ThreadService()


def _ctx(request: Request, extra: dict | None = None) -> dict:
    svc = _svc()
    current = svc.current()
    snapshots = svc.snapshots(current.id) if current else []
    data = {
        "request": request,
        "threads": svc.list(include_archived=False),
        "current": current,
        "current_id": svc.store.get_current_id(),
        "gate": svc.gate(),
        "snapshots": snapshots,
        "statuses": WRITE_STATUSES,
        "error": None,
        "notice": None,
    }
    if extra:
        data.update(extra)
    return data


def create_app() -> FastAPI:
    app = FastAPI(title="ThreadDesk", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def workspace(request: Request, extra: dict | None = None) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "partials/workspace.html", _ctx(request, extra)
        )

    @app.exception_handler(ThreadDeskError)
    async def _on_error(request: Request, exc: ThreadDeskError) -> HTMLResponse:
        html = workspace(request, {"error": str(exc)})
        html.status_code = 400
        return html

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "index.html", _ctx(request))

    @app.get("/partials/threads", response_class=HTMLResponse)
    def partial_threads(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "partials/thread_list.html", _ctx(request)
        )

    @app.get("/partials/main", response_class=HTMLResponse)
    def partial_main(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "partials/thread_detail.html", _ctx(request)
        )

    @app.get("/partials/gate", response_class=HTMLResponse)
    def partial_gate(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "partials/gate.html", _ctx(request))

    @app.post("/threads", response_class=HTMLResponse)
    def create_thread(
        request: Request,
        title: str = Form(...),
        description: str = Form(""),
    ) -> HTMLResponse:
        thread = _svc().create(title, description)
        return workspace(request, {"notice": f"angelegt: {thread.title}"})

    @app.post("/threads/{thread_id}/switch", response_class=HTMLResponse)
    def switch_thread(thread_id: str, request: Request) -> HTMLResponse:
        _svc().switch(thread_id)
        return workspace(request)

    @app.post("/threads/{thread_id}/note", response_class=HTMLResponse)
    def set_note(
        thread_id: str,
        request: Request,
        text: str = Form(""),
        append: str = Form(""),
    ) -> HTMLResponse:
        _svc().set_note(text, thread_id, append=bool(append))
        return workspace(request, {"notice": "Notiz gespeichert"})

    @app.post("/threads/{thread_id}/describe", response_class=HTMLResponse)
    def set_description(
        thread_id: str,
        request: Request,
        text: str = Form(""),
    ) -> HTMLResponse:
        _svc().set_description(text, thread_id)
        return workspace(request, {"notice": "Beschreibung gespeichert"})

    @app.post("/threads/{thread_id}/status", response_class=HTMLResponse)
    def set_status(
        thread_id: str,
        request: Request,
        status: str = Form(...),
    ) -> HTMLResponse:
        thread = _svc().set_status(status, thread_id)
        return workspace(request, {"notice": f"Status: {thread.status}"})

    @app.post("/threads/{thread_id}/snapshot", response_class=HTMLResponse)
    def save_snapshot(
        thread_id: str,
        request: Request,
        label: str = Form(""),
    ) -> HTMLResponse:
        snap = _svc().snapshot(label, thread_id)
        return workspace(request, {"notice": f"Snapshot {snap.id}"})

    @app.post("/snapshots/{snap_id}/restore", response_class=HTMLResponse)
    def restore_snapshot(snap_id: str, request: Request) -> HTMLResponse:
        thread = _svc().restore(snap_id)
        return workspace(request, {"notice": f"geladen: {thread.current_snapshot_id}"})

    @app.post("/gate/freeze", response_class=HTMLResponse)
    def freeze_gate(request: Request, frozen: str = Form(...)) -> HTMLResponse:
        status = _svc().gate_freeze(frozen == "1")
        label = "Gate frozen" if status["frozen"] else "Gate offen"
        return workspace(request, {"notice": label})

    return app


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port, log_level="info")
