"""
ClawMate Auth — single-user session management + middleware.

Components:
- Session store (in-memory dict, lazy expiry cleanup)
- bcrypt password hashing + verification
- AuthMiddleware (BaseHTTPMiddleware, whitelist-based, session cookie check)
- Brute-force protection (IP-level failure counter, 5 failures → 15-minute lockout)
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import hmac
import json
import logging
import os
import re
import secrets
import socket
import time
from pathlib import Path
from typing import Optional

import bcrypt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from urllib.parse import quote
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse

logger = logging.getLogger("clawmate.auth")

# ── Session store ─────────────────────────────────────────────────────────────
# session_id -> {"user": str, "created_at": float, "last_active": float}
_sessions: dict[str, dict] = {}
_sessions_lock = asyncio.Lock()
_sessions_file = Path(__file__).parent / "sessions.json"
_request_user: contextvars.ContextVar[object | None] = contextvars.ContextVar("clawmate_request_user", default=None)


def current_request_user():
    """Return the authenticated user for the current request, if any."""
    return _request_user.get()


async def websocket_user(websocket):
    """Resolve and validate the session used by a browser WebSocket."""
    if not is_auth_enabled():
        return None
    cookies = getattr(websocket, "cookies", None)
    if cookies is None:
        # Lightweight protocol tests and non-browser callers do not expose
        # ASGI cookie parsing; preserve the legacy unauthenticated test mode.
        return None
    sid = cookies.get("clawmate_session")
    if not sid:
        return False
    session = await get_session(sid)
    if not session or session.get("must_change_password"):
        return False
    try:
        user = get_user_store().get(str(session.get("user_id", "")))
    except RuntimeError:
        return False
    return user or False


def bind_request_user(user):
    """Bind the caller for the current request. Returns a reset handle.

    Callers that bind mid-request (a share token authorizes its recipient, who
    holds no session) must pair this with release_request_user in a finally, the
    same way the middleware does, so one request's principal cannot outlive it.
    """
    return _request_user.set(user)


def release_request_user(handle) -> None:
    """Undo bind_request_user."""
    _request_user.reset(handle)


@contextlib.contextmanager
def request_user_scope(user):
    """Bind `user` as the caller for the duration of the block.

    Background work loses the request context: a plain threading.Thread does not
    inherit the ContextVar, so current_request_user() reads None there and every
    root-aware helper fails closed. Wrap such work in this scope -- with
    local_admin_principal() it says the *server* is the caller.
    """
    handle = bind_request_user(user)
    try:
        yield user
    finally:
        release_request_user(handle)


def _load_sessions() -> None:
    """Load sessions from JSON file on startup. Silently ignore missing/corrupt files."""
    global _sessions
    try:
        if _sessions_file.exists():
            with open(_sessions_file, "r", encoding="utf-8") as f:
                _sessions = json.load(f)
        else:
            _sessions = {}
    except Exception as e:
        print(f"[auth] Warning: failed to load sessions from {_sessions_file}: {e}")
        _sessions = {}


def _save_sessions() -> None:
    """Write current _sessions dict to JSON file. Failures are non-fatal."""
    try:
        with open(_sessions_file, "w", encoding="utf-8") as f:
            json.dump(_sessions, f)
    except Exception as e:
        print(f"[auth] Warning: failed to save sessions to {_sessions_file}: {e}")


# Load persisted sessions on module import
_load_sessions()

# ── Brute-force protection ────────────────────────────────────────────────────
# ip -> {"failures": int, "locked_until": float}
_ip_failures: dict[str, dict] = {}  # key: f"{username}:{client_ip}"
_MAX_FAILURES = 5
_LOCKOUT_SECONDS = 15 * 60  # 15 minutes


def _generate_session_id() -> str:
    return secrets.token_urlsafe(32)


def _session_cleanup() -> None:
    """Remove expired sessions (call lazily on login/logout/status)."""
    now = time.time()
    to_delete = [sid for sid, s in _sessions.items() if now - s["last_active"] > s.get("ttl", 28800)]
    for sid in to_delete:
        _sessions.pop(sid, None)


# Startup cleanup: remove expired sessions from persisted store
_session_cleanup()


# ── Password hashing ──────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── Session management ────────────────────────────────────────────────────────
async def create_session(username: str, ttl_seconds: int = 28800, *, user_id: str = "",
                         is_admin: bool = False, must_change_password: bool = False) -> tuple[str, dict]:
    """Create a new session, return (session_id, session_data)."""
    sid = _generate_session_id()
    now = time.time()
    data = {"user": username, "user_id": user_id, "is_admin": is_admin,
            "must_change_password": must_change_password, "created_at": now,
            "last_active": now, "ttl": ttl_seconds}
    async with _sessions_lock:
        _sessions[sid] = data
    _save_sessions()
    return sid, data


async def clear_must_change_password(sid: str) -> None:
    async with _sessions_lock:
        if sid in _sessions:
            _sessions[sid]["must_change_password"] = False
    _save_sessions()


async def get_session(sid: str) -> Optional[dict]:
    """Return session data if valid and not expired."""
    async with _sessions_lock:
        s = _sessions.get(sid)
        if not s:
            return None
        if time.time() - s["last_active"] > s.get("ttl", 28800):
            _sessions.pop(sid, None)
            return None
        s["last_active"] = time.time()
        return s


async def delete_session(sid: str) -> None:
    async with _sessions_lock:
        _sessions.pop(sid, None)
    _save_sessions()


def get_session_from_cookie(request: Request) -> Optional[str]:
    return request.cookies.get("clawmate_session")


def get_client_ip(request: Request) -> str:
    """Resolve the caller IP.

    ``x-forwarded-for`` is honored ONLY when the immediate peer is itself a
    trusted local host, because the header is otherwise fully attacker
    controlled and would let any remote client claim to be loopback and inherit
    the local-client trust bypass.

    The LAST hop is used rather than the first: the common nginx directive
    ``$proxy_add_x_forwarded_for`` preserves whatever the client sent at the
    front and appends the address the proxy actually observed at the end, so
    the first element is the spoofable one. When a proxy replaces the header
    instead, there is a single element and first equals last.
    """
    peer = request.client.host if request.client else "unknown"
    if _is_local_client(peer):
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return peer


# ── IP-level brute-force guard ───────────────────────────────────────────────
def _failure_key(username: str, client_ip: str) -> str:
    """Composite key for brute-force tracking: username@IP."""
    return f"{username}:{client_ip}"


def check_ip_lockout(username: str, client_ip: str) -> tuple[bool, int]:
    """
    Returns (locked, seconds_remaining).
    Performs lazy cleanup of old entries.
    """
    now = time.time()
    entry = _ip_failures.get(_failure_key(username, client_ip))
    if not entry:
        return False, 0
    locked_until = entry.get("locked_until", 0)
    if now < locked_until:
        return True, int(locked_until - now)
    # expired lockout
    _ip_failures.pop(_failure_key(username, client_ip), None)
    return False, 0


def record_failure(username: str, client_ip: str) -> tuple[bool, int]:
    """Record a failed attempt for username@IP. Returns (is_now_locked, seconds_remaining)."""
    now = time.time()
    key = _failure_key(username, client_ip)
    entry = _ip_failures.setdefault(key, {"failures": 0, "locked_until": 0})
    entry["failures"] = entry.get("failures", 0) + 1
    if entry["failures"] >= _MAX_FAILURES:
        entry["locked_until"] = now + _LOCKOUT_SECONDS
        return True, _LOCKOUT_SECONDS
    return False, 0


def clear_failures(username: str, client_ip: str) -> None:
    _ip_failures.pop(_failure_key(username, client_ip), None)


# ── Auth config helpers ──────────────────────────────────────────────────────
def load_auth_config(config: dict | None = None) -> dict:
    """Return auth config dict from config.load(), with safe defaults.

    v1.26: 从 config.load() 读取，不再依赖传入的 dict。
    保留 config 参数供向后兼容。
    """
    from config import load as _cfg
    return _cfg().auth.__dict__ if _cfg().auth else {}


def is_auth_enabled(config: dict | None = None) -> bool:
    """Return True only when auth section exists with a non-empty password_hash."""
    from config import load as _cfg
    c = _cfg()
    return bool(c.system_root_dir or (c.auth and c.auth.password_hash.strip()))


def config_path() -> Path:
    """Single source of truth for the active config file."""
    from config import _CONFIG_PATH  # noqa: PLC0415
    return Path(_CONFIG_PATH) if _CONFIG_PATH else Path(os.environ.get("CLAWMATE_CONFIG", "config.json"))


def get_user_store():
    """Return the private account store for the configured system root."""
    from config import load as _cfg
    from user_store import UserStore
    cfg = _cfg()
    if not cfg.system_root_dir:
        raise RuntimeError("system_root_dir is not configured")
    return UserStore(config_path().parent / "users.json", cfg.system_root_dir)


def get_root_registry():
    """Return the root registry for the configured system root."""
    from config import load as _cfg
    from root_registry import RootRegistry
    cfg = _cfg()
    if not cfg.system_root_dir:
        raise RuntimeError("system_root_dir is not configured")
    return RootRegistry(config_path().parent / "roots.json", cfg.system_root_dir)


def local_admin_principal():
    from root_auth import LocalAdmin
    return LocalAdmin()


def get_session_ttl(config: dict | None = None) -> int:
    from config import load as _cfg
    return _cfg().auth.session_ttl_minutes * 60


# ── Middleware ────────────────────────────────────────────────────────────────
# Whitelist: paths that do NOT require authentication
_WHITELIST = frozenset([
    "/",
    "/api/health",
    "/login",
    "/api/clawmate/auth/login",
    "/api/clawmate/auth/logout",
    "/api/clawmate/auth/status",
    "/api/clawmate/auth/change-password",
    # ONLYOFFICE: the Document Server fetches the document and posts the save
    # callback server-to-server, so those two carry no session cookie. They are
    # authenticated by the HS256 token in the request, which already names the
    # file. The rest of the prefix (/config, /script-url) is called by the app
    # page and stays a session route -- /config takes root and path as plain
    # query params, so exempting it would hand out an anonymous file reader.
    "/api/clawmate/onlyoffice/file",
    "/api/clawmate/onlyoffice/callback",
    "/clawmate/login.html",
    "/clawmate/share-view.html",
    "/clawmate/manifest.json",
    "/clawmate/sw.js",
    "/clawmate/api/health",
])

# Prefix-based whitelist (order matters — checked after exact match)
# NOTE: /api/clawmate/feedback/ 不再白名单免登录，改用内部 token 或 localhost 鉴权。
_WHITELIST_PREFIXES = (
    "/clawmate/static/",
    "/clawmate/css/",
    "/clawmate/vendor/",
    "/clawmate/asset/",
    "/clawmate/m/",
    "/clawmate/js/",
)

# Share *recipient* endpoints, addressed by token. The recipient holds no
# account -- the token in the path is the whole capability -- so these must stay
# anonymous. They are matched by pattern rather than by the `/api/clawmate/share/`
# prefix because the owner endpoints under that same prefix (/create, /active,
# /expire) mint and lapse links: whitelisting the prefix left them anonymous AND,
# since every share handler resolves paths through safe_path() -> get_roots(),
# which fails closed without a resolved caller, answered 403 to everyone --
# breaking sharing for owners and recipients alike. Anonymous callers could also
# read the whole shared-file inventory (/active) and expire anyone's link.
_SHARE_RECIPIENT = re.compile(
    r"^/api/clawmate/share/[A-Za-z0-9_-]+/(?:data|raw|asset|feedback|feedback/delete)$")

# Paths that are always allowed regardless of auth config.
#
# The read-serving routes (preview/download/raw) used to be listed here. They
# cannot be: the exemption returns from the middleware *before* the session is
# resolved, and every one of them resolves the caller's roots through
# resolve_root() -> get_roots(), which fails closed for an unresolved caller.
# The result was a 403 for every user on every one of them -- thumbnails and
# previews included -- while the non-exempt `list` route kept working. They are
# ordinary session-cookie routes now: a same-origin <img> sends the cookie, and
# the loopback localhost bypass below still covers a local operator.
_ALWAYS_ALLOWED = frozenset([
    "/",
    "/api/health",
    "/api/clawmate/agent/terminal",
    "/clawmate/share-view.html",
])


def _is_whitelisted(path: str) -> bool:
    # Exact match
    if path in _WHITELIST:
        return True
    # Strip trailing slash and re-check
    if path.endswith("/"):
        stripped = path.rstrip("/")
        if stripped in _WHITELIST:
            return True
    # Share recipients are authorized by their token, never by a session.
    if _SHARE_RECIPIENT.match(path):
        return True
    # Prefix match
    for prefix in _WHITELIST_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def _is_local_client(client_ip: str) -> bool:
    """判断请求来源是否为本地客户端（auth bypass）。

    硬编码的 localhost IP 始终有效，此外还会检查 auth.local_hosts 配置的
    主机名/IP。主机名会通过 DNS 解析后比较 IP 地址。
    """
    if client_ip in ("127.0.0.1", "::1", "localhost"):
        return True
    from config import load as _cfg
    local_hosts = _cfg().auth.local_hosts
    for host in local_hosts:
        if client_ip == host:
            return True
        try:
            resolved = socket.gethostbyname(host)
            if client_ip == resolved:
                return True
        except socket.gaierror:
            pass
    return False


class AuthMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware that:
    1. Skips entirely when auth is not configured (backward compatible)
    2. Allows whitelisted paths without auth
    3. Checks session cookie on all other paths
    4. Redirects to /login on missing/invalid session
    5. Serves 401 JSON for API routes on auth failure
    """

    def __init__(self, app, config: dict):
        super().__init__(app)
        self._config = config

    async def dispatch(self, request: Request, call_next):
        # Skip if auth not configured
        if not is_auth_enabled(self._config):
            return await call_next(request)

        path = request.url.path

        # Always-allowed paths (health, root)
        if path in _ALWAYS_ALLOWED:
            return await call_next(request)

        # Whitelist check
        if _is_whitelisted(path):
            return await call_next(request)

        # Localhost bypass: 服务器本机进程访问不需要登录
        # request.client.host 在直接连接时有效，代理场景走 x-forwarded-for
        # 同时支持 auth.local_hosts 配置的 LAN 主机名/IP
        # Trusted local clients get an explicit principal so downstream root
        # authorization resolves registered roots instead of seeing no user.
        client_host = self._get_client_ip(request)  # already normalizes to IP
        if _is_local_client(client_host):
            principal = local_admin_principal()
            request.state.session = {"user": principal.username, "is_admin": True,
                                     "must_change_password": False, "user_id": ""}
            request.state.user = principal
            token = _request_user.set(principal)
            try:
                return await call_next(request)
            finally:
                _request_user.reset(token)

        # A locally spawned executor calls review/result over loopback and
        # bypasses auth above. A non-loopback fallback is allowed only with
        # the existing internal capability token.
        if (path.startswith("/api/clawmate/feedback/")
                or path.startswith("/api/clawmate/task/")
                or path == "/api/clawmate/review/result"):
            if verify_internal_token(request):
                # Same treatment as the loopback bypass above: the token
                # authenticates the executor, so give it the server principal.
                # Without one these routes resolved no root at all and answered
                # 403 to a caller the token had already authorized.
                principal = local_admin_principal()
                request.state.session = {"user": principal.username, "is_admin": True,
                                         "must_change_password": False, "user_id": ""}
                request.state.user = principal
                token = _request_user.set(principal)
                try:
                    return await call_next(request)
                finally:
                    _request_user.reset(token)

        # IP lockout check — pre-auth stage, username not yet known
        client_ip = self._get_client_ip(request)
        locked, remaining = check_ip_lockout("?", client_ip)
        if locked:
            if self._is_api_route(path):
                return JSONResponse(
                    {"error": "too_many_requests", "detail": f"登录失败次数过多，请 {remaining} 秒后重试"},
                    status_code=429,
                )
            return PlainTextResponse(
                f"登录失败次数过多，请在 {remaining} 秒后重试。",
                status_code=429,
            )

        # Session check
        sid = get_session_from_cookie(request)
        if not sid:
            if path == "/api/clawmate/review/result":
                task_id = "unknown"
                try:
                    body = await request.json()
                    if isinstance(body, dict) and isinstance(body.get("task_id"), str):
                        task_id = body["task_id"].strip() or "unknown"
                except Exception:
                    pass
                logger.warning("[review.result] status=401 task_id=%s source=non_loopback reason=authentication_required", task_id)
            return self._auth_failure_redirect(request, "请先登录")

        session = await get_session(sid)
        if not session:
            return self._auth_failure_redirect(request, "会话已过期，请重新登录")

        if (session.get("must_change_password") and path.startswith("/api/") and path not in {
            "/api/clawmate/auth/me", "/api/clawmate/auth/change-password", "/api/clawmate/auth/logout",
        }):
            return JSONResponse({"error": "password_change_required", "detail": "请先修改初始密码"}, status_code=403)

        # Attach session user to request state. A session whose account has
        # gone away must not continue as an anonymous user: that was the path
        # that previously reached the legacy-roots fallback.
        request.state.session = session
        try:
            user = get_user_store().get(str(session.get("user_id", "")))
        except (RuntimeError, ValueError):
            user = None
        if user is None:
            self._clear_session_cookie(request)
            return self._auth_failure_redirect(request, "账号不存在或已停用，请重新登录")
        request.state.user = user
        token = _request_user.set(user)
        try:
            return await call_next(request)
        finally:
            _request_user.reset(token)

    def _get_client_ip(self, request: Request) -> str:
        # Rely on the shared module helper for reverse-proxy aware resolution.
        return get_client_ip(request)

    def _is_api_route(self, path: str) -> bool:
        return path.startswith("/api/")

    def _clear_session_cookie(self, request: Request) -> None:
        request.state.clear_session_cookie = True

    def _auth_failure_redirect(self, request: Request, message: str) -> PlainTextResponse | RedirectResponse:
        if self._is_api_route(request.url.path):
            response: PlainTextResponse | RedirectResponse = JSONResponse(
                {"error": "unauthorized", "detail": message}, status_code=401)
        else:
            # Build full path with query string so login can redirect back to the original URL
            full_path = request.url.path
            if request.url.query:
                full_path += "?" + request.url.query
            redirect_to = f"/clawmate/login.html?redirect={quote(full_path, safe='')}"
            response = RedirectResponse(url=redirect_to, status_code=302)
        if getattr(request.state, "clear_session_cookie", False):
            response.delete_cookie("clawmate_session")
        return response


# ── Internal API token（供 OpenClaw agent 回调 /feedback 接口）────────────

def verify_internal_token(request: Request) -> bool:
    """验证内部 API token（X-Internal-Token header 或 Authorization Bearer）。

    用于 feedback API 等需要免 session 但非公开的接口。
    token 值来自 config.json → openclaw.hook_token。
    """
    from config import load as _cfg
    expected = _cfg().openclaw.hook_token
    if not expected:
        return False  # 未配置则拒绝
    # 支持两种格式: X-Internal-Token: <token> 或 Authorization: Bearer <token>
    internal = request.headers.get("X-Internal-Token", "")
    if internal and hmac.compare_digest(internal, expected):
        return True
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        bearer = auth_header[7:]
        if hmac.compare_digest(bearer, expected):
            return True
    return False
