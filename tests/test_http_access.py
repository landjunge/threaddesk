"""Real HTTP sessions, browser CSRF and exact peer-route separation."""
import re
import time

import pytest
from fastapi.testclient import TestClient

from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore
from threaddesk.ui.http_access import LocalHTTPAccess, MACHINE_PATHS, SESSION_SECONDS
from threaddesk.ui.server import create_app


@pytest.fixture
def desk(tmp_path, monkeypatch):
    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    monkeypatch.setenv("THREADDESK_STORAGE", "json")
    monkeypatch.setattr("threaddesk.ui.server._hausmeister_status", lambda *_: {
        "enabled": False, "model": "", "models": [], "ollama_ok": False, "phase": "off"
    })
    return ThreadService(JsonStore(tmp_path)), create_app()


def raw(app):
    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


def bootstrap(client):
    response = client.get("/")
    assert response.status_code == 200
    token = re.search(r'name="threaddesk-csrf" content="([a-f0-9]+)"', response.text)[1]
    assert token and token.encode() not in response.url.query
    assert "HttpOnly" in response.headers.get("set-cookie", "") or client.cookies
    return token


@pytest.mark.parametrize("host", ["attacker.invalid", "127.0.0.1:9999", "127.0.0.1:0", "127.0.0.1.evil", "[bad"])
def test_invalid_host_never_opens_workspace(desk, monkeypatch, host):
    _, app = desk
    monkeypatch.setattr("threaddesk.ui.server._svc", lambda: pytest.fail("opened workspace"))
    response = raw(app).get("/", headers={"Host": host})
    assert response.status_code == 403
    assert response.json()["error"] == "invalid_host"


@pytest.mark.parametrize("origin", ["http://127.0.0.1:9999", "http://localhost", "https://127.0.0.1", "null", "http://evil.invalid"])
def test_foreign_origin_rejected_even_with_valid_cookie_and_csrf(desk, origin):
    svc, app = desk
    client = raw(app)
    csrf = bootstrap(client)
    before = [t.id for t in svc.list(True)]
    response = client.post("/threads", data={"title": "forged"}, headers={
        "Origin": origin, "X-ThreadDesk-CSRF": csrf,
    })
    assert response.status_code == 403
    assert response.json()["error"] == "foreign_origin"
    assert [t.id for t in svc.list(True)] == before


def test_real_form_and_json_header_routes_accept_only_bound_csrf(desk):
    svc, app = desk
    client = raw(app)
    assert client.post("/threads", data={"title": "no session"}).status_code == 403
    csrf = bootstrap(client)
    assert client.post("/threads", data={"title": "no csrf"}).status_code == 403
    response = client.post("/threads", data={"title": "valid", "csrf_token": csrf,
                                              "operation_id": "csrf-create", "expected_revision": 0})
    assert response.status_code == 200
    thread = svc.current()
    assert thread.title == "valid"
    response = client.post(f"/api/threads/{thread.id}/whiteboard", json={
        "actor": "User", "actor_type": "human", "entry_type": "note", "content": "JSON"
    }, headers={"X-ThreadDesk-CSRF": csrf, "Origin": "http://127.0.0.1"})
    assert response.status_code == 200
    stranger = raw(app)
    bootstrap(stranger)
    assert stranger.post("/threads", data={"title": "other session", "csrf_token": csrf}).status_code == 403
    assert raw(app).post("/threads", data={"title": "token only", "csrf_token": csrf}).status_code == 403


def test_all_unsafe_ui_routes_enforce_boundary_before_body_or_side_effect(desk):
    svc, app = desk
    client = raw(app)
    csrf = bootstrap(client)
    # Recent FastAPI versions retain included routers as deferred objects;
    # OpenAPI resolves both those routes and directly installed form routes.
    routes = [path for path, methods in app.openapi()["paths"].items() if "post" in methods]
    assert {"/api/commands", "/api/graph/v2", "/api/graph/views",
            "/api/graph/view-control/connect", "/threads"} <= set(routes)
    assert len(routes) >= 48
    for route in routes:
        if route in MACHINE_PATHS:
            continue
        path = re.sub(r"\{[^}]+\}", "missing", route)
        response = client.post(path, content=b"not a valid body", headers={
            "Origin": "http://attacker.invalid", "X-ThreadDesk-CSRF": csrf,
        })
        assert response.status_code == 403, route
        assert response.json()["error"] == "foreign_origin"
    assert not svc.list(True)


def test_get_preview_cannot_switch_and_preference_redirect_stays_local(desk):
    svc, app = desk
    selected = svc.create("Selected")
    other = svc.create("Current")
    client = raw(app)
    csrf = bootstrap(client)
    response = client.get(f"/?thread={selected.id}")
    assert response.status_code == 200
    assert svc.current().id == other.id
    assert 'value="Selected"' in response.text
    updated = client.post(f"/threads/{selected.id}/note", data={"text": "preview edited", "csrf_token": csrf,
                                                               "operation_id": "csrf-preview-edit", "expected_revision": selected.revision})
    assert updated.status_code == 200 and "preview edited" in updated.text
    assert 'value="Selected"' in updated.text
    assert svc.current().id == other.id  # Reading/editing the preview is not a global selection command.
    assert client.get("/lang/en").status_code == 405
    response = client.post("/lang/en", data={"csrf_token": csrf}, headers={
        "Referer": "http://attacker.invalid/steal"
    }, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/"
    response = client.post("/mode/technical", data={"csrf_token": csrf}, headers={
        "Referer": "http://127.0.0.1/map?thread=" + selected.id
    }, follow_redirects=False)
    assert response.headers["location"] == "/map?thread=" + selected.id


def test_peer_routes_never_accept_browser_session_in_place_of_peer_auth(desk):
    _, app = desk
    client = raw(app)
    csrf = bootstrap(client)
    for path in MACHINE_PATHS:
        response = client.post(path, json={}, headers={
            "Origin": "http://127.0.0.1", "X-ThreadDesk-CSRF": csrf,
        })
        assert response.status_code == 403
        assert response.json()["error"] == "browser_peer_request_denied"
        assert client.post(path, json={}).status_code == 403  # Domain token/code still mandatory.


def test_process_restart_does_not_replay_or_accept_old_cookie(desk):
    svc, app = desk
    client = raw(app)
    csrf = bootstrap(client)
    restarted = raw(create_app())
    restarted.cookies.update(client.cookies)
    response = restarted.post("/threads", data={"title": "old", "csrf_token": csrf})
    assert response.status_code == 403
    assert response.json()["error"] == "ui_session_required"
    assert not svc.list(True)
    fresh = bootstrap(restarted)
    assert fresh != csrf
    assert restarted.post("/threads", data={"title": "new", "csrf_token": fresh,
                                             "operation_id": "csrf-restarted-create", "expected_revision": 0}).status_code == 200


def test_signed_but_expired_session_is_not_accepted(desk):
    svc, app = desk
    client = raw(app)
    csrf = bootstrap(client)
    middleware = app.middleware_stack
    while not isinstance(middleware, LocalHTTPAccess):
        middleware = middleware.app
    cookie = next(iter(client.cookies.jar))
    nonce = cookie.value.split(".")[1]
    expired = str(int(time.time()) - SESSION_SECONDS - 5) + "." + nonce
    cookie.value = expired + "." + middleware._sign(expired)
    response = client.post("/threads", data={"title": "expired", "csrf_token": csrf})
    assert response.status_code == 403
    assert response.json()["error"] == "ui_session_required"
    assert not svc.list(True)


def test_private_network_peer_contract_retains_invitation_and_token_checks(desk):
    from threaddesk.services.room_sync import RoomBook

    svc, app = desk
    room = RoomBook(svc.store)
    room.create_room("Synthetic private network")
    code = room.invite("read_only")
    peer = TestClient(app, base_url="http://192.168.50.1:40001", client=("192.168.50.2", 40002))
    # Explicitly simulate the LAN address/port at the transport boundary, not an auth bypass.
    assert peer.get("/").status_code == 403
    paired = peer.post("/api/rooms/pair", json={
        "code": code, "instance_id": "synthetic-peer", "base_url": "http://192.168.50.2:40002"
    })
    assert paired.status_code == 200
    result = paired.json()
    headers = {"X-ThreadDesk-Instance": "synthetic-peer", "X-ThreadDesk-Token": result["token"]}
    assert peer.post("/api/rooms/pull", json={"room_id": result["room"]["id"]},
                     headers={**headers, "Host": "192.168.50.99:40001"}).status_code == 403
    assert peer.post("/api/rooms/pull", json={"room_id": result["room"]["id"]}, headers=headers).status_code == 200
    invalid = {**headers, "X-ThreadDesk-Token": "incorrect"}
    assert peer.post("/api/rooms/pull", json={"room_id": result["room"]["id"]}, headers=invalid).status_code == 403
    # Invitation replay is rejected; an instance string alone never creates a peer.
    assert peer.post("/api/rooms/pair", json={
        "code": code, "instance_id": "another-peer", "base_url": "http://192.168.50.3:40003"
    }).status_code == 403


@pytest.mark.parametrize("registry", ["absent", "existing", "removed_after_start"])
def test_cross_site_get_never_initializes_registries_or_contacts_ollama(tmp_path, monkeypatch, registry):
    from threaddesk.services.actors import ActorRegistry
    from threaddesk.services.hausmeister import Hausmeister
    from threaddesk.services.room_sync import RoomBook

    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    monkeypatch.setenv("THREADDESK_STORAGE", "json")
    svc = ThreadService(JsonStore(tmp_path))
    thread = svc.create("Synthetic prepared workspace")
    if registry != "absent":
        RoomBook(svc.store).create_room("Existing room")
        Hausmeister(svc.store).install()
        Hausmeister(svc.store).registry.set_enabled("local-assistant", True)
    registered = {name: (svc.store.artifact_path(name).read_bytes(),
                         svc.store.artifact_path(name).stat().st_mtime_ns)
                  for name in ["actors.json", "modules.json"]
                  if svc.store.artifact_path(name).exists()}
    calls = []

    def discover(transport, timeout):
        assert timeout == 0.4
        calls.append("explicit startup")
        return ["synthetic-startup-model"]

    monkeypatch.setattr("threaddesk.services.hausmeister.list_models", discover)
    with raw(create_app()) as client:
        assert calls == ["explicit startup"]
        for name, saved in registered.items():
            path = svc.store.artifact_path(name)
            assert (path.read_bytes(), path.stat().st_mtime_ns) == saved
        if registry == "removed_after_start":
            svc.store.artifact_path("actors.json").unlink()
            svc.store.artifact_path("modules.json").unlink()
        before = {str(p.relative_to(tmp_path)): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in tmp_path.rglob("*") if p.is_file()}
        monkeypatch.setattr("threaddesk.services.hausmeister.list_models",
                            lambda *a, **kw: pytest.fail("GET contacted Ollama"))
        monkeypatch.setattr(Hausmeister, "install", lambda *a: pytest.fail("GET installed a module"))
        monkeypatch.setattr(ActorRegistry, "instance_id", lambda *a: pytest.fail("GET created an identity"))
        for path in ["/", f"/?thread={thread.id}", "/data", "/partials/main", "/partials/gate"]:
            response = client.get(path, headers={
                "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate",
            })
            assert response.status_code == 200
            if path == "/":
                assert "synthetic-startup-model" in response.text
        after = {str(p.relative_to(tmp_path)): (p.read_bytes(), p.stat().st_mtime_ns)
                 for p in tmp_path.rglob("*") if p.is_file()}
        assert after == before
        assert svc.current().id == thread.id


def test_restore_and_profile_switch_probe_only_the_selected_profile(tmp_path, monkeypatch):
    from threaddesk.storage.portable_backup import download_backup, selected_profile

    root = tmp_path / "ui-profile"
    monkeypatch.setenv("THREADDESK_HOME", str(root))
    monkeypatch.setenv("THREADDESK_STORAGE", "json")
    svc = ThreadService(JsonStore(root))
    svc.create("Initial profile")
    exported = ThreadService(JsonStore(tmp_path / "exported"))
    restored_thread = exported.create("Restored profile")
    body = download_backup(exported.store)
    discoveries = []

    def discover(transport, timeout):
        discoveries.append(str(selected_profile(root)[0]))
        return [f"synthetic-probe-{len(discoveries)}"]

    monkeypatch.setattr("threaddesk.services.hausmeister.list_models", discover)
    app = create_app()
    with raw(app) as client:
        csrf = bootstrap(client)
        response = client.post("/data/restore", data={"confirm": "yes", "csrf_token": csrf},
                               files={"backup": ("synthetic.zip", body, "application/zip")},
                               follow_redirects=False)
        assert response.status_code == 303
        restored_root, _ = selected_profile(root)
        assert restored_root != root
        assert discoveries == [str(root), str(restored_root)]
        before = {str(p.relative_to(restored_root)): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in restored_root.rglob("*") if p.is_file()}
        response = client.get("/", headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"})
        assert response.status_code == 200
        assert 'value="Restored profile"' in response.text
        assert "synthetic-probe-2" in response.text and "synthetic-probe-1" not in response.text
        assert (restored_root / "actors.json").exists()
        assert (restored_root / "modules.json").exists()
        assert before == {str(p.relative_to(restored_root)): (p.read_bytes(), p.stat().st_mtime_ns)
                          for p in restored_root.rglob("*") if p.is_file()}
        assert ThreadService(JsonStore(restored_root)).current().id == restored_thread.id
        # A second restore is a different active profile, with an independent probe.
        response = client.post("/data/restore", data={"confirm": "yes", "csrf_token": csrf},
                               files={"backup": ("synthetic.zip", body, "application/zip")},
                               follow_redirects=False)
        assert response.status_code == 303
        second_root, _ = selected_profile(root)
        assert second_root != restored_root
        assert discoveries == [str(root), str(restored_root), str(second_root)]
        response = client.get("/")
        assert "synthetic-probe-3" in response.text and "synthetic-probe-2" not in response.text
        response = client.post("/data/profile", data={"name": restored_root.name, "csrf_token": csrf},
                               follow_redirects=False)
        assert response.status_code == 303
        assert discoveries == [str(root), str(restored_root), str(second_root), str(restored_root)]
        response = client.get("/")
        assert "synthetic-probe-4" in response.text and "synthetic-probe-3" not in response.text
        response = client.post("/data/original", data={"csrf_token": csrf}, follow_redirects=False)
        assert response.status_code == 303
        assert selected_profile(root)[0] == root
        assert discoveries == [str(root), str(restored_root), str(second_root), str(restored_root), str(root)]
        response = client.get("/")
        assert 'value="Initial profile"' in response.text
        assert "synthetic-probe-5" in response.text and "synthetic-probe-4" not in response.text


def test_get_expires_only_probe_status_without_network_or_cache_rewrite(tmp_path, monkeypatch):
    from threaddesk.services.hausmeister import MODEL_STATUS_TTL_SECONDS

    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    monkeypatch.setenv("THREADDESK_STORAGE", "json")
    svc = ThreadService(JsonStore(tmp_path))
    svc.create("Expiring observation")
    svc.store.write_json_artifact("hausmeister.json", {"version": 1, "model": "saved-synthetic"})
    monkeypatch.setattr("threaddesk.services.hausmeister.list_models", lambda *a, **kw: ["discovered-synthetic"])
    app = create_app()
    with raw(app) as client:
        response = client.get("/")
        assert 'data-ollama="up"' in response.text and '<time datetime="' in response.text
        key = str(svc.store.artifact_path("hausmeister.json"))
        app.state.hausmeister_probes[key]["observed_monotonic"] -= MODEL_STATUS_TTL_SECONDS + 1
        cache = {k: dict(v) for k, v in app.state.hausmeister_probes.items()}
        before = {str(p.relative_to(tmp_path)): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in tmp_path.rglob("*") if p.is_file()}
        monkeypatch.setattr("threaddesk.services.hausmeister.list_models",
                            lambda *a, **kw: pytest.fail("GET refreshed expired probe"))
        response = client.get("/")
        assert response.status_code == 200 and 'data-ollama="unknown"' in response.text
        assert 'value="saved-synthetic" selected' in response.text
        assert "discovered-synthetic" in response.text
        assert app.state.hausmeister_probes == cache
        assert before == {str(p.relative_to(tmp_path)): (p.read_bytes(), p.stat().st_mtime_ns)
                          for p in tmp_path.rglob("*") if p.is_file()}


def test_without_startup_probe_status_is_explicitly_unverified(tmp_path, monkeypatch):
    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    monkeypatch.setenv("THREADDESK_STORAGE", "json")
    ThreadService(JsonStore(tmp_path)).create("No implicit startup")
    monkeypatch.setattr("threaddesk.services.hausmeister.list_models",
                        lambda *a, **kw: pytest.fail("GET discovered models"))
    response = raw(create_app()).get("/")  # No lifespan/startup was requested by this client.
    assert response.status_code == 200
    assert 'data-ollama="unknown"' in response.text
    assert not (tmp_path / "actors.json").exists()
    assert not (tmp_path / "modules.json").exists()
