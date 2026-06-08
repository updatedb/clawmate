# Store / Config 标准化设计

> 评审稿 · 2026-06-06
> 注意：cls 的简单性。ConfigLoader 是一个字段对象，不是类。FeedbackStore 是一个方法集，不是类。

---

## 一、ConfigLoader — 配置访问

### 设计原则

- 模块级单例 `_cfg`，lazy init，TTL 缓存（60s + mtime 变化即 invalidate）
- 访问路径类型化，不暴露原始 dict
- `__init__` 不做文件 I/O

### 接口

```python
# dev/config.py

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import os, json, time


# ── 类型化数据类 ────────────────────────────────────────────────────

@dataclass
class RootEntry:
    id: str
    label: str
    dir: str          # 绝对路径
    agent_id: str = "default"


@dataclass
class OpenClawConfig:
    gateway_url: str = "http://127.0.0.1:18789"
    hook_token: str = ""


@dataclass
class FeedbackTag:
    label: str = ""
    prompt: str = ""


@dataclass
class FeedbackConfig:
    tags: list[FeedbackTag] = field(default_factory=list)


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
        """返回 root_id 对应的 agent_id"""
        for r in self.roots:
            if r.id == root_id:
                return r.agent_id
        return "default"

    def root_dir(self, root_id: str) -> Path:
        """返回 root_id 的绝对路径"""
        for r in self.roots:
            if r.id == root_id:
                return Path(r.dir).expanduser().resolve()
        raise ValueError(f"Root not found: {root_id}")


# ── 模块级单例 ──────────────────────────────────────────────────────

_CONFIG_PATH: Path | None = None
_CONFIG_CACHE: tuple[float, AppConfig] | None = None  # (loaded_at, config)
_CONFIG_TTL: int = 60


def set_config_path(path: str | Path) -> None:
    """由 main.py 启动时调用，设 config.json 路径（等价于 setdefault('CLAWMATE_CONFIG', ...)）。"""
    global _CONFIG_PATH
    _CONFIG_PATH = Path(path)


def _resolve_path() -> Path:
    if _CONFIG_PATH:
        return _CONFIG_PATH
    return Path(os.environ.get("CLAWMATE_CONFIG", "config.json"))


def load() -> AppConfig:
    """读取并缓存 config.json，返回 AppConfig 实例。"""
    global _CONFIG_CACHE

    now = time.time()
    if _CONFIG_CACHE is not None:
        loaded_at, cfg = _CONFIG_CACHE
        if now - loaded_at < _CONFIG_TTL:
            return cfg

    path = _resolve_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        raw = {}

    cfg = _parse_config(raw)
    _CONFIG_CACHE = (now, cfg)
    return cfg


def _parse_config(raw: dict) -> AppConfig:
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

    oc_raw = raw.get("openclaw") or {}
    fb_raw = raw.get("feedback") or {}
    oo_raw = raw.get("onlyoffice") or {}
    ac_raw = raw.get("auth") or {}

    return AppConfig(
        roots=roots,
        default_root_id=raw.get("defaultRootId", ""),
        port=int(raw.get("port", 5533)),
        max_upload_mb=int(raw.get("max_upload_mb", 100)),
        public_base_url=str(raw.get("public_base_url", "")),
        fallback_cron_interval=str(raw.get("fallback_cron_interval", "24h")),
        openclaw=OpenClawConfig(
            gateway_url=str(oc_raw.get("gateway_url", "http://127.0.0.1:18789")),
            hook_token=str(oc_raw.get("hook_token", "")),
        ),
        feedback=FeedbackConfig(
            tags=[
                FeedbackTag(label=t.get("label", ""), prompt=t.get("prompt", ""))
                for t in (fb_raw.get("tags") or [])
                if isinstance(t, dict)
            ],
        ),
        onlyoffice=OnlyOfficeConfig(
            api_js_url=str(oo_raw.get("api_js_url", "")),
            jwt_secret=str(oo_raw.get("jwt_secret", "")),
            mode=str(oo_raw.get("mode", "edit")),
            callback_url=str(oo_raw.get("callback_url", "")),
        ),
        auth=AuthConfig(
            username=str(ac_raw.get("username", "admin")),
            password_hash=str(ac_raw.get("password_hash", "")),
            session_ttl_minutes=int(ac_raw.get("session_ttl_minutes", 480)),
        ),
    )
```

### 现有代码迁移映射

| 旧写法 | 新写法 |
|--------|--------|
| `cfg.get("roots", [])` | `config.roots` |
| `r.get("agent_id", "default")` | `config.root_agent(root_id)` |
| `oc = cfg.get("openclaw", {})` | `config.openclaw.hook_token` |
| `fb_cfg = cfg.get("feedback", {})` | `config.feedback.tags` |
| `oo_cfg = cfg.get("onlyoffice", {})` | `config.onlyoffice.jwt_secret` |
| ~~`cfg.get("llm", {})`~~ | 已删除（死代码 `subtitle.py:correct_srt` / `_load_llm_config`，LLM 操作全部走 OpenClaw agent） |

---

## 二、FeedbackStore — 反馈 CRUD

### 设计原则

- 纯工具函数集，无状态
- 输入 `(root_id, project)`，读写对应目录的 `feedback.json`
- 不管理 session/auth，只做文件 I/O
- 所有函数写 journalctl INFO 日志

### 接口

```python
# dev/store.py

from __future__ import annotations
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone, timedelta

from feedback_schema import FEEDBACK_STATUSES, FeedbackItem


class ScanResult(dict):
    """返回给 cron-tick 的扫描结果"""
    checked_roots: int
    pending_total: int
    pending_roots: list[str]  # 有 pending 的 root_id 列表


# ── 读 ─────────────────────────────────────────────────────────────

def list_items(
    root_id: str,
    project: str,
    status: str = "",
    file: str = "",
    since: str = "",
) -> tuple[list[FeedbackItem], int]:
    """
    列出指定 project 的反馈条目。

    Args:
        status: 过滤状态。""=全部 "all"=全部 "pending" 等
        file: 文件名模糊匹配
        since: "today" 或 "YYYY-MM-DD"

    Returns:
        (items[], total_pending)
    """


def status_count(root_id: str, project: str) -> dict[str, int]:
    """返回 {pending, in_progress, done, failed} 计数。"""


# ── 写 ─────────────────────────────────────────────────────────────

def create_items(
    root_id: str,
    project: str,
    file_path: str,
    selections: list[dict],
    preview_url: str = "",
) -> list[FeedbackItem]:
    """
    写入新反馈条目。

    内部自动：
    - 去重（同 content + file 跳过）
    - 自增 ID (FD-{abbr}-{NNNN})
    - 写 feedback.json（原子写: tmp → rename）
    - journalctl INFO 日志

    Returns:
        新建的条目列表
    """


def update_item(
    root_id: str,
    project: str,
    item_id: str,
    new_status: str,
    result: str = "",
) -> FeedbackItem:
    """
    更新一条反馈的状态。

    Raises:
        ValueError: status 不合法
        FileNotFoundError: feedback.json 不存在
        LookupError: item_id 不存在
    """


# ── 扫描 ──────────────────────────────────────────────────────────

def scan_all() -> ScanResult:
    """
    扫描 config.json 所有 root 下所有 project 的 feedback.json。

    Returns:
        ScanResult: {checked_roots, pending_total, pending_roots}

    不抛异常（日志记录错误）。
    由 cron-tick 端点调用。
    """


# ── 项目缩写 ───────────────────────────────────────────────────────

def project_abbr(project: str) -> str:
    """从 project 名生成 2 字符缩写（复用现有 _project_abbr 逻辑）。"""
```

### 现有代码迁移映射

| 旧调用 | 新调用 |
|--------|--------|
| `_get_feedback_path(root_id, project)` | 内部实现，不暴露 |
| `_read_feedback_json(path)` | `store.list_items(root_id, project)` |
| `_build_feedback_json(...)` | 内部实现 |
| `_filter_items(path, status, file, since)` | `store.list_items` 参数 |
| `fb_path.write_text(...)` | `store.create_items` / `store.update_item` |
| `cleanup_old_feedback()` | 后续版本考虑，当前不迁移 |

---

## 三、迁移范围

| 文件 | 替换 | 保留 |
|------|------|------|
| `service.py` | `_load_config()` 内部实现改为 `dev.config.load()` | 接口不变 |
| `feedback_api.py` | `_read_feedback_json` / `_build_feedback_json` / `_filter_items` / `_get_feedback_path` → `store.*` | API 路由不变 |
| `feedback_api.py` | `cfg.get("openclaw")` etc → `config.load().openclaw` | — |
| `routes.py` SRT 端点 | 内联 feedback 读/写 → `store.create_items()` | 端点不变 |
| `routes.py` /config | `json.load(config_path)` → `config.load()` | 端点不变 |
| `main.py` | `json.load(CONFIG_PATH)` → `config.set_config_path()` + `config.load()` | 启动流程不变 |
| `auth.py` | `config.get("auth")` → `config.load().auth` | 接口不变 |
| `subtitle.py` | 删除 `correct_srt` / `_load_llm_config` / `_parse_srt` / `_build_srt`（死代码，功能已被 agent feedback 替代） | `extract_subtitle` 保留 |
