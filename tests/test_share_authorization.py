"""The share authorization boundary: who may mint a link, and what a token
reaches once it exists.

A share token is handed to someone with no account, so the recipient endpoints
have to stay anonymous -- and must still resolve exactly the one file the link
recorded. The owner endpoints (/create, /active, /expire) sit under the same URL
prefix and inherited its blanket whitelist. That made them anonymous *and*, once
the root registry made get_roots() user-scoped, answered 403 to everyone: every
share handler resolves paths through safe_path() -> get_roots(), which reports
nothing for a caller the session middleware never resolved -- including for the
recipients who by design have no session at all.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))

import auth  # noqa: E402
import config  # noqa: E402
import routes  # noqa: E402
import share_routes  # noqa: E402

ADMIN_PASSWORD = "new-password"

# A `.local` host, like the rest of this suite: _request_is_https() short-circuits
# on a LAN alias before consulting public_base_url, which is set to an https URL in
# this deployment. Without it the login cookie is issued Secure and httpx never
# sends it back over plain http, so every session silently reads as unauthenticated.
BASE = "http://testserver.local"


def _fresh_client(client: TestClient) -> TestClient:
    """An independent client over the same app, with its own cookie jar."""
    return TestClient(client.app, base_url=BASE)


def _write_registry(tmp_path: Path, dirs: dict[str, str]) -> None:
    (tmp_path / "roots.json").write_text(json.dumps({"roots": [
        {"id": root_id, "label": root_id.title(), "dir": directory, "agent_id": "default"}
        for root_id, directory in dirs.items()]}), encoding="utf-8")


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """A live app with the auth middleware, a registry, and its own share store."""
    for name in ("projects", "private"):
        (tmp_path / name).mkdir()
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "system_root_dir": str(tmp_path),
        "auth": {"session_ttl_minutes": 480},
    }), encoding="utf-8")
    monkeypatch.setenv("CLAWMATE_CONFIG", str(config_path))
    config.set_config_path(config_path)
    config.clear_config_cache()
    _write_registry(tmp_path, {"projects": "projects", "private": "private"})

    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware, config=config.load())
    app.include_router(routes.router)  # login / change-password live here
    app.include_router(share_routes.router)
    # Not a loopback host: the middleware's local-client bypass would otherwise
    # hand every request an administrator principal and hide the boundary.
    return TestClient(app, base_url=BASE), tmp_path


def _login(client: TestClient) -> None:
    login = client.post("/api/clawmate/auth/login",
                        json={"username": "admin", "password": "password"})
    assert login.status_code == 200, login.text
    changed = client.post("/api/clawmate/auth/change-password",
                          json={"password": ADMIN_PASSWORD})
    assert changed.status_code == 200, changed.text


def _mint(client: TestClient, path: str, *, root: str = "projects") -> dict:
    response = client.post("/api/clawmate/share/create",
                           json={"root": root, "path": path, "expires_days": 1})
    assert response.status_code == 200, response.text
    return response.json()


def _create_writer(*root_ids: str) -> None:
    """A regular account, granted only the roots named.

    Created straight through the store: the settings user API needs its own
    admin flow, which is not what these tests are about.
    """
    auth.get_user_store().create_user("writer", "writer-password", list(root_ids))


def _login_as(client: TestClient, username: str, password: str) -> None:
    response = client.post("/api/clawmate/auth/login",
                           json={"username": username, "password": password})
    assert response.status_code == 200, response.text


def test_owner_endpoints_require_a_session(wired):
    """Minting, listing and lapsing links are owner actions. They used to be
    anonymous: a stranger could read the whole shared-file inventory and expire
    anyone's link.
    """
    client, _ = wired

    for path in ("/api/clawmate/share/create", "/api/clawmate/share/expire"):
        response = client.post(path, json={"root": "projects", "path": "doc.md"})
        assert response.status_code == 401, f"{path} -> {response.status_code}"
    assert client.get("/api/clawmate/share/active").status_code == 401


def test_owner_mints_a_link_for_its_own_root(wired):
    """The reported symptom: /share/create answered 403 to the owner."""
    client, tmp_path = wired
    (tmp_path / "projects" / "doc.md").write_text("hello\n", encoding="utf-8")
    _login(client)

    payload = _mint(client, "doc.md")

    assert payload["ok"] is True and payload["token"]
    assert payload["file"] == "doc.md"


def test_recipient_reads_the_shared_file_without_a_session(wired):
    client, tmp_path = wired
    (tmp_path / "projects" / "doc.md").write_text("shared body\n", encoding="utf-8")
    _login(client)
    token = _mint(client, "doc.md")["token"]

    anonymous = _fresh_client(client)
    data = anonymous.get(f"/api/clawmate/share/{token}/data")
    raw = anonymous.get(f"/api/clawmate/share/{token}/raw")

    assert data.status_code == 200, data.text
    assert "shared body" in data.json()["content"]
    assert raw.status_code == 200
    assert "shared body" in raw.text


def test_recipient_fails_closed_once_its_root_leaves_the_registry(wired):
    """The recipient principal grants exactly the link's root, so removing that
    root from the registry must not fall back to serving it anyway."""
    client, tmp_path = wired
    (tmp_path / "projects" / "doc.md").write_text("shared body\n", encoding="utf-8")
    _login(client)
    token = _mint(client, "doc.md")["token"]

    _write_registry(tmp_path, {"private": "private"})
    config.clear_config_cache()

    anonymous = _fresh_client(client)
    response = anonymous.get(f"/api/clawmate/share/{token}/data")

    assert response.status_code != 200
    assert "shared body" not in response.text


def test_asset_must_be_referenced_by_the_shared_document(wired):
    """The basename fallback used to let a recipient fetch any file whose name
    merely appeared in the text -- one mention of README.md exposed every
    README.md under the root."""
    client, tmp_path = wired
    projects = tmp_path / "projects"
    (projects / "img").mkdir()
    (projects / "img" / "only.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (projects / "deep" / "nested").mkdir(parents=True)
    (projects / "deep" / "nested" / "README.md").write_text("not shared", encoding="utf-8")
    (projects / "doc.md").write_text(
        "# doc\n\n![only](img/only.png)\n\nsee README.md for details\n", encoding="utf-8")
    _login(client)
    token = _mint(client, "doc.md")["token"]

    anonymous = _fresh_client(client)

    def asset(path: str) -> int:
        return anonymous.get(f"/api/clawmate/share/{token}/asset",
                             params={"root": "projects", "path": path}).status_code

    assert asset("img/only.png") == 200
    # Named in the document, but not *referenced* by it as an asset.
    assert asset("deep/nested/README.md") == 403
    assert asset("../private/doc.md") == 403


def test_asset_is_read_relative_to_the_shared_files_own_directory(wired):
    """A document in a subdirectory writes `img/x.png`; the recipient's browser
    asks for `notes/img/x.png`. Reading the request relative to the document is
    what keeps that working -- dropping the basename fallback alone would break
    every image in a nested document."""
    client, tmp_path = wired
    projects = tmp_path / "projects"
    (projects / "notes" / "img").mkdir(parents=True)
    (projects / "notes" / "img" / "x.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (projects / "notes" / "doc.md").write_text("![x](img/x.png)\n", encoding="utf-8")
    _login(client)
    token = _mint(client, "notes/doc.md")["token"]

    anonymous = _fresh_client(client)
    response = anonymous.get(f"/api/clawmate/share/{token}/asset",
                             params={"root": "projects", "path": "notes/img/x.png"})

    assert response.status_code == 200, response.text


def test_asset_refuses_a_root_other_than_the_links_own(wired):
    client, tmp_path = wired
    projects = tmp_path / "projects"
    (projects / "img").mkdir()
    (projects / "img" / "only.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (projects / "doc.md").write_text("![only](img/only.png)\n", encoding="utf-8")
    (tmp_path / "private" / "secret.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    _login(client)
    token = _mint(client, "doc.md")["token"]

    anonymous = _fresh_client(client)
    response = anonymous.get(f"/api/clawmate/share/{token}/asset",
                             params={"root": "private", "path": "secret.png"})

    assert response.status_code == 403


def test_active_reports_only_the_roots_the_caller_holds(wired):
    """The inventory spans every root, so an unfiltered list would tell a user
    granted one root which files are shared out of all the others."""
    client, tmp_path = wired
    (tmp_path / "projects" / "doc.md").write_text("x\n", encoding="utf-8")
    (tmp_path / "private" / "secret.md").write_text("y\n", encoding="utf-8")
    _login(client)
    _mint(client, "doc.md", root="projects")
    _mint(client, "secret.md", root="private")
    _create_writer("projects")

    writer = _fresh_client(client)
    _login_as(writer, "writer", "writer-password")
    shared = writer.get("/api/clawmate/share/active").json()["shared"]

    assert set(shared) == {"projects"}
    assert shared["projects"] == ["doc.md"]


def test_expire_refuses_a_root_the_caller_was_not_granted(wired):
    """Expiring matches on plain strings, so without an access check any
    logged-in user could lapse another root's link just by naming it."""
    client, tmp_path = wired
    (tmp_path / "projects" / "doc.md").write_text("x\n", encoding="utf-8")
    (tmp_path / "private" / "secret.md").write_text("y\n", encoding="utf-8")
    _login(client)
    _mint(client, "doc.md", root="projects")
    _mint(client, "secret.md", root="private")
    _create_writer("projects")

    writer = _fresh_client(client)
    _login_as(writer, "writer", "writer-password")

    denied = writer.post("/api/clawmate/share/expire",
                         json={"root": "private", "path": "secret.md"})
    assert denied.status_code == 403
    # Control: the caller's own root is still expirable, so the check rejects the
    # grant mismatch rather than refusing every request.
    allowed = writer.post("/api/clawmate/share/expire",
                          json={"root": "projects", "path": "doc.md"})
    assert allowed.status_code == 200
