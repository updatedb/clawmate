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
import hmac
import json
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

# ── Config keys (read from shared config dict injected by main.py) ────────────
AUTH_CONFIG_KEY = "auth"

# ── Session store ─────────────────────────────────────────────────────────────
# session_id -> {"user": str, "created_at": float, "last_active": float}
_sessions: dict[str, dict] = {}
_sessions_lock = asyncio.Lock()
_sessions_file = Path(__file__).parent / "sessions.json"


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
async def create_session(username: str, ttl_seconds: int = 28800) -> tuple[str, dict]:
    """Create a new session, return (session_id, session_data)."""
    sid = _generate_session_id()
    now = time.time()
    data = {"user": username, "created_at": now, "last_active": now, "ttl": ttl_seconds}
    async with _sessions_lock:
        _sessions[sid] = data
    _save_sessions()
    return sid, data


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
    return bool(c.auth and c.auth.password_hash.strip())


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
    "/api/clawmate/onlyoffice/",
    "/clawmate/login.html",
    "/clawmate/share-view.html",
    "/clawmate/api/health",
])

# Prefix-based whitelist (order matters — checked after exact match)
# NOTE: /api/clawmate/feedback/ 不再白名单免登录，改用内部 token 或 localhost 鉴权。
_WHITELIST_PREFIXES = (
    "/api/clawmate/onlyoffice/",
    "/clawmate/static/",
    "/clawmate/css/",
    "/clawmate/vendor/",
    "/clawmate/asset/",
    "/clawmate/m/",
    "/api/clawmate/share/",
)

# Paths that are always allowed regardless of auth config
_ALWAYS_ALLOWED = frozenset([
    "/",
    "/api/health",
    "/api/clawmate/preview",
    "/api/clawmate/download",
    "/api/clawmate/raw",
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
        client_host = self._get_client_ip(request)  # already normalizes to IP
        if _is_local_client(client_host):
            return await call_next(request)

        # Internal token check for feedback/shared API routes (used by OpenClaw agent callbacks)
        if path.startswith("/api/clawmate/feedback/") or path.startswith("/api/clawmate/task/"):
            if verify_internal_token(request):
                return await call_next(request)

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
            return self._auth_failure_redirect(request, "请先登录")

        session = await get_session(sid)
        if not session:
            return self._auth_failure_redirect(request, "会话已过期，请重新登录")

        # Attach session user to request state
        request.state.session = session
        return await call_next(request)

    def _get_client_ip(self, request: Request) -> str:
        # Support reverse proxy headers
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _is_api_route(self, path: str) -> bool:
        return path.startswith("/api/")

    def _auth_failure_redirect(self, request: Request, message: str) -> PlainTextResponse | RedirectResponse:
        if self._is_api_route(request.url.path):
            return JSONResponse({"error": "unauthorized", "detail": message}, status_code=401)
        # Build full path with query string so login can redirect back to the original URL
        full_path = request.url.path
        if request.url.query:
            full_path += "?" + request.url.query
        redirect_to = f"/clawmate/login.html?redirect={quote(full_path, safe='')}"
        return RedirectResponse(url=redirect_to, status_code=302)


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
