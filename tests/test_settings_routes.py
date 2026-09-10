from __future__ import annotations

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
import settings_routes  # noqa: E402


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    (tmp_path / "projects").mkdir()
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


def test_initial_admin_can_only_change_password(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    login = client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})

    assert login.status_code == 200
    assert client.get("/api/clawmate/auth/me").json()["must_change_password"] is True
    assert client.get("/api/clawmate/list?root=projects").status_code == 403
    changed = client.post("/api/clawmate/auth/change-password", json={"password": "new-password"})
    assert changed.status_code == 200
    assert client.get("/api/clawmate/auth/me").json()["must_change_password"] is False


def test_admin_creates_user_with_child_root(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})
    client.post("/api/clawmate/auth/change-password", json={"password": "new-password"})

    response = client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_dirs": ["projects"],
    })

    assert response.status_code == 201
    assert response.json()["root_dirs"] == ["projects"]
    assert "password_hash" not in response.text


def test_regular_user_cannot_forge_another_root(tmp_path: Path, monkeypatch):
    (tmp_path / "private").mkdir()
    client = _client(tmp_path, monkeypatch)
    client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})
    client.post("/api/clawmate/auth/change-password", json={"password": "new-password"})
    client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_dirs": ["projects"],
    })
    client.post("/api/clawmate/auth/logout")
    client.post("/api/clawmate/auth/login", json={"username": "writer", "password": "writer-password"})

    assert client.get("/api/clawmate/list?root=projects").status_code == 200
    assert client.get("/api/clawmate/list?root=private").status_code == 403


def test_regular_user_config_exposes_only_granted_root_without_path(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})
    client.post("/api/clawmate/auth/change-password", json={"password": "new-password"})
    client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_dirs": ["projects"],
    })
    client.post("/api/clawmate/auth/logout")
    client.post("/api/clawmate/auth/login", json={"username": "writer", "password": "writer-password"})

    roots = client.get("/api/clawmate/config").json()["roots"]

    assert roots == [{"id": "projects", "label": "projects", "agent_id": "default"}]


def test_admin_settings_uses_current_account_role_not_stale_session_role(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    admin = auth.get_user_store().authenticate("admin", "password")
    assert admin is not None

    import asyncio
    session_id, _ = asyncio.run(auth.create_session(
        admin.username,
        3600,
        user_id=admin.id,
        is_admin=False,
    ))
    client.cookies.set("clawmate_session", session_id)

    assert client.get("/api/clawmate/auth/status").json()["is_admin"] is True
    assert client.get("/api/clawmate/settings/users").status_code == 200
