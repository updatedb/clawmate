# ClawMate 登录管理方案

> 状态：待审查 | 日期：2026-06-02

## 1. 背景

ClawMate 当前**无任何认证机制**，所有页面和 API 端点完全开放。公网部署场景下（`note.updatedb.online:18443`），任何人都能浏览文件、修改反馈、操作文件。

唯一例外：ONLYOFFICE 预览使用内部 JWT，但那是对 ONLYOFFICE 服务的鉴权，不是对用户的鉴权。

## 2. 目标

- 单用户方案（一个管理员账号）
- 最小实现，不引入外部依赖（数据库、Redis 等）
- 登录页简洁，不破坏现有 ClawMate 品牌风格
- API 全量保护，未登录无法访问
- 密码存储安全（bcrypt 哈希，不存明文）

## 3. 方案

### 3.1 认证机制：Session Cookie

```
用户 → 登录页 /login
     → POST /api/clawmate/auth/login {username, password}
     → 服务端验证 → 签发 session cookie
     → 之后所有请求携带 cookie
     → 中间件校验 cookie → 放行或 302 → /login
```

选择 Session Cookie 而非 JWT 的理由：
- 浏览器天然支持，前端无需改代码
- 登出即时生效（服务端删除 session）
- 单用户场景不需要 JWT 的无状态优势

### 3.2 密码存储

```json
// config.json 新增
{
  "auth": {
    "username": "admin",
    "password_hash": "$2b$12$...",   // bcrypt
    "session_ttl_minutes": 480       // 8 小时，默认
  }
}
```

- 密码通过 CLI 工具设置：`python main.py --set-password`
- 也支持在 API 登录后修改（`POST /api/clawmate/auth/change-password`）
- bcrypt 成本因子 12

### 3.3 Session 管理

```
SessionMiddleware 拦截所有请求
  ├── 白名单路径（跳过）:
  │     /login                        ← 登录页
  │     /api/clawmate/auth/login       ← 登录接口
  │     /api/clawmate/auth/logout      ← 登出接口
  │     /api/clawmate/onlyoffice/*     ← ONLYOFFICE 回调使用自己的 JWT
  │     /static/css/*, /static/vendor/* ← CSS/JS 资源（登录页需要加载）
  │
  └── 受保护路径:
        检查 Cookie: session_id=xxx
          ├── 有效 → 放行
          └── 无效/过期 → 302 跳转到 /login?redirect=<原URL>
```

Session 存储：**内存 dict**（单进程、单用户，无需 Redis）。

```python
sessions: dict[str, Session] = {}
# Session = {username, created_at, last_access, expires_at}

# 清理过期 session 的后台任务
# 每次请求时顺便清理（lazy cleanup）
```

### 3.4 Session TTL

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `session_ttl_minutes` | 480 (8h) | 绝对过期时间 |
| idle timeout | 无 | 不强制空闲超时（简化） |
| cookie HttpOnly | true | JS 无法读取 |
| cookie SameSite | Lax | 防止 CSRF |
| cookie Secure | false | 当前 HTTP 部署，HTTPS 后打 true |

### 3.5 登录页设计

```
┌──────────────────────────────────┐
│                                  │
│         ClawMate                 │
│      文件预览与管理               │
│                                  │
│   ┌──────────────────────┐       │
│   │ 用户名               │       │
│   └──────────────────────┘       │
│   ┌──────────────────────┐       │
│   │ 密码                 │       │
│   └──────────────────────┘       │
│   ┌──────────────────────┐       │
│   │      登  录           │       │
│   └──────────────────────┘       │
│                                  │
│        错误提示区域               │
│                                  │
└──────────────────────────────────┘
```

- 居中卡片布局，暗色背景（与 ClawMate 主题一致）
- 用户名 + 密码 + 登录按钮
- 登录失败显示红色提示
- 无注册、无忘记密码（单用户）
- 响应式，手机端友好
- 登录成功后跳转到 `/`（或 `redirect` 参数指定的 URL）

### 3.6 API 设计

#### POST /api/clawmate/auth/login

```json
// Request
{"username": "admin", "password": "xxx"}

// Response 200
{"ok": true, "redirect": "/"}

// Response 401
{"ok": false, "error": "用户名或密码错误"}
```

生成 session_id → Set-Cookie → 返回 redirect URL。

#### POST /api/clawmate/auth/logout

```json
// Response 200
{"ok": true}
```

清除服务端 session + 清除 cookie → 返回。

#### POST /api/clawmate/auth/change-password

```json
// Request (需已登录)
{"old_password": "xxx", "new_password": "yyy"}

// Response 200
{"ok": true}

// Response 401
{"ok": false, "error": "原密码错误"}
```

更新 config.json 中的 `password_hash`。

#### GET /api/clawmate/auth/status

```json
// Response 200 (已登录)
{"ok": true, "username": "admin"}

// Response 401 (未登录)
{"ok": false}
```

前端用来检测登录状态。

### 3.7 文件变更清单

| 文件 | 变更类型 | 描述 |
|------|----------|------|
| `dev/config.example.json` | 修改 | 增加 `auth` 配置节 |
| `dev/routes.py` | 修改 | 增加 4 个 auth 端点 |
| `dev/auth.py` | **新建** | Session 管理 + 密码验证 + 中间件 |
| `dev/static/login.html` | **新建** | 登录页 |
| `dev/static/css/login.css` | **新建** | 登录页样式 |
| `dev/main.py` | 修改 | 注册 auth middleware |
| `dev/requirements.txt` | 修改 | 增加 `bcrypt` |
| `dev/routes.py` | 修改 | 白名单路径标记 |

### 3.8 中间件实现伪代码

```python
# auth.py

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse

WHITELIST = [
    "/login",
    "/api/clawmate/auth/login",
    "/api/clawmate/auth/logout",
    "/api/clawmate/onlyoffice/",
    "/static/css/",
    "/static/vendor/",
]

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path

        # 白名单放行
        if any(path.startswith(w) for w in WHITELIST):
            return await call_next(request)

        # 检查 session cookie
        session_id = request.cookies.get("session_id")
        session = get_session(session_id)

        if session and not session.is_expired():
            session.touch()  # 刷新最后访问时间
            return await call_next(request)

        # 未登录 → 跳转到登录页
        redirect_url = f"/login?redirect={quote(request.url.path)}"
        return RedirectResponse(url=redirect_url, status_code=302)
```

### 3.9 密码设置 CLI

```bash
# 初次设置
python main.py --set-password
# 交互式输入密码（不显示在终端）

# 修改密码
python main.py --set-password
# 交互式输入旧密码 + 新密码

# 重置密码（忘记密码时，直接覆盖 config.json）
python main.py --set-password --force
```

### 3.10 安全考虑

| 项目 | 措施 |
|------|------|
| 密码传输 | HTTPS 部署后自动安全；HTTP 阶段明文，但单用户内网可接受 |
| 暴力破解 | 连续 5 次失败 → 锁定 15 分钟（IP 级别，内存计数器） |
| Session 劫持 | HttpOnly cookie + SameSite Lax |
| XSS | 登录页无用户生成内容，天然免疫 |
| CSRF | SameSite Lax + 仅 GET/POST 操作 |
| 密码强度 | 最小 6 字符，建议 8+ 含数字字母 |

## 4. 任务列表

| # | 任务 | 描述 | 文件 |
|---|------|------|------|
| A1 | auth.py 模块 | Session 管理 + bcrypt 验证 + 中间件 + 白名单 | `dev/auth.py` |
| A2 | Auth API | login / logout / status / change-password 4 个端点 | `dev/routes.py` |
| A3 | 中间件注册 | main.py 中注册 AuthMiddleware | `dev/main.py` |
| A4 | 登录页 | login.html + login.css，居中卡片，暗色主题 | `dev/static/login.html` + `css/login.css` |
| A5 | 密码 CLI | `--set-password` 命令行参数 | `dev/main.py` |
| A6 | config 扩展 | config.json 增加 auth 节 | `dev/config.example.json` |
| A7 | 暴力防护 | IP 级别失败计数 + 锁定定时器 | `dev/auth.py` |
| A8 | 前端适配 | 未登录 API 请求时前端展示友好提示（非裸 302） | `dev/static/js/app.js` |

## 5. 不处理项

| 项目 | 理由 |
|------|------|
| 多用户支持 | 单用户方案，不引入用户管理系统 |
| OAuth / SSO | 过度设计 |
| 2FA / MFA | 单用户场景不需要 |
| 数据库存储 | 单用户内存足够 |
| 注册页面 | 单用户，管理员直接设密码 |
| 记住我 | 8 小时 TTL 够长，不需要 |
| 密码找回 | 单用户，忘记密码直接改 config |
| HTTPS | 依赖外部反向代理（nginx），不在 ClawMate 内部处理 |

## 6. 部署影响

- 现有部署**零影响**：未配置 `auth` 节时，AuthMiddleware 不启用（向后兼容）
- 新增依赖：`bcrypt`（Python 标准库兼容，无系统依赖）
- Session 内存占用：单用户 < 1KB
