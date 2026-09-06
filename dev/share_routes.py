"""
Share Routes — 分享链接生成与访问

Endpoints:
    POST /api/clawmate/share/create  — 为指定文件生成 1/3/7/30 天分享链接
    GET  /api/clawmate/share/{token}/data — 返回分享文件内容 JSON
    GET  /api/clawmate/share/{token}/raw  — 返回原始文件（媒体文件用）
    GET  /api/clawmate/share/{token}/feedback — 返回该分享链接提交的反馈
"""

from __future__ import annotations

import json
import os
import secrets
import time
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
def _fmt_expiry(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%m-%d %H:%M")

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse

from constants import CONFIG_PATH_ENV
from service import safe_path, guess_category, file_info, preview_text, find_project_marker

router = APIRouter()

SHARE_LINKS_FILE = "share_links.json"
SHARE_EXPIRY_DAYS = (1, 3, 7, 30)
SHARE_TTL = 86400  # 兼容旧代码：默认 1 天
_share_feedback_rate: dict[str, list[float]] = {}
_SHARE_FEEDBACK_LIMIT = 12
_SHARE_FEEDBACK_WINDOW = 3600


def _get_share_file_path() -> Path:
    """share_links.json 与 config.json 同目录"""
    config_path_str = os.environ.get(CONFIG_PATH_ENV, "config.json")
    config_path = Path(config_path_str)
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    return config_path.parent / SHARE_LINKS_FILE


def _load_share_links() -> dict:
    path = _get_share_file_path()
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"links": []}


def _save_share_links(data: dict):
    path = _get_share_file_path()
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _clean_expired(data: dict) -> dict:
    now = int(time.time())
    data["links"] = [l for l in data["links"] if l.get("expires_at", 0) > now]
    return data


def _find_link(token: str) -> dict | None:
    data = _load_share_links()
    now = int(time.time())
    for l in data["links"]:
        if l["token"] == token:
            if l["expires_at"] < now:
                return None  # expired
            return l
    return None


def _allow_share_feedback(token: str, request: Request) -> bool:
    now = time.time()
    actor = request.client.host if request.client else "unknown"
    key = hashlib.sha256(f"{token}:{actor}".encode()).hexdigest()[:24]
    values = [v for v in _share_feedback_rate.get(key, []) if now - v < _SHARE_FEEDBACK_WINDOW]
    if len(values) >= _SHARE_FEEDBACK_LIMIT:
        _share_feedback_rate[key] = values
        return False
    values.append(now)
    _share_feedback_rate[key] = values
    return True


@router.post("/api/clawmate/share/create")
async def share_create(request: Request):
    """为指定文件生成可选天数的分享链接"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    root_id = str(body.get("root", "")).strip()
    file_path = str(body.get("path", "")).strip()

    expires_days = body.get("expires_days", 1)
    if (
        isinstance(expires_days, bool)
        or not isinstance(expires_days, int)
        or expires_days not in SHARE_EXPIRY_DAYS
    ):
        raise HTTPException(status_code=400, detail="expires_days must be one of 1, 3, 7, 30")

    if not root_id or not file_path:
        raise HTTPException(status_code=400, detail="Missing root/path")

    # Verify the file exists and is accessible
    try:
        _, target, safe_rel = safe_path(root_id, file_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Cannot share a directory")

    now = int(time.time())
    expires_at = now + expires_days * SHARE_TTL

    data = _load_share_links()
    data = _clean_expired(data)

    # 同一文件复用 token，仅更新有效期
    existing = None
    for l in data["links"]:
        if l["root"] == root_id and l["file"] == safe_rel:
            existing = l
            break

    if existing:
        existing["expires_at"] = expires_at
        existing["created_at"] = now
        token = existing["token"]
        _save_share_links(data)
    else:
        token = secrets.token_hex(12)  # 24 hex chars
        data["links"].append({
            "token": token,
            "root": root_id,
            "file": safe_rel,
            "created_at": now,
            "expires_at": expires_at,
        })
        _save_share_links(data)

    # Build share URL — 优先用 config public_base_url，兜底用请求 host
    try:
        from config import load as cfg
        base = cfg().public_base_url
    except Exception:
        base = ""
    if base:
        share_url = f"{base.rstrip('/')}/clawmate/share-view.html?token={token}"
    else:
        host = request.headers.get("host", f"localhost:{os.environ.get('CLAWMATE_PORT', '5533')}")
        scheme = request.headers.get("x-forwarded-proto", "http")
        share_url = f"{scheme}://{host}/clawmate/share-view.html?token={token}"

    # Format expiry time for display
    expires_str = _fmt_expiry(expires_at)

    return JSONResponse(content={
        "ok": True,
        "token": token,
        "url": share_url,
        "expires_at": expires_at,
        "expires_days": expires_days,
        "expires_str": expires_str,
        "file": safe_rel,
        "reused": bool(existing),
    })


@router.get("/api/clawmate/share/active", response_class=JSONResponse)
async def share_active():
    """返回所有当前有效的分享文件列表（免登录）。

    Response: {"shared": {"root_id": ["file1", "file2", ...], ...}}
    """
    data = _load_share_links()
    data = _clean_expired(data)
    # Save cleaned data back (housekeeping)
    if len(data.get("links", [])) < len(_load_share_links().get("links", [])):
        _save_share_links(data)
    result = {}
    for link in data.get("links", []):
        root = link.get("root", "")
        file = link.get("file", "")
        if root and file:
            result.setdefault(root, []).append(file)
    return JSONResponse(content={"shared": result})


@router.post("/api/clawmate/share/expire")
async def share_expire(request: Request):
    """将指定文件的分享标记为过期"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    root_id = str(body.get("root", "")).strip()
    file_path = str(body.get("path", "")).strip()

    if not root_id or not file_path:
        raise HTTPException(status_code=400, detail="Missing root/path")

    data = _load_share_links()
    data = _clean_expired(data)

    now = int(time.time())
    found = False
    for l in data["links"]:
        if l["root"] == root_id and l["file"] == file_path:
            l["expires_at"] = now  # Expire immediately
            found = True
            break

    if found:
        _save_share_links(data)
        return JSONResponse(content={"ok": True})
    else:
        return JSONResponse(content={"ok": False, "reason": "not_found"}, status_code=404)


@router.get("/api/clawmate/share/{token}/data")
async def share_data(token: str):
    """返回分享文件的内容 JSON（免登录）"""
    link = _find_link(token)
    if not link:
        raise HTTPException(status_code=410, detail="链接已过期或不存在")

    try:
        _, target, safe_rel = safe_path(link["root"], link["file"])
    except Exception:
        raise HTTPException(status_code=404, detail="文件已不存在")

    if not target.exists():
        raise HTTPException(status_code=404, detail="文件已不存在")

    category = guess_category(target)
    meta = file_info(target, safe_rel)

    result = {
        "name": target.name,
        "path": safe_rel,
        "root": link["root"],
        "category": category,
        "suffix": target.suffix.lower(),
        "meta": meta,
        "expires_at": link["expires_at"],
        "expires_str": _fmt_expiry(link["expires_at"]),
    }

    if category == "text":
        content, truncated = preview_text(target)
        result["content"] = content
        result["truncated"] = truncated
    else:
        result["content"] = ""
        result["truncated"] = False

    return JSONResponse(content=result)


@router.post("/api/clawmate/share/{token}/feedback")
async def share_feedback_create(token: str, request: Request):
    """Public capability: submit a suggestion for exactly the shared file."""
    link = _find_link(token)
    if not link:
        raise HTTPException(status_code=410, detail="链接已过期或不存在")
    if not _allow_share_feedback(token, request):
        raise HTTPException(status_code=429, detail="反馈过于频繁，请稍后再试")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    selections = body.get("selections") or []
    if not isinstance(selections, list) or not selections or len(selections) > 10:
        raise HTTPException(status_code=422, detail="Invalid selections")
    try:
        root_path, _, safe_rel = safe_path(link["root"], link["file"])
        project = find_project_marker(root_path, safe_rel)
    except Exception:
        project = ""
    if not project:
        raise HTTPException(status_code=422, detail="共享文件不属于已初始化项目")
    nickname = str(body.get("author") or body.get("nickname") or "匿名评审人").strip()[:80]
    normalized = []
    for selection in selections:
        if not isinstance(selection, dict):
            continue
        normalized.append({"text": str(selection.get("text") or selection.get("content") or "").strip(),
            "note": str(selection.get("note", "")).strip()[:4000],
            "position": str(selection.get("position") or selection.get("location") or "").strip()[:240],
            "start_line": selection.get("start_line") or selection.get("startLine") or 0,
            "end_line": selection.get("end_line") or selection.get("endLine") or 0,
            "context_before": str(selection.get("context_before", ""))[-240:],
            "context_after": str(selection.get("context_after", ""))[:240],
            "action": str(selection.get("action", "other")), "source": "share", "author": nickname,
            "share_token_id": hashlib.sha256(token.encode()).hexdigest()[:16]})
    if not normalized or not all(s["text"] for s in normalized):
        raise HTTPException(status_code=422, detail="反馈必须包含选中内容")
    from store import create_items
    items = create_items(link["root"], project, safe_rel, normalized)
    if not items:
        raise HTTPException(status_code=409, detail="重复反馈")
    return {"ok": True, "ids": [i["id"] for i in items]}


@router.get("/api/clawmate/share/{token}/feedback")
async def share_feedback_list(token: str):
    """Return only feedback submitted through this token for its shared file."""
    link = _find_link(token)
    if not link:
        raise HTTPException(status_code=410, detail="链接已过期或不存在")
    try:
        root_path, _, safe_rel = safe_path(link["root"], link["file"])
        project = find_project_marker(root_path, safe_rel)
    except Exception:
        project = ""
    if not project:
        raise HTTPException(status_code=422, detail="共享文件不属于已初始化项目")

    # A token is a public capability, so do not expose the project's general
    # feedback list. Match both its non-reversible token identifier and the
    # shared file (including legacy root-relative/project-prefixed paths).
    from store import _feedback_paths_match, list_items
    token_id = hashlib.sha256(token.encode()).hexdigest()[:16]
    try:
        items, _ = list_items(link["root"], project, file=safe_rel)
    except (FileNotFoundError, ValueError):
        items = []
    # Keep `location` as a read-only legacy alias so the public card can use
    # the same position compatibility fallback as the review surface.
    fields = ("id", "status", "created", "updated", "action", "content", "note", "position", "location")
    visible = [
        {field: item.get(field, "") for field in fields}
        for item in items
        if item.get("share_token_id") == token_id
        and _feedback_paths_match(safe_rel, item.get("file", ""))
    ]
    return {"items": visible}


@router.get("/api/clawmate/share/{token}/raw")
async def share_raw(token: str):
    """返回原始文件内容（用于图片/音频/视频播放）"""
    link = _find_link(token)
    if not link:
        raise HTTPException(status_code=410, detail="链接已过期或不存在")

    try:
        _, target, _ = safe_path(link["root"], link["file"])
    except Exception:
        raise HTTPException(status_code=404, detail="文件已不存在")

    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="文件已不存在")

    import mimetypes
    media_type, _ = mimetypes.guess_type(str(target))
    if not media_type:
        media_type = "application/octet-stream"

    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "X-Content-Type-Options": "nosniff",
    }
    return FileResponse(target, media_type=media_type, headers=headers)


@router.get("/api/clawmate/share/{token}/asset")
async def share_asset(token: str, root: str = "", path: str = ""):
    """Serve an asset file referenced by the shared document (e.g. markdown images)."""
    link = _find_link(token)
    if not link:
        raise HTTPException(status_code=410, detail="链接已过期或不存在")

    # Security: only allow assets under the same root as the shared file
    if root != link["root"]:
        raise HTTPException(status_code=403, detail="Asset root mismatch")

    # A share token authorizes one document, never arbitrary files under its
    # root.  Permit only assets explicitly referenced by that document.
    try:
        _, shared_file, _ = safe_path(link["root"], link["file"])
        source = shared_file.read_text(encoding="utf-8", errors="replace")
        requested = path.replace("\\", "/")
        if requested not in source and Path(requested).name not in source:
            raise HTTPException(status_code=403, detail="Asset is not referenced by the shared file")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=403, detail="Cannot validate shared asset")

    try:
        _, target, _ = safe_path(root, path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="Asset not found")

    import mimetypes
    media_type, _ = mimetypes.guess_type(str(target))
    if not media_type:
        media_type = "application/octet-stream"

    return FileResponse(target, media_type=media_type, headers={
        "Cache-Control": "public, max-age=3600",
        "X-Content-Type-Options": "nosniff",
    })
