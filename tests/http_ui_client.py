"""Exercise the real local bootstrap for existing positive HTTP UI tests."""
import re
import json
from html.parser import HTMLParser
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from threaddesk.ui.http_access import MACHINE_PATHS, SAFE_METHODS


class UIClient(TestClient):
    def __init__(self, app, **kwargs):
        kwargs.setdefault("base_url", "http://127.0.0.1")
        kwargs.setdefault("client", ("127.0.0.1", 50000))
        super().__init__(app, **kwargs)
        response = super().get("/")
        assert response.status_code == 200
        self.csrf = re.search(r'name="threaddesk-csrf" content="([a-f0-9]+)"', response.text)[1]

    def request(self, method, url, **kwargs):
        if method.upper() not in SAFE_METHODS and urlsplit(str(url)).path not in MACHINE_PATHS:
            headers = dict(kwargs.pop("headers", {}) or {})
            headers.setdefault("Origin", str(self.base_url).rstrip("/"))
            headers.setdefault("X-ThreadDesk-CSRF", getattr(self, "csrf", ""))
            kwargs["headers"] = headers
        return super().request(method, url, **kwargs)

    def post_thread_form(self, url, *, data=None, **kwargs):
        """Submit a freshly displayed thread form, including its CAS envelope.

        Positive UI tests use this explicitly. Raw post() remains available to
        verify that missing/stale preconditions and unauthorized writes fail.
        """
        path = urlsplit(str(url)).path
        thread = re.fullmatch(r"/threads/([^/]+)/.*", path)
        view = "/?thread=" + thread[1] if thread else "/"
        page = self.get(view)
        parser = _ThreadForm(path)
        parser.feed(page.text)
        assert parser.envelope is not None, f"No displayed mutation form: {path}"
        return self.post(url, data={**parser.envelope, **(data or {})}, **kwargs)


class _ThreadForm(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.path = path
        self.match = False
        self.envelope = None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "form":
            self.match = attrs.get("hx-post") == self.path
            if self.match:
                self.envelope = {}
        if self.match and tag == "input" and attrs.get("type") == "hidden":
            self.envelope[attrs["name"]] = attrs.get("value", "")
        if tag == "button" and attrs.get("hx-post") == self.path:
            self.envelope = json.loads(attrs["hx-vals"])

    def handle_endtag(self, tag):
        if tag == "form":
            self.match = False


def choose_language(page, url, language):
    """Use the same protected preference form as a user, without token URLs."""
    page.goto(url + "/?lang=" + language, wait_until="networkidle")
    page.locator(".preferences > summary").click()
    page.get_by_role("button", name=language.upper(), exact=True).click()
    page.wait_for_load_state("networkidle")
