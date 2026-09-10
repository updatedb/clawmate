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


def _seed_roots(tmp_path: Path, *entries: tuple[str, str, str, str]) -> None:
    (tmp_path / "roots.json").write_text(json.dumps({"roots": [
        {"id": root_id, "label": label, "dir": directory, "agent_id": agent_id}
        for root_id, label, directory, agent_id in entries
    ]}), encoding="utf-8")


def _login_admin(client: TestClient) -> None:
    client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})
    client.post("/api/clawmate/auth/change-password", json={"password": "new-password"})


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    (tmp_path / "projects").mkdir(exist_ok=True)
    (tmp_path / "private").mkdir(exist_ok=True)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "system_root_dir": str(tmp_path),
        "auth": {"session_ttl_minutes": 480},
    }))
    _seed_roots(tmp_path,
                ("projects", "Projects", "projects", "work"),
                ("private", "Private", "private", "main"))
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
    _login_admin(client)

    response = client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["projects"],
    })

    assert response.status_code == 201
    assert response.json()["root_ids"] == ["projects"]
    assert "password_hash" not in response.text


def test_regular_user_cannot_forge_another_root(tmp_path: Path, monkeypatch):
    (tmp_path / "private").mkdir()
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["projects"],
    })
    client.post("/api/clawmate/auth/logout")
    client.post("/api/clawmate/auth/login", json={"username": "writer", "password": "writer-password"})

    assert client.get("/api/clawmate/list?root=projects").status_code == 200
    assert client.get("/api/clawmate/list?root=private").status_code == 403


def test_regular_user_config_exposes_only_granted_root_without_path(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["projects"],
    })
    client.post("/api/clawmate/auth/logout")
    client.post("/api/clawmate/auth/login", json={"username": "writer", "password": "writer-password"})

    roots = client.get("/api/clawmate/config").json()["roots"]

    assert roots == [{"id": "projects", "label": "Projects", "agent_id": "work"}]
    assert str(tmp_path) not in json.dumps({"roots": roots})


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


def test_config_exposes_registry_labels_and_agent_ids(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)

    roots = client.get("/api/clawmate/config").json()["roots"]

    assert roots[0] == {"id": ".", "label": "系统根目录", "agent_id": "default"}
    assert {"id": "projects", "label": "Projects", "agent_id": "work"} in roots


def test_settings_users_returns_registry_summary_not_directory_dump(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)

    data = client.get("/api/clawmate/settings/users").json()

    assert data["roots"] == [{"id": "projects", "label": "Projects"},
                             {"id": "private", "label": "Private"}]


def test_admin_creates_root_with_derived_id(tmp_path: Path, monkeypatch):
    (tmp_path / "helper" / "3gpp").mkdir(parents=True)
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)

    response = client.post("/api/clawmate/settings/roots", json={
        "label": "3GPP Meetings", "dir": "helper/3gpp", "agent_id": "helper"})

    assert response.status_code == 201
    assert response.json() == {"id": "3gpp", "label": "3GPP Meetings",
                               "dir": "helper/3gpp", "agent_id": "helper"}


def test_admin_updates_a_root_without_changing_its_id(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)

    response = client.patch("/api/clawmate/settings/roots/projects",
                            json={"label": "Work", "agent_id": "helper"})

    assert response.status_code == 200
    assert response.json() == {"id": "projects", "label": "Work",
                               "dir": "projects", "agent_id": "helper"}
    assert client.get("/api/clawmate/settings/roots").json()["roots"][0] == response.json()


def test_admin_cannot_delete_a_root_in_use(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["projects"]})

    response = client.delete("/api/clawmate/settings/roots/projects")

    assert response.status_code == 422
    assert "正被用户引用" in response.text
    assert client.get("/api/clawmate/settings/roots").json()["roots"][0]["id"] == "projects"


def test_admin_cannot_register_a_directory_outside_the_system_root(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)

    response = client.post("/api/clawmate/settings/roots", json={
        "label": "Escape", "dir": "../outside", "agent_id": "default"})

    assert response.status_code == 422


def test_grant_referencing_an_unregistered_root_id_is_rejected(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)

    response = client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["no-such-root"]})

    assert response.status_code == 422
    assert "no-such-root" in response.text
    assert [user["username"] for user in
            client.get("/api/clawmate/settings/users").json()["users"]] == ["admin"]


def test_grant_ids_are_validated_against_the_registry_not_the_filesystem(tmp_path: Path, monkeypatch):
    """A root whose id differs from its directory basename must still be grantable."""
    (tmp_path / "helper" / "3gpp").mkdir(parents=True)
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    created = client.post("/api/clawmate/settings/roots", json={
        "label": "3GPP Meetings", "dir": "helper/3gpp", "agent_id": "helper"})
    assert created.json()["id"] == "3gpp"

    response = client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["3gpp"]})

    assert response.status_code == 201
    assert response.json()["root_ids"] == ["3gpp"]


def test_patch_rejects_an_unregistered_grant_id(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    created = client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["projects"]})

    response = client.patch(f"/api/clawmate/settings/users/{created.json()['id']}",
                            json={"root_ids": ["no-such-root"]})

    assert response.status_code == 422


def test_promoting_a_user_to_admin_discards_stale_grants(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    created = client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["projects"]})

    response = client.patch(f"/api/clawmate/settings/users/{created.json()['id']}",
                            json={"is_admin": True, "root_ids": ["no-such-root"]})

    assert response.status_code == 200
    assert response.json()["is_admin"] is True
    assert response.json()["root_ids"] == []


def test_regular_user_cannot_reach_root_management(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["projects"]})
    client.post("/api/clawmate/auth/logout")
    client.post("/api/clawmate/auth/login", json={"username": "writer", "password": "writer-password"})

    assert client.get("/api/clawmate/settings/roots").status_code == 403
    assert client.post("/api/clawmate/settings/roots",
                       json={"label": "X", "dir": "projects"}).status_code == 403


def test_auth_me_exposes_granted_root_summaries(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["projects"]})
    client.post("/api/clawmate/auth/logout")
    client.post("/api/clawmate/auth/login", json={"username": "writer", "password": "writer-password"})

    me = client.get("/api/clawmate/auth/me").json()

    assert me["roots"] == [{"id": "projects", "label": "Projects", "agent_id": "work"}]


def test_local_admin_principal_is_never_listed_as_an_account(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)

    usernames = [user["username"] for user in client.get("/api/clawmate/settings/users").json()["users"]]

    assert "local-admin" not in usernames
    assert usernames == ["admin"]


def test_admin_accounts_are_stored_without_root_ids(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)

    created = client.post("/api/clawmate/settings/users", json={
        "username": "root2", "password": "root2-password",
        "root_ids": ["projects"], "is_admin": True})

    assert created.status_code == 201
    assert created.json()["root_ids"] == []


def test_agent_routing_follows_the_registry_not_legacy_config(tmp_path: Path, monkeypatch):
    (tmp_path / "helper" / "3gpp").mkdir(parents=True)
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    created = client.post("/api/clawmate/settings/roots", json={
        "label": "3GPP Meetings", "dir": "helper/3gpp", "agent_id": "helper"})
    assert created.json()["id"] == "3gpp"
    client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["3gpp"]})
    client.post("/api/clawmate/auth/logout")
    client.post("/api/clawmate/auth/login", json={"username": "writer", "password": "writer-password"})

    assert client.get("/api/clawmate/config").json()["roots"] == [
        {"id": "3gpp", "label": "3GPP Meetings", "agent_id": "helper"}]
    assert config.load().root_agent("3gpp") == "helper"


def test_root_mutation_endpoints_require_admin(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["projects"]})
    client.post("/api/clawmate/auth/logout")
    client.post("/api/clawmate/auth/login", json={"username": "writer", "password": "writer-password"})

    assert client.patch("/api/clawmate/settings/roots/projects",
                        json={"label": "X"}).status_code == 403
    assert client.delete("/api/clawmate/settings/roots/projects").status_code == 403
    assert client.patch("/api/clawmate/settings/users/whatever",
                        json={"username": "x"}).status_code == 403
    assert client.delete("/api/clawmate/settings/users/whatever").status_code == 403


def test_unknown_root_id_gives_404_on_patch_and_delete(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)

    assert client.patch("/api/clawmate/settings/roots/nope",
                        json={"label": "X"}).status_code == 404
    assert client.delete("/api/clawmate/settings/roots/nope").status_code == 404


def test_create_root_rejects_an_out_of_charset_id_or_agent_id(tmp_path: Path, monkeypatch):
    # A fresh directory: a seeded one would be rejected as already registered
    # before the charset checks run, which would not exercise them.
    (tmp_path / "docs").mkdir()
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)

    assert client.post("/api/clawmate/settings/roots", json={
        "id": "bad id", "label": "Bad", "dir": "docs"}).status_code == 422
    assert client.post("/api/clawmate/settings/roots", json={
        "label": "Bad", "dir": "docs", "agent_id": "bad agent"}).status_code == 422


def test_explicit_json_null_id_derives_instead_of_creating_a_None_root(tmp_path: Path, monkeypatch):
    # A fresh directory, for the same reason as the charset test above.
    (tmp_path / "docs").mkdir()
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)

    created = client.post("/api/clawmate/settings/roots", json={
        "id": None, "label": None, "dir": "docs", "agent_id": None})

    assert created.status_code == 201
    body = created.json()
    assert body["id"] == "docs"
    assert body["id"] != "None"
    assert body["label"] != "None"
    assert body["agent_id"] == "default"


def test_corrupt_registry_returns_422_not_500(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    (tmp_path / "roots.json").write_text("{ not json", encoding="utf-8")

    assert client.get("/api/clawmate/settings/roots").status_code == 422
    assert client.get("/api/clawmate/settings/users").status_code == 422
