# admin 内容面板权限边界设计

## 目标

把 `is_admin` 账号从**内容工作**中排除出去：agent 面板、项目面板、反馈面板对管理员既不可见、也不可达。管理员保留系统管理职责（Rootdir 管理、用户管理）与文件浏览/预览/下载/上传。

这条规则是**权限边界**，不是界面偏好——因此前端隐藏入口与服务端拒绝必须同时成立，绕过 UI 直接调 API 也应失败。

## 背景

### 现有鉴权顺序（`dev/auth.py` `AuthMiddleware.dispatch`，实测）

```
1. auth 未启用              → 放行
2. _ALWAYS_ALLOWED          → 放行
3. _is_whitelisted()        → 放行（分享 token 路径、静态资源、登录页）
4. loopback 绕过            → bind LocalAdmin → 立即 return
5. 内部能力 token           → bind LocalAdmin → 立即 return
6. IP 锁定
7. 会话 cookie → user = get_user_store().get(...) → _request_user.set(user) → call_next
```

### 关键约束：`LocalAdmin.is_admin` 为 `True`

第 4、5 步绑定的都是 `local_admin_principal()`，而 `LocalAdmin.is_admin = True`（`dev/root_auth.py:23`）。因此闸口位置决定了"本机操作者是否受这条规则约束"：

- 闸口放在**第 7 步之后** → 本机 loopback 操作者不受影响（第 4 步已 return），只有真实登录的 admin 被拒。
- 闸口放在**第 4 步之前** → 本机操作者一并受限，需额外按客户端 IP 判断。

**本设计采用前者（第 7 步之后）。** 理由：`LocalAdmin` 的 docstring 明确写着 *"Synthetic principal for trusted local clients. Never persisted."* —— 它是**服务器本身**，不是可被降权的**账号**。本规则约束的是账号的角色，合成 principal 无角色可撤；能连上 loopback 的调用方已具备主机级信任，不构成有意义的绕过。

**已知后果**：在服务器本机通过 `localhost:5533` 访问无法验证本规则——必须使用非 loopback 地址并以真实 admin 账号登录。

## 范围

**包含**：中间件的 admin 拒绝闸口、拒绝前缀清单、两条 WebSocket 的握手拒绝、前端三个面板入口的隐藏与面板本体抑制、错误响应形状、单元/契约/e2e 测试、README 与 CHANGELOG。

**不包含**：角色层级（多级管理员）、admin 对文件系统本身的写权限收紧（明确保留）、普通用户之间的隔离、share-view 的匿名接收者（其权限由 token 决定，与账号角色无关）。

## 闸口设计

### 位置

`dev/auth.py` `dispatch()` 第 7 步内，`request.state.user = user` 之后、`call_next(request)` 之前：

```python
request.state.user = user
if getattr(user, "is_admin", False) and _is_admin_denied(path):
    return JSONResponse(
        {"error": "forbidden", "detail": "管理员账号不参与内容工作"},
        status_code=403,
    )
token = _request_user.set(user)
```

### 拒绝前缀

```python
_ADMIN_DENIED_PREFIXES = (
    "/api/clawmate/agent/",       # PTY / openclaw WS、会话历史、diagnostics
    "/api/clawmate/project/",     # 任务执行、推荐、overview、convert
    "/api/clawmate/feedback",     # 创建、列表、更新、删除、批量
    "/api/clawmate/review/",      # decision / plan / confirm / execute
)
```

**不需要豁免表，且这是必须被钉住的不变式。** 服务端到服务端的两条调用——`/api/clawmate/review/result`（执行器回调）与 `/api/clawmate/feedback/cron-tick`（定时任务）——在**第 4 步（loopback）或第 5 步（内部 token）**就被接走并 `return`，永远到不了第 7 步。若日后有人把闸口上移，这两条会静默 403，而该失败没有任何日志或报错，因此必须由测试守卫（见"测试"）。

前缀用 `/api/clawmate/feedback`（无尾斜杠）以覆盖 `/api/clawmate/feedback` 本身的 POST 创建端点。

## WebSocket

中间件不覆盖 WebSocket。两条 WS 各自处理：

- `dev/agent_routes.py` `/api/clawmate/agent/openclaw`（约 966 行）
- `dev/agent_routes.py` `/api/clawmate/agent/terminal/v2`（约 1054 行）

两者现有的形状是 `user = await websocket_user(ws)` 后 `if user is False: close(4401)`。在 `bind_request_user(user)` 之前插入：

```python
if getattr(user, "is_admin", False):
    await ws.close(code=4403, reason="Content panels are unavailable to administrators")
    return
```

关闭码 4403 与既有的 4401 区分。注意 `websocket_user()` 在鉴权未启用时返回 `None`，而现有代码判的是 `is False`；`getattr(None, "is_admin", False)` 为 `False`，因此未启用鉴权的模式不受影响。

## 前端显隐

三个入口：`#btnToggleAgent`、`#btnProjectPanel`、`#btnToggleFeedback`（`index.html` 与 `preview.html`）。

`dev/static/js/topbar.js` 的 `_syncItems()` 已按目标按钮的 `hidden` 属性同步 more-menu 镜像，**因此只需处理顶栏按钮**，手机端菜单自动跟随。`8326d00` 已补 `.topbar-btn[hidden]` / `.more-item[hidden]` 的 `display: none`，特异性足以压过 `.topbar-btn { display: flex }`。

三件事：

1. 三个按钮置 `hidden`。
2. **抑制项目面板的自动展开。** `dev/static/js/app.js:2302` 是 `_setProjectPanelOpen(firstVisit)`——首次进入某个项目目录时无条件展开。admin 下必须强制 `false`，否则会出现"入口没了、面板还在"。
3. 防御性关闭：确认 admin 身份后把三个面板各关一次（覆盖面板已打开再登录/提权的时序）。

`is_admin` 来源为 `/api/clawmate/auth/status`（index 侧 `initSettings()` 已在用）。preview 页目前无此调用，因此在 `topbar.js` 增加一个只请求一次的共享 helper（暴露给两页），避免两处各写一套。

**一帧闪烁的取舍**：按钮默认可见，取到 `is_admin` 后再隐藏，admin 侧可能出现一帧闪烁。消除它需要把 `is_admin` 内联进首屏 HTML（如主题的 anti-flash 脚本），会给静态文件引入服务端渲染。**本设计不做**——边界由服务端保证，UI 闪烁属观感问题。

## 错误响应形状

403 + JSON `{"error": "forbidden", "detail": ...}`，复用 `dev/root_auth.py` `root_not_authorized_handler` 的既有形状，不新造一套。

## 测试

| 断言 | 类型 |
|---|---|
| 四个前缀下的端点 → admin 得 403 | 单元 |
| 普通用户走同样端点 → 正常（回归） | 单元 |
| loopback 操作者 → 正常（钉住第 4 步不被误伤） | 单元 |
| `/review/result` 与 `/feedback/cron-tick` 在 loopback / token 下仍通过 | 单元（钉住"无豁免表"这一不变式） |
| 两条 WS：admin → 4403，且未 `accept()`；非 admin → 可连 | 单元 |
| 鉴权未启用时（`websocket_user()` 返回 `None`）不受影响 | 单元 |
| 三个按钮在 admin 下带 `hidden`，more-menu 镜像同步 | 契约 |
| admin 登录后三个入口不可见、项目面板不自动展开 | e2e（真实浏览器） |
| admin 仍可访问设置路由与文件读路由 | 单元（确认边界没有画过头） |

## 文档

- README「认证与 Rootdir」一节补一句：管理员账号用于系统管理，不参与内容工作。
- CHANGELOG 记为 v1.55。
