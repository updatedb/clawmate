from __future__ import annotations

import json
import logging
import os
import mimetypes
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from constants import CONFIG_PATH_ENV, PUBLIC_BASE_URL_ENV
from config import load as load_config

logger = logging.getLogger("clawmate.service")

# CONFIG_PATH is set via CLAWMATE_CONFIG env var by main.py before import
CONFIG_PATH = Path(os.environ.get(CONFIG_PATH_ENV, str(Path(__file__).parent / "config.json")))
PREVIEW_MAX_BYTES = 5 * 1024 * 1024  # 5MB, large enough for HTML/code files

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".mdx", ".json", ".csv", ".log", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".html", ".css", ".yaml", ".yml", ".ini", ".toml", ".xml", ".gpx", ".kml", ".conf", ".env", ".sh", ".bat",
    ".ps1", ".sql", ".r", ".go", ".java", ".c", ".cpp", ".h", ".hpp", ".vue", ".srt",
}

# v1.8 B3: TTL 兜底 — 当 config.json mtime 不变时，强制在 TTL 到期后重新加载
# (mtime 检查仍保留：mtime 改变 → 立即失效；TTL 是兜底)
_CONFIG_CACHE: Dict[str, Optional[object]] = {"mtime": None, "data": None, "expires_at": 0.0}
_CONFIG_CACHE_TTL_SECONDS = 60  # dev 可调 (<5min)


def _normalize_rel_path(rel_path: str) -> str:
    rel_path = str(rel_path or "").strip()
    if not rel_path:
        return ""
    if rel_path.startswith("/"):
        raise ValueError("Absolute path not allowed")
    if "\\" in rel_path:
        raise ValueError("Backslash not allowed")
    rel_path = rel_path.strip("/")
    if not rel_path:
        return ""
    parts = rel_path.split("/")
    if any(part in ("", "..") for part in parts):
        raise ValueError("Invalid path segment")
    return "/".join(parts)


def _load_config() -> Dict:
    """从 config.load() 返回 dict 格式（保持外部兼容）。"""
    cfg = load_config()
    return {
        "roots": [{"id": r.id, "label": r.label, "dir": r.dir, "agent_id": r.agent_id} for r in cfg.roots],
        "defaultRootId": cfg.default_root_id,
        "port": cfg.port,
        "public_base_url": cfg.public_base_url,
        "fallback_cron_interval": cfg.fallback_cron_interval,
        "openclaw": {
            "gateway_url": cfg.openclaw.gateway_url,
            "hook_token": cfg.openclaw.hook_token,
        },
        "feedback": {
            "tags": [{"label": t.label, "prompt": t.agent_prompt} for t in load_task_templates() if t.frontend.get("tooltip") or t.frontend.get("panel")],
        },
        "onlyoffice": {
            "api_js_url": cfg.onlyoffice.api_js_url,
            "jwt_secret": cfg.onlyoffice.jwt_secret,
            "mode": cfg.onlyoffice.mode,
            "callback_url": cfg.onlyoffice.callback_url,
        },
        "auth": {
            "username": cfg.auth.username,
            "password_hash": cfg.auth.password_hash,
            "session_ttl_minutes": cfg.auth.session_ttl_minutes,
        },
    }


def get_roots() -> Tuple[List[Dict], str]:
    data = _load_config()
    roots: List[Dict] = []
    for item in data.get("roots", []) or []:
        if not isinstance(item, dict):
            continue
        root_id = str(item.get("id", "")).strip()
        if not root_id:
            continue
        root_dir = str(item.get("dir", "")).strip()
        if not root_dir:
            continue
        if not os.path.isabs(root_dir):
            continue
        root_path = str(Path(root_dir).expanduser().resolve())
        roots.append({
            "id": root_id,
            "label": str(item.get("label") or root_id),
            "dir": root_path,
        })

    if not roots:
        roots = [{
            "id": "media",
            "label": "媒体",
            "dir": str((Path.home() / ".openclaw" / "media").resolve()),
        }]

    default_id = str(data.get("defaultRootId") or roots[0]["id"])
    return roots, default_id


def _root_map() -> Dict[str, Dict]:
    roots, _ = get_roots()
    return {root["id"]: root for root in roots}


def resolve_root(root_id: str) -> Path:
    root_id = str(root_id or "").strip()
    if not root_id:
        raise PermissionError("Missing root")
    root = _root_map().get(root_id)
    if not root:
        raise PermissionError("Root not allowed")
    root_path = Path(root["dir"]).resolve()
    if not root_path.exists() or not root_path.is_dir():
        raise FileNotFoundError("Root not found")
    return root_path


def safe_path(root_id: str, rel_path: str) -> Tuple[Path, Path, str]:
    root_path = resolve_root(root_id)
    safe_rel = _normalize_rel_path(rel_path)
    target = (root_path / safe_rel).resolve()
    try:
        target.relative_to(root_path)
    except ValueError:
        raise PermissionError("Path outside root")
    return root_path, target, safe_rel


def guess_category(path: Path) -> str:
    if path.is_dir():
        return "dir"
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        if mime.startswith("image/"):
            return "image"
        if mime.startswith("audio/"):
            return "audio"
        if mime.startswith("video/"):
            return "video"
        if mime.startswith("text/"):
            return "text"
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return "text"
    # Fallback for extensionless files: sniff content to distinguish text/binary
    try:
        with open(path, "rb") as f:
            head = f.read(8192)
        # Null byte → binary
        if b"\x00" in head:
            return "other"
        # Try UTF-8 decode
        try:
            head.decode("utf-8")
            return "text"
        except UnicodeDecodeError:
            return "other"
    except (OSError, PermissionError):
        pass
    return "other"


def get_public_base_url(request) -> str:
    """从环境变量读取 public_base_url，fallback 到请求信息."""
    env_base_url = os.environ.get(PUBLIC_BASE_URL_ENV)
    if env_base_url:
        return env_base_url.rstrip("/")

    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_proto and forwarded_host:
        proto = forwarded_proto.split(",")[0].strip()
        host = forwarded_host.split(",")[0].strip()
        if proto and host:
            return f"{proto}://{host}".rstrip("/")

    return str(request.base_url).rstrip("/")


def file_info(path: Path, rel_path: str) -> Dict:
    stat = path.stat()
    mime, _ = mimetypes.guess_type(str(path))
    return {
        "name": path.name,
        "path": rel_path,
        "is_dir": path.is_dir(),
        "size": stat.st_size,
        "mtime": int(stat.st_mtime),
        "ext": path.suffix.lower(),
        "mime": mime or "application/octet-stream",
        "category": guess_category(path),
    }


def list_dir(root_id: str, rel_dir: str = "") -> Dict:
    root_path, target, _ = safe_path(root_id, rel_dir)
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError("Directory not found")

    entries: List[Dict] = []

    for entry in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        rel_path = str(entry.relative_to(root_path))
        entries.append(file_info(entry, rel_path))

    result = {
        "path": "" if target == root_path else str(target.relative_to(root_path)),
        "name": target.name if target != root_path else root_path.name,
        "entries": entries,
    }

    return result


def search_media(query: str, root_id: str, rel_dir: str = "", recursive: bool = True, limit: int = 200) -> Dict:
    root_path, target, _ = safe_path(root_id, rel_dir)
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError("Directory not found")

    query_lower = query.lower().strip()
    results: List[Dict] = []
    if not query_lower:
        return {"query": query, "results": results}

    def maybe_add(path: Path, rel_path: str):
        nonlocal results
        results.append(file_info(path, rel_path))

    if recursive:
        for root, dirs, files in os.walk(target):
            for name in dirs + files:
                if query_lower in name.lower():
                    maybe_add(Path(root) / name, str(Path(root).relative_to(root_path) / name))
                    if len(results) >= limit:
                        break
            if len(results) >= limit:
                break
    else:
        for entry in target.iterdir():
            if query_lower in entry.name.lower():
                rel_path = str(entry.relative_to(root_path))
                maybe_add(entry, rel_path)
                if len(results) >= limit:
                    break

    return {"query": query, "results": results}


def preview_text(path: Path) -> Tuple[str, bool]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read(PREVIEW_MAX_BYTES)
        truncated = len(content.encode("utf-8", errors="replace")) >= PREVIEW_MAX_BYTES
    return content, truncated


def delete_file(root_id: str, rel_path: str) -> None:
    """Delete a file after validating root access."""
    root_path, target, safe_rel = safe_path(root_id, rel_path)
    if not target.exists():
        raise FileNotFoundError("File not found")
    if target.is_dir():
        raise ValueError("Cannot delete directory")
    target.unlink()


def delete_dir(root_id: str, rel_path: str) -> None:
    """Delete a directory and all its contents after validating root access."""
    import shutil
    root_path, target, safe_rel = safe_path(root_id, rel_path)
    if not target.exists():
        raise FileNotFoundError("Directory not found")
    if not target.is_dir():
        raise ValueError("Not a directory")
    shutil.rmtree(target)


def upload_file(root_id: str, rel_dir: str, filename: str, content: bytes) -> Path:
    """Save an uploaded file to the given directory. Returns the saved Path."""
    root_path, target_dir, safe_rel = safe_path(root_id, rel_dir)
    if not target_dir.exists() or not target_dir.is_dir():
        raise FileNotFoundError("Directory not found")
    dest = (target_dir / filename).resolve()
    # Ensure file stays within root
    try:
        dest.relative_to(root_path)
    except ValueError:
        raise PermissionError("Path outside root")
    dest.write_bytes(content)
    return dest
