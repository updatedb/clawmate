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


def test_share_feedback_history_is_limited_to_its_token_and_file(share_client, monkeypatch):
    now = 1_700_000_000
    monkeypatch.setattr(share_routes.time, "time", lambda: now)
    token = share_client.post(
        "/api/clawmate/share/create",
        json={"root": "root-a", "path": "note.md"},
    ).json()["token"]
    token_id = share_routes.hashlib.sha256(token.encode()).hexdigest()[:16]
    monkeypatch.setattr(share_routes, "find_project_marker", lambda root, path: "project-a")
    monkeypatch.setattr(
        "store.list_items",
        lambda *args, **kwargs: ([
            {"id": "FD-visible", "share_token_id": token_id, "file": "project-a/note.md", "status": "approved", "created": "2026-01-01 10:00:00", "updated": "2026-01-02 10:00:00", "action": "modify", "content": "visible", "note": "keep", "position": "Line 1"},
            {"id": "FD-legacy", "share_token_id": token_id, "file": "note.md", "status": "approved", "content": "legacy", "location": "Line 2"},
            {"id": "FD-other-token", "share_token_id": "other", "file": "note.md", "content": "hidden"},
            {"id": "FD-other-file", "share_token_id": token_id, "file": "other.md", "content": "hidden"},
        ], 1),
    )

    response = share_client.get(f"/api/clawmate/share/{token}/feedback")

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "id": "FD-visible", "status": "approved", "created": "2026-01-01 10:00:00",
            "updated": "2026-01-02 10:00:00", "action": "modify", "scope": "", "task_id": "", "content": "visible",
            "note": "keep", "position": "Line 1",
        },
        {
            "id": "FD-legacy", "status": "approved", "created": "", "updated": "",
            "action": "", "scope": "", "task_id": "", "content": "legacy", "note": "", "position": "Line 2",
            "location": "Line 2",
        },
    ]


def test_share_feedback_create_preserves_canonical_locator_and_selected_action(share_client, monkeypatch):
    token = share_client.post(
        "/api/clawmate/share/create", json={"root": "root-a", "path": "note.md"}
    ).json()["token"]
    monkeypatch.setattr(share_routes, "find_project_marker", lambda root, path: "project-a")
    captured = []
    monkeypatch.setattr("store.create_items", lambda root, project, path, selections: (captured.extend(selections) or [{"id": "FD-1"}]))

    response = share_client.post(f"/api/clawmate/share/{token}/feedback", json={"selections": [{
        "text": "selected", "note": "remove this", "position": "Line 2-3",
        "start_line": 2, "end_line": 3, "action": "delete", "scope": "paragraph",
        "task_id": "review_delete",
    }]})

    assert response.status_code == 200
    assert response.json()["ids"] == ["FD-1"]
    assert captured == [{
        "text": "selected", "note": "remove this", "position": "Line 2-3",
        "action": "delete", "scope": "paragraph", "task_id": "review_delete",
        "source": "share", "author": "匿名评审人",
        "share_token_id": share_routes.hashlib.sha256(token.encode()).hexdigest()[:16],
    }]


def test_share_feedback_delete_is_scoped_to_the_share_token_and_file(share_client, monkeypatch):
    token = share_client.post(
        "/api/clawmate/share/create", json={"root": "root-a", "path": "note.md"}
    ).json()["token"]
    token_id = share_routes.hashlib.sha256(token.encode()).hexdigest()[:16]
    monkeypatch.setattr(share_routes, "find_project_marker", lambda root, path: "project-a")
    monkeypatch.setattr(
        "store.list_items",
        lambda *args, **kwargs: ([{"id": "FD-visible", "share_token_id": token_id, "file": "note.md"}], 1),
    )
    removed = []
    monkeypatch.setattr("store.delete_item", lambda root, project, item_id: removed.append((root, project, item_id)))

    response = share_client.post(f"/api/clawmate/share/{token}/feedback/delete", json={"id": "FD-visible"})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "id": "FD-visible"}
    assert removed == [("root-a", "project-a", "FD-visible")]
