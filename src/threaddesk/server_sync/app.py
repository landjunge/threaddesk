"""Authenticated server adapter. Never mounts the desktop localhost application."""
from __future__ import annotations

import base64
import binascii
import hmac
import hashlib
import ipaddress
import json
import threading
import time
from copy import deepcopy
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from starlette.concurrency import run_in_threadpool
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import InvalidState, ManagementError, NotFound, SecretRejected
from threaddesk.core.models import Snapshot, new_id, new_thread, now_iso
from threaddesk.core.secrets import reject_secrets
from threaddesk.server_sync.auth import Credentials, SESSION_SECONDS
from threaddesk.server_sync.backup import server_lock
from threaddesk.server_sync.store import SyncError, SyncStore
from threaddesk.storage.json_store import JsonStore

COOKIE = "threaddesk_server_session"
MAX_BODY = 512 * 1024
# 20000 paths of up to 2048 UTF-8 bytes, JSON escaping and bounded issues.
MAX_MANIFEST_BODY = 96 * 1024 * 1024


def body_limit(path: str) -> int:
    if path.startswith('/api/projects/') and path.endswith('/manifest'):
        return MAX_MANIFEST_BODY
    return 4 * 1024 * 1024 if '/metadata/' in path else MAX_BODY


async def body(request: Request, required: set[str], optional: set[str] | None = None) -> dict:
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(415, "application/json required")
    data = bytearray()
    limit = body_limit(request.url.path)
    async for part in request.stream():
        data.extend(part)
        if len(data) > limit:
            raise HTTPException(413, "Request exceeds endpoint body limit")
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Invalid JSON")
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - (optional or set()):
        raise HTTPException(400, "Missing or unsupported fields")
    return value


def text(value, limit=8000) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise HTTPException(400, "Invalid text")
    return value


def create_app(data_dir: Path, *, public_origin: str, allow_http_loopback: bool = False) -> FastAPI:
    origin = urlsplit(public_origin)
    if origin.scheme not in {"http", "https"} or not origin.hostname or origin.path not in {"", "/"} or origin.query or origin.fragment or origin.username:
        raise ValueError("public-origin must be an absolute origin")
    local_origin = origin.hostname in {"localhost", "127.0.0.1", "::1"}
    if origin.scheme != "https" and not (allow_http_loopback and local_origin):
        raise ValueError("HTTPS required; explicit loopback mode is development only")
    public_origin = public_origin.rstrip("/")
    creds = Credentials(data_dir)
    @asynccontextmanager
    async def lifespan(app):
        with server_lock(data_dir):
            app.state.server_locked = True
            try:
                yield
            finally:
                app.state.server_locked = False

    app = FastAPI(title="ThreadDesk Server & Sync", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[origin.hostname])
    cache = {}
    cache_lock = threading.RLock()
    # Per-user core mutations and sync creation are serialized within this one-worker app.
    failures = {}

    def stores(user):
        with cache_lock:
            if user not in cache:
                root = creds.user_root(user)
                cache[user] = (SyncStore(root / "sync"), ThreadService(JsonStore(root / "core")), threading.RLock())
            return cache[user]

    @app.exception_handler(SyncError)
    async def sync_error(request, exc):
        return JSONResponse({"error": exc.code, "detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(NotFound)
    async def missing(request, exc):
        return JSONResponse({"error": "not_found"}, status_code=404)

    @app.exception_handler(InvalidState)
    async def invalid(request, exc):
        return JSONResponse({"error": "invalid", "detail": str(exc)}, status_code=400)

    @app.exception_handler(SecretRejected)
    async def secret_rejected(request, exc):
        return JSONResponse({"error": "secret_rejected", "detail": "Secret-like metadata was refused"}, status_code=400)

    @app.exception_handler(ManagementError)
    async def core_conflict(request, exc):
        return JSONResponse({"error": "revision_conflict", "detail": str(exc)}, status_code=409)

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        peer = request.client.host if request.client else ""
        try:
            local_peer = ipaddress.ip_address(peer).is_loopback
        except ValueError:
            local_peer = False
        if request.url.scheme != "https" and not (allow_http_loopback and local_origin and local_peer):
            return JSONResponse({"error": "tls_required"}, 403)
        supplied_origin = request.headers.getlist("origin")
        if supplied_origin and supplied_origin != [public_origin]:
            return JSONResponse({"error": "foreign_origin"}, 403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"error": "foreign_origin"}, 403)
        if request.headers.get("content-length"):
            try:
                limit = body_limit(request.url.path)
                if int(request.headers["content-length"]) > limit:
                    return JSONResponse({"error": "body_too_large"}, 413)
            except ValueError:
                return JSONResponse({"error": "invalid_length"}, 400)
        if request.url.path.startswith("/api/"):
            if not getattr(app.state,'server_locked',False):
                return JSONResponse({'error':'server_lifecycle_required'},503)
            auth = request.headers.get("authorization", "")
            session = request.cookies.get(COOKIE, "")
            user = creds.authenticate(auth[7:]) if auth.startswith("Bearer ") else creds.session_user(session)
            if not user:
                return JSONResponse({"error": "login_required"}, 401)
            if not auth.startswith("Bearer ") and request.method not in {"GET", "HEAD", "OPTIONS"}:
                if not hmac.compare_digest(request.headers.get("x-threaddesk-csrf", ""), creds.csrf(session)):
                    return JSONResponse({"error": "csrf_required"}, 403)
            request.state.user = user
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        if origin.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (Path(__file__).parent / "web" / "index.html").read_text(encoding="utf-8")

    @app.get("/app.js")
    def javascript():
        return Response((Path(__file__).parent / "web" / "app.js").read_bytes(), media_type="application/javascript")

    @app.get("/style.css")
    def css():
        return Response((Path(__file__).parent / "web" / "style.css").read_bytes(), media_type="text/css")

    @app.post("/auth/login")
    async def login(request: Request):
        value = await body(request, {"token"})
        def operation():
            token = text(value["token"], 256)
            peer = request.client.host if request.client else "unknown"
            with cache_lock:
                # Bounded worker-local throttle; reverse proxy should also limit login.
                now = time.monotonic()
                for key in list(failures):
                    if now - failures[key][0] > 60:
                        del failures[key]
                if len(failures) >= 4096 or failures.get(peer, (now, 0))[1] >= 10:
                    raise HTTPException(429, "Try again in one minute")
                user = creds.authenticate(token)
                if not user:
                    stamp, count = failures.get(peer, (now, 0))
                    failures[peer] = (stamp, count + 1)
                    raise HTTPException(401, "Invalid login")
                failures.pop(peer, None)
            session = creds.session(user)
            response = JSONResponse({"user": user, "csrf": creds.csrf(session)})
            response.set_cookie(COOKIE, session, max_age=SESSION_SECONDS, httponly=True,
                                secure=origin.scheme == "https", samesite="strict", path="/")
            return response
        return await run_in_threadpool(operation)

    @app.get("/api/session")
    def session(request: Request):
        return {"user": request.state.user, "csrf": creds.csrf(request.cookies.get(COOKIE, ""))}

    @app.post("/api/logout")
    def logout():
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE, path="/", secure=origin.scheme == "https", httponly=True, samesite="strict")
        return response

    def project(request, pid):
        sync, core, lock = stores(request.state.user)
        sync.project(pid)
        return sync, core, lock

    from threaddesk.server_sync.metadata import export_document, metadata_status
    from threaddesk.server_sync.metadata_routes import install_routes
    install_routes(app, project, body)

    @app.post('/api/projects/bind')
    async def bind_project(request: Request):
        value = await body(request, {'binding_id','title'})
        def operation():
            from threaddesk.server_sync.store import _id
            binding = _id(value['binding_id'])
            title = reject_secrets(text(value['title'],200)).strip()
            if not title:
                raise HTTPException(400,'Project title required')
            pid = hashlib.sha256(binding.encode()).hexdigest()[:24]
            key = 'serverbind_'+pid
            sync,core,lock = stores(request.state.user)
            with lock, core.store.transaction():
                saved = core.store.get_management_operation(key)
                if saved:
                    sync.project(pid)
                    return saved['result']
                try:
                    core.get(pid)
                except NotFound:
                    thread = new_thread(title)
                    thread.id = pid
                    core.store.save_thread(thread)
                else:
                    raise HTTPException(409,'Existing project has no binding receipt; select its ID explicitly')
                try:
                    sync.project(pid)
                except SyncError as exc:
                    if exc.status != 404:
                        raise
                    sync.create_project(title,project_id=pid)
                result = {**sync.project(pid),'bootstrap_document':export_document(core,pid),'operation_id':key}
                core.store.save_management_operation(key,{'request_hash':hashlib.sha256(binding.encode()).hexdigest(),
                    'recorded_at':now_iso(),'result':result})
                return result
        return await run_in_threadpool(operation)

    @app.get("/api/projects")
    def projects(request: Request):
        sync, core, lock = stores(request.state.user)
        with lock:
            return {"projects": [{**value, 'title':core.get(value['id']).title}
                                 for value in sync.projects()
                                 if not core.store.object_in_trash('thread', value['id'])]}

    @app.post("/api/projects")
    async def create(request: Request):
        value = await body(request, {"title"})
        def operation():
            title = text(value["title"], 200).strip()
            sync, core, lock = stores(request.state.user)
            with lock:
                thread = core.create(title)
                return sync.create_project(title, project_id=thread.id)
        return await run_in_threadpool(operation)

    @app.get("/api/projects/{pid}/status")
    def status(pid: str, request: Request):
        sync, core, lock = project(request, pid)
        with lock, core.store.transaction():
            meta = metadata_status(core,pid)
        result = {**sync.status(pid), **meta}
        if meta['metadata_conflict_count']:
            result['state'] = 'conflict'
        return result

    @app.put("/api/projects/{pid}/offline")
    async def offline(pid: str, request: Request):
        value = await body(request, {"enabled"})
        def operation():
            if type(value["enabled"]) is not bool:
                raise HTTPException(400, "enabled must be boolean")
            sync, _, _ = project(request, pid)
            return sync.set_offline(pid, value["enabled"])
        return await run_in_threadpool(operation)

    @app.post("/api/projects/{pid}/manifest")
    async def manifest(pid: str, request: Request):
        value = await body(request, {"files", "issues", "device_id"})
        def operation():
            sync, _, _ = project(request, pid)
            return sync.declare_manifest(pid, **value)
        return await run_in_threadpool(operation)

    @app.get("/api/projects/{pid}/files")
    def files(pid: str, request: Request):
        sync, _, _ = project(request, pid)
        return {"files": sync.list_files(pid)}

    @app.get("/api/projects/{pid}/history")
    def history(pid: str, path: str, request: Request):
        sync, _, _ = project(request, pid)
        return {"versions": sync.history(pid, path)}

    @app.post("/api/projects/{pid}/uploads/{transfer}")
    async def begin(pid: str, transfer: str, request: Request):
        value = await body(request, {"path", "size", "sha256"}, {"base_revision"})
        def operation():
            sync, _, _ = project(request, pid)
            return sync.start_upload(pid, transfer, **value)
        return await run_in_threadpool(operation)

    @app.get("/api/projects/{pid}/uploads")
    def pending_uploads(pid: str, request: Request):
        sync, _, _ = project(request, pid)
        return {"uploads": sync.pending_uploads(pid)}

    @app.get("/api/projects/{pid}/uploads/{transfer}")
    def upload_status(pid: str, transfer: str, request: Request):
        sync, _, _ = project(request, pid)
        return sync.upload_status(pid, transfer)

    @app.patch("/api/projects/{pid}/uploads/{transfer}")
    async def chunk(pid: str, transfer: str, request: Request):
        value = await body(request, {"offset", "data_base64"})
        def operation():
            try:
                data = base64.b64decode(text(value["data_base64"], 350000), validate=True)
            except (ValueError, binascii.Error):
                raise HTTPException(400, "Invalid base64")
            sync, _, _ = project(request, pid)
            return sync.append_chunk(pid, transfer, value["offset"], data)
        return await run_in_threadpool(operation)

    @app.post("/api/projects/{pid}/uploads/{transfer}/commit")
    def commit(pid: str, transfer: str, request: Request):
        sync, _, _ = project(request, pid)
        return sync.finish_upload(pid, transfer)

    @app.post("/api/projects/{pid}/uploads/{transfer}/abort")
    def abort(pid: str, transfer: str, request: Request):
        sync, _, _ = project(request, pid)
        return sync.abort_upload(pid, transfer)

    @app.get("/api/projects/{pid}/revisions/{revision}")
    def download(pid: str, revision: str, request: Request):
        sync, _, _ = project(request, pid)
        return Response(sync.read_revision(pid, revision), media_type="application/octet-stream",
                        headers={"Content-Disposition": 'attachment; filename="project-file"'})

    @app.post("/api/projects/{pid}/resolve")
    async def resolve(pid: str, request: Request):
        value = await body(request, {"path", "expected_heads", "chosen_revision"})
        def operation():
            sync, _, _ = project(request, pid)
            return sync.resolve(pid, **value)
        return await run_in_threadpool(operation)

    @app.get("/api/projects/{pid}/thread")
    def get_thread(pid: str, request: Request):
        _, core, lock = project(request, pid)
        with lock:
            return core.get(pid).to_dict()

    @app.put("/api/projects/{pid}/thread")
    async def put_thread(pid: str, request: Request):
        value = await body(request, {"revision", "description", "notes"})
        def operation():
            if type(value["revision"]) is not int:
                raise HTTPException(400, "revision must be integer")
            _, core, lock = project(request, pid)
            with lock, core.store.transaction():
                thread = core.get(pid)
                if thread.revision != value["revision"]:
                    raise HTTPException(409, "Thread changed; reload before saving")
                previous = deepcopy(thread.context)
                previous.extra["server_previous_description"] = thread.description
                core.store.save_snapshot(Snapshot(
                    id=new_id(), thread_id=pid, created_at=now_iso(),
                    label="Before server metadata edit", context=previous))
                thread.description = reject_secrets(text(value["description"], 100000))
                thread.context.notes = reject_secrets(text(value["notes"], 100000))
                thread.updated_at = now_iso()
                core.store.save_thread(thread)
                return thread.to_dict()
        return await run_in_threadpool(operation)

    @app.get("/api/projects/{pid}/whiteboard")
    def whiteboard(pid: str, request: Request):
        _, core, lock = project(request, pid)
        with lock:
            return {"entries": [e.to_dict() for e in core.whiteboard(pid)]}

    @app.post("/api/projects/{pid}/whiteboard")
    async def append_whiteboard(pid: str, request: Request):
        value = await body(request, {"content", "entry_type", "external_key"})
        def operation():
            _, core, lock = project(request, pid)
            with lock, core.store.transaction():
                return core.append_whiteboard(pid, actor=request.state.user, actor_type="human",
                                              content=text(value["content"]), entry_type=text(value["entry_type"], 32),
                                              external_key=text(value["external_key"], 128))
        return await run_in_threadpool(operation)

    return app
