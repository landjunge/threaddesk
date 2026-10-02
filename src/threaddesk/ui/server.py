"""Local ThreadDesk UI. Talks only to ThreadService. Never executes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import InvalidState, NotFound, ThreadDeskError
from threaddesk.services.actors import ActorRegistry
from threaddesk.services.hausmeister import SURFACE_KINDS, Hausmeister, live_snapshot, note_activity
from threaddesk.services.room_sync import RoomBook
from threaddesk.services.ollama_local import OllamaError
from threaddesk.core import i18n
from threaddesk.core.models import (
    ENTRY_TYPES,
    NODE_KINDS,
    NODE_STATUSES,
    RELATION_KINDS,
    STATUSES,
    Thread,
)
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.services.migration import (
    AtomicImportError,
    BundleValidationError,
    ImportBlocked,
    ImportOutcomeUncertain,
    MigrationPreviewService,
    MigrationReviewService,
)

HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = HERE / "templates"
STATIC_DIR = HERE / "static"
WRITE_STATUSES = tuple(s for s in STATUSES if s != "archived")
_BOARD_FIELDS = {
    "actor",
    "actor_type",
    "entry_type",
    "content",
    "task_id",
    "handoff_id",
    "run_id",
    "metadata",
    "external_key",
    "created_at",
}


def _svc() -> ThreadService:
    home = os.environ.get("THREADDESK_HOME")
    root = Path(home) if home else None
    if os.environ.get("THREADDESK_STORAGE") == "sqlite":
        return ThreadService(store=SQLiteStore(root))
    if root:
        return ThreadService(store=JsonStore(root))
    return ThreadService()


def _last_packet(svc: ThreadService, thread: Thread | None) -> dict | None:
    if thread is None:
        return None
    files = [
        svc.store.artifact_path(name)
        for name in ("gnom.json", "handoff.json", "grok.json")
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


def _browser_strings(language: str, register: str) -> str:
    return json.dumps(
        {
            key: value
            for key, value in i18n.catalog_for(language, register).items()
            if key.startswith("browser.")
        },
        ensure_ascii=False,
    )


def _hausmeister_status(store) -> dict:
    try:
        return Hausmeister(store).status()
    except (ThreadDeskError, OSError, ValueError):
        return {
            "enabled": False,
            "model": "",
            "models": [],
            "ollama_ok": False,
            "actor_id": "",
            "agent_type": "",
            "kind": "",
            "phase": "off",
        }


def _linked_nodes(svc: ThreadService, thread: Thread | None) -> list:
    if thread is None:
        return []
    return [
        node for node in svc.list_nodes()
        if isinstance(node.metadata, dict) and node.metadata.get("thread_id") == thread.id
    ]


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
        "browser_strings": _browser_strings(lang, _register(request)),
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
        "whiteboard": svc.whiteboard(current.id) if current else [],
        "stand": svc.working_stand(current.id) if current else None,
        "whiteboard_types": ENTRY_TYPES,
        "actor_marks": ActorRegistry(svc.store).marks(),
        "linked_nodes": _linked_nodes(svc, current),
        "focus_node": "",
        "hausmeister": _hausmeister_status(svc.store),
        "room": RoomBook(svc.store).view(),
    }
    if current is not None:
        chosen = request.query_params.get("node") or ""
        if any(node.id == chosen for node in data["linked_nodes"]):
            data["focus_node"] = chosen
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
        try:
            note_activity(_svc().store)
        except OSError:
            pass
        return templates.TemplateResponse(
            request, "partials/workspace.html", _ctx(request, extra)
        )

    @app.exception_handler(ThreadDeskError)
    async def _on_error(request: Request, exc: ThreadDeskError) -> Response:
        if request.url.path.startswith("/api/"):
            status = 404 if isinstance(exc, NotFound) else 400
            return JSONResponse(
                {"error": type(exc).__name__, "detail": str(exc)},
                status_code=status,
            )
        html = workspace(
            request, {"error": i18n.translate("ui.error", _language(request))}
        )
        html.status_code = 400
        return html

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, thread: str | None = None) -> HTMLResponse:
        if thread:
            try:
                _svc().switch(thread)
            except ThreadDeskError:
                pass
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

    @app.get("/api/threads/{thread_id}", response_class=JSONResponse)
    def api_thread(thread_id: str) -> dict:
        svc = _svc()
        thread = svc.get(thread_id)
        return {"thread": thread.to_dict(), "stand": svc.working_stand(thread.id)}

    @app.get("/api/threads/{thread_id}/whiteboard", response_class=JSONResponse)
    def api_whiteboard(thread_id: str) -> dict:
        svc = _svc()
        thread = svc.get(thread_id)
        return {
            "thread_id": thread.id,
            "entries": [entry.to_dict() for entry in svc.whiteboard(thread.id)],
        }

    @app.post("/api/threads/{thread_id}/whiteboard", response_class=JSONResponse)
    async def api_append_whiteboard(thread_id: str, request: Request) -> dict:
        try:
            body = await request.json()
        except Exception as exc:
            raise InvalidState("whiteboard_body") from exc
        if not isinstance(body, dict) or set(body) - _BOARD_FIELDS:
            raise InvalidState("whiteboard_fields")
        if not {"actor", "actor_type", "entry_type", "content"} <= set(body):
            raise InvalidState("whiteboard_fields")
        return _svc().append_whiteboard(thread_id, **body)

    @app.get("/api/threads/{thread_id}/stand", response_class=JSONResponse)
    def api_stand(thread_id: str) -> dict:
        return _svc().working_stand(thread_id)

    @app.get("/map", response_class=HTMLResponse)
    def map_view(request: Request) -> HTMLResponse:
        lang = _language(request)
        register = _register(request)
        return templates.TemplateResponse(request, "map.html", {
            "request": request,
            "lang": lang,
            "register": register,
            "browser_strings": _browser_strings(lang, register),
            "map_strings": json.dumps(
                i18n.catalog_for(lang, register), ensure_ascii=False),
            "actor_marks_json": json.dumps(
                ActorRegistry(_svc().store).marks(), ensure_ascii=False),
        })

    @app.get("/migration", response_class=HTMLResponse)
    def migration(request: Request) -> HTMLResponse:
        lang = _language(request)
        register = _register(request)
        return templates.TemplateResponse(request, "migration.html", {
            "request": request, "lang": lang, "register": register,
            "browser_strings": _browser_strings(lang, register),
        })

    @app.post("/api/migration/dry-run", response_class=JSONResponse)
    async def migration_dry_run(bundle: UploadFile = File(...)) -> dict:
        """Validate and plan only; import requires the separate confirm route."""
        if not bundle.filename or not bundle.filename.lower().endswith(".tdbundle"):
            raise HTTPException(status_code=400, detail="bundle_file")
        with tempfile.TemporaryDirectory(prefix="threaddesk-preview-") as temporary:
            path = Path(temporary) / "bundle.tdbundle"
            size = 0
            with path.open("wb") as output:
                while chunk := await bundle.read(1024 * 1024):
                    size += len(chunk)
                    if size > 128 * 1024 * 1024:
                        raise HTTPException(status_code=413, detail="bundle_upload_size")
                    output.write(chunk)
            try:
                store = _svc().store
                if isinstance(store, SQLiteStore):
                    return MigrationReviewService(store).stage(path)
                result = MigrationPreviewService(store).inspect(path)
                return {**result, "can_confirm_import": False,
                    "blockers": sorted(set(result["blockers"]) | {"sqlite_storage_not_active"})}
            except BundleValidationError as exc:
                raise HTTPException(status_code=400, detail=exc.code) from exc
            finally:
                await bundle.close()

    @app.post("/api/migration/confirm", response_class=JSONResponse)
    async def migration_confirm(
        bundle_sha256: str = Form(...),
        resolutions_json: str = Form("{}"),
    ) -> dict:
        """Commit only a previously reviewed immutable bundle."""
        store = _svc().store
        if not isinstance(store, SQLiteStore):
            raise HTTPException(status_code=409, detail="sqlite_storage_not_active")
        try:
            resolutions = json.loads(resolutions_json)
            if not isinstance(resolutions, dict):
                raise ValueError("resolution_format")
            return MigrationReviewService(store).commit(
                bundle_sha256,
                resolutions=resolutions,
            )
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="resolution_format") from exc
        except (BundleValidationError, ImportBlocked, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc).split(":", 1)[0]) from exc
        except ImportOutcomeUncertain as exc:
            return JSONResponse(status_code=202, content={"status": "uncertain", "batch_id": exc.batch_id})
        except AtomicImportError as exc:
            raise HTTPException(status_code=400, detail=str(exc).split(":", 1)[0]) from exc

    @app.post("/api/migration/recover", response_class=JSONResponse)
    async def migration_recover(batch_id: str = Form(...)) -> dict:
        """Prepare a verified recovery copy without overwriting the live workspace."""
        store = _svc().store
        if not isinstance(store, SQLiteStore):
            raise HTTPException(status_code=409, detail="sqlite_storage_not_active")
        try:
            path = MigrationReviewService(store).recover(batch_id)
            return {"status": "recovered_copy", "batch_id": batch_id, "path": str(path)}
        except AtomicImportError as exc:
            raise HTTPException(status_code=400, detail=str(exc).split(":", 1)[0]) from exc

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
        lang = _language(request)
        register = _register(request)
        return templates.TemplateResponse(
            request,
            "knowledge.html",
            {
                "request": request,
                "lang": lang,
                "register": register,
                "browser_strings": _browser_strings(lang, register),
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
        return workspace(request, {"notice": i18n.translate("ui.created", _language(request), title=thread.title)})

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
        return workspace(request, {"notice": i18n.translate("ui.note_saved", _language(request))})

    @app.post("/threads/{thread_id}/whiteboard", response_class=HTMLResponse)
    def append_whiteboard_form(
        thread_id: str,
        request: Request,
        actor: str = Form(...),
        actor_type: str = Form("human"),
        entry_type: str = Form("note"),
        content: str = Form(...),
        next_step: str = Form(""),
        in_room: str = Form(""),
    ) -> HTMLResponse:
        metadata = {"next_step": next_step.strip()} if next_step.strip() else {}
        fields: dict = {
            "actor": actor,
            "actor_type": actor_type,
            "entry_type": entry_type,
            "content": content,
            "metadata": metadata,
        }
        if in_room == "1":
            current_room = RoomBook(_svc().store).view().get("current")
            if current_room:
                fields["room_id"] = current_room["id"]
        _svc().append_whiteboard(thread_id, **fields)
        return workspace(
            request,
            {"notice": i18n.translate("ui.whiteboard_saved", _language(request))},
        )

    def _hausmeister_notice(request: Request, code: str) -> HTMLResponse:
        key = {
            "module_disabled": "hausmeister.disabled",
            "ollama_unavailable": "hausmeister.unreachable",
            "ollama_model_missing": "hausmeister.no_model",
            "hausmeister_rejected": "hausmeister.failed",
        }.get(code, "hausmeister.failed")
        page = workspace(request, {"error": i18n.translate(key, _language(request))})
        page.status_code = 400
        return page

    @app.post("/hausmeister/toggle", response_class=HTMLResponse)
    def hausmeister_toggle(request: Request, enabled: str = Form("0")) -> HTMLResponse:
        Hausmeister(_svc().store).set_enabled(enabled == "1")
        key = "hausmeister.turn_on" if enabled == "1" else "hausmeister.turn_off"
        return workspace(request, {"notice": i18n.translate(key, _language(request))})

    @app.post("/hausmeister/model", response_class=HTMLResponse)
    def hausmeister_model(request: Request, model: str = Form("")) -> HTMLResponse:
        try:
            Hausmeister(_svc().store).set_model(model)
        except OllamaError as exc:
            return _hausmeister_notice(request, str(exc))
        return workspace(request, {"notice": i18n.translate("hausmeister.use_model", _language(request))})

    @app.post("/threads/{thread_id}/hausmeister", response_class=HTMLResponse)
    def hausmeister_run(
        thread_id: str,
        request: Request,
        order: str = Form(...),
        mode: str = Form("now"),
    ) -> HTMLResponse:
        home = Hausmeister(_svc().store)
        try:
            if mode == "later":
                result = home.enqueue(thread_id, order)
                if not result["ok"]:
                    return _hausmeister_notice(request, result["error"])
                return workspace(request, {"notice": i18n.translate("hausmeister.queued", _language(request))})
            result = home.run_now(thread_id, order)
        except ThreadDeskError as exc:
            return _hausmeister_notice(request, str(exc))
        if not result["ok"]:
            return _hausmeister_notice(request, result["error"])
        return workspace(request, {"notice": i18n.translate("hausmeister.done", _language(request))})

    @app.post("/hausmeister/activity")
    async def hausmeister_activity(request: Request) -> JSONResponse:
        """One throttled ping from the open desk. Not a poll."""
        try:
            raw = await request.json()
        except Exception:
            raw = None
        kind = raw.get("kind") if isinstance(raw, dict) else None
        if not isinstance(kind, str) or kind not in SURFACE_KINDS:
            return JSONResponse({"ok": False}, status_code=400)
        try:
            recorded = note_activity(_svc().store, kind=kind)
        except OSError:
            return JSONResponse({"ok": False}, status_code=400)
        return JSONResponse({"ok": True, "recorded": recorded})

    def _room_page(request: Request, key: str, **values: object) -> HTMLResponse:
        return workspace(request, {"notice": i18n.translate(key, _language(request), **values)})

    def _room_error(request: Request) -> HTMLResponse:
        page = workspace(request, {"error": i18n.translate("room.failed", _language(request))})
        page.status_code = 400
        return page

    @app.post("/rooms", response_class=HTMLResponse)
    def create_room(request: Request, name: str = Form(...)) -> HTMLResponse:
        try:
            RoomBook(_svc().store).create_room(name)
        except ThreadDeskError:
            return _room_error(request)
        return _room_page(request, "room.created")

    @app.post("/rooms/select", response_class=HTMLResponse)
    def select_room(request: Request, room_id: str = Form(...)) -> HTMLResponse:
        try:
            RoomBook(_svc().store).select_room(room_id)
        except ThreadDeskError:
            return _room_error(request)
        return _room_page(request, "room.choose")

    @app.post("/rooms/invite", response_class=HTMLResponse)
    def invite_room(request: Request) -> HTMLResponse:
        try:
            code = RoomBook(_svc().store).invite()
        except ThreadDeskError:
            return _room_error(request)
        return _room_page(request, "room.invited", code=code)

    @app.post("/rooms/join", response_class=HTMLResponse)
    def join_room(
        request: Request,
        code: str = Form(...),
        base_url: str = Form(...),
    ) -> HTMLResponse:
        try:
            RoomBook(_svc().store).join(code, base_url, str(request.base_url))
        except ThreadDeskError as exc:
            if str(exc) == "room_offline":
                return _room_page(request, "room.state.peer_down")
            return _room_error(request)
        return _room_page(request, "room.paired")

    @app.post("/rooms/sync", response_class=HTMLResponse)
    def sync_room(request: Request) -> HTMLResponse:
        try:
            result = RoomBook(_svc().store).sync()
        except ThreadDeskError:
            return _room_error(request)
        return _room_page(request, f"room.state.{result['state']}")

    @app.post("/api/rooms/pair")
    async def pair_room(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            return JSONResponse({"ok": False}, status_code=403)
        try:
            result = RoomBook(_svc().store).accept(
                str(body.get("code") or ""),
                str(body.get("instance_id") or ""),
                str(body.get("base_url") or ""),
            )
        except ThreadDeskError:
            return JSONResponse({"ok": False}, status_code=403)
        return JSONResponse(result)

    @app.post("/api/rooms/pull")
    async def pull_room(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            body = None
        room_id = body.get("room_id") if isinstance(body, dict) else ""
        try:
            result = RoomBook(_svc().store).serve_pull(
                request.headers.get("x-threaddesk-instance", ""),
                request.headers.get("x-threaddesk-token", ""),
                str(room_id or ""),
            )
        except ThreadDeskError:
            return JSONResponse({"ok": False}, status_code=403)
        return JSONResponse(result)

    @app.post("/api/rooms/push")
    async def push_room(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            body = None
        try:
            result = RoomBook(_svc().store).serve_push(
                request.headers.get("x-threaddesk-instance", ""),
                request.headers.get("x-threaddesk-token", ""),
                body,
            )
        except ThreadDeskError:
            return JSONResponse({"ok": False}, status_code=403)
        return JSONResponse(result)

    @app.post("/threads/{thread_id}/describe", response_class=HTMLResponse)
    def set_description(
        thread_id: str,
        request: Request,
        text: str = Form(""),
    ) -> HTMLResponse:
        _svc().set_description(text, thread_id)
        return workspace(request, {"notice": i18n.translate("ui.description_saved", _language(request))})

    @app.post("/threads/{thread_id}/status", response_class=HTMLResponse)
    def set_status(
        thread_id: str,
        request: Request,
        status: str = Form(...),
    ) -> HTMLResponse:
        thread = _svc().set_status(status, thread_id)
        return workspace(request, {"notice": i18n.translate("ui.status_saved", _language(request), status=thread.status)})

    @app.post("/threads/{thread_id}/snapshot", response_class=HTMLResponse)
    def save_snapshot(
        thread_id: str,
        request: Request,
        label: str = Form(""),
    ) -> HTMLResponse:
        snap = _svc().snapshot(label, thread_id)
        return workspace(request, {"notice": i18n.translate("ui.snapshot_saved", _language(request), id=snap.id)})

    @app.post("/threads/{thread_id}/rename", response_class=HTMLResponse)
    def rename_thread(
        thread_id: str,
        request: Request,
        title: str = Form(...),
    ) -> HTMLResponse:
        thread = _svc().rename(thread_id, title)
        return workspace(request, {"notice": i18n.translate("ui.renamed", _language(request), title=thread.title)})

    @app.post("/threads/{thread_id}/files", response_class=HTMLResponse)
    def add_file(
        thread_id: str,
        request: Request,
        path: str = Form(...),
    ) -> HTMLResponse:
        _svc().add_file(path, thread_id)
        return workspace(request, {"notice": i18n.translate("ui.file_added", _language(request), path=path.strip())})

    @app.post("/threads/{thread_id}/files/remove", response_class=HTMLResponse)
    def remove_file(
        thread_id: str,
        request: Request,
        path: str = Form(...),
    ) -> HTMLResponse:
        _svc().remove_file(path, thread_id)
        return workspace(request, {"notice": i18n.translate("ui.file_removed", _language(request))})

    @app.post("/threads/{thread_id}/prompt", response_class=HTMLResponse)
    def preview_prompt(
        thread_id: str,
        request: Request,
        target: str = Form("gnom"),
        variant: str = Form("detailed"),
        save: str = Form(""),
    ) -> HTMLResponse:
        text = _svc().prompt(target, variant, thread_id, save=bool(save))
        notice = i18n.translate(
            "ui.prompt_saved" if save else "ui.prompt_preview", _language(request)
        )
        return workspace(request, {"notice": notice, "prompt_preview": text})

    @app.post("/threads/{thread_id}/archive", response_class=HTMLResponse)
    def archive_thread(thread_id: str, request: Request) -> HTMLResponse:
        thread = _svc().archive(thread_id)
        return workspace(request, {"notice": i18n.translate("ui.archived", _language(request), title=thread.title)})

    @app.post("/threads/{thread_id}/handoff", response_class=HTMLResponse)
    def write_handoff(thread_id: str, request: Request) -> HTMLResponse:
        payload = _svc().handoff(thread_id)
        return workspace(
            request,
            {"notice": i18n.translate("ui.handoff_written", _language(request)), "packet": payload},
        )

    @app.post("/threads/{thread_id}/gnom", response_class=HTMLResponse)
    def write_gnom(thread_id: str, request: Request) -> HTMLResponse:
        packet = _svc().gnom("brainstorm", "detailed", thread_id)
        return workspace(
            request,
            {"notice": i18n.translate("ui.gnom_written", _language(request)), "packet": packet},
        )

    @app.post("/threads/{thread_id}/grok", response_class=HTMLResponse)
    def write_grok(thread_id: str, request: Request) -> HTMLResponse:
        packet = _svc().grok("brainstorm", "detailed", thread_id)
        return workspace(
            request,
            {"notice": i18n.translate("ui.grok_written", _language(request)), "packet": packet},
        )

    @app.post("/snapshots/{snap_id}/restore", response_class=HTMLResponse)
    def restore_snapshot(snap_id: str, request: Request) -> HTMLResponse:
        thread = _svc().restore(snap_id)
        return workspace(request, {"notice": i18n.translate("ui.snapshot_loaded", _language(request), id=thread.current_snapshot_id)})

    @app.post("/gate/freeze", response_class=HTMLResponse)
    def freeze_gate(request: Request, frozen: str = Form(...)) -> HTMLResponse:
        status = _svc().gate_freeze(frozen == "1")
        label = i18n.translate(
            "ui.gate_closed" if status["frozen"] else "ui.gate_opened",
            _language(request),
        )
        return workspace(request, {"notice": label})

    return app


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    import threading
    import time
    import uvicorn

    def _idle() -> None:
        while True:
            time.sleep(60)
            try:
                store = ThreadService().store
                Hausmeister(store).tick(live_snapshot(store))
            except Exception:
                continue

    threading.Thread(target=_idle, name="hausmeister-idle", daemon=True).start()
    uvicorn.run(create_app(), host=host, port=port, log_level="info")
