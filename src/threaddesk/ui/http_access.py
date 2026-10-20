"""Local browser request boundary, not person or same-user process authentication."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import time
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse, Response

MACHINE_PATHS = frozenset({"/api/rooms/pair", "/api/rooms/pull", "/api/rooms/push"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
SESSION_SECONDS = 8 * 60 * 60


def _authority(value: str, scheme: str) -> tuple[str, int]:
    if not value or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        raise ValueError("invalid authority")
    parsed = urlsplit(scheme + "://" + value)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.path
            or parsed.query or parsed.fragment):
        raise ValueError("invalid authority")
    port = parsed.port if parsed.port is not None else (443 if scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise ValueError("invalid port")
    return parsed.hostname.lower(), port


def _local(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def _private(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
        return ip.is_loopback or any(ip in ipaddress.ip_network(n) for n in
                                    ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
    except ValueError:
        return False


class LocalHTTPAccess:
    """Validate before parsing a body or opening the selected workspace.

    Browser sessions are bootstrapped locally without an account. Any process
    able to make local HTTP calls can obtain one: this is not an OS sandbox.
    The three peer routes retain their invitation/token authorization in RoomBook.
    """

    def __init__(self, app):
        self.app = app
        self.key = secrets.token_bytes(32)

    def _sign(self, value: str) -> str:
        return hmac.new(self.key, value.encode(), hashlib.sha256).hexdigest()

    def _valid(self, value: str) -> bool:
        try:
            stamp, nonce, signature = value.split(".")
            age = time.time() - int(stamp)
            return (len(nonce) == 43 and -60 <= age <= SESSION_SECONDS
                    and hmac.compare_digest(signature, self._sign(stamp + "." + nonce)))
        except (ValueError, TypeError):
            return False

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        machine = scope.get("path") in MACHINE_PATHS
        unsafe = request.method not in SAFE_METHODS
        scheme = scope.get("scheme", "http")
        try:
            hosts = request.headers.getlist("host")
            if len(hosts) != 1 or scheme not in {"http", "https"}:
                raise ValueError("host")
            host, port = _authority(hosts[0], scheme)
            server = scope.get("server")
            if not server or port != server[1]:
                raise ValueError("port")
            names = {"127.0.0.1", "localhost"}
            if server[0] == "::1":
                names.add("::1")
            local_authority = _local(server[0]) and host in names
            peer_authority = machine and _private(server[0]) and host == server[0]
            if not (local_authority or peer_authority):
                raise ValueError("host")
        except (ValueError, TypeError):
            return await JSONResponse({"error": "invalid_host"}, status_code=403)(scope, receive, send)

        origins = request.headers.getlist("origin")
        site = request.headers.get("sec-fetch-site", "")
        error = None
        if machine:
            peer = scope.get("client")
            if not peer or not _private(peer[0]):
                error = "local_peer_required"
            if origins or any(k.startswith("sec-fetch-") for k in request.headers):
                error = "browser_peer_request_denied"
        else:
            peer = scope.get("client")
            if not peer or not _local(peer[0]):
                error = "local_ui_required"
            if origins:
                try:
                    origin = urlsplit(origins[0])
                    if (len(origins) != 1 or origin.scheme != scheme or origin.path
                            or origin.query or origin.fragment
                            or _authority(origin.netloc, scheme) != (host, port)):
                        raise ValueError("origin")
                except ValueError:
                    error = "foreign_origin"
            if site == "cross-site" and (unsafe or request.headers.get("sec-fetch-mode") != "navigate"):
                error = "foreign_origin"
        if error:
            return await JSONResponse({"error": error}, status_code=403)(scope, receive, send)
        if machine:
            return await self.app(scope, receive, send)

        cookie_name = "threaddesk_ui_" + str(port)
        cookie = request.cookies.get(cookie_name, "")
        valid = len(cookie) <= 160 and self._valid(cookie)
        if unsafe and not valid:
            return await JSONResponse({"error": "ui_session_required"}, status_code=403)(scope, receive, send)
        if not valid:
            value = str(int(time.time())) + "." + secrets.token_urlsafe(32)
            cookie = value + "." + self._sign(value)
        scope.setdefault("state", {})["csrf_token"] = self._sign("csrf:" + cookie)

        async def guarded_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend([(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"),
                                (b"referrer-policy", b"same-origin"), (b"x-frame-options", b"DENY"),
                                (b"content-security-policy", b"frame-ancestors 'none'")])
                if not valid:
                    response = Response()
                    # Lax preserves an existing editor on incoming top-level links.
                    # Every write still needs its bound CSRF token and Origin checks.
                    response.set_cookie(cookie_name, cookie, max_age=SESSION_SECONDS, httponly=True,
                                        samesite="lax", secure=scheme == "https")
                    headers.extend((k, v) for k, v in response.raw_headers if k == b"set-cookie")
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, guarded_send)


async def require_ui_csrf(request: Request) -> None:
    if request.method in SAFE_METHODS or request.url.path in MACHINE_PATHS:
        return
    values = request.headers.getlist("x-threaddesk-csrf")
    token = values[0] if len(values) == 1 else ""
    if not values and request.headers.get("content-type", "").split(";", 1)[0] in {
        "application/x-www-form-urlencoded", "multipart/form-data"
    }:
        form = await request.form()
        values = form.getlist("csrf_token")
        token = values[0] if len(values) == 1 else ""
    expected = getattr(request.state, "csrf_token", "")
    if (not isinstance(token, str) or not 1 <= len(token) <= 128 or not expected
            or not hmac.compare_digest(token.encode(), expected.encode())):
        raise HTTPException(status_code=403, detail="csrf_invalid")


def safe_return_path(request: Request, *, exclude_query=()) -> str:
    """Keep the current local view without reflecting a foreign Referer."""
    try:
        value = request.headers.get("referer", "")
        if any(ord(c) <= 32 for c in value):
            return "/"
        if "\\" in value:
            return "/"
        parsed = urlsplit(value)
        relative = not parsed.scheme and not parsed.netloc and value.startswith("/")
        scheme = request.scope.get("scheme", "http")
        if (not parsed.path.startswith("/") or parsed.path.startswith("//")
                or (not relative and (parsed.scheme != scheme or _authority(parsed.netloc, scheme)
                                     != _authority(request.headers["host"], scheme)))):
            return "/"
        query = urlencode([(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                           if k not in exclude_query])
        return parsed.path + ("?" + query if query else "")
    except ValueError:
        return "/"
