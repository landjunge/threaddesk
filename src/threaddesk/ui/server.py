"""Local ThreadDesk UI. Talks only to ThreadService. Never executes."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ThreadDeskError
from threaddesk.storage.json_store import JsonStore

HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = HERE / "templates"
STATIC_DIR = HERE / "static"


def _svc() -> ThreadService:
    home = os.environ.get("THREADDESK_HOME")
    if home:
        return ThreadService(store=JsonStore(Path(home)))
    return ThreadService()


def _ctx(request: Request, extra: dict | None = None) -> dict:
    svc = _svc()
    data = {
        "request": request,
        "threads": svc.list(include_archived=False),
        "current": svc.current(),
        "current_id": svc.store.get_current_id(),
        "gate": svc.gate(),
        "error": None,
    }
    if extra:
        data.update(extra)
    return data


def create_app() -> FastAPI:
    app = FastAPI(title="ThreadDesk", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.exception_handler(ThreadDeskError)
    async def _on_error(request: Request, exc: ThreadDeskError) -> HTMLResponse:
        html = templates.TemplateResponse(
            request,
            "partials/workspace.html",
            _ctx(request, {"error": str(exc)}),
        )
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

    @app.post("/threads/{thread_id}/switch", response_class=HTMLResponse)
    def switch_thread(thread_id: str, request: Request) -> HTMLResponse:
        _svc().switch(thread_id)
        return templates.TemplateResponse(
            request, "partials/workspace.html", _ctx(request)
        )

    return app


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port, log_level="info")
