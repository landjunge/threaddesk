"""Local ThreadDesk UI. Talks only to ThreadService. Never executes."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import tempfile
from typing import Optional
from urllib.parse import parse_qs, urlsplit

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from threaddesk.ui.http_access import LocalHTTPAccess, require_ui_csrf, safe_return_path
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context

from threaddesk.api.service import ThreadService
from threaddesk.build_info import BUILD_DESCRIPTION, BUILD_ID, BUILD_LABEL
from threaddesk.core.errors import InvalidState, NotFound, ThreadDeskError
from threaddesk.services.actors import ActorRegistry
from threaddesk.services.hausmeister import SURFACE_KINDS, Hausmeister, live_snapshot, note_activity
from threaddesk.services.room_sync import RoomBook
from threaddesk.server_sync.desktop import install_routes as install_sync_routes, record_owner_reference
from threaddesk.server_sync.store import SyncError
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
from threaddesk.storage.portable_backup import base_root, selected_profile, download_backup, restore_backup, LIMIT, profiles, activate_profile
from threaddesk.storage.workspace_backup import BackupError
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.services.library_bridge import contract as library_bridge_contract
from threaddesk.services.library_commands import execute as execute_library_command
from threaddesk.services.library_import import LibraryImportError, LibraryImporter
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
    root, backend = selected_profile(base_root())
    if (backend or os.environ.get("THREADDESK_STORAGE")) == "sqlite":
        return ThreadService(store=SQLiteStore(root))
    return ThreadService(store=JsonStore(root))


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
    """Keep a saved preference, then this view's choice, then browser language."""
    cookie = request.cookies.get(LANGUAGE_COOKIE)
    if cookie in i18n.LANGUAGES:
        return cookie
    chosen = request.query_params.get("lang")
    if chosen:
        return i18n.normalise(chosen)
    chosen = request.headers.get("x-threaddesk-view-language") or _view_choice(request, "lang")
    if chosen:
        return i18n.normalise(chosen)
    return i18n.from_accept_header(request.headers.get("accept-language"))


def _view_choice(request: Request, key: str) -> str | None:
    """Read transient display context only from a validated local Referer."""
    values = parse_qs(urlsplit(safe_return_path(request)).query).get(key)
    return values[0] if values else None


def _register(request: Request) -> str:
    """Keep a saved register, then the current view, then the plain default.

    Anders als bei der Sprache fragen wir den Browser nicht: Klartext ist der
    Normalfall fuer alle, und wer Fachwoerter will, sagt es einmal.
    """
    cookie = request.cookies.get(REGISTER_COOKIE)
    if cookie in i18n.REGISTERS:
        return cookie
    chosen = (request.query_params.get("mode")
              or request.headers.get("x-threaddesk-view-register")
              or _view_choice(request, "mode"))
    if chosen:
        return i18n.normalise_register(chosen)
    return i18n.DEFAULT_REGISTER


def _browser_strings(language: str, register: str) -> str:
    return json.dumps(
        {
            key: value
            for key, value in i18n.catalog_for(language, register).items()
            if key.startswith("browser.")
        },
        ensure_ascii=False,
    )


def _hausmeister_status(store, model_status: dict | None = None) -> dict:
    try:
        return Hausmeister(store).status(model_status=model_status)
    except (ThreadDeskError, OSError, ValueError):
        return {
            "enabled": False,
            "model": "",
            "models": [],
            "ollama_ok": None,
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


def _return_review_states(svc, current, entries):
    """Project current-thread decision labels only; never render another return."""
    refs = {entry.metadata.get("return_id") for entry in entries if isinstance(entry.metadata.get("return_id"), str)}
    if current is None or not refs:
        return {}
    states = {}
    for item in svc.returns():
        payload = item.get("return") or {}
        identity = payload.get("return_id")
        if identity not in refs or payload.get("thread_id") != current.id:
            continue
        decision = item.get("decision") or {}
        choice = decision.get("choice")
        states[identity] = choice if choice in {"accepted", "rejected", "rework"} else "unverified" if not decision else "unknown"
    return states


def _ctx(request: Request, extra: dict | None = None) -> dict:
    svc = _svc()
    current = svc.current()
    selected = request.query_params.get("thread")
    if request.method == "POST" and not request.url.path.endswith("/archive"):
        selected = request.path_params.get("thread_id") or selected
    if selected:
        try:
            current = svc.get(selected)
        except ThreadDeskError:
            pass
    snapshots = svc.snapshots(current.id) if current else []
    entries = svc.whiteboard(current.id) if current else []
    extra = extra or {}
    lang = _language(request)
    data = {
        "request": request,
        "lang": lang,
        "register": _register(request),
        "browser_strings": _browser_strings(lang, _register(request)),
        "threads": svc.list(include_archived=False),
        "current": current,
        "current_id": current.id if current else None,
        "gate": svc.gate(),
        "snapshots": snapshots,
        "statuses": WRITE_STATUSES,
        "packet": extra.get("packet") or _last_packet(svc, current),
        "prompt_preview": None,
        "error": None,
        "notice": None,
        "whiteboard": entries,
        "return_review_states": _return_review_states(svc, current, entries),
        "stand": svc.working_stand(current.id) if current else None,
        "whiteboard_types": ENTRY_TYPES,
        "actor_marks": ActorRegistry(svc.store).marks(),
        "linked_nodes": _linked_nodes(svc, current),
        "focus_node": "",
        "hausmeister": _hausmeister_status(svc.store, request.app.state.hausmeister_probes.get(
            str(svc.store.artifact_path("hausmeister.json"))
        )),
        "room": RoomBook(svc.store).view(),
        "library_files": LibraryImporter(svc.store).for_thread(current.id) if current else [],
    }
    if current is not None:
        chosen = request.query_params.get("node") or ""
        if any(node.id == chosen for node in data["linked_nodes"]):
            data["focus_node"] = chosen
    data.update(extra)
    return data


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup is separate from HTTP GET. Restored/selected profiles are
        # refreshed by their protected POST actions, never by rendering a view.
        bootstrap_profile()
        app.state.server_sync_manager.start()
        try:
            yield
        finally:
            app.state.server_sync_manager.stop()

    app = FastAPI(title="ThreadDesk", docs_url=None, redoc_url=None,
                  dependencies=[Depends(require_ui_csrf)], lifespan=lifespan)
    app.state.hausmeister_probes = {}
    app.add_middleware(LocalHTTPAccess)

    def remember_probe(store, status: dict) -> None:
        key = str(store.artifact_path("hausmeister.json"))
        app.state.hausmeister_probes[key] = {
            "models": list(status.get("models", [])), "ollama_ok": status.get("ollama_ok"),
            "observed_at": status.get("observed_at"),
            "observed_monotonic": status.get("observed_monotonic"),
        }

    def bootstrap_profile() -> None:
        store = _svc().store
        try:
            # Controlled app/profile startup, before serving its GET views.
            # Keep existing identities, module enablement and grants unchanged.
            ActorRegistry(store).instance_id()
            home = Hausmeister(store)
            home.install()
            # Transport timeout 0.4s, caller budget 0.5s; late results cannot
            # alter this profile's cache or install/execute a model.
            remember_probe(store, home.probe_models())
        finally:
            if isinstance(store, SQLiteStore):
                store.connection.close()
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
    templates.env.globals.update(
        build_label=BUILD_LABEL, build_description=BUILD_DESCRIPTION, build_id=BUILD_ID,
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def workspace(request: Request, extra: dict | None = None) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "partials/workspace.html", _ctx(request, extra)
        )

    def sync_page(request: Request, extra: dict) -> HTMLResponse:
        selected = _svc().get(request.path_params['thread_id'])
        return templates.TemplateResponse(request,'server_sync.html',_ctx(request,{**extra,'current':selected}))

    install_sync_routes(app, lambda: _svc(), sync_page)

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

    app.add_exception_handler(SyncError, _on_error)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, thread: Optional[str] = None) -> HTMLResponse:
        return templates.TemplateResponse(request, "index.html", _ctx(request))

    def data_page(request: Request, **extra) -> HTMLResponse:
        active, _ = selected_profile(base_root())
        return templates.TemplateResponse(request, "data.html", _ctx(request, {
            "restored_profile": active != base_root(), "profiles": profiles(base_root()),
            "active_profile": active.name, **extra,
        }))

    @app.get("/data", response_class=HTMLResponse)
    def data_view(request: Request) -> HTMLResponse:
        return data_page(request)

    @app.post("/data/download")
    def data_download(request: Request) -> Response:
        store = _svc().store
        try:
            body = download_backup(store)
            return Response(body, media_type="application/zip", headers={
                "Content-Disposition": 'attachment;filename="ThreadDesk-backup.zip"',
                "Cache-Control": "no-store",
            })
        except BackupError:
            response = data_page(request, error=i18n.translate("data.backup_error", _language(request)))
            response.status_code = 400
            return response
        finally:
            if isinstance(store, SQLiteStore):
                store.connection.close()

    @app.post("/data/restore", response_class=HTMLResponse)
    async def data_restore(request: Request, backup: UploadFile = File(...),
                           confirm: str = Form("")) -> Response:
        try:
            if confirm != "yes":
                raise BackupError("backup_confirmation")
            body = await backup.read(LIMIT + 1)
            restore_backup(body, base_root())
            bootstrap_profile()
            return RedirectResponse("/?restored=1", status_code=303)
        except BackupError:
            response = data_page(request, error=i18n.translate("data.restore_error", _language(request)))
            response.status_code = 400
            return response
        finally:
            await backup.close()

    @app.post("/data/profile")
    def data_profile(request: Request, name: str = Form(...)) -> Response:
        try:
            activate_profile(base_root(), name)
            bootstrap_profile()
            return RedirectResponse("/", status_code=303)
        except BackupError:
            response = data_page(request, error=i18n.translate("data.restore_error", _language(request)))
            response.status_code = 400
            return response

    def library_page(request: Request, **extra) -> HTMLResponse:
        catalog = LibraryImporter(_svc().store).catalog()
        return templates.TemplateResponse(
            request, "library_import.html", _ctx(request, {"library": catalog, **extra}),
        )

    @app.get("/library", response_class=HTMLResponse)
    def library_view(request: Request) -> HTMLResponse:
        return library_page(request)

    def _library_summary(request: Request, summary: dict) -> HTMLResponse:
        notice = i18n.translate(
            "library.summary", _language(request),
            stored=summary["stored"], duplicate=summary["duplicate"], failed=summary["failed"],
        )
        return library_page(request, notice=notice)

    def _library_failure(request: Request, exc: LibraryImportError) -> HTMLResponse:
        key = f"library.error.{exc.code}"
        message = i18n.translate(key, _language(request))
        if message == key:
            message = i18n.translate("ui.error", _language(request))
        response = library_page(request, error=message)
        response.status_code = 400
        return response

    @app.post("/library/folder", response_class=HTMLResponse)
    def library_folder(request: Request, source: str = Form(...)) -> HTMLResponse:
        try:
            summary = LibraryImporter(_svc().store).import_tree(Path(source))
        except LibraryImportError as exc:
            return _library_failure(request, exc)
        return _library_summary(request, summary)

    @app.post("/library/files", response_class=HTMLResponse)
    async def library_files(request: Request, files: list[UploadFile] = File(...)) -> HTMLResponse:
        saved: list[tuple[str, Path]] = []
        with tempfile.TemporaryDirectory(prefix="threaddesk-library-upload-") as folder:
            root = Path(folder)
            try:
                for upload in files:
                    relative = upload.filename or ""
                    target = root / f"upload-{len(saved)}"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    size = 0
                    with target.open("wb") as handle:
                        while True:
                            chunk = await upload.read(1024 * 1024)
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > 256 * 1024 * 1024:
                                raise LibraryImportError("file_too_large")
                            handle.write(chunk)
                    saved.append((relative, target))
                summary = LibraryImporter(_svc().store).import_files(saved)
            except LibraryImportError as exc:
                return _library_failure(request, exc)
            finally:
                for upload in files:
                    await upload.close()
        return _library_summary(request, summary)

    @app.post("/library/package", response_class=HTMLResponse)
    async def library_package(request: Request, package: UploadFile = File(...)) -> HTMLResponse:
        with tempfile.TemporaryDirectory(prefix="threaddesk-library-zip-") as folder:
            target = Path(folder) / "package.zip"
            try:
                size = 0
                with target.open("wb") as handle:
                    while True:
                        chunk = await package.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > 256 * 1024 * 1024:
                            raise LibraryImportError("file_too_large")
                        handle.write(chunk)
                summary = LibraryImporter(_svc().store).import_zip_package(target)
            except LibraryImportError as exc:
                return _library_failure(request, exc)
            finally:
                await package.close()
        return _library_summary(request, summary)

    @app.post("/library/command", response_class=HTMLResponse)
    def library_command(request: Request, command: str = Form(...)) -> HTMLResponse:
        importer = LibraryImporter(_svc().store)
        from threaddesk.services.library_index import LibraryIndex
        index = LibraryIndex(importer.root)
        if index.status()["status"] in {"missing", "failed"}:
            importer.rebuild_index()

        def search(text: str):
            return LibraryIndex(importer.root).search(text)

        result = execute_library_command(command, search=search, reassign=importer.reassign)
        record_id = str(result.get("record_id") or "")
        if (
            result.get("ok")
            and result.get("action") == "open"
            and len(record_id) == 12
            and all(character in "0123456789abcdef" for character in record_id)
        ):
            return RedirectResponse(f"/library/files/{record_id}", status_code=303)
        if not result.get("ok"):
            code = str(result.get("error") or "unknown_command")
            key = f"library.command_error.{code}"
            message = i18n.translate(key, _language(request))
            result = {**result, "error": message if message != key else i18n.translate("ui.error", _language(request))}
        return library_page(request, command_result=result)

    @app.get("/library/bridge")
    def library_bridge() -> JSONResponse:
        return JSONResponse(library_bridge_contract())

    @app.post("/library/resume", response_class=HTMLResponse)
    def library_resume(request: Request) -> HTMLResponse:
        try:
            summary = LibraryImporter(_svc().store).resume()
        except LibraryImportError as exc:
            return _library_failure(request, exc)
        return _library_summary(request, summary)

    @app.get("/library/files/{record_id}")
    def library_open(record_id: str) -> FileResponse:
        try:
            path, record = LibraryImporter(_svc().store).open_record(record_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail="not_found") from exc
        except LibraryImportError as exc:
            raise HTTPException(status_code=409, detail=exc.code) from exc
        filename = str(record.get("filename") or "file").replace('"', "").replace("\r", "").replace("\n", "")
        return FileResponse(
            path,
            media_type=str(record.get("media_type") or "application/octet-stream"),
            filename=filename,
            content_disposition_type="attachment",
        )

    @app.post("/data/original")
    def data_original() -> Response:
        (base_root() / "active-profile.json").unlink(missing_ok=True)
        bootstrap_profile()
        return RedirectResponse("/", status_code=303)

    @app.post("/lang/{code}", response_class=RedirectResponse)
    def switch_language(code: str, request: Request) -> RedirectResponse:
        """Merkt die Sprache und kehrt dorthin zurueck, wo der Nutzer war."""
        target = safe_return_path(request, exclude_query={"lang"})
        response = RedirectResponse(target, status_code=303)
        response.set_cookie(
            LANGUAGE_COOKIE, i18n.normalise(code),
            max_age=60 * 60 * 24 * 365, samesite="lax",
        )
        return response

    @app.post("/mode/{value}", response_class=RedirectResponse)
    def switch_register(value: str, request: Request) -> RedirectResponse:
        """Merkt die Sprachebene — Klartext oder Fachsprache."""
        target = safe_return_path(request, exclude_query={"mode"})
        response = RedirectResponse(target, status_code=303)
        response.set_cookie(
            REGISTER_COOKIE, i18n.normalise_register(value),
            max_age=60 * 60 * 24 * 365, samesite="lax",
        )
        return response

    @app.get("/api/graph", response_class=JSONResponse)
    def graph(kind: Optional[str] = None, status: Optional[str] = None) -> dict:
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
        request: Request, kind: Optional[str] = None, status: Optional[str] = None
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
            room_view = RoomBook(_svc().store).view()
            current_room = room_view.get("current")
            if not current_room or room_view.get("role") not in {"owner", "member"}:
                page = _room_error(request)
                page.status_code = 403
                return page
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
        # 200, damit HTMX die Meldung in den Schreibtisch tauscht. Bei 400
        # bleibt die Seite stehen und der Auftrag sieht aus, als wäre nichts passiert.
        return workspace(request, {"error": i18n.translate(key, _language(request))})

    @app.post("/hausmeister/toggle", response_class=HTMLResponse)
    def hausmeister_toggle(request: Request, enabled: str = Form("0")) -> HTMLResponse:
        store = _svc().store
        remember_probe(store, Hausmeister(store).set_enabled(enabled == "1"))
        key = "hausmeister.turn_on" if enabled == "1" else "hausmeister.turn_off"
        return workspace(request, {"notice": i18n.translate(key, _language(request))})

    @app.post("/hausmeister/model", response_class=HTMLResponse)
    def hausmeister_model(request: Request, model: str = Form("")) -> HTMLResponse:
        try:
            store = _svc().store
            chosen = Hausmeister(store).set_model(model)
            remember_probe(store, chosen)
        except OllamaError as exc:
            return _hausmeister_notice(request, str(exc))
        key = "hausmeister.no_model" if not chosen["model"] else "hausmeister.use_model"
        return workspace(request, {"notice": i18n.translate(key, _language(request))})

    @app.post("/threads/{thread_id}/hausmeister", response_class=HTMLResponse)
    def hausmeister_run(
        thread_id: str,
        request: Request,
        # Leeres order kommt als "" an. Form(...) wertet das als fehlend und
        # antwortet 422, bevor der Auftrag geprüft wird. HTMX zeigt 422 nicht.
        order: str = Form(""),
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
    def invite_room(request: Request, role: str = Form("member")) -> HTMLResponse:
        try:
            code = RoomBook(_svc().store).invite(role)
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
        core = _svc()
        core.add_file(path, thread_id)
        record_owner_reference(core,thread_id,path)
        return workspace(request, {"notice": i18n.translate("ui.file_added", _language(request), path=path.strip())})

    @app.post("/threads/{thread_id}/files/remove", response_class=HTMLResponse)
    def remove_file(
        thread_id: str,
        request: Request,
        path: str = Form(...),
    ) -> HTMLResponse:
        core = _svc()
        core.remove_file(path, thread_id)
        record_owner_reference(core,thread_id,path,allowed=False)
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


def run(host: str = "127.0.0.1", port: int = 8765, *, open_browser: bool = False) -> None:
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
    server = uvicorn.Server(uvicorn.Config(
        create_app(), host=host, port=port, log_level="info", proxy_headers=False,
    ))
    if open_browser:
        def _open_when_ready():
            import webbrowser

            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and not server.should_exit:
                if server.started:
                    name = "127.0.0.1" if host == "0.0.0.0" else "::1" if host == "::" else host
                    authority = f"[{name}]" if ":" in name else name
                    bound_port = server.servers[0].sockets[0].getsockname()[1]
                    webbrowser.open(f"http://{authority}:{bound_port}/")
                    return
                time.sleep(0.05)

        threading.Thread(target=_open_when_ready, name="browser-open", daemon=True).start()
    server.run()
