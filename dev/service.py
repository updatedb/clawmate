from __future__ import annotations

import json
import os
import mimetypes
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# CONFIG_PATH is set via CLAWMATE_CONFIG env var by main.py before import
CONFIG_PATH = Path(os.environ.get("CLAWMATE_CONFIG", str(Path(__file__).parent / "config.json")))
PREVIEW_MAX_BYTES = 5 * 1024 * 1024  # 5MB, large enough for HTML/code files

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".mdx", ".json", ".csv", ".log", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".html", ".css", ".yaml", ".yml", ".ini", ".toml", ".xml", ".gpx", ".kml", ".conf", ".env", ".sh", ".bat",
    ".ps1", ".sql", ".r", ".go", ".java", ".c", ".cpp", ".h", ".hpp", ".vue", ".srt",
}

# 文件过滤配置：针对特定目录只显示允许的文件类型
FILTER_CONFIG = {
    "enabled": True,
    "target_directories": {"math", "physics", "chemical"},
    "allowed_extensions": {".html", ".htm", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"},
    "forbidden_extensions": {
        ".js", ".ts", ".py", ".sh", ".bash", ".zsh", ".fish",
        ".ps1", ".bat", ".cmd", ".rb", ".php", ".pl", ".lua",
        ".mjs", ".cjs", ".jsx", ".tsx", ".vue", ".svelte",
        ".exe", ".bin", ".dll", ".so", ".dylib", ".class",
    },
}

_CONFIG_CACHE: Dict[str, Optional[object]] = {"mtime": None, "data": None}


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


def _is_in_target_directory(rel_path: str) -> bool:
    """检查文件路径是否在目标过滤目录中（math、physics、chemical）"""
    if not FILTER_CONFIG["enabled"]:
        return False
    parts = rel_path.lower().split("/") if rel_path else []
    return any(part in FILTER_CONFIG["target_directories"] for part in parts)


def _should_show_file(filename: str, rel_path: str) -> bool:
    """检查文件是否应该显示"""
    if not FILTER_CONFIG["enabled"]:
        return True

    # 不在目标目录，显示所有文件
    if not _is_in_target_directory(rel_path):
        return True

    ext = Path(filename).suffix.lower()

    # 禁止的扩展名
    if ext in FILTER_CONFIG["forbidden_extensions"]:
        return False

    # 允许的扩展名
    if ext in FILTER_CONFIG["allowed_extensions"]:
        return True

    # 其他文件在目标目录中不显示
    return False


def _load_config() -> Dict:
    try:
        stat = CONFIG_PATH.stat()
    except FileNotFoundError:
        return {
            "roots": [{"id": "media", "label": "媒体", "dir": str((Path.home() / ".openclaw" / "media").resolve())}],
            "defaultRootId": "media",
        }

    mtime = stat.st_mtime
    cached = _CONFIG_CACHE.get("data")
    if cached is not None and _CONFIG_CACHE.get("mtime") == mtime:
        return cached  # type: ignore[return-value]

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {
            "roots": [{"id": "media", "label": "媒体", "dir": str((Path.home() / ".openclaw" / "media").resolve())}],
            "defaultRootId": "media",
        }

    _CONFIG_CACHE["mtime"] = mtime
    _CONFIG_CACHE["data"] = data
    return data


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
    return "other"


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
    hidden_count = 0

    for entry in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        rel_path = str(entry.relative_to(root_path))

        # 应用文件过滤规则
        if entry.is_file() and not _should_show_file(entry.name, rel_path):
            hidden_count += 1
            continue

        entries.append(file_info(entry, rel_path))

    result = {
        "path": "" if target == root_path else str(target.relative_to(root_path)),
        "name": target.name if target != root_path else root_path.name,
        "entries": entries,
    }

    # 如果有隐藏的文件，添加统计信息
    if hidden_count > 0:
        result["hidden_count"] = hidden_count
        result["filter_applied"] = _is_in_target_directory(rel_dir)

    return result


def search_media(query: str, root_id: str, rel_dir: str = "", recursive: bool = True, limit: int = 200) -> Dict:
    root_path, target, _ = safe_path(root_id, rel_dir)
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError("Directory not found")

    query_lower = query.lower().strip()
    results: List[Dict] = []
    hidden_count = 0
    if not query_lower:
        return {"query": query, "results": results}

    def maybe_add(path: Path, rel_path: str):
        nonlocal results, hidden_count
        # 应用文件过滤规则
        if path.is_file() and not _should_show_file(path.name, rel_path):
            hidden_count += 1
            return
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

    result = {"query": query, "results": results}
    if hidden_count > 0:
        result["hidden_count"] = hidden_count

    return result


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
