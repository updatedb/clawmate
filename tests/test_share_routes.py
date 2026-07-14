import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))

import share_routes  # noqa: E402


@pytest.fixture
def share_client(tmp_path, monkeypatch):
    target = tmp_path / "note.md"
    target.write_text("hello", encoding="utf-8")
    monkeypatch.setenv("CLAWMATE_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(
        share_routes,
        "safe_path",
        lambda root, path: (tmp_path, target, "note.md"),
    )
    share_routes._save_share_links({"links": []})
    app = FastAPI()
    app.include_router(share_routes.router)
    return TestClient(app)


@pytest.mark.parametrize("days", [1, 3, 7, 30])
def test_create_share_uses_requested_expiry_days(share_client, days, monkeypatch):
    now = 1_700_000_000
    monkeypatch.setattr(share_routes.time, "time", lambda: now)

    response = share_client.post(
        "/api/clawmate/share/create",
        json={"root": "root-a", "path": "note.md", "expires_days": days},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["expires_at"] - now == days * 86400
    assert payload["expires_days"] == days


def test_create_share_defaults_to_one_day(share_client, monkeypatch):
    now = 1_700_000_000
    monkeypatch.setattr(share_routes.time, "time", lambda: now)

    response = share_client.post(
        "/api/clawmate/share/create",
        json={"root": "root-a", "path": "note.md"},
    )

    assert response.status_code == 200
    assert response.json()["expires_at"] - now == 86400
    assert response.json()["expires_days"] == 1


@pytest.mark.parametrize("value", [0, -1, 2, "7", None])
def test_create_share_rejects_invalid_expiry_days(share_client, value):
    response = share_client.post(
        "/api/clawmate/share/create",
        json={"root": "root-a", "path": "note.md", "expires_days": value},
    )

    assert response.status_code == 400
    assert "expires_days" in response.json()["detail"]


def test_create_share_reuses_token_and_updates_expiry(share_client, monkeypatch):
    now = 1_700_000_000
    monkeypatch.setattr(share_routes.time, "time", lambda: now)
    first = share_client.post(
        "/api/clawmate/share/create",
        json={"root": "root-a", "path": "note.md", "expires_days": 1},
    ).json()

    monkeypatch.setattr(share_routes.time, "time", lambda: now + 100)
    second = share_client.post(
        "/api/clawmate/share/create",
        json={"root": "root-a", "path": "note.md", "expires_days": 30},
    ).json()

    assert second["token"] == first["token"]
    assert second["reused"] is True
    assert second["expires_at"] == now + 100 + 30 * 86400
