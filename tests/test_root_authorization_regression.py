from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))

import auth  # noqa: E402
import config  # noqa: E402
import routes  # noqa: E402
import service  # noqa: E402
import settings_routes  # noqa: E402


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    (tmp_path / "projects").mkdir(exist_ok=True)
    (tmp_path / "private").mkdir(exist_ok=True)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "system_root_dir": str(tmp_path),
        "auth": {"session_ttl_minutes": 480},
    }))
    monkeypatch.setenv("CLAWMATE_CONFIG", str(config_path))
    config.set_config_path(config_path)
    config.clear_config_cache()
    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware, config=config.load())
    app.include_router(routes.router)
    app.include_router(settings_routes.router)
    return TestClient(app, base_url="http://testserver.local")


def _seed_roots(tmp_path: Path) -> None:
    (tmp_path / "roots.json").write_text(json.dumps({"roots": [
        {"id": "private", "label": "Private", "dir": "private", "agent_id": "default"},
        {"id": "projects", "label": "Projects", "dir": "projects", "agent_id": "work"},
    ]}), encoding="utf-8")


def _login_admin(client: TestClient) -> None:
    client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})
    client.post("/api/clawmate/auth/change-password", json={"password": "new-password"})


def _create_writer() -> object:
    """Create the regular user straight through the store.

    The settings user API does not take root_ids until Task 5 rewrites it, so
    these regression tests bind the account the same way the login path does.
    """
    return auth.get_user_store().create_user("writer", "writer-password", ["projects"])


def test_deleted_user_session_is_rejected(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    _seed_roots(tmp_path)
    writer_id = _create_writer().id

    client.delete(f"/api/clawmate/settings/users/{writer_id}")
    session_id, _ = asyncio.run(auth.create_session("writer", 480, user_id=writer_id, is_admin=False))
    client.cookies.set("clawmate_session", session_id)

    assert client.get("/api/clawmate/config").status_code == 401
    assert client.get("/api/clawmate/list?root=private").status_code == 401


def test_registered_root_outside_user_grants_is_forbidden(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    _seed_roots(tmp_path)
    _create_writer()
    client.post("/api/clawmate/auth/logout")
    client.post("/api/clawmate/auth/login", json={"username": "writer", "password": "writer-password"})

    assert client.get("/api/clawmate/list?root=projects").status_code == 200
    assert client.get("/api/clawmate/list?root=private").status_code == 403


def test_unregistered_root_is_not_resolved_from_legacy_config(tmp_path: Path, monkeypatch):
    """A root id present only in the old config.json roots array must not resolve."""
    outside = tmp_path.parent / "legacy-outside"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    client = _client(tmp_path, monkeypatch)
    config_path = tmp_path / "config.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["roots"] = [{"id": "legacy", "label": "Legacy", "dir": str(outside), "agent_id": "main"}]
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    config.clear_config_cache()

    client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})
    client.post("/api/clawmate/auth/change-password", json={"password": "new-password"})

    ids = [root["id"] for root in client.get("/api/clawmate/config").json()["roots"]]
    assert "legacy" not in ids
    assert client.get("/api/clawmate/list?root=legacy").status_code == 403


def test_authorization_failure_maps_to_403_not_400(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    _seed_roots(tmp_path)
    _create_writer()
    client.post("/api/clawmate/auth/logout")
    client.post("/api/clawmate/auth/login", json={"username": "writer", "password": "writer-password"})

    response = client.get("/api/clawmate/list?root=private")

    assert response.status_code == 403


def test_registry_entry_escaping_the_system_root_is_never_served(tmp_path: Path, monkeypatch):
    """A hand-edited dir must not let reads resolve outside system_root_dir."""
    outside = tmp_path.parent / "outside-served"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    client = _client(tmp_path, monkeypatch)
    (tmp_path / "roots.json").write_text(json.dumps({"roots": [
        {"id": "escape", "label": "Escape", "dir": "..", "agent_id": "default"},
        {"id": "projects", "label": "Projects", "dir": "projects", "agent_id": "work"},
    ]}), encoding="utf-8")
    _login_admin(client)

    # The reported set comes from get_roots() directly, not /api/clawmate/config:
    # that route's admin branch still hardcodes ["."] (dev/routes.py:65) and never
    # consults the registry, so it cannot report a registered root either way. The
    # boundary that matters for reads is the one resolve_root() -> _root_map() ->
    # get_roots() walks.
    auth.bind_request_user(auth.get_user_store().get_administrator())
    try:
        reported, _ = service.get_roots()
    finally:
        auth.bind_request_user(None)
    ids = [root["id"] for root in reported]

    assert "escape" not in ids
    assert "projects" in ids
    assert client.get("/api/clawmate/list?root=escape").status_code == 403
    assert client.get("/api/clawmate/list?root=projects").status_code == 200


def test_read_endpoints_serve_a_granted_file_to_a_logged_in_user(tmp_path: Path, monkeypatch):
    """`/preview`, `/download` and `/raw` must resolve the caller's roots.

    All three sit in `auth._ALWAYS_ALLOWED` ("always allowed regardless of auth
    config"), and that exemption returns from the middleware *before* the session
    is resolved. `get_roots()` fails closed for an unresolved caller, so it
    reported no roots and every one of these endpoints answered 403 to everyone,
    session or not -- while `list`, which is not exempt, kept working. The
    gallery thumbnail is an <img> pointing at /preview and the preview page
    fetches its content from the same route, so the app lost its thumbnails and
    every preview; the user saw it as a 403 on one image.

    Nothing covered these routes before, which is how the regression shipped.
    """
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    _seed_roots(tmp_path)
    (tmp_path / "projects" / "note.md").write_text("# hello\n", encoding="utf-8")
    _create_writer()
    client.post("/api/clawmate/auth/logout")
    client.post("/api/clawmate/auth/login", json={"username": "writer", "password": "writer-password"})

    # Control: the non-exempt route resolves the same root for the same session.
    assert client.get("/api/clawmate/list?root=projects").status_code == 200

    for endpoint in ("preview", "download", "raw"):
        response = client.get(f"/api/clawmate/{endpoint}",
                              params={"root": "projects", "path": "note.md"})
        assert response.status_code == 200, f"{endpoint} -> {response.status_code}"


def test_read_endpoints_still_deny_a_root_outside_the_callers_grants(tmp_path: Path, monkeypatch):
    """Removing the exemption must not widen anything: the boundary still holds."""
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    _seed_roots(tmp_path)
    (tmp_path / "private" / "secret.md").write_text("secret\n", encoding="utf-8")
    _create_writer()
    client.post("/api/clawmate/auth/logout")
    client.post("/api/clawmate/auth/login", json={"username": "writer", "password": "writer-password"})

    for endpoint in ("preview", "download", "raw"):
        response = client.get(f"/api/clawmate/{endpoint}",
                              params={"root": "private", "path": "secret.md"})
        assert response.status_code == 403, f"{endpoint} -> {response.status_code}"


def test_read_endpoints_deny_an_unauthenticated_caller(tmp_path: Path, monkeypatch):
    """These routes are no longer anonymous: the caller must hold a session."""
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    _seed_roots(tmp_path)
    (tmp_path / "projects" / "note.md").write_text("# hello\n", encoding="utf-8")
    client.post("/api/clawmate/auth/logout")

    for endpoint in ("preview", "download", "raw"):
        response = client.get(f"/api/clawmate/{endpoint}",
                              params={"root": "projects", "path": "note.md"})
        assert response.status_code == 401, f"{endpoint} -> {response.status_code}"
