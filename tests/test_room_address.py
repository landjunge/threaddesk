"""A desktop window must reveal the actual address needed by its peer."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from threaddesk.ui.server import create_app


@pytest.mark.parametrize("port", [19876, 19877])
def test_room_panel_shows_its_actual_endpoint(tmp_path, monkeypatch, port):
    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    url = f"http://127.0.0.1:{port}"
    with TestClient(create_app(), base_url=url) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert f'<code data-room-address>{url}/</code>' in response.text
