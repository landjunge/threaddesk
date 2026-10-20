"""Opt-in navigation recorder: ``-p http_navigation_diagnostics`` or
``PYTEST_PLUGINS=http_navigation_diagnostics`` with ``tests`` on PYTHONPATH.

Only pytest plugin registration installs the wrapper. Ordinary imports do not.
THREADDESK_NAV_DIAGNOSTICS_DIR optionally receives private JSON artifacts.
No navigation retry, argument/timeout change, response body/header read, or
subprocess signal is performed. Unknown path segments are deliberately redacted.
"""

from collections import deque
from functools import wraps
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import parse_qsl, unquote, urlsplit
import weakref


EVENT_LIMIT = 64
PENDING_LIMIT = 128
THREAD_LIMIT = 16
FRAME_LIMIT = 24
SAFE_SEGMENTS = frozenset("""
static api threads thread snapshots knowledge nodes relations data download
restore profile original lang de en mode plain expert graph migration dry-run
confirm recover partials main gate whiteboard stand note switch hausmeister
activity toggle model rooms select invite join sync pair pull push describe
status snapshot rename files remove prompt archive handoff gnom grok freeze
networkpunkt.css style.css polish.css networkpunkt.js app.js htmx.min.js
alpine.min.js map.js design-reference.html favicon.ico
""".split())
QUERY_KEYS = frozenset("lang mode thread node restored limit offset page token key code".split())


def location(value):
    """Keep the local origin and known route shape, never URL credentials/values."""
    try:
        parsed = urlsplit(str(value))
        host = parsed.hostname
        if parsed.scheme not in {"http", "https"} or not host:
            return {"origin": "<unsupported>", "path": "<redacted>", "query_keys": []}
        host = host if host in {"127.0.0.1", "localhost", "::1"} else "<external-host>"
        host = "[::1]" if host == "::1" else host
        origin = f"{parsed.scheme}://{host}" + (f":{parsed.port}" if parsed.port else "")
        parts = unquote(parsed.path).split("/")[:16]
        path = "/".join(part if part in SAFE_SEGMENTS or not part else ":value" for part in parts)
        keys = sorted({key if key in QUERY_KEYS else ":key"
                       for key, _ in parse_qsl(parsed.query, max_num_fields=32)})
        return {"origin": origin, "path": path[:256], "query_keys": keys}
    except (ValueError, TypeError):
        return {"origin": "<invalid>", "path": "<redacted>", "query_keys": []}


def thread_stacks():
    """Inspect only this live process; no locals, source lines or exception text."""
    result = []
    frames = sys._current_frames()
    for identity, frame in list(frames.items())[:THREAD_LIMIT]:
        stack = []
        while frame is not None and len(stack) < FRAME_LIMIT:
            stack.append({"file": Path(frame.f_code.co_filename).name[:100],
                          "line": frame.f_lineno, "function": frame.f_code.co_name[:100]})
            frame = frame.f_back
        result.append({"thread_id": identity, "frames": stack,
                       "frames_truncated": frame is not None})
    return {"threads": result, "threads_truncated": len(frames) > THREAD_LIMIT}


class PageRecorder:
    def __init__(self):
        self.events = deque(maxlen=EVENT_LIMIT)
        self.pending = {}
        self.overflow = 0
        self.capture_errors = 0

    def add(self, event, record):
        self.events.append({"event": event, "at_monotonic": round(time.monotonic(), 6), **record})

    def request(self, request):
        try:
            method = request.method
            method = method if re.fullmatch("[A-Z]{1,12}", method) else "<other>"
            record = {"method": method, **location(request.url),
                      "resource_type": request.resource_type[:32], "status": None}
            if len(self.pending) < PENDING_LIMIT:
                self.pending[id(request)] = record
            else:
                self.overflow += 1
            self.add("request", record)
        except Exception:
            self.capture_errors += 1

    def response(self, response):
        try:
            record = self.pending.get(id(response.request))
            if record is not None:
                record = {**record, "status": response.status}
                self.pending[id(response.request)] = record
                self.add("response", record)
        except Exception:
            self.capture_errors += 1

    def end(self, request, event):
        try:
            record = self.pending.pop(id(request), None)
            if record is not None:
                # request.failure may contain a URL; deliberately do not read it.
                self.add(event, record)
        except Exception:
            self.capture_errors += 1

    def attach(self, page):
        page.on("request", self.request)
        page.on("response", self.response)
        page.on("requestfinished", lambda request: self.end(request, "finished"))
        page.on("requestfailed", lambda request: self.end(request, "failed"))


class NavigationDiagnostics:
    def __init__(self, directory=None, emit=None):
        self.directory = Path(directory) if directory else None
        self.emit = emit or self.write
        self.pages = weakref.WeakKeyDictionary()
        self.page_class = None
        self.original = None
        self.wrapper = None

    def install(self, page_class, timeout_class):
        if self.original is not None:
            raise RuntimeError("Navigation diagnostics already installed")
        original = page_class.goto

        @wraps(original)
        def goto(page, *args, **kwargs):
            try:
                recorder = self.pages.get(page)
                if recorder is None:
                    recorder = PageRecorder()
                    recorder.attach(page)
                    self.pages[page] = recorder
                target = args[0] if args else kwargs.get("url", "")
                recorder.add("goto", location(target))
            except Exception:
                return original(page, *args, **kwargs)
            try:
                return original(page, *args, **kwargs)
            except timeout_class:
                # Synchronous, before the original exception reaches fixture cleanup.
                try:
                    self.emit({
                        "kind": "navigation_original_timeout", "pid": os.getpid(),
                        "target": location(target), "events": list(recorder.events),
                        "pending_requests": list(recorder.pending.values()),
                        "pending_overflow_total": recorder.overflow,
                        "capture_errors": recorder.capture_errors,
                        "python_stacks": thread_stacks(),
                        "subprocess_stacks": {"available": False,
                                              "reason": "no_registered_child_diagnostic_channel"},
                        "pipe_fill": {"available": False, "reason": "no_owned_pipe_handles"},
                    })
                except Exception as error:
                    # Diagnosis must never replace the original timeout.
                    try:
                        print(json.dumps({"kind": "navigation_diagnostic_failed",
                                          "error_type": type(error).__name__}), file=sys.stderr)
                    except Exception:
                        pass
                raise

        self.page_class, self.original, self.wrapper = page_class, original, goto
        page_class.goto = goto

    def uninstall(self):
        if self.page_class is not None and self.page_class.goto is self.wrapper:
            self.page_class.goto = self.original
        self.pages.clear()
        self.page_class = self.original = self.wrapper = None

    def write(self, report):
        body = json.dumps(report, ensure_ascii=True, separators=(",", ":"))
        try:
            if self.directory is not None:
                self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                filename = self.directory / f"navigation-timeout-{os.getpid()}-{time.monotonic_ns()}.json"
                descriptor = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                    output.write(body + "\n")
        finally:
            print("THREADDESK_NAVIGATION_DIAGNOSTICS " + body, file=sys.stderr, flush=True)


_plugin = None


def pytest_configure(config):
    """Called only when this module was explicitly registered as a pytest plugin."""
    global _plugin
    from playwright.sync_api import Page, TimeoutError

    _plugin = NavigationDiagnostics(os.environ.get("THREADDESK_NAV_DIAGNOSTICS_DIR"))
    _plugin.install(Page, TimeoutError)


def pytest_unconfigure(config):
    global _plugin
    if _plugin is not None:
        _plugin.uninstall()
        _plugin = None
