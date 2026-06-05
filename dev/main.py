"""
ClawMate v0.1 — Standalone ClawMate service.
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

# ── config resolution ──────────────────────────────────────────────
CONFIG_PATH = Path(
    os.environ.get(CONFIG_PATH_ENV) or (Path(__file__).parent / "config.json")
)
STATIC_DIR = Path(__file__).parent / "static"

try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    print(f"[clawmate] WARNING: config.json not found or invalid at {CONFIG_PATH}, using defaults", file=sys.stderr)
    config = {
        "roots": [
            {
                "id": "media",
                "label": "媒体",
                "dir": str((Path.home() / ".openclaw" / "media").resolve()),
            }
        ],
        "defaultRootId": "media",
    }

# env overrides (highest priority)
_onlyoffice_cfg = config.get("onlyoffice", {}) or {}
ONLYOFFICE_API_JS_URL = os.environ.get(
    ONLYOFFICE_URL_ENV,
    _onlyoffice_cfg.get("api_js_url"),
)
ONLYOFFICE_JWT_SECRET = os.environ.get(
    ONLYOFFICE_JWT_SECRET_ENV,
    _onlyoffice_cfg.get("jwt_secret", ""),
)
PUBLIC_BASE_URL = os.environ.get(
    PUBLIC_BASE_URL_ENV,
    config.get("public_base_url", ""),
)

# v1.12 C2: 启动前快照 env var 是否被显式设置（setdefault 之后无法分辨）
# 部署者如果忘了在 systemd/环境里设 CLAWMATE_PUBLIC_BASE_URL，
# 仅靠 config.json 兜底会让下面的 setdefault 把 env 填上，导致检查失效。
_CLAWMATE_PUBLIC_BASE_URL_ENV_SET = PUBLIC_BASE_URL_ENV in os.environ

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

    # Load current config
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
        print("请输入当前密码（输入后按回车）:")
        old = getpass.getpass("当前密码: ")
        if not verify_password(old, current_hash):
            print("原密码错误，操作取消。")
            sys.exit(1)
        print("原密码验证成功。")
    elif current_hash:
        print("(force 模式，跳过原密码验证)")

    while True:
        p1 = getpass.getpass("新密码（至少4字符）: ")
        if len(p1) < 4:
            print("新密码太短，至少需要4个字符。")
            continue
        p2 = getpass.getpass("确认新密码: ")
        if p1 != p2:
            print("两次输入的密码不一致，请重试。")
            continue
        break

    new_hash = hash_password(p1)
    if "auth" not in cfg:
        cfg["auth"] = {}
    cfg["auth"]["username"] = current_user
    cfg["auth"]["password_hash"] = new_hash
    cfg["auth"]["session_ttl_minutes"] = ac.get("session_ttl_minutes", 480)

    # Preserve onlyoffice section exactly as-is
    onlyoffice = cfg.get("onlyoffice") or {}
    cfg["onlyoffice"] = onlyoffice

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    print(f"密码已更新（用户: {current_user}）。")
    print("重启 ClawMate 服务使新密码生效。")


# ── FastAPI app ────────────────────────────────────────────────────
app = FastAPI(
    title="ClawMate",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
)


# CORS 白名单：从 public_base_url 动态计算，保留本机调试
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
    # CORS 白名单已在上方构建
    allow_origins=_cors_allowed,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Import auth middleware — must be after CORS, before static files
from auth import AuthMiddleware  # noqa: E402

app.add_middleware(AuthMiddleware, config=config)

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


# ── 启动时同步 cron job（根据 config.json roots 自动生成）───────

from cron_manager import add_cron, remove_all, _get_cron_bin  # noqa: E402


def _sync_cron_jobs():
    """读取 config.json，为每个 unique agent_id 创建/更新 cron job"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        print("[clawmate] WARNING: 无法加载 config.json，跳过 cron job 同步")
        return

    roots = cfg.get("roots", [])
    if not roots:
        return

    cron_bin = _get_cron_bin()

    # 按 agent_id 分组
    agent_roots_map = {}
    for r in roots:
        aid = r.get("agent_id", "default")
        agent_roots_map.setdefault(aid, []).append(r["id"])

    # 删除旧的泛用 cron job（历史遗留命名）
    for old_name in ("clawmate-feedback-inbox-check", "clawmate-feedback-inbox"):
        remove_all(cron_bin, old_name)

    # 读取 cron message 模板
    template_path = Path(__file__).parent / "cron_template.txt"
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()
    except Exception:
        print(f"[clawmate] WARNING: 无法读取 {template_path}，跳过 cron job 同步")
        return

    # v1.7: 从 config.json 读取 feedback.tags，生成动作列表 (注入到 {feedback_action_list} 占位符)
    # 如果没有 tags，降级为默认动作列表以保持现有 cron 任务不中断
    DEFAULT_ACTION_LIST = (
        "   - **删除**：移除 item.content 指向的段落/代码/章节\n"
        "   - **修改**：用 item.note 的要求改写对应内容\n"
        "   - **扩展**：基于 item.content 扩写，如增加章节、补充细节\n"
        "   - **简化**：精简或重构对应内容\n"
        "   - **审批**: 文档通过人工审核\n"
        "   - **执行**：如果 item.note 指向 research/*.md 中的方案文档，将该方案作为工作实施的内容，完成方案计划。"
    )
    feedback_cfg = cfg.get("feedback") or {}
    tags = feedback_cfg.get("tags") if isinstance(feedback_cfg, dict) else None
    if isinstance(tags, list) and len(tags) > 0:
        action_lines = []
        for t in tags:
            if not isinstance(t, dict):
                continue
            label = (t.get("label") or "").strip()
            prompt = (t.get("prompt") or "").strip()
            if not label and not prompt:
                continue
            if not prompt:
                # label-only entry
                action_lines.append(f"   - **{label}**")
            else:
                action_lines.append(f"   - **{label}**：{prompt}" if label else f"   - {prompt}")
        action_list_text = "\n".join(action_lines) if action_lines else DEFAULT_ACTION_LIST
    else:
        # No tags configured → fallback to default action list (backward compat)
        action_list_text = DEFAULT_ACTION_LIST

    base_url = "http://localhost:5533"

    for agent_id, root_ids in agent_roots_map.items():
        cron_name = f"clawmate-fb-{agent_id}"
        roots_str = ",".join(root_ids)
        agent_roots = ", ".join(root_ids)
        message = template.format(
            base_url=base_url,
            roots_str=roots_str,
            agent_roots=agent_roots,
            feedback_action_list=action_list_text,
        )
        if add_cron(cron_bin, cron_name, agent_id, message):
            print(f"[clawmate] cron job 已创建: {cron_name} (agent={agent_id}, roots={root_ids})")
        else:
            print(f"[clawmate] WARNING: 创建失败 {cron_name}")


# ── entrypoint ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    do_set_password, force_password = _cli_set_password()
    if do_set_password:
        _run_set_password(force=force_password)
        sys.exit(0)

    port = int(os.environ.get("CLAWMATE_PORT", config.get("port", 5533)))
    max_upload = int(os.environ.get("CLAWMATE_MAX_UPLOAD_MB", config.get("max_upload_mb", 100)))
    print(f"[clawmate] Starting on http://0.0.0.0:{port}")
    print(f"[clawmate] Web UI at /clawmate/")
    print(f"[clawmate] Config: {CONFIG_PATH}")
    print(f"[clawmate] ONLYOFFICE API JS: {ONLYOFFICE_API_JS_URL}")
    print(f"[clawmate] Max upload: {max_upload}MB")

    # Increase multipart upload size limit (default 1MB)
    from starlette.formparsers import MultiPartParser
    MultiPartParser.spool_max_size = max_upload * 1024 * 1024

    # 启动时同步 cron job（后台运行，不阻塞服务器）
    import threading
    t = threading.Thread(target=_sync_cron_jobs, name="cron-sync", daemon=True)
    t.start()

    # v1.8 B5: 启动时执行一次 feedback 归档/清理 (后台线程, 不阻塞 server)
    # - 默认保留 90 天, 归档到 feedback.archive.json
    # - try/except 包裹, 失败不报错不阻塞 (清理失败不影响主流程)
    def _startup_cleanup():
        try:
            from feedback_api import cleanup_old_feedback
            stats = cleanup_old_feedback(days=90, archive=True)
            print(f"[clawmate] startup cleanup: scanned={stats['scanned_files']} "
                  f"archived={stats['archived_count']} removed={stats['removed_count']} "
                  f"errors={len(stats['errors'])}")
        except Exception as e:
            print(f"[clawmate] WARNING: startup cleanup failed: {e}", file=sys.stderr)

    t2 = threading.Thread(target=_startup_cleanup, name="feedback-cleanup", daemon=True)
    t2.start()

    # v1.12 C2: 启动时检查 CLAWMATE_PUBLIC_BASE_URL 是否被显式设置
    # 未设置时打印 WARNING（不阻塞启动）— 强哥部署时如果忘了设 env var，
    # 反向代理后 preview URL 可能用错 scheme (http vs https)
    if not _CLAWMATE_PUBLIC_BASE_URL_ENV_SET:
        print(
            f"[clawmate] WARNING: {PUBLIC_BASE_URL_ENV} not set; "
            "preview URLs may use wrong scheme (http vs https) when behind "
            "reverse proxy without X-Forwarded-* headers. "
            "Fix: export CLAWMATE_PUBLIC_BASE_URL=https://note.updatedb.online:18443"
        )

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
