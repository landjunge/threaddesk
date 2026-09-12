"""Local ThreadDesk UI. Talks only to ThreadService. Never executes."""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ThreadDeskError
from threaddesk.core import i18n
from threaddesk.core.models import (
    NODE_KINDS,
    NODE_STATUSES,
    RELATION_KINDS,
    STATUSES,
    Thread,
)
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


def _last_packet(svc: ThreadService, thread: Thread | None) -> dict | None:
    if thread is None:
        return None
    files = [
        svc.store.root / name for name in ("gnom.json", "handoff.json", "grok.json")
    ]
    files = [p for p in files if p.exists()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("thread_id") == thread.id:
            return data
    return None


LANGUAGE_COOKIE = "threaddesk_lang"
REGISTER_COOKIE = "threaddesk_register"


def _language(request: Request) -> str:
    """Sprache fuer diese Anfrage. Reihenfolge: ?lang=, Cookie, Browser."""
    chosen = request.query_params.get("lang")
    if chosen:
        return i18n.normalise(chosen)
    cookie = request.cookies.get(LANGUAGE_COOKIE)
    if cookie:
        return i18n.normalise(cookie)
    return i18n.from_accept_header(request.headers.get("accept-language"))


def _register(request: Request) -> str:
    """Sprachebene fuer diese Anfrage. Reihenfolge: ?mode=, Cookie, Klartext.

    Anders als bei der Sprache fragen wir den Browser nicht: Klartext ist der
    Normalfall fuer alle, und wer Fachwoerter will, sagt es einmal.
    """
    chosen = request.query_params.get("mode")
    if chosen:
        return i18n.normalise_register(chosen)
    return i18n.normalise_register(request.cookies.get(REGISTER_COOKIE))


def _ctx(request: Request, extra: dict | None = None) -> dict:
    svc = _svc()
    current = svc.current()
    snapshots = svc.snapshots(current.id) if current else []
    extra = extra or {}
    lang = _language(request)
    data = {
        "request": request,
        "lang": lang,
        "register": _register(request),
        "threads": svc.list(include_archived=False),
        "current": current,
        "current_id": svc.store.get_current_id(),
        "gate": svc.gate(),
        "snapshots": snapshots,
        "statuses": WRITE_STATUSES,
        "packet": extra.get("packet") or _last_packet(svc, current),
        "prompt_preview": None,
        "error": None,
        "notice": None,
    }
    data.update(extra)
    return data


def create_app() -> FastAPI:
    app = FastAPI(title="ThreadDesk", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    # Kein sichtbarer Text gehoert direkt ins Template — nur Schluessel.
    @pass_context
    def _t(context, key: str, **values: object) -> str:
        return i18n.translate(key, context.get("lang") or i18n.DEFAULT_LANGUAGE,
                              context.get("register") or i18n.DEFAULT_REGISTER,
                              **values)

    templates.env.globals["t"] = _t
    templates.env.globals["languages"] = i18n.LANGUAGES
    templates.env.globals["language_names"] = i18n.LANGUAGE_NAMES
    templates.env.globals["registers"] = i18n.REGISTERS
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

    @app.get("/lang/{code}", response_class=RedirectResponse)
    def switch_language(code: str, request: Request) -> RedirectResponse:
        """Merkt die Sprache und kehrt dorthin zurueck, wo der Nutzer war."""
        target = request.headers.get("referer") or "/"
        response = RedirectResponse(target, status_code=303)
        response.set_cookie(
            LANGUAGE_COOKIE, i18n.normalise(code),
            max_age=60 * 60 * 24 * 365, samesite="lax",
        )
        return response

    @app.get("/mode/{value}", response_class=RedirectResponse)
    def switch_register(value: str, request: Request) -> RedirectResponse:
        """Merkt die Sprachebene — Klartext oder Fachsprache."""
        target = request.headers.get("referer") or "/"
        response = RedirectResponse(target, status_code=303)
        response.set_cookie(
            REGISTER_COOKIE, i18n.normalise_register(value),
            max_age=60 * 60 * 24 * 365, samesite="lax",
        )
        return response

    @app.get("/api/graph", response_class=JSONResponse)
    def graph(kind: str | None = None, status: str | None = None) -> dict:
        return _svc().graph(kind=kind, status=status)

    @app.get("/map", response_class=HTMLResponse)
    def map_view(request: Request) -> HTMLResponse:
        lang = _language(request)
        register = _register(request)
        return templates.TemplateResponse(request, "map.html", {
            "request": request,
            "lang": lang,
            "register": register,
            "map_strings": json.dumps(
                i18n.catalog_for(lang, register), ensure_ascii=False),
        })

    @app.get("/knowledge", response_class=HTMLResponse)
    def knowledge(
        request: Request, kind: str | None = None, status: str | None = None
    ) -> HTMLResponse:
        svc = _svc()
        graph_data = svc.graph(kind=kind, status=status)
        node_ids = {node["id"] for node in graph_data["nodes"]}
        nodes = [node for node in svc.list_nodes() if node.id in node_ids]
        relation_ids = {relation["id"] for relation in graph_data["relations"]}
        relations = [
            relation
            for relation in svc.list_relations()
            if relation.id in relation_ids
        ]
        return templates.TemplateResponse(
            request,
            "knowledge.html",
            {
                "request": request,
                "lang": _language(request),
                "nodes": nodes,
                "relations": relations,
                "transitions_by_node": {
                    node.id: svc.allowed_node_transitions(node.id) for node in nodes
                },
                "node_kinds": NODE_KINDS,
                "node_statuses": NODE_STATUSES,
                "relation_kinds": RELATION_KINDS,
                "active_kind": graph_data["filters"]["kind"],
                "active_status": graph_data["filters"]["status"],
            },
        )

    @app.post("/knowledge/nodes", response_class=RedirectResponse)
    def create_knowledge_node(
        kind: str = Form(...),
        title: str = Form(...),
        status: str = Form("idea"),
        details: str = Form(""),
    ) -> RedirectResponse:
        _svc().create_node(kind, title, status=status, details=details)
        return RedirectResponse("/knowledge", status_code=303)

    @app.post("/knowledge/relations", response_class=RedirectResponse)
    def create_knowledge_relation(
        source_id: str = Form(...),
        target_id: str = Form(...),
        kind: str = Form(...),
    ) -> RedirectResponse:
        _svc().connect(source_id, target_id, kind)
        return RedirectResponse("/knowledge", status_code=303)

    @app.post(
        "/knowledge/nodes/{node_id}/transition", response_class=RedirectResponse
    )
    def transition_knowledge_node(
        node_id: str,
        status: str = Form(...),
        expected_revision: int = Form(...),
    ) -> RedirectResponse:
        _svc().transition_node(
            node_id, status, expected_revision=expected_revision
        )
        return RedirectResponse("/knowledge", status_code=303)

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

    @app.post("/threads/{thread_id}/rename", response_class=HTMLResponse)
    def rename_thread(
        thread_id: str,
        request: Request,
        title: str = Form(...),
    ) -> HTMLResponse:
        thread = _svc().rename(thread_id, title)
        return workspace(request, {"notice": f"umbenannt: {thread.title}"})

    @app.post("/threads/{thread_id}/files", response_class=HTMLResponse)
    def add_file(
        thread_id: str,
        request: Request,
        path: str = Form(...),
    ) -> HTMLResponse:
        _svc().add_file(path, thread_id)
        return workspace(request, {"notice": f"Datei: {path.strip()}"})

    @app.post("/threads/{thread_id}/files/remove", response_class=HTMLResponse)
    def remove_file(
        thread_id: str,
        request: Request,
        path: str = Form(...),
    ) -> HTMLResponse:
        _svc().remove_file(path, thread_id)
        return workspace(request, {"notice": "Pfad entfernt"})

    @app.post("/threads/{thread_id}/prompt", response_class=HTMLResponse)
    def preview_prompt(
        thread_id: str,
        request: Request,
        target: str = Form("gnom"),
        variant: str = Form("detailed"),
        save: str = Form(""),
    ) -> HTMLResponse:
        text = _svc().prompt(target, variant, thread_id, save=bool(save))
        notice = "Prompt gespeichert" if save else "Prompt-Vorschau"
        return workspace(request, {"notice": notice, "prompt_preview": text})

    @app.post("/threads/{thread_id}/archive", response_class=HTMLResponse)
    def archive_thread(thread_id: str, request: Request) -> HTMLResponse:
        thread = _svc().archive(thread_id)
        return workspace(request, {"notice": f"archiviert: {thread.title}"})

    @app.post("/threads/{thread_id}/handoff", response_class=HTMLResponse)
    def write_handoff(thread_id: str, request: Request) -> HTMLResponse:
        payload = _svc().handoff(thread_id)
        return workspace(
            request,
            {"notice": "Handoff geschrieben · nicht gesendet", "packet": payload},
        )

    @app.post("/threads/{thread_id}/gnom", response_class=HTMLResponse)
    def write_gnom(thread_id: str, request: Request) -> HTMLResponse:
        packet = _svc().gnom("brainstorm", "detailed", thread_id)
        return workspace(
            request,
            {"notice": "Gnom-Paket geschrieben · nicht gestartet", "packet": packet},
        )

    @app.post("/threads/{thread_id}/grok", response_class=HTMLResponse)
    def write_grok(thread_id: str, request: Request) -> HTMLResponse:
        packet = _svc().grok("brainstorm", "detailed", thread_id)
        return workspace(
            request,
            {"notice": "Grok-Paket geschrieben · nicht gestartet", "packet": packet},
        )

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
