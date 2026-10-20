"""The opt-in recorder observes navigation; it cannot change its outcome."""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

import http_navigation_diagnostics as diagnostics


class OriginalTimeout(Exception):
    pass


class Page:
    def __init__(self, timeout=None):
        self.handlers = {}
        self.calls = []
        self.timeout = timeout
        self.closed = False
        self.request = SimpleNamespace(method="GET", resource_type="stylesheet",
                                       url="http://127.0.0.1:40001/static/style.css?token=CANARY")

    def on(self, name, callback):
        self.handlers.setdefault(name, []).append(callback)

    def event(self, name, item):
        for callback in self.handlers[name]:
            callback(item)

    def goto(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        self.event("request", self.request)
        self.event("response", SimpleNamespace(request=self.request, status=200))
        if self.timeout is not None:
            raise self.timeout
        self.event("requestfinished", self.request)
        return self.request


def test_import_is_inert_and_positive_navigation_retains_arguments_and_result():
    assert Page.goto.__name__ == "goto"
    original = Page.goto
    emitted = []
    recorder = diagnostics.NavigationDiagnostics(emit=emitted.append)
    recorder.install(Page, OriginalTimeout)
    try:
        page = Page()
        result = page.goto("http://127.0.0.1:40001/", wait_until="networkidle", timeout=1234)
        assert result is page.request
        assert page.calls == [(("http://127.0.0.1:40001/",),
                               {"wait_until": "networkidle", "timeout": 1234})]
        assert not emitted and not recorder.pages[page].pending
        page.goto(url="http://127.0.0.1:40001/", timeout=5678)
        assert len(page.handlers["request"]) == 1
    finally:
        recorder.uninstall()
    assert Page.goto is original


def test_plain_import_does_not_import_playwright_or_register_plugin():
    code = ("import sys, http_navigation_diagnostics as d; "
            "assert 'playwright' not in sys.modules; assert d._plugin is None")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parent),
           "PYTHONDONTWRITEBYTECODE": "1"}
    subprocess.run([sys.executable, "-c", code], env=env, check=True, timeout=5)


def test_original_timeout_emits_pending_before_cleanup_without_retry_or_secrets():
    error = OriginalTimeout("raw error URL contains CANARY")
    page = Page(error)
    reports = []

    def receive(report):
        assert not page.closed
        reports.append(report)

    recorder = diagnostics.NavigationDiagnostics(emit=receive)
    recorder.install(Page, OriginalTimeout)
    try:
        with pytest.raises(OriginalTimeout) as failure:
            page.goto("http://user:CANARY@127.0.0.1:40001/threads/CANARY?token=CANARY",
                      wait_until="networkidle", timeout=321)
        assert failure.value is error and len(page.calls) == 1
        report, = reports
        assert report["pending_requests"][0]["status"] == 200
        assert report["pending_requests"][0]["path"] == "/static/style.css"
        assert report["pending_requests"][0]["query_keys"] == ["token"]
        assert [item["event"] for item in report["events"]] == ["goto", "request", "response"]
        assert "CANARY" not in json.dumps(report)
        assert not report["subprocess_stacks"]["available"]
        assert not report["pipe_fill"]["available"]
        for thread in report["python_stacks"]["threads"]:
            assert all(set(frame) == {"file", "line", "function"} for frame in thread["frames"])
    finally:
        page.closed = True
        recorder.uninstall()


def test_diagnostic_write_failure_cannot_replace_original_timeout(capsys):
    error = OriginalTimeout("original")

    def broken(_):
        raise OSError("CANARY")

    recorder = diagnostics.NavigationDiagnostics(emit=broken)
    recorder.install(Page, OriginalTimeout)
    try:
        with pytest.raises(OriginalTimeout) as failure:
            Page(error).goto("http://127.0.0.1:40001/")
        assert failure.value is error
        captured = capsys.readouterr().err
        assert "navigation_diagnostic_failed" in captured and "CANARY" not in captured
    finally:
        recorder.uninstall()


def test_finished_and_failed_requests_leave_pending_and_events_stay_bounded():
    recorder = diagnostics.PageRecorder()
    request = SimpleNamespace(method="GET", resource_type="document", url="http://localhost:12345/")
    for _ in range(diagnostics.EVENT_LIMIT + 5):
        recorder.request(request)
        recorder.end(request, "failed")
    assert len(recorder.events) == diagnostics.EVENT_LIMIT and not recorder.pending
    assert recorder.events[-1]["event"] == "failed"
    recorder = diagnostics.PageRecorder()
    requests = [SimpleNamespace(method="GET", resource_type="document", url="http://localhost:12345/")
                for _ in range(diagnostics.PENDING_LIMIT + 3)]
    for request in requests:
        recorder.request(request)
    assert len(recorder.pending) == diagnostics.PENDING_LIMIT and recorder.overflow == 3


def test_json_artifact_is_private_and_url_values_are_redacted(tmp_path, capsys):
    recorder = diagnostics.NavigationDiagnostics(tmp_path)
    recorder.write({"target": diagnostics.location("https://user:CANARY@example.org/private/CANARY?token=CANARY#CANARY")})
    path, = tmp_path.iterdir()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    body = path.read_text()
    assert "CANARY" not in body and "example.org" not in body
    assert json.loads(body)["target"]["origin"] == "https://<external-host>"
    assert "CANARY" not in capsys.readouterr().err
