"""Root access for work that has no request behind it.

The registry migration moved roots out of `config.json` and made resolution
user-scoped through `auth.current_request_user()`. Two kinds of caller broke, and
both broke silently:

* unattended work iterated the legacy `cfg.roots` array, which the migration left
  empty -- so cron, startup recovery and the session TTL reaper scanned nothing;
* work off the request thread resolved no caller at all -- a plain
  `threading.Thread` does not inherit the ContextVar -- so root resolution raised
  `RootNotAuthorized` and left a review task reserved as `in_progress` forever.

Server-to-server callers authenticated by a capability token (the ONLYOFFICE
Document Server, a non-loopback executor) had the same gap with no thread
involved: the token authorized them, but nothing bound a principal.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))

import agent_routes  # noqa: E402
import auth  # noqa: E402
import config  # noqa: E402
import routes  # noqa: E402
import service  # noqa: E402
import store  # noqa: E402
import task_runner  # noqa: E402
from root_auth import RootNotAuthorized  # noqa: E402

BASE = "http://testserver.local"  # see tests/test_share_authorization.py
ONLYOFFICE_SECRET = "test-onlyoffice-secret"


@pytest.fixture
def system_root(tmp_path, monkeypatch):
    """A system root with two registered roots and one project."""
    for name in ("projects", "private"):
        (tmp_path / name).mkdir()
    (tmp_path / "projects" / "app" / ".clawmate").mkdir(parents=True)
    (tmp_path / "projects" / ".clawmate").mkdir()
    (tmp_path / "roots.json").write_text(json.dumps({"roots": [
        {"id": "projects", "label": "Projects", "dir": "projects", "agent_id": "default"},
        {"id": "private", "label": "Private", "dir": "private", "agent_id": "default"},
    ]}), encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "system_root_dir": str(tmp_path),
        "auth": {"session_ttl_minutes": 480},
    }), encoding="utf-8")
    monkeypatch.setenv("CLAWMATE_CONFIG", str(config_path))
    config.set_config_path(config_path)
    config.clear_config_cache()
    return tmp_path


def _in_thread(fn):
    """Run fn() on a plain Thread, which does NOT inherit the ContextVar."""
    box = {}

    def target():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - reported back to the test
            box["error"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    return box


def _server():
    return auth.request_user_scope(auth.local_admin_principal())


def test_registered_roots_needs_no_caller(system_root):
    """The server can ask which roots exist without a request behind it."""
    assert auth.current_request_user() is None

    roots = service.registered_roots()

    assert {r["id"] for r in roots} == {"projects", "private"}
    assert all(Path(r["dir"]).is_absolute() for r in roots)


def test_a_background_thread_resolves_no_root_without_a_principal(system_root):
    """The failure that stranded a review task: the launch thread had no caller.

    Pinned rather than fixed away, because it is the reason every unattended path
    needs an explicit principal -- and the reason the fix cannot be "just retry".
    """
    box = _in_thread(lambda: config.load().root_dir("projects"))

    assert isinstance(box.get("error"), RootNotAuthorized)


def test_the_server_scope_restores_root_access_in_a_background_thread(system_root):
    def work():
        with _server():
            directory = config.load().root_dir("projects")
            items, _ = store.list_items("projects", "app")
            return directory, items

    box = _in_thread(work)

    assert "error" not in box
    directory, items = box["value"]
    assert Path(directory) == system_root / "projects"
    assert items == []


def test_cron_tick_scans_the_registry_not_the_legacy_array(system_root, monkeypatch):
    """The scan list came from cfg.roots, which is empty once roots are registered.

    cron is also the one wake path with no thread: it runs its scan inside the
    request, so a loopback caller carries the server principal and this needs no
    scope of its own.
    """
    (system_root / "projects" / "app" / ".clawmate" / "feedback.json").write_text(
        json.dumps({"items": [{"id": "FD-1", "status": "pending"}]}), encoding="utf-8")
    woken = []
    monkeypatch.setattr(task_runner, "_wake_agent_for_root",
                        lambda root_id, **kw: woken.append((root_id, kw.get("project"))))
    monkeypatch.setattr(task_runner, "list_items", lambda *a, **kw: ([], 1))

    asyncio.run(task_runner.cron_tick())

    assert woken == [("projects", "app")]


def test_a_wake_that_cannot_resolve_its_root_releases_the_reservation(system_root):
    """A launch that never happens must not leave the item reserved forever.

    `create_execution_task` refuses to reserve an item that carries an
    execution_task_id, so a stranded reservation is unrecoverable through the API
    -- the panel just spins.
    """
    with _server():
        created = store.create_items("projects", "app", "notes.md", [
            {"text": "body", "note": "n", "position": "L1", "action": "modify"}])
        ids = [item["id"] for item in created]
        store.review_items("projects", "app", ids, "approved")
        task = store.create_execution_task("projects", "app", ids)
        assert task["status"] == "in_progress"

        # No principal: exactly what the launch thread had.
        box = _in_thread(lambda: task_runner._wake_agent_for_root(
            "projects", project="app", include_in_progress=True, review_task_id=task["id"]))
        assert "error" not in box

        released = store.execution_task("projects", "app", task["id"])
        assert released["status"] == "failed"
        assert "wake failed" in released["release_reason"]

        item = next(i for i in store.list_items("projects", "app")[0] if i["id"] == ids[0])
        assert item["status"] == "approved"
        assert item["execution_task_id"] == ""

        # The whole point: it can be reserved again.
        assert store.create_execution_task("projects", "app", ids)["status"] == "in_progress"


def test_release_refuses_a_task_that_is_not_reserved(system_root):
    with _server():
        created = store.create_items("projects", "app", "notes.md", [
            {"text": "body", "note": "n", "position": "L1", "action": "modify"}])
        ids = [item["id"] for item in created]
        store.review_items("projects", "app", ids, "approved")
        task = store.create_execution_task("projects", "app", ids)
        store.release_execution_task("projects", "app", task["id"], "first release")

        with pytest.raises(ValueError, match="not reserved"):
            store.release_execution_task("projects", "app", task["id"], "second release")


def test_session_query_roots_follow_the_callers_grants(system_root):
    """The session history APIs read every registered root before, with no
    scoping at all and nothing to read once cfg.roots went empty."""
    auth.get_user_store().create_user("writer", "writer-password", ["projects"])
    writer = auth.get_user_store().get_by_username("writer")
    auth.bind_request_user(writer)
    try:
        assert [r["id"] for r in agent_routes._roots_for_session_query("")] == ["projects"]
        assert agent_routes._roots_for_session_query("private") == []
    finally:
        auth.bind_request_user(None)


@pytest.fixture
def app_client(system_root, monkeypatch):
    monkeypatch.setenv("CLAWMATE_ONLYOFFICE_JWT_SECRET", ONLYOFFICE_SECRET)
    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware, config=config.load())
    app.include_router(routes.router)
    return TestClient(app, base_url=BASE)


def _login(client: TestClient) -> None:
    client.post("/api/clawmate/auth/login",
                json={"username": "admin", "password": "password"})
    assert client.post("/api/clawmate/auth/change-password",
                       json={"password": "new-password"}).status_code == 200


def test_onlyoffice_document_server_is_authorized_by_its_token(app_client, system_root):
    """The Document Server holds no session, so /file and /callback must stay
    reachable anonymously -- authenticated by the HS256 token, which names the
    file. Nothing bound a principal for them, so root resolution failed and the
    whole editing feature answered 403.
    """
    document = system_root / "projects" / "doc.txt"
    document.write_text("edited body\n", encoding="utf-8")
    token = routes._encode_jwt(
        {"root": "projects", "path": "doc.txt", "exp": 4_000_000_000}, ONLYOFFICE_SECRET)

    anonymous = TestClient(app_client.app, base_url=BASE)
    fetched = anonymous.get("/api/clawmate/onlyoffice/file", params={"token": token})

    assert fetched.status_code == 200, fetched.text
    assert fetched.text == "edited body\n"


def test_onlyoffice_config_is_a_session_route(app_client, system_root):
    """/config takes root and path as plain query params with no token, so
    exempting it would hand out an anonymous file reader."""
    (system_root / "projects" / "doc.txt").write_text("body\n", encoding="utf-8")

    anonymous = TestClient(app_client.app, base_url=BASE)
    assert anonymous.get("/api/clawmate/onlyoffice/config",
                         params={"root": "projects", "path": "doc.txt"}).status_code == 401

    _login(app_client)
    assert app_client.get("/api/clawmate/onlyoffice/config",
                          params={"root": "projects", "path": "doc.txt"}).status_code == 200
