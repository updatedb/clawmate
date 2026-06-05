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

from fastapi import FastAPI
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
CONFIG_PATH_STR = os.environ.get(CONFIG_PATH_ENV) or str(Path(__file__).parent / "config.json")
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
    version="0.1.0",
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
])
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Import auth middleware - must be after CORS, before static files
from auth import AuthMiddleware  # noqa: E402

# v1.26: AuthMiddleware 内部使用 config.load()，不再需要传入 config dict
app.add_middleware(AuthMiddleware, config=load_cfg())

# import routes AFTER env vars are set (they read env at import time)
from routes import router as clawmate_router  # noqa: E402

app.include_router(clawmate_router)

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
    return {"status": "ok", "service": "clawmate", "version": "0.1.0"}


# ── 启动时同步 cron job(根据 config.json roots 自动生成)───────

import subprocess  # noqa: E402

from cron_manager import add_cron, _get_cron_bin  # noqa: E402


def _sync_cron_jobs():
    """读取 config，创建单一的兜底 cron job。

    v1.26: 使用 config.load() 替代 json.load。
    """
    cfg = load_cfg()

    roots = cfg.roots
    if not roots:
        return

    cron_bin = _get_cron_bin()
    cron_name = "clawmate-fb-fallback"

    # 先删除已存在的 clawmate-fb-fallback（幂等）
    try:
        list_out = subprocess.run(
            [cron_bin, "cron", "list"],
            timeout=10, capture_output=True, text=True,
        ).stdout
        for line in list_out.splitlines():
            if cron_name in line[:28]:
                parts = line.split()
                if parts:
                    subprocess.run(
                        [cron_bin, "cron", "rm", parts[0]],
                        timeout=10, capture_output=True,
                    )
    except Exception:
        pass

    # 读取 cron message 模板
    template_path = Path(__file__).parent / "cron_template.txt"
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()
    except Exception:
        print(f"[clawmate] WARNING: 无法读取 {template_path}，跳过 cron job 同步")
        return

    base_url = "http://localhost:5533"
    all_root_ids = [r.id for r in roots]
    all_roots = ", ".join(all_root_ids)

    # agent_id 用第一个 root 的 agent（cron 扫所有 root）
    primary_agent = roots[0].agent_id

    # 兜底间隔：无 webhook 时 6h，否则 24h
    has_webhook = bool(cfg.openclaw.hook_token)
    interval = "6h" if not has_webhook else cfg.fallback_cron_interval

    message = template.format(base_url=base_url, all_roots=all_roots)
    if add_cron(cron_bin, cron_name, primary_agent, message, every=interval):
        print(f"[clawmate] 兜底 cron job 已创建: {cron_name} (interval={interval}, agent={primary_agent}, roots=[{all_roots}])")
    else:
        print(f"[clawmate] WARNING: 兜底 cron 创建失败 {cron_name}")


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
    t = threading.Thread(target=_sync_cron_jobs, name="cron-sync", daemon=True)
    t.start()

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
