"""Content panels are for ordinary accounts; an administrator runs the system.

The gate lives inside the session branch of AuthMiddleware.dispatch, after the
loopback and internal-token branches have already returned. That placement is
what leaves the local operator untouched and what makes the two server-to-server
paths (/review/result, /feedback/cron-tick) need no exemption entry -- both are
taken by an earlier branch. Moving the gate up would silently 403 the executor
callback, so the last test here pins that.

The two agent websockets are the other half: BaseHTTPMiddleware never processes a
`ws` scope, so no middleware placement covers them and each handler refuses on its
own. Those tests live here too, and they pin both directions -- the admin is
closed at handshake, and an ordinary account still reaches `ready` on the socket.
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
import feedback_api  # noqa: E402
import project_routes  # noqa: E402
import routes  # noqa: E402
from terminal_manager import TerminalManager  # noqa: E402

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


def test_both_agent_websockets_close_an_admin_at_handshake(client):
    """Websockets bypass the middleware entirely, so each handler has to refuse
    on its own. 4403 rather than 4401: the caller authenticated fine, the
    account role is what closed it.

    No receive() on the socket: the close happens before accept(), so
    WebSocketDisconnect comes out of `websocket_connect.__enter__` (starlette
    calls _raise_on_close on the first server message). Reading a frame here
    would instead park on WebSocketTestSession.receive() -- an unbounded
    portal.call with no pytest timeout configured -- so a regression that drops
    one gate would hang the file rather than fail it.
    """
    from starlette.websockets import WebSocketDisconnect

    _login_admin(client)
    for path in ("/api/clawmate/agent/openclaw", "/api/clawmate/agent/terminal/v2"):
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect(path):
                pass
        assert excinfo.value.code == 4403, path


class _NeverEndingPty:
    """PTY stand-in modelled on FakePty in tests/test_terminal_websocket_v2.py.

    read() parks forever, which is what an interactive shell looks like to the
    handler between keystrokes -- so the session reaches `ready` and then sits
    idle instead of the fake process exiting under the test.
    """

    async def read(self, size: int) -> bytes:
        await asyncio.Future()
        return b""

    async def write_all(self, data: bytes) -> None:
        return None

    async def resize(self, cols: int, rows: int) -> None:
        return None

    async def terminate(self) -> None:
        return None


def _run_within(timeout: float, body, label: str):
    """Run `body` on a worker thread, and fail if it has not finished in time.

    WebSocketTestSession.receive() is an unbounded portal.call, so a handler
    that accepts and then stalls parks the test forever instead of failing it.
    The bound cannot come from `@pytest.mark.timeout`: pytest-timeout is not a
    dependency of this repo and no conftest registers the marker, so it only
    ever produced a PytestUnknownMarkWarning (`--strict-markers` refuses to even
    collect this file). The bound therefore lives here.

    The whole interaction runs on the worker rather than just the receive: the
    portal that WebSocketTestSession talks through is started inside that same
    thread, so every websocket call stays on the thread that owns it. The worker
    is a daemon, so one abandoned to a stalled handler cannot hold up
    interpreter shutdown.
    """
    outcome: dict[str, object] = {}

    def worker() -> None:
        try:
            outcome["value"] = body()
        except BaseException as exc:  # noqa: BLE001 -- re-raised on this thread
            outcome["error"] = exc

    thread = threading.Thread(target=worker, daemon=True, name="clawmate-ws-check")
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        pytest.fail(f"{label}: 服务端 {timeout:g}s 内没有完成交互（handler 接受连接后卡住）")
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")


def test_an_ordinary_account_reaches_ready_on_the_terminal_websocket(client, monkeypatch):
    """The other direction of the same gate: it must not over-block.

    A bare truthiness test (`if user:`) in place of `getattr(user, "is_admin", False)`
    would 4403 every logged-in account -- both panels dead for ordinary users --
    and the admin test above would still pass. Nothing else in the repo covers
    that: tests/test_terminal_websocket_v2.py drives the handler with no cookies,
    so websocket_user() answers None and the role check is never consulted.

    `ready` is the assertion rather than "not 4403": it is emitted only from
    inside the handler, after the hello parse, get_or_create and subscribe have
    all succeeded, so routing, auth and the role check had to pass for it to
    arrive.

    The interaction is bounded (_run_within) on purpose -- a handler that accepts
    and then stalls would otherwise park on receive() forever. Measured: with the
    ready frame withheld, this test used to hang until killed, because the
    @pytest.mark.timeout(30) that stood here was inert under this repo's own
    runner.
    """
    async def factory(request):
        return _NeverEndingPty()

    manager = TerminalManager(factory, replay_bytes=4096)
    monkeypatch.setattr(agent_routes, "_terminal_v2_manager", manager)
    # Same isolation as the protocol tests: without this the handler falls back
    # to the user's HOME, which is not a fixture-owned directory.
    monkeypatch.setattr(agent_routes, "resolve_session_cwd", lambda root, dir_: "/tmp/project")
    _login_writer(client)

    def exchange():
        with client.websocket_connect("/api/clawmate/agent/terminal/v2") as ws:
            ws.send_text(json.dumps({
                "v": 2,
                "type": "hello",
                "id": "hello-1",
                "client_id": "browser-1",
                "root": "projects",
                "dir": "app",
                "backend": "claude",
                "cols": 80,
                "rows": 24,
            }))
            return ws.receive_json()

    ready = _run_within(30, exchange, "ordinary account reaches ready")

    assert ready["type"] == "ready", ready
    assert ready["session_id"], ready
