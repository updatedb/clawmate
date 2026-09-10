"""Content panels are for ordinary accounts; an administrator runs the system.

The gate lives inside the session branch of AuthMiddleware.dispatch, after the
loopback and internal-token branches have already returned. That placement is
what leaves the local operator untouched and what makes the two server-to-server
paths (/review/result, /feedback/cron-tick) need no exemption entry -- both are
taken by an earlier branch. Moving the gate up would silently 403 the executor
callback, so the last test here pins that.
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

import agent_routes  # noqa: E402
import auth  # noqa: E402
import config  # noqa: E402
import feedback_api  # noqa: E402
import project_routes  # noqa: E402
import routes  # noqa: E402

# Non-loopback on purpose: the loopback bypass binds LocalAdmin and would never
# reach the session branch this gate lives in.
BASE = "http://testserver.local"

# One existing route per denied prefix. The paths must exist, or a 404 would be
# masked as a 403 by the middleware running ahead of routing.
DENIED = [
    ("GET", "/api/clawmate/agent/sessions", {}),
    ("GET", "/api/clawmate/project/projects/app/overview", {}),
    ("GET", "/api/clawmate/feedback/list", {"params": {"root": "projects", "project": "app"}}),
    ("POST", "/api/clawmate/review/decision", {"json": {}}),
]


@pytest.fixture
def system_root(tmp_path, monkeypatch):
    for name in ("projects", "private"):
        (tmp_path / name).mkdir()
    (tmp_path / "projects" / "app" / ".clawmate").mkdir(parents=True)
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


@pytest.fixture
def client(system_root):
    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware, config=config.load())
    for module in (routes, agent_routes, project_routes, feedback_api):
        app.include_router(module.router)
    return TestClient(app, base_url=BASE)


def _login_admin(client: TestClient) -> None:
    """Complete the seeded account's forced password change.

    Without this the middleware answers 403 password_change_required for every
    /api/ path, and a bare 403 assertion would pass for the wrong reason.
    """
    client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})
    changed = client.post("/api/clawmate/auth/change-password", json={"password": "new-password"})
    assert changed.status_code == 200, changed.text


def _login_writer(client: TestClient) -> None:
    auth.get_user_store().create_user("writer", "writer-password", ["projects"])
    logged_in = client.post("/api/clawmate/auth/login",
                            json={"username": "writer", "password": "writer-password"})
    # Without this a failed login leaves the request under test unauthenticated,
    # and the 401 that follows gets attributed to the route instead of to the
    # missing ordinary-user session. (Under a bare `!= 403` it passed silently.)
    assert logged_in.status_code == 200, logged_in.text


@pytest.mark.parametrize("method,path,kwargs", DENIED)
def test_an_admin_is_refused_on_every_denied_prefix(client, method, path, kwargs):
    _login_admin(client)
    response = client.request(method, path, **kwargs)
    assert response.status_code == 403, response.text
    # The body, not just the code: 403 alone is also what the forced
    # password-change guard returns.
    assert response.json()["error"] == "forbidden"


@pytest.mark.parametrize("method,path,kwargs", DENIED)
def test_an_ordinary_account_reaches_the_same_routes(client, method, path, kwargs):
    """Proves the route exists, so the admin 403 is the gate and not a 404."""
    _login_writer(client)
    response = client.request(method, path, **kwargs)
    # The handler's own code, not `!= 403`: a path that no longer exists answers
    # 404, which satisfies `!= 403` and would let a masked route deletion pass.
    # 200 is the two GETs; 422 is the POSTs, whose empty bodies fail their own
    # validation -- both mean routing ran.
    assert response.status_code in (200, 422), response.text


def test_the_local_operator_is_not_affected(client):
    """Loopback binds LocalAdmin (is_admin=True) and returns before the gate.

    The peer address must be set explicitly: starlette's TestClient defaults it
    to ("testclient", 50000) and `base_url` does NOT change it, so
    `_is_local_client` would answer False and this test would 401 on the session
    check -- passing `!= 403` without ever taking the loopback branch it names.
    """
    local = TestClient(client.app, client=("127.0.0.1", 43210))
    response = local.get("/api/clawmate/feedback/list",
                         params={"root": "projects", "project": "app"})
    # 200 from the handler, not merely "not 403": an unauthenticated non-loopback
    # caller would 401 here, which `!= 403` would have accepted.
    assert response.status_code == 200, response.text
    assert "items" in response.json()


def test_the_executor_result_callback_is_not_affected(client):
    """The invariant that lets the gate carry no exemption list.

    /review/result sits inside a denied prefix, and only the branch order keeps
    it reachable: the loopback branch takes it before the session branch is
    reached. Assert both halves -- the prefix really does cover it, and a real
    executor call still gets through. A tautological constant check would not
    catch the gate being moved up.
    """
    assert auth._is_admin_denied("/api/clawmate/review/result")

    # Peer address set explicitly for the same reason as the test above: the
    # default ("testclient", ...) is not loopback, so the executor's own call
    # would fall through to the session check and 401.
    executor = TestClient(client.app, client=("127.0.0.1", 43210))
    response = executor.post("/api/clawmate/review/result", json={
        "root": "projects", "project": "app",
        "task_id": "RV-does-not-exist", "status": "done", "result": "",
    })
    # 422 is the evidence, and it must be *this* 422: the route's own field
    # validator rejects the minimal payload above (summary/diff/success are
    # missing), so the message is produced inside the handler. Auth middleware
    # short-circuits (401/403) could never carry it, so a loopback caller that
    # quietly stopped reaching the handler would fail here rather than satisfy
    # a bare `!= 403`.
    assert response.status_code == 422, response.text
    assert "Invalid review result fields" in response.json()["detail"]
