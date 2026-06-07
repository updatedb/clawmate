"""
ConfigLoader — 类型化 data class + 模块级单例。

Usage:
    from dev.config import set_config_path, load as config

    config.roots                     # list[RootEntry]
    config.root_agent("writer")      # → "writer"
    config.root_dir("writer")        # → Path(...)
    config.openclaw.hook_token       # → str
    config.feedback.tags             # → list[FeedbackTag]
    config.onlyoffice.jwt_secret     # → str
    config.auth.password_hash        # → str
    config.port                      # → 5533
    config.public_base_url           # → str
    config.fallback_cron_interval    # → "24h"
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path


# ── 类型定义 ──────────────────────────────────────────────────────────


@dataclass
class RootEntry:
    id: str
    label: str
    dir: str  # 绝对路径
    agent_id: str = "default"


@dataclass
class OpenClawConfig:
    gateway_url: str = "http://127.0.0.1:18789"
    hook_token: str = ""


@dataclass
class FeedbackTag:
    label: str = ""
    prompt: str = ""
    action: str = "other"
    scope: str = "document"


@dataclass
class FeedbackConfig:
    tags: list[FeedbackTag] = field(default_factory=list)
    enable_subtitle: bool = False


@dataclass
class OnlyOfficeConfig:
    api_js_url: str = ""
    jwt_secret: str = ""
    mode: str = "edit"
    callback_url: str = ""


@dataclass
class AuthConfig:
    username: str = "admin"
    password_hash: str = ""
    session_ttl_minutes: int = 480


@dataclass
class AppConfig:
    roots: list[RootEntry] = field(default_factory=list)
    default_root_id: str = ""
    port: int = 5533
    max_upload_mb: int = 100
    public_base_url: str = ""
    fallback_cron_interval: str = "24h"
    openclaw: OpenClawConfig = field(default_factory=OpenClawConfig)
    feedback: FeedbackConfig = field(default_factory=FeedbackConfig)
    onlyoffice: OnlyOfficeConfig = field(default_factory=OnlyOfficeConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)

    # ── 便捷方法 ──

    def root_agent(self, root_id: str) -> str:
        """返回指定 root 对应的 agent_id。"""
        for r in self.roots:
            if r.id == root_id:
                return r.agent_id
        return "default"

    def root_dir(self, root_id: str) -> Path:
        """返回指定 root 的绝对路径 Path，找不到时抛 ValueError。"""
        for r in self.roots:
            if r.id == root_id:
                return Path(r.dir).expanduser().resolve()
        raise ValueError(f"Root not found: {root_id}")


# ── 单例 ─────────────────────────────────────────────────────────────

_CONFIG_PATH: Path | None = None
_CONFIG_CACHE: tuple[float, AppConfig] | None = None
_CONFIG_TTL: int = 60


def set_config_path(path: str | Path) -> None:
    """main.py 启动时调用，设定 config.json 路径。"""
    global _CONFIG_PATH
    _CONFIG_PATH = Path(path)


def load() -> AppConfig:
    """读 config.json，缓存 TTL 60s，mtime 变化即 invalidate。"""
    global _CONFIG_CACHE
    now = time.time()
    if _CONFIG_CACHE is not None:
        loaded_at, cfg = _CONFIG_CACHE
        if now - loaded_at < _CONFIG_TTL:
            return cfg

    path = _CONFIG_PATH or Path(os.environ.get("CLAWMATE_CONFIG", "config.json"))
    raw = {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    cfg = _parse_config(raw)
    _CONFIG_CACHE = (now, cfg)
    return cfg


def _parse_config(raw: dict) -> AppConfig:
    """从原始 dict 构造 AppConfig 实例。"""
    roots = [
        RootEntry(
            id=r.get("id", ""),
            label=r.get("label", ""),
            dir=r.get("dir", ""),
            agent_id=r.get("agent_id", "default"),
        )
        for r in (raw.get("roots") or [])
        if isinstance(r, dict) and r.get("id")
    ]
    oc = raw.get("openclaw") or {}
    fb = raw.get("feedback") or {}
    oo = raw.get("onlyoffice") or {}
    ac = raw.get("auth") or {}
    # Env var overrides (Docker / CI)
    env_hook_token = os.getenv("CLAWMATE_HOOK_TOKEN")
    env_gateway_url = os.getenv("CLAWMATE_GATEWAY_URL")
    env_public_base_url = os.getenv("CLAWMATE_PUBLIC_BASE_URL")
    env_port = os.getenv("CLAWMATE_PORT")
    env_max_upload = os.getenv("CLAWMATE_MAX_UPLOAD_MB")
    env_onlyoffice_js_url = os.getenv("CLAWMATE_ONLYOFFICE_URL")
    env_onlyoffice_jwt = os.getenv("CLAWMATE_ONLYOFFICE_JWT_SECRET")

    return AppConfig(
        roots=roots,
        default_root_id=str(raw.get("defaultRootId", "")),
        port=int(env_port or raw.get("port", 5533)),
        max_upload_mb=int(env_max_upload or raw.get("max_upload_mb", 100)),
        public_base_url=env_public_base_url or str(raw.get("public_base_url", "")),
        fallback_cron_interval=str(raw.get("fallback_cron_interval", "24h")),
        openclaw=OpenClawConfig(
            gateway_url=env_gateway_url or str(oc.get("gateway_url", "http://127.0.0.1:18789")),
            hook_token=env_hook_token or str(oc.get("hook_token", "")),
        ),
        feedback=FeedbackConfig(
            enable_subtitle=bool(fb.get("enable_subtitle", False)),
            tags=[
                FeedbackTag(
                    label=t.get("label", ""),
                    prompt=t.get("prompt", ""),
                    action=t.get("action", "other"),
                    scope=t.get("scope", "document"),
                )
                for t in (fb.get("tags") or [])
                if isinstance(t, dict)
            ]
        ),
        onlyoffice=OnlyOfficeConfig(
            api_js_url=env_onlyoffice_js_url or str(oo.get("api_js_url", "")),
            jwt_secret=env_onlyoffice_jwt or str(oo.get("jwt_secret", "")),
            mode=str(oo.get("mode", "edit")),
            callback_url=str(oo.get("callback_url", "")),
        ),
        auth=AuthConfig(
            username=str(ac.get("username", "admin")),
            password_hash=str(ac.get("password_hash", "")),
            session_ttl_minutes=int(ac.get("session_ttl_minutes", 480)),
        ),
    )
