from __future__ import annotations

import json
import logging
import os
import mimetypes
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from constants import CONFIG_PATH_ENV, PUBLIC_BASE_URL_ENV
from config import load as load_config, load_task_templates

logger = logging.getLogger("clawmate.service")

# CONFIG_PATH is set via CLAWMATE_CONFIG env var by main.py before import
CONFIG_PATH = Path(os.environ.get(CONFIG_PATH_ENV, str(Path(__file__).parent / "config.json")))
PREVIEW_MAX_BYTES = 5 * 1024 * 1024  # 5MB, large enough for HTML/code files

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".mdx", ".json", ".csv", ".log", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".html", ".css", ".yaml", ".yml", ".ini", ".toml", ".xml", ".gpx", ".kml", ".conf", ".env", ".sh", ".bat",
    ".ps1", ".sql", ".r", ".go", ".java", ".c", ".cpp", ".h", ".hpp", ".vue", ".srt",
}

ARCHIVE_EXTENSIONS = {
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".tbz2", ".xz", ".txz", ".rar", ".7z",
}

# Compound extensions that indicate archive even when suffix doesn't match directly
_ARCHIVE_COMPOUND_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz")


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
    if any(part in ("", ".", "..") for part in parts):
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


def find_project_marker(root_path: Path, rel_dir: str) -> Optional[str]:
    """在 rel_dir 的路径链上查找 .clawmate/ 目录。

    从 rel_dir 开始逐级向上（直到 root_path），找到第一个 .clawmate/ 目录，
    返回该目录名（即 project 名）。未找到返回 None。
    """
    target = (root_path / rel_dir).resolve() if rel_dir else root_path
    for p in [target] + list(target.parents):
        if root_path not in p.parents and p != root_path:
            break
        if (p / ".clawmate").is_dir():
            return p.name
    return None


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
    # Check archive extensions (including compound .tar.gz etc.)
    name_lower = path.name.lower()
    if path.suffix.lower() in ARCHIVE_EXTENSIONS or name_lower.endswith(_ARCHIVE_COMPOUND_SUFFIXES):
        return "archive"
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


def list_archive(path: Path) -> Dict:
    """List contents of an archive file. Returns entries dict with file tree.

    Supported formats: zip, tar, tar.gz/bz2/xz, rar, 7z.
    RAR and 7z support requires optional dependencies (rarfile, py7zr).
    """
    import datetime

    suffix = path.suffix.lower()
    name_lower = path.name.lower()

    entries: list = []
    encrypted = False

    def _make_entry(name: str, is_dir: bool, size: int,
                    compressed_size: int | None = None,
                    mtime: float | None = None) -> Dict:
        return {
            "name": name,
            "path": "",
            "is_dir": is_dir,
            "size": size,
            "compressed_size": compressed_size,
            "mtime": int(mtime) if mtime else None,
        }

    # ── ZIP ──────────────────────────────────────────────
    if suffix == ".zip":
        import zipfile
        try:
            with zipfile.ZipFile(path, "r") as zf:
                for info in zf.infolist():
                    name = info.filename.rstrip("/")
                    is_dir = info.is_dir()
                    size = info.file_size if not is_dir else 0
                    entries.append(_make_entry(
                        name=name.split("/")[-1] or name,
                        is_dir=is_dir,
                        size=size,
                        compressed_size=info.compress_size,
                        mtime=datetime.datetime(*info.date_time).timestamp() if info.date_time != (1980, 1, 1, 0, 0, 0) else None,
                    ))
                    # Fix path field
                    entries[-1]["path"] = info.filename.rstrip("/")
        except zipfile.BadZipFile:
            raise ValueError("Invalid or corrupted ZIP file")

    # ── TAR / TAR.GZ / TAR.BZ2 / TAR.XZ ─────────────────
    elif suffix in (".tar", ".gz", ".bz2", ".xz") or name_lower.endswith(_ARCHIVE_COMPOUND_SUFFIXES):
        import tarfile
        try:
            # Determine compression mode from filename
            mode = "r"
            if name_lower.endswith((".gz", ".tgz")):
                mode = "r:gz"
            elif name_lower.endswith((".bz2", ".tbz2")):
                mode = "r:bz2"
            elif name_lower.endswith((".xz", ".txz")):
                mode = "r:xz"
            elif suffix in (".tar",):
                mode = "r"
            else:
                mode = "r:*"  # auto-detect

            with tarfile.open(path, mode) as tf:
                for member in tf.getmembers():
                    name = member.name.rstrip("/")
                    entries.append(_make_entry(
                        name=name.split("/")[-1] or name,
                        is_dir=member.isdir(),
                        size=member.size if not member.isdir() else 0,
                        mtime=member.mtime,
                    ))
                    entries[-1]["path"] = member.name.rstrip("/")
        except tarfile.TarError:
            raise ValueError("Invalid or corrupted TAR file")

    # ── RAR ─────────────────────────────────────────────
    elif suffix == ".rar":
        try:
            import rarfile
        except ImportError:
            raise ValueError(
                "RAR format requires the 'rarfile' package. "
                "Install it with: pip install rarfile"
            )
        try:
            with rarfile.RarFile(path, "r") as rf:
                # Check if encrypted (any file has encrypted flag)
                for info in rf.infolist():
                    if getattr(info, "needs_password", False):
                        encrypted = True
                    name = info.filename.rstrip("/")
                    is_dir = info.is_dir()
                    size = info.file_size if not is_dir else 0
                    entries.append(_make_entry(
                        name=name.split("/")[-1] or name,
                        is_dir=is_dir,
                        size=size,
                        compressed_size=getattr(info, "compress_size", 0) or None,
                        mtime=info.mtime if hasattr(info, "mtime") else None,
                    ))
                    entries[-1]["path"] = info.filename.rstrip("/")
        except rarfile.BadRarFile:
            raise ValueError("Invalid or corrupted RAR file")
        except rarfile.RarCannotExec:
            raise ValueError(
                "Cannot extract RAR — 'unrar' tool not found. "
                "Install unrar: sudo apt install unrar"
            )
        except rarfile.PasswordRequired:
            encrypted = True

    # ── 7z ───────────────────────────────────────────────
    elif suffix == ".7z":
        try:
            import py7zr
        except ImportError:
            raise ValueError(
                "7z format requires the 'py7zr' package. "
                "Install it with: pip install py7zr"
            )
        try:
            with py7zr.SevenZipFile(path, "r") as szf:
                if szf.needs_password():
                    encrypted = True
                for info in szf.list():
                    name = info.filename.rstrip("/") if info.filename else ""
                    is_dir = getattr(info, "is_directory", False) or (info.filename or "").endswith("/")
                    entries.append(_make_entry(
                        name=name.split("/")[-1] or name,
                        is_dir=is_dir,
                        size=getattr(info, "uncompressed_size", 0) or 0 if not is_dir else 0,
                        compressed_size=getattr(info, "compressed_size", 0) or None,
                        mtime=getattr(info, "modification_time", None),
                    ))
                    entries[-1]["path"] = (info.filename or "").rstrip("/")
        except py7zr.Bad7zFile:
            raise ValueError("Invalid or corrupted 7z file")

    else:
        raise ValueError(f"Unsupported archive format: {suffix}")

    # Sort: directories first, then by name
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))

    total_size = sum(e["size"] for e in entries if not e["is_dir"])
    file_count = sum(1 for e in entries if not e["is_dir"])
    dir_count = sum(1 for e in entries if e["is_dir"])

    return {
        "entries": entries,
        "total": len(entries),
        "file_count": file_count,
        "dir_count": dir_count,
        "total_size": total_size,
        "encrypted": encrypted,
    }


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


def list_dir(root_id: str, rel_dir: str = "", offset: int = 0, limit: int = 200,
             marker_filter: bool = False) -> Dict:
    """列出目录内容。

    marker_filter=True 时只返回包含 .clawmate/ marker 的子目录（项目列表），
    文件和非 marker 目录被过滤掉。
    """
    root_path, target, _ = safe_path(root_id, rel_dir)
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError("Directory not found")

    all_entries: List[Dict] = []

    # marker 模式: 检查 root 自身是否就是一个 project
    if marker_filter and target == root_path and (root_path / ".clawmate").is_dir():
        all_entries.append(file_info(root_path, ""))

    for entry in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        # marker 过滤: 仅 clawmate 项目列表使用，跳过非项目（无 .clawmate/ 的目录 + 所有文件）
        if marker_filter:
            if not entry.is_dir() or not (entry / ".clawmate").is_dir():
                continue
        rel_path = str(entry.relative_to(root_path))
        info = file_info(entry, rel_path)
        # 标记 clawmate 项目目录
        if entry.is_dir():
            info["marker"] = (entry / ".clawmate").is_dir()
        all_entries.append(info)

    total = len(all_entries)
    entries = all_entries[offset:offset + limit] if limit > 0 else all_entries

    result = {
        "path": "" if target == root_path else str(target.relative_to(root_path)),
        "name": target.name if target != root_path else root_path.name,
        "entries": entries,
        "total": total,
        "offset": offset,
        "limit": limit,
    }

    return result


def search_media(query: str, root_id: str, rel_dir: str = "", recursive: bool = True,
                 limit: int = 200, max_depth: int = 8, timeout: float = 10.0) -> Dict:
    """搜索文件/目录名，支持递归深度限制和硬超时。

    Args:
        max_depth: 递归最大深度（从 start_dir 算起），默认 8 层
        timeout: 搜索超时秒数，默认 10s；超时后返回已有结果并标记 truncated=True
    """
    import time as _time
    _deadline = _time.time() + timeout

    root_path, target, _ = safe_path(root_id, rel_dir)
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError("Directory not found")

    query_lower = query.lower().strip()
    results: List[Dict] = []
    truncated = False
    if not query_lower:
        return {"query": query, "results": results, "truncated": False}

    if recursive:
        from collections import deque
        queue: deque = deque([(target, 0)])  # (dir_path, depth)
        while queue:
            if _time.time() > _deadline:
                truncated = True
                break
            dir_path, depth = queue.popleft()
            if depth > max_depth:
                continue
            try:
                entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except (OSError, PermissionError):
                continue
            for entry in entries:
                if query_lower in entry.name.lower():
                    results.append(file_info(entry, str(entry.relative_to(root_path))))
                    if len(results) >= limit:
                        break
            if len(results) >= limit:
                break
            if depth < max_depth:
                for entry in entries:
                    if entry.is_dir():
                        queue.append((entry, depth + 1))
    else:
        for entry in target.iterdir():
            if _time.time() > _deadline:
                truncated = True
                break
            if query_lower in entry.name.lower():
                results.append(file_info(entry, str(entry.relative_to(root_path))))
                if len(results) >= limit:
                    break

    return {"query": query, "results": results, "truncated": truncated}


def preview_text(path: Path) -> Tuple[str, bool]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read(PREVIEW_MAX_BYTES)
        truncated = len(content.encode("utf-8", errors="replace")) >= PREVIEW_MAX_BYTES
    return content, truncated


def delete_file(root_id: str, rel_path: str) -> None:
    """Delete a file after validating root access."""
    root_path, target, safe_rel = safe_path(root_id, rel_path)
    if not safe_rel:
        raise PermissionError("Cannot delete root directory")
    if not target.exists():
        raise FileNotFoundError("File not found")
    if target.is_dir():
        raise ValueError("Cannot delete directory")
    target.unlink()


def delete_dir(root_id: str, rel_path: str) -> None:
    """Delete a directory and all its contents after validating root access."""
    import shutil
    root_path, target, safe_rel = safe_path(root_id, rel_path)
    if not safe_rel:
        raise PermissionError("Cannot delete root directory")
    if not target.exists():
        raise FileNotFoundError("Directory not found")
    if not target.is_dir():
        raise ValueError("Not a directory")
    shutil.rmtree(target)


def create_dir(root_id: str, rel_dir: str, name: str) -> Path:
    """在指定目录下创建子目录，返回创建的目录路径。"""
    name = name.strip()
    if not name:
        raise ValueError("目录名不能为空")
    if "/" in name or "\\" in name:
        raise ValueError("目录名不能包含路径分隔符")
    root_path, target_dir, safe_rel = safe_path(root_id, rel_dir)
    if not target_dir.exists() or not target_dir.is_dir():
        raise FileNotFoundError("Directory not found")
    new_dir = target_dir / name
    if new_dir.exists():
        raise FileExistsError(f"目录已存在: {name}")
    new_dir.mkdir(parents=False)
    return new_dir


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


def move_file(root_id: str, rel_path: str, dest_dir: str) -> Dict:
    """Move a file or directory to a new location within the same root.

    Args:
        root_id: The root identifier.
        rel_path: Current relative path of the file/directory.
        dest_dir: Destination directory relative path.

    Returns:
        {ok: True, newPath: "dest_dir/filename", newName: "filename"}
    """
    import shutil
    root_path, source, safe_src = safe_path(root_id, rel_path)
    _, dest_dir_path, safe_dest = safe_path(root_id, dest_dir)

    if not source.exists():
        raise FileNotFoundError("Source file/directory not found")
    if not dest_dir_path.exists() or not dest_dir_path.is_dir():
        raise FileNotFoundError("Destination directory not found")

    # Prevent moving a directory into itself or its subdirectories
    if source.is_dir():
        try:
            dest_dir_path.relative_to(source)
            raise ValueError("Cannot move a directory into itself or its subdirectory")
        except ValueError:
            pass  # dest_dir is NOT inside source — OK

    dest = dest_dir_path / source.name
    if dest.exists():
        raise FileExistsError(f"'{source.name}' already exists in the destination directory")

    try:
        shutil.move(str(source), str(dest))
    except PermissionError:
        raise PermissionError("Permission denied: filesystem is read-only")
    except OSError as e:
        raise OSError(f"Move failed: {e}")

    # Compute new relative path
    new_safe_rel = str(dest.relative_to(root_path))
    return {
        "ok": True,
        "newName": dest.name,
        "newPath": new_safe_rel,
    }


def extract_archive(root_id: str, rel_path: str, dest_dir: str) -> Dict:
    """Extract an archive file to a destination directory within the same root.

    Args:
        root_id: The root identifier.
        rel_path: Relative path of the archive file.
        dest_dir: Destination directory for extracted files.

    Returns:
        {ok: True, destPath: "dest_dir", count: N}
    """
    import shutil
    root_path, source, safe_src = safe_path(root_id, rel_path)
    _, dest_dir_path, safe_dest = safe_path(root_id, dest_dir)

    if not source.exists() or source.is_dir():
        raise FileNotFoundError("Archive file not found")
    if not dest_dir_path.exists() or not dest_dir_path.is_dir():
        # Create destination directory if it doesn't exist
        dest_dir_path.mkdir(parents=True, exist_ok=True)

    suffix = source.suffix.lower()
    name_lower = source.name.lower()

    count = 0

    # ── ZIP ──────────────────────────────────────────────
    if suffix == ".zip":
        import zipfile
        try:
            with zipfile.ZipFile(source, "r") as zf:
                zf.extractall(dest_dir_path)
                count = len(zf.namelist())
        except zipfile.BadZipFile:
            raise ValueError("Invalid or corrupted ZIP file")

    # ── TAR / TAR.GZ / TAR.BZ2 / TAR.XZ ─────────────────
    elif suffix in (".tar", ".gz", ".bz2", ".xz") or name_lower.endswith((".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz")):
        import tarfile
        try:
            mode = "r"
            if name_lower.endswith((".gz", ".tgz")):
                mode = "r:gz"
            elif name_lower.endswith((".bz2", ".tbz2")):
                mode = "r:bz2"
            elif name_lower.endswith((".xz", ".txz")):
                mode = "r:xz"
            elif suffix in (".tar",):
                mode = "r"
            else:
                mode = "r:*"

            with tarfile.open(source, mode) as tf:
                tf.extractall(dest_dir_path)
                count = len(tf.getmembers())
        except tarfile.TarError:
            raise ValueError("Invalid or corrupted TAR file")

    # ── RAR ─────────────────────────────────────────────
    elif suffix == ".rar":
        try:
            import rarfile
        except ImportError:
            raise ValueError(
                "RAR format requires the 'rarfile' package. "
                "Install it with: pip install rarfile"
            )
        try:
            with rarfile.RarFile(source, "r") as rf:
                rf.extractall(dest_dir_path)
                count = len(rf.namelist())
        except rarfile.BadRarFile:
            raise ValueError("Invalid or corrupted RAR file")
        except rarfile.RarCannotExec:
            raise ValueError(
                "Cannot extract RAR — 'unrar' tool not found. "
                "Install unrar: sudo apt install unrar"
            )
        except rarfile.PasswordRequired:
            raise ValueError("Cannot extract password-protected RAR file")

    # ── 7z ───────────────────────────────────────────────
    elif suffix == ".7z":
        try:
            import py7zr
        except ImportError:
            raise ValueError(
                "7z format requires the 'py7zr' package. "
                "Install it with: pip install py7zr"
            )
        try:
            with py7zr.SevenZipFile(source, "r") as szf:
                if szf.needs_password():
                    raise ValueError("Cannot extract password-protected 7z file")
                szf.extractall(dest_dir_path)
                # Count entries
                entries = szf.list()
                count = len(entries) if entries else 0
        except py7zr.Bad7zFile:
            raise ValueError("Invalid or corrupted 7z file")

    else:
        raise ValueError(f"Unsupported archive format: {suffix}")

    return {
        "ok": True,
        "destPath": safe_dest,
        "count": count,
    }
