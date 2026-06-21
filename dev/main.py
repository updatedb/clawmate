"""
ClawMate v0.1 - Standalone ClawMate service.
Independent FastAPI server, Docker-deployable.

Usage:
    python main.py                          # uses defaults from config.json
    CLAWMATE_PORT=8080 python main.py       # override port
    CLAWMATE_CONFIG=/path/to/config.json python main.py
    python main.py --set-password           # set/change password interactively
    python main.py --set-password --force   # skip old-password verification
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from constants import (
    CONFIG_PATH_ENV,
    PUBLIC_BASE_URL_ENV,
    ONLYOFFICE_JWT_SECRET_ENV,
    ONLYOFFICE_URL_ENV,
)

from config import set_config_path, load as load_cfg

# ── config resolution ──────────────────────────────────────────────
CONFIG_PATH_STR = os.environ.get(CONFIG_PATH_ENV) or str(Path(__file__).resolve().parent.parent / "config.json")
CONFIG_PATH = Path(CONFIG_PATH_STR)
set_config_path(CONFIG_PATH_STR)
STATIC_DIR = Path(__file__).parent / "static"

# Load config via config.py
cfg = load_cfg()

# env overrides (highest priority)
ONLYOFFICE_API_JS_URL = os.environ.get(
    ONLYOFFICE_URL_ENV,
    cfg.onlyoffice.api_js_url,
)
ONLYOFFICE_JWT_SECRET = os.environ.get(
    ONLYOFFICE_JWT_SECRET_ENV,
    cfg.onlyoffice.jwt_secret,
)
PUBLIC_BASE_URL = os.environ.get(
    PUBLIC_BASE_URL_ENV,
    cfg.public_base_url,
)

# inject env vars for routes.py / service.py
os.environ.setdefault("CLAWMATE_ONLYOFFICE_JWT_SECRET", ONLYOFFICE_JWT_SECRET)
os.environ.setdefault("CLAWMATE_PUBLIC_BASE_URL", PUBLIC_BASE_URL)
os.environ.setdefault("CLAWMATE_CONFIG", str(CONFIG_PATH))


# ── CLI: --set-password ─────────────────────────────────────────────
def _cli_set_password():
    import argparse
    parser = argparse.ArgumentParser(description="ClawMate password management")
    parser.add_argument("--set-password", action="store_true", help="Set or update the admin password")
    parser.add_argument("--force", action="store_true", help="Skip old-password verification (first-time setup)")
    args, _ = parser.parse_known_args()
    return args.set_password, args.force


def _run_set_password(force: bool = False):
    """Interactively set the admin password."""
    import getpass
    from auth import hash_password, verify_password

    # Load current config (direct file read for write operations)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cfg = {}

    ac = cfg.get("auth") or {}
    current_hash = ac.get("password_hash", "")
    current_user = ac.get("username", "admin")

    print("=== ClawMate 密码设置 ===")
    print(f"当前用户名: {current_user}")

    if current_hash and not force:
        print("请输入当前密码(输入后按回车):")
        old = getpass.getpass("当前密码: ")
        if not verify_password(old, current_hash):
            print("原密码错误,操作取消。")
            sys.exit(1)
        print("原密码验证成功。")
    elif current_hash:
        print("(force 模式,跳过原密码验证)")

    while True:
        p1 = getpass.getpass("新密码(至少4字符): ")
        if len(p1) < 4:
            print("新密码太短,至少需要4个字符。")
            continue
        p2 = getpass.getpass("确认新密码: ")
        if p1 != p2:
            print("两次输入的密码不一致,请重试。")
            continue
        break

    new_hash = hash_password(p1)
    if "auth" not in cfg:
        cfg["auth"] = {}
    cfg["auth"]["username"] = current_user
    cfg["auth"]["password_hash"] = new_hash
    cfg["auth"]["session_ttl_minutes"] = ac.get("session_ttl_minutes", 480)

    onlyoffice = cfg.get("onlyoffice") or {}
    cfg["onlyoffice"] = onlyoffice

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    print(f"密码已更新(用户: {current_user})。")
    print("重启 ClawMate 服务使新密码生效。")


# ── FastAPI app ────────────────────────────────────────────────────
app = FastAPI(
    title="ClawMate",
    docs_url=None,
    redoc_url=None,
)


# CORS 白名单:从 public_base_url 动态计算,保留本机调试
_cors_allowed = []
if PUBLIC_BASE_URL:
    _cors_allowed.append(PUBLIC_BASE_URL.rstrip("/"))
_cors_allowed.extend([
    "http://localhost",
    "http://localhost:5533",
    "http://127.0.0.1",
    "http://127.0.0.1:5533",
    "https://cdnjs.cloudflare.com",
])
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Request logging middleware — before auth, to log all requests
from logging_middleware import RequestLoggingMiddleware  # noqa: E402
app.add_middleware(RequestLoggingMiddleware)

# Import auth middleware - must be after CORS, before static files
from auth import AuthMiddleware, is_auth_enabled  # noqa: E402

# v1.26: AuthMiddleware 内部使用 config.load()，不再需要传入 config dict
app.add_middleware(AuthMiddleware, config=load_cfg())

# import routes AFTER env vars are set (they read env at import time)
from routes import router as clawmate_router  # noqa: E402
from task_runner import router as task_router  # noqa: E402
from subtitle_routes import router as subtitle_router  # noqa: E402
from share_routes import router as share_router  # noqa: E402

app.include_router(clawmate_router)
app.include_router(task_router)
app.include_router(subtitle_router)
app.include_router(share_router)

# mount static files under /clawmate/
if STATIC_DIR.exists() and STATIC_DIR.is_dir():
    app.mount("/clawmate", StaticFiles(directory=str(STATIC_DIR), html=True), name="clawmate_static")


# redirect root to /clawmate/
@app.get("/")
async def root_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/clawmate/")


# ── health check ───────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "clawmate"}


# ── 兜底定时扫描（替代 openclaw CLI cron 管理）────────────

import httpx  # noqa: E402


def _start_periodic_cron_tick():
    """容器内定时调用 cron-tick，替代 openclaw CLI 的兜底 cron job。

    即时唤醒已有 webhook (POST /hooks/agent) 负责，
    此函数仅为网络波动等场景提供兜底扫描。
    """
    import time

    interval_hours = 6
    if load_cfg().openclaw.hook_token:
        interval_hours = 24  # 有 webhook 时减少兜底频率

    url = "http://localhost:5533/api/clawmate/feedback/cron-tick"
    print(f"[clawmate] 兜底定时器已启动: 每{interval_hours}h 扫描一次")

    while True:
        time.sleep(interval_hours * 3600)
        try:
            resp = httpx.post(url, timeout=10)
            if resp.status_code == 200:
                rj = resp.json()
                print(f"[cron-tick] periodic check: checked={rj.get('checked',0)} pending={rj.get('pending',0)}")
        except Exception:
            pass  # 下次重试


# ── entrypoint ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    do_set_password, force_password = _cli_set_password()
    if do_set_password:
        _run_set_password(force=force_password)
        sys.exit(0)

    port = int(os.environ.get("CLAWMATE_PORT", cfg.port))
    max_upload = int(os.environ.get("CLAWMATE_MAX_UPLOAD_MB", cfg.max_upload_mb))
    print(f"[clawmate] Starting on http://0.0.0.0:{port}")
    print(f"[clawmate] Web UI at /clawmate/")
    print(f"[clawmate] Config: {CONFIG_PATH}")
    print(f"[clawmate] ONLYOFFICE API JS: {ONLYOFFICE_API_JS_URL}")
    print(f"[clawmate] Max upload: {max_upload}MB")

    # 认证状态
    _auth_enabled = is_auth_enabled(load_cfg())
    if not _auth_enabled:
        print(f"[clawmate] ⚠️  认证未配置（auth.password_hash 为空），任何人都可访问")
        print(f"[clawmate] ⚠️  请运行: python3 main.py --set-password")
    else:
        print(f"[clawmate] Auth: ENABLED")

    # webhook wake 状态
    if cfg.openclaw.hook_token:
        print(f"[clawmate] Webhook wake: ENABLED  (wake -> {cfg.openclaw.gateway_url}/hooks/agent)")
        print(f"[clawmate]   config source: config.json -> openclaw.hook_token")
    else:
        print(f"[clawmate] Webhook wake: DISABLED  (openclaw.hook_token empty, fallback to cron only)", file=sys.stderr)

    # Increase multipart upload size limit (default 1MB)
    from starlette.formparsers import MultiPartParser
    MultiPartParser.spool_max_size = max_upload * 1024 * 1024

    # 启动时同步 cron job（后台运行，不阻塞服务器）
    import threading
    t = threading.Thread(target=_start_periodic_cron_tick, name="cron-tick", daemon=True)
    t.start()

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
