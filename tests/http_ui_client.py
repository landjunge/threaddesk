"""Exercise the real local bootstrap for existing positive HTTP UI tests."""
import re
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


def choose_language(page, url, language):
    """Use the same protected preference form as a user, without token URLs."""
    page.goto(url + "/?lang=" + language, wait_until="networkidle")
    page.locator(".preferences > summary").click()
    page.get_by_role("button", name=language.upper(), exact=True).click()
    page.wait_for_load_state("networkidle")
