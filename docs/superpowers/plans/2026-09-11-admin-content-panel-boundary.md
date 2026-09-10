# admin 内容面板权限边界 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `is_admin` 账号对 agent / 项目 / 反馈三个面板既不可见也不可达，同时保留其系统管理与文件浏览能力。

**Architecture:** 在 `AuthMiddleware.dispatch()` 的**会话分支内**插入一个按路径前缀判定的闸口，使 loopback 与内部 token 两类调用方（它们在更早的分支 `return`）不受影响——这同时让两条服务端到服务端的调用无需豁免表。两条 agent WebSocket 不走中间件，各自在握手处加同一条判定。前端在 `topbar.js` 增加一个只请求一次的 `is_admin` 取数点，两个页面据此隐藏三个入口、抑制项目面板的自动展开。

**Tech Stack:** Python 3 / FastAPI / Starlette（中间件、WebSocket）、pytest + `TestClient`、原生 JS（无框架）、Playwright（e2e）。

## Global Constraints

- 规范来源：`docs/superpowers/specs/2026-09-11-admin-content-panel-boundary-design.md`。
- 闸口**必须在会话分支内**（`request.state.user = user` 之后、`_request_user.set(user)` 之前）。上移到 loopback 分支之前会静默 403 掉执行器回调。
- 拒绝前缀固定为四项：`/api/clawmate/agent/`、`/api/clawmate/project/`、`/api/clawmate/feedback`、`/api/clawmate/review/`。注意 `/api/clawmate/feedback` **不带尾斜杠**（要覆盖 `POST /api/clawmate/feedback` 本身）。
- 错误形状固定为 `{"error": "forbidden", "detail": ...}` + `403`，与 `dev/root_auth.py:root_not_authorized_handler` 一致。
- WebSocket 关闭码固定为 `4403`（与既有 `4401` 区分）。
- 测试客户端 base_url 必须是非 loopback 的 `http://testserver.local`，否则会走 loopback 绕过分支，测不到会话路径。
- 前端尺寸/颜色一律走 `dev/static/css/tokens.css` 的既有 token，不新增魔法值。
- 提交信息用 Conventional Commits，结尾带 `Co-Authored-By: Claude Code <noreply@anthropic.com>`。

---

### Task 1: 中间件 admin 闸口

**Files:**
- Modify: `dev/auth.py`（在 `_WHITELIST_PREFIXES` 之后新增常量与判定函数；在 `dispatch()` 的 `request.state.user = user` 之后插入闸口）
- Test: `tests/test_admin_content_boundary.py`（新建）

**Interfaces:**
- Consumes: 无（本任务是最底层）
- Produces: `auth._ADMIN_DENIED_PREFIXES: tuple[str, ...]`、`auth._is_admin_denied(path: str) -> bool`。Task 2 不消费它们（WS 是独立判定），Task 5 的 e2e 依赖其行为。

> **两个测试陷阱，必须先处理，否则测试会因错误的原因通过：**
>
> 1. **`must_change_password` 会先返回 403。** 种子账号 `admin` 的该标记为 `True`，中间件在会话分支之前就会对 `/api/` 返回 `{"error": "password_change_required"}`。若测试不先走完改密流程，断言 `status_code == 403` 会通过——但测的是改密拦截，不是本闸口。因此**必须同时断言响应体**。`user_store.create_user()` 创建的账号该标记为 `False`，不受影响。
> 2. **404 也会变成 403。** 中间件在路由之前运行，所以一个不存在的路径只要落在前缀下也会返回 403。因此测试**必须挂载真实路由器**，并用"普通用户得到非 403"来证明该路径确实存在。

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_admin_content_boundary.py`：

```python
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
    client.post("/api/clawmate/auth/login", json={"username": "writer", "password": "writer-password"})


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
    assert response.status_code != 403, response.text


def test_the_local_operator_is_not_affected(client):
    """Loopback binds LocalAdmin (is_admin=True) and returns before the gate."""
    local = TestClient(client.app, base_url="http://127.0.0.1")
    response = local.get("/api/clawmate/feedback/list",
                         params={"root": "projects", "project": "app"})
    assert response.status_code != 403, response.text


def test_the_executor_result_callback_is_not_affected(client):
    """The invariant that lets the gate carry no exemption list.

    /review/result sits inside a denied prefix, and only the branch order keeps
    it reachable: the loopback branch takes it before the session branch is
    reached. Assert both halves -- the prefix really does cover it, and a real
    executor call still gets through. A tautological constant check would not
    catch the gate being moved up.
    """
    assert auth._is_admin_denied("/api/clawmate/review/result")

    executor = TestClient(client.app, base_url="http://127.0.0.1")
    response = executor.post("/api/clawmate/review/result", json={
        "root": "projects", "project": "app",
        "task_id": "RV-does-not-exist", "status": "done", "result": "",
    })
    assert response.status_code != 403, response.text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest tests/test_admin_content_boundary.py -v`
Expected: FAIL —— `AttributeError: module 'auth' has no attribute '_is_admin_denied'`，且四条 admin 用例返回 200/404 而非 403。

- [ ] **Step 3: 加常量与判定函数**

在 `dev/auth.py` 的 `_WHITELIST_PREFIXES` 定义（约 349 行）之后插入：

```python
# Content work -- agent sessions, project tasks, feedback review -- belongs to
# ordinary accounts. An administrator's job is the system itself.
#
# There is deliberately no exemption list. The two server-to-server paths under
# these prefixes (/api/clawmate/review/result, /api/clawmate/feedback/cron-tick)
# are taken by the loopback and internal-token branches ABOVE this gate, which
# return before the session branch is reached. Moving this gate up would
# silently 403 the executor callback, so tests/test_admin_content_boundary.py
# pins that ordering.
_ADMIN_DENIED_PREFIXES = (
    "/api/clawmate/agent/",
    "/api/clawmate/project/",
    "/api/clawmate/feedback",  # no trailing slash: covers POST /feedback itself
    "/api/clawmate/review/",
)


def _is_admin_denied(path: str) -> bool:
    """True when this path is closed to administrator accounts."""
    return any(path.startswith(prefix) for prefix in _ADMIN_DENIED_PREFIXES)
```

- [ ] **Step 4: 在会话分支插入闸口**

`dev/auth.py` 约 544-545 行，把：

```python
        request.state.user = user
        token = _request_user.set(user)
```

改成：

```python
        request.state.user = user
        # Inside the session branch on purpose: the loopback and internal-token
        # callers above already returned, so this refuses account holders only.
        if getattr(user, "is_admin", False) and _is_admin_denied(path):
            return JSONResponse(
                {"error": "forbidden", "detail": "管理员账号不参与内容工作"},
                status_code=403,
            )
        token = _request_user.set(user)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python3 -m pytest tests/test_admin_content_boundary.py -v`
Expected: PASS（10 条：4 admin + 4 普通账号 + 1 loopback + 1 回调）

- [ ] **Step 6: 跑全量回归**

Run: `python3 -m pytest -q`
Expected: 无新增失败。

- [ ] **Step 7: 提交**

```bash
git add dev/auth.py tests/test_admin_content_boundary.py
git commit -m "fix: refuse content routes to administrator accounts"
```

---

### Task 2: 两条 WebSocket 的握手拒绝

**Files:**
- Modify: `dev/agent_routes.py`（约 971 行与 1059 行，两处 `bind_request_user(user)` 之前）
- Test: `tests/test_admin_content_boundary.py`（追加）

**Interfaces:**
- Consumes: 无（与 Task 1 的常量无关——WS 判定按账号角色，不按路径）
- Produces: 无新符号

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_admin_content_boundary.py`：

```python
def test_both_agent_websockets_close_an_admin_at_handshake(client, monkeypatch):
    """Websockets bypass the middleware entirely, so each handler has to refuse
    on its own. 4403 rather than 4401: the caller authenticated fine, the
    account role is what closed it."""
    from starlette.websockets import WebSocketDisconnect

    _login_admin(client)
    for path in ("/api/clawmate/agent/openclaw", "/api/clawmate/agent/terminal/v2"):
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect(path) as ws:
                ws.receive_text()
        assert excinfo.value.code == 4403, path
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest tests/test_admin_content_boundary.py::test_both_agent_websockets_close_an_admin_at_handshake -v`
Expected: FAIL —— 关闭码是 4401 或连接被接受后超时，不是 4403。

- [ ] **Step 3: 在两处握手处插入判定**

`dev/agent_routes.py` 两处（`/agent/openclaw` 的 handler 与 `/agent/terminal/v2` 的 handler）均为同一形状：

```python
    user = await websocket_user(ws)
    if user is False:
        await ws.close(code=4401, reason="Authentication required")
        return
    bind_request_user(user)
```

改成：

```python
    user = await websocket_user(ws)
    if user is False:
        await ws.close(code=4401, reason="Authentication required")
        return
    # The middleware never runs for a websocket, so the content-panel boundary
    # has to be enforced here too. websocket_user() returns None when auth is
    # disabled; getattr(None, "is_admin", False) is False, so that mode is
    # unaffected -- which is why this checks `is_admin` rather than `is not None`.
    if getattr(user, "is_admin", False):
        await ws.close(code=4403, reason="Content panels are unavailable to administrators")
        return
    bind_request_user(user)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m pytest tests/test_admin_content_boundary.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add dev/agent_routes.py tests/test_admin_content_boundary.py
git commit -m "fix: close the agent websockets to administrators at handshake"
```

---

### Task 3: 前端 is_admin 取数点与三个入口的隐藏

**Files:**
- Modify: `dev/static/js/topbar.js`（新增共享取数 + 隐藏入口）
- Modify: `dev/static/js/app.js`（index 侧接线）
- Modify: `dev/static/js/preview.js`（preview 侧接线）
- Test: `tests/test_admin_panel_contract.py`（新建）

**Interfaces:**
- Consumes: `/api/clawmate/auth/status` 的 `{logged_in, is_admin}` 字段（`app.js:3111` 的 `initSettings()` 已在消费）
- Produces: `window.ClawMateAdmin.load(): Promise<boolean>` 与 `window.ClawMateAdmin.isAdmin(): boolean`，供 `app.js`、`preview.js`（Task 4）、契约测试引用

- [ ] **Step 1: 写失败的契约测试**

创建 `tests/test_admin_panel_contract.py`：

```python
"""The panels are gone for an administrator on both pages, and the more-menu
mirror follows without being told separately -- topbar.js's _syncItems() reads
the target button's `hidden`, so hiding the button IS the whole mechanism.
"""

from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "dev" / "static"
ENTRIES = ("btnToggleAgent", "btnProjectPanel", "btnToggleFeedback")


def test_the_shared_gate_is_a_single_fetch():
    topbar = (STATIC / "js" / "topbar.js").read_text(encoding="utf-8")
    assert "ClawMateAdmin" in topbar
    assert "/api/clawmate/auth/status" in topbar
    # One request per page load, not one per caller.
    assert topbar.count("/api/clawmate/auth/status") == 1


def test_the_three_entries_are_the_ones_hidden():
    """Hiding the topbar button is the whole mechanism: _syncItems() derives
    each more-menu mirror from its target's `hidden`, so the mobile menu needs
    no separate code. The attribute is used rather than an inline display
    because #btnProjectPanel has its display rewritten on every navigation."""
    topbar = (STATIC / "js" / "topbar.js").read_text(encoding="utf-8")
    for entry in ENTRIES:
        assert entry in topbar, entry
    assert "el.hidden = true" in topbar


def test_both_pages_apply_the_boundary():
    for page in ("app.js", "preview.js"):
        source = (STATIC / "js" / page).read_text(encoding="utf-8")
        assert "ClawMateAdmin" in source, page
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest tests/test_admin_panel_contract.py -v`
Expected: FAIL —— `topbar.js` 中不存在 `ClawMateAdmin`。

- [ ] **Step 3: 在 topbar.js 增加共享取数点**

在 `dev/static/js/topbar.js` 的 `window._topbarResolvedTheme` 定义之后、`initMoreMenu` 之前插入：

```javascript
  // ── Account role (shared by index + preview) ──
  // One fetch per page load. The boundary it feeds is enforced on the server;
  // this only decides which entries are drawn.
  var _adminPromise = null;
  var _isAdmin = null;

  function loadIsAdmin() {
    if (_adminPromise) return _adminPromise;
    // Plain fetch, not authFetch: a loopback client is not "logged in" and
    // authFetch would bounce it to the login page on its expected 401.
    _adminPromise = fetch('/api/clawmate/auth/status')
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (me) { _isAdmin = !!(me && me.logged_in && me.is_admin); return _isAdmin; })
      .catch(function () { _isAdmin = false; return false; });
    return _adminPromise;
  }

  // The three content panels are closed to administrators. Hiding the topbar
  // button is the whole mechanism: _syncItems() derives each more-menu mirror
  // from its target's `hidden`, so the mobile menu follows for free. The
  // attribute is used rather than an inline display because #btnProjectPanel
  // has its display rewritten on every navigation.
  //
  // Panel containers are listed per entry rather than derived, because index
  // and preview name them differently (agentPanel vs previewAgentPanel) and
  // preview has no project container at all. Absent ids are skipped.
  var CONTENT_PANEL_ENTRIES = [
    { toggle: 'btnToggleAgent', panels: ['agentPanel', 'previewAgentPanel'] },
    { toggle: 'btnProjectPanel', panels: ['projectPanel'] },
    { toggle: 'btnToggleFeedback', panels: ['rightSidebar'] },
  ];

  function hideContentPanelEntries() {
    CONTENT_PANEL_ENTRIES.forEach(function (entry) {
      var el = document.getElementById(entry.toggle);
      if (el) el.hidden = true;
    });
  }

  // Close through the page's own toggle so the panel animation and the grid
  // bookkeeping stay in the code path that owns them. #btnToggleFeedback's
  // handler lives in a nested scope of preview.js and is not reachable from a
  // new top-level function; the toggle is the supported way in.
  function closeContentPanels() {
    CONTENT_PANEL_ENTRIES.forEach(function (entry) {
      var toggle = document.getElementById(entry.toggle);
      if (!toggle) return;
      var open = entry.panels.some(function (id) {
        var panel = document.getElementById(id);
        return panel && !panel.classList.contains('hidden');
      });
      if (open) toggle.click();
    });
  }
```

并把导出改成（`initMoreMenu` 之前或紧随其后）：

```javascript
  window.ClawMateAdmin = {
    load: loadIsAdmin,
    isAdmin: function () { return _isAdmin === true; },
    hideContentPanelEntries: hideContentPanelEntries,
    closeContentPanels: closeContentPanels,
  };
```

- [ ] **Step 4: 在 app.js 接线**

在 `dev/static/js/app.js` 的 `_initAgent()` 之后新增，并在页面初始化处调用一次：

```javascript
// Administrators run the system, not the content panels: the server refuses
// these routes for them (auth._ADMIN_DENIED_PREFIXES), and this keeps the
// entries from being drawn. _updateProjectPanelBtn() is what closes the
// project panel -- it must not auto-open it either (see _adminDeniesContentPanels).
let _adminDeniesContentPanels = false;

function _applyAdminContentPanelBoundary() {
  if (!window.ClawMateAdmin) return;
  window.ClawMateAdmin.load().then(function (isAdmin) {
    if (!isAdmin) return;
    _adminDeniesContentPanels = true;
    window.ClawMateAdmin.hideContentPanelEntries();
    _setProjectPanelOpen(false);
    window.ClawMateAdmin.closeContentPanels();
  });
}
```

在页面初始化的同一处（`_initAgent()` 被调用的位置附近）加上 `_applyAdminContentPanelBoundary();`。

- [ ] **Step 5: 在 preview.js 接线**

在 `dev/static/js/preview.js` 增加同形函数并在初始化处调用：

```javascript
// Same boundary as index: hidden entries, and no panel left open behind them.
// Both effects live in topbar.js so the two pages cannot drift apart; the
// preview page names its panels differently (previewAgentPanel / rightSidebar)
// and closeContentPanels() covers that.
function _applyAdminContentPanelBoundary() {
  if (!window.ClawMateAdmin) return;
  window.ClawMateAdmin.load().then(function (isAdmin) {
    if (!isAdmin) return;
    window.ClawMateAdmin.hideContentPanelEntries();
    window.ClawMateAdmin.closeContentPanels();
  });
}
```

- [ ] **Step 6: 运行契约测试确认通过**

Run: `python3 -m pytest tests/test_admin_panel_contract.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add dev/static/js/topbar.js dev/static/js/app.js dev/static/js/preview.js tests/test_admin_panel_contract.py
git commit -m "feat: hide the content panel entries from administrators"
```

---

### Task 4: 抑制项目面板的自动展开

**Files:**
- Modify: `dev/static/js/app.js`（`_updateProjectPanelBtn()`，约 2302 行）
- Test: `tests/test_admin_panel_contract.py`（追加）

**Interfaces:**
- Consumes: `_adminDeniesContentPanels`（Task 3 产生）
- Produces: 无新符号

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_admin_panel_contract.py`：

```python
def test_the_project_panel_does_not_auto_open_for_an_admin():
    """_updateProjectPanelBtn() opens the panel on a project's first visit in a
    login session. With the entry hidden, that would open a panel nobody can
    close."""
    source = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert "_setProjectPanelOpen(firstVisit && !_adminDeniesContentPanels)" in source
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest tests/test_admin_panel_contract.py::test_the_project_panel_does_not_auto_open_for_an_admin -v`
Expected: FAIL —— 源码里仍是 `_setProjectPanelOpen(firstVisit);`

- [ ] **Step 3: 改一行**

`dev/static/js/app.js` 约 2302 行：

```javascript
  // Only a newly visited project opens automatically. Switching to a project
  // already visited in this login session always starts closed.
  _setProjectPanelOpen(firstVisit);
```

改成：

```javascript
  // Only a newly visited project opens automatically. Switching to a project
  // already visited in this login session always starts closed. An
  // administrator gets no panel at all: the entry is hidden, so an auto-open
  // would leave a panel with no way to close it.
  _setProjectPanelOpen(firstVisit && !_adminDeniesContentPanels);
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m pytest tests/test_admin_panel_contract.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add dev/static/js/app.js tests/test_admin_panel_contract.py
git commit -m "fix: stop the project panel auto-opening for administrators"
```

---

### Task 5: 浏览器验收与文档

**Files:**
- Modify: `tests/test_e2e_browser.py`（在既有 admin 验收流程旁新增一条）
- Modify: `README.md`（「认证与 Rootdir」一节）
- Modify: `CHANGELOG.md`（v1.55）

**Interfaces:**
- Consumes: Task 1-4 的全部行为
- Produces: 无

- [ ] **Step 1: 写 e2e 检查**

在 `tests/test_e2e_browser.py` 中，紧跟 `test_ordinary_user_does_not_render_the_settings_entry`（约 752 行）之后新增。复用该文件既有的 `page` 夹具、`login(page)` 辅助函数（签名为 `login(page, username=None, password=None)`，默认即模块级的管理员凭据）与临时实例启动流程——**不要新建启动逻辑**。

> **实测注意（Task 3、Task 4 执行时各踩一次，务必先读）**：service worker 会**静默地**接管请求——不只是路由，**静态资源也一样**。
>
> - `page.route()` **拦不住 `/api/clawmate/config`**，桩会失效，探测可能**因错误的原因**看起来是绿的；
> - Task 4 的前两次浏览器尝试拿到的是 SW 缓存的**旧 `app.js`**，改动的效果根本没加载。
>
> 因此：浏览器夹具必须用 `service_workers="block"`，且**只有 SW 屏蔽后的运行才算数**。不要因为第一次跑是绿的（或红的）就下结论。
>
> 同时：本仓库**可以**用真实 admin 会话做浏览器验收。`tests/test_e2e_browser.py` 已预置 admin 账号（`is_admin: True`、`must_change_password: False`，约 `:408-410`）并设置 `CLIENT_HEADERS = {"X-Forwarded-For": "203.0.113.9"}`（`:514`），让服务端把浏览器当作**远程客户端**而非 loopback 主体——`test_ordinary_user_does_not_render_the_settings_entry`（`:750`）正是这样给 `#btnSettings` 断言反向行为的。不要因为"loopback 不是登录态"就认为这条无法验收。

```python
def test_an_admin_sees_no_content_panel_entries(page: Page):
    """The inverse of the settings check: the one entry an admin keeps is
    settings, and the three content panels are gone -- including on mobile,
    where the more-menu mirrors them."""
    login(page)

    # The gate resolves asynchronously, so poll rather than sampling once.
    for entry in ("#btnToggleAgent", "#btnProjectPanel", "#btnToggleFeedback"):
        page.wait_for_selector(f"{entry}[hidden]", timeout=10000)
        check(page.locator(entry).is_hidden(), f"管理员看不到 {entry}")

    # The more-menu mirror follows the same gate; a mirror left behind would be
    # a way back in on a phone.
    page.set_viewport_size({"width": 375, "height": 812})
    page.locator("#btnMoreMenu").click()
    for mirror in ('[data-more="btnToggleAgent"]', '[data-more="btnProjectPanel"]'):
        check(page.locator(mirror).is_hidden(), f"移动端菜单不提供 {mirror}")
```

**还要加一条：项目面板对 admin 不自动展开。**

Task 4 的行为（`_setProjectPanelOpen(firstVisit && !_adminDeniesContentPanels)`）目前**只有一个源码契约测试守着，而且它可被绕过**——在受守卫的调用后面再补一句不受守卫的 `_setProjectPanelOpen(firstVisit);`，正则仍匹配第一行，测试照绿而 admin 的面板又自动展开了。

但**不要照着"登录后断言 `#projectPanel` 隐藏"来写，那会是一条空过的断言**，有两个独立的陷阱：

1. `_updateProjectPanelBtn()` 在 `state.project` 为空时提前 return（`app.js:2293` 附近），裸页面上的断言恒真；
2. 更关键：**真实 admin 结构上拿不到任何 root**（`user_store` 创建/更新时 `if admin: roots = []`），所以 `init()` 在加载目录前就 return 了，`state.project` 永远为空——即便"先选个项目"也到不了那个状态。

因此这条断言要成立，夹具必须**显式预置一个带授权的 admin**（在临时实例的 `users.json` 里给 admin 记录写上 `root_ids: ["projects"]`；v1.54 已移除读取时的授权重校验，手写的授权会被沿用），然后：

```python
def test_the_project_panel_does_not_auto_open_for_an_admin(page: Page):
    """The guard's only other coverage is a source-text test that can be
    bypassed by appending an unguarded call, so it needs a behavioural pin.

    A real admin is granted no roots, so `state.project` can never be set and a
    bare assertion would be vacuous. The fixture therefore seeds an admin that
    *does* hold a grant, which is also the config where the guard actually
    fires.
    """
    login(page, username=E2E_ADMIN_USERNAME, password=PASSWORD)  # 用预置了授权的 admin
    page.goto(f"{CLAWMATE_URL}/?root=.&dir=projects")
    page.wait_for_function("() => state.dir === 'projects'", timeout=15000)
    check(not page.locator("#projectPanel").is_visible(),
          "管理员进入项目目录时项目面板不自动展开")
```

若实现时发现这个状态**仍然不可达**（例如 admin 的授权被 `get_roots()` 过滤掉），**不要改写成一条恒真的断言**——报告 `NEEDS_CONTEXT` 说明卡在哪，由控制者决定是换手段还是把该守卫记录为"不可达的防御性代码"。

> **这三条 `check` 是"循环覆盖"的唯一保障，不要删。** Task 3 的源码契约测试能钉住 `CONTENT_PANEL_ENTRIES` 的内容和每条的处理方式，但**看不见循环访问了几条**——把 `CONTENT_PANEL_ENTRIES.forEach(` 改成 `.slice(0, 1).forEach(` 时，契约测试仍然 3 passed，而只隐藏了第一个入口。上面逐条断言三个 `#btnToggle*` 才能抓到它（index 页只有两个，`btnProjectPanel` 可见即失败）。这是源码契约测试的固有代价，浏览器断言是唯一的真修法。

- [ ] **Step 2: 运行 e2e 确认通过**

Run: `python3 -m pytest tests/test_e2e_browser.py -m e2e -v -k "admin_sees_no_content_panel"`
Expected: PASS

- [ ] **Step 3: 更新 README**

在「认证与 Rootdir」一节末尾（`README.md` 约 399 行「首次启动会创建 `admin / password`…」之后）追加一句：

```markdown
管理员账号用于系统管理（Rootdir 与用户），不参与内容工作：Agent 终端、项目面板与反馈面板对管理员账号既不可见、也不可达。文件浏览、预览与下载不受影响。
```

- [ ] **Step 4: 更新 CHANGELOG**

在 `CHANGELOG.md` 的 `# Changelog` 之后新增（v1.55 尚未发布，若已存在同名版本则并入其下）：

```markdown
## v1.55 (2026-09-11)
### 权限边界
- 管理员账号不再参与内容工作：agent 终端、项目面板、反馈面板对其不可见且不可达。闸口位于 `AuthMiddleware.dispatch()` 的会话分支内、按四个 API 前缀拒绝；两条 agent WebSocket 因不经中间件而在握手处单独拒绝（关闭码 4403）。loopback 与内部 token 调用方在更早的分支返回，因此本机操作者与执行器回调（`/review/result`）不受影响——这也让闸口无需豁免表。
- 前端隐藏三个顶栏入口（手机端 more-menu 镜像自动跟随），并抑制项目面板的首次访问自动展开。
- 管理员保留系统设置与文件浏览、预览、下载、上传能力。
```

- [ ] **Step 5: 跑全量测试**

Run: `python3 -m pytest -q && python3 -m pytest -m e2e -q`
Expected: 两者均无失败。

- [ ] **Step 6: 提交**

```bash
git add tests/test_e2e_browser.py README.md CHANGELOG.md
git commit -m "docs: record the administrator content-panel boundary"
```

---

## Self-Review

**Spec coverage:**

| Spec 章节 | 对应任务 |
|---|---|
| 闸口位置（会话分支内） | Task 1 Step 4 |
| 拒绝前缀 | Task 1 Step 3 |
| 无豁免表的不变式 | Task 1 Step 1（`test_the_executor_result_callback_is_not_affected`）+ 注释 |
| WebSocket 两条 | Task 2 |
| 前端显隐（含 more-menu 镜像） | Task 3 |
| 项目面板自动展开抑制 | Task 4 |
| 防御性关闭 | Task 3 Step 4 / Step 5 |
| 一帧闪烁的取舍（不做） | 无任务——spec 明确排除 |
| 错误响应形状 | Task 1 Step 4 |
| 测试表 9 行 | Task 1（4 行）、Task 2（2 行：4403 + 未启用鉴权由 `getattr(None,...)` 覆盖）、Task 3-4 契约（2 行）、Task 5 e2e（1 行）、Task 1 Step 1 的普通账号用例（边界没画过头） |
| README / CHANGELOG | Task 5 Step 3-4 |

**Placeholder scan:** 无 TBD/TODO；每个代码步骤都给了完整代码。Task 3 Step 5 与 Task 5 Step 1 明确标注了"以文件中实际的函数/夹具名为准"并给出核对要求，因为那两个符号是文件局部的。

**Type consistency:** `_ADMIN_DENIED_PREFIXES` / `_is_admin_denied` 在 Task 1 定义并在测试中按名引用；前端 `window.ClawMateAdmin.load()` / `.isAdmin()` / `.hideContentPanelEntries()` / `.entries` 在 Task 3 定义，Task 3/4 一致引用；`_adminDeniesContentPanels` 在 Task 3 定义、Task 4 消费，名字一致。
