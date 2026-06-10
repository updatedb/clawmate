"""
Share Routes — 分享链接生成与访问

Endpoints:
    POST /api/clawmate/share/create  — 为指定文件生成 24h 分享链接
    GET  /s/{token}                  — 访问分享链接（只读预览页）
    GET  /api/clawmate/share/{token}/data — 返回分享文件内容 JSON
    GET  /api/clawmate/share/{token}/raw  — 返回原始文件（媒体文件用）
"""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

from constants import CONFIG_PATH_ENV
from service import safe_path, guess_category, file_info, preview_text

router = APIRouter()

SHARE_LINKS_FILE = "share_links.json"
SHARE_TTL = 86400  # 24 hours


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


@router.post("/api/clawmate/share/create")
async def share_create(request: Request):
    """为指定文件生成 24h 分享链接"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    root_id = str(body.get("root", "")).strip()
    file_path = str(body.get("path", "")).strip()

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

    # Generate token
    token = secrets.token_hex(12)  # 24 hex chars
    now = int(time.time())
    expires_at = now + SHARE_TTL

    data = _load_share_links()
    data = _clean_expired(data)
    data["links"].append({
        "token": token,
        "root": root_id,
        "file": safe_rel,
        "created_at": now,
        "expires_at": expires_at,
    })
    _save_share_links(data)

    # Build share URL
    host = request.headers.get("host", f"localhost:{os.environ.get('CLAWMATE_PORT', '5533')}")
    scheme = request.headers.get("x-forwarded-proto", "http")
    share_url = f"{scheme}://{host}/s/{token}"

    # Format expiry time for display
    expires_dt = datetime.fromtimestamp(expires_at, tz=timezone.utc).astimezone()
    expires_str = expires_dt.strftime("%m-%d %H:%M")

    return JSONResponse(content={
        "ok": True,
        "token": token,
        "url": share_url,
        "expires_at": expires_at,
        "expires_str": expires_str,
        "file": safe_rel,
    })


@router.get("/s/{token}")
async def share_view(token: str):
    """访问分享链接 — 返回只读预览页"""
    link = _find_link(token)
    if not link:
        return HTMLResponse(
            "<h2 style='text-align:center;margin-top:20vh;color:#888;'>🔗 链接已过期或不存在</h2>",
            status_code=410,
        )

    # Verify file still exists
    try:
        _, target, safe_rel = safe_path(link["root"], link["file"])
    except Exception:
        return HTMLResponse(
            "<h2 style='text-align:center;margin-top:20vh;color:#888;'>📄 文件已不存在</h2>",
            status_code=404,
        )

    if not target.exists():
        return HTMLResponse(
            "<h2 style='text-align:center;margin-top:20vh;color:#888;'>📄 文件已不存在</h2>",
            status_code=404,
        )

    # Serve the share page
    share_html_path = Path(__file__).parent / "static" / "share.html"
    if not share_html_path.exists():
        return HTMLResponse("share.html not found", status_code=500)

    with open(share_html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Inject token and file info into the page
    expires_dt = datetime.fromtimestamp(link["expires_at"], tz=timezone.utc).astimezone()
    expires_str = expires_dt.strftime("%m-%d %H:%M")

    html = html.replace("{{TOKEN}}", token)
    html = html.replace("{{FILE_NAME}}", target.name)
    html = html.replace("{{EXPIRES_STR}}", expires_str)

    return HTMLResponse(content=html)


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
        "category": category,
        "suffix": target.suffix.lower(),
        "meta": meta,
    }

    if category == "text":
        content, truncated = preview_text(target)
        result["content"] = content
        result["truncated"] = truncated
    else:
        result["content"] = ""
        result["truncated"] = False

    return JSONResponse(content=result)


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
