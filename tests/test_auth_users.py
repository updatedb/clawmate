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
    (tmp_path / "projects").mkdir(exist_ok=True)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "system_root_dir": str(tmp_path),
        "auth": {"session_ttl_minutes": 480},
    }))
    (tmp_path / "roots.json").write_text(json.dumps({"roots": [
        {"id": "projects", "label": "Projects", "dir": "projects", "agent_id": "work"},
    ]}), encoding="utf-8")
    monkeypatch.setenv("CLAWMATE_CONFIG", str(config_path))
    config.set_config_path(config_path)
    config.clear_config_cache()
    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware, config=config.load())
    app.include_router(routes.router)
    app.include_router(settings_routes.router)
    return TestClient(app, base_url="http://testserver.local")


def test_bootstrap_admin_must_change_password_before_anything_else(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    login = client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})

    assert login.status_code == 200
    assert client.get("/api/clawmate/auth/me").json()["must_change_password"] is True
    assert client.get("/api/clawmate/list?root=projects").status_code == 403
    assert client.get("/api/clawmate/settings/users").status_code == 403


def test_changing_the_initial_password_lifts_the_restriction(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})

    changed = client.post("/api/clawmate/auth/change-password", json={"password": "new-password"})

    assert changed.status_code == 200
    assert client.get("/api/clawmate/auth/me").json()["must_change_password"] is False
    assert client.get("/api/clawmate/list?root=projects").status_code == 200


def test_identity_and_logout_stay_reachable_during_forced_change(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})

    assert client.get("/api/clawmate/auth/me").status_code == 200
    assert client.get("/api/clawmate/auth/status").status_code == 200


def test_wrong_password_is_rejected(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "nope"})

    assert response.status_code != 200


def test_login_response_never_carries_a_password_hash(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    login = client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})
    me = client.get("/api/clawmate/auth/me")

    assert "password_hash" not in login.text
    assert "password_hash" not in me.text


def test_spoofed_forwarded_header_does_not_grant_local_trust():
    """A remote peer must not be able to claim loopback via a header."""
    from types import SimpleNamespace

    def _request(peer: str, forwarded: str | None):
        headers = {"x-forwarded-for": forwarded} if forwarded else {}
        return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)

    assert auth.get_client_ip(_request("203.0.113.9", "127.0.0.1")) == "203.0.113.9"
    assert auth.get_client_ip(_request("203.0.113.9", None)) == "203.0.113.9"
    assert auth.get_client_ip(_request("127.0.0.1", "203.0.113.9")) == "203.0.113.9"
    assert auth.get_client_ip(
        _request("127.0.0.1", "127.0.0.1, 203.0.113.9")) == "203.0.113.9"


def test_spoofed_forwarded_header_cannot_reach_admin_endpoints(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    spoof = {"X-Forwarded-For": "127.0.0.1"}

    assert client.get("/api/clawmate/config", headers=spoof).status_code == 401
    assert client.get("/api/clawmate/auth/me", headers=spoof).status_code == 401
    assert client.get("/api/clawmate/settings/users", headers=spoof).status_code == 401
    assert client.post("/api/clawmate/settings/users", headers=spoof, json={
        "username": "attacker", "password": "attacker-pw",
        "root_dirs": ["projects"]}).status_code == 401
