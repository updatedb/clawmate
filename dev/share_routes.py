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
import posixpath
import secrets
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
def _fmt_expiry(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%m-%d %H:%M")

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse

from constants import CONFIG_PATH_ENV
from service import (safe_path, guess_category, file_info, get_roots,
                     preview_text, find_project_marker)

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


class _ShareRecipient:
    """Synthetic principal for the holder of a share link.

    A recipient has no account -- the token is the capability. Binding this as
    the caller is what lets the existing safe_path() -> get_roots() -> registry
    chain resolve the link's root for an anonymous request, instead of reporting
    nothing and failing closed on every share route. The grant is exactly one
    root, and get_roots() still drops it once the registry no longer holds that
    id, so a deleted root keeps failing closed rather than widening.
    """

    id = ""
    username = "share-recipient"
    is_admin = False
    must_change_password = False

    def __init__(self, root_id: str):
        self.root_ids = (root_id,)

    def public(self) -> dict:
        """Same shape as UserRecord.public() so anything that serialises a
        principal does not trip over this one."""
        return {"id": self.id, "username": self.username, "is_admin": False,
                "must_change_password": False, "root_ids": list(self.root_ids)}


def _shared_path(link: dict, rel_path: str):
    """Resolve a path under the root the share link recorded.

    The root comes from the link, never from the caller: a token authorizes one
    document, so a recipient must not be able to name a different root. Binding
    the recipient principal keeps safe_path() the single fail-closed
    authorization choke point rather than adding a second way to resolve paths.
    """
    from auth import bind_request_user, release_request_user

    handle = bind_request_user(_ShareRecipient(link["root"]))
    try:
        return safe_path(link["root"], rel_path)
    finally:
        release_request_user(handle)


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
    """返回当前调用者有权访问的 root 下、有效的分享文件列表。

    Response: {"shared": {"root_id": ["file1", "file2", ...], ...}}
    """
    data = _load_share_links()
    data = _clean_expired(data)
    # Save cleaned data back (housekeeping)
    if len(data.get("links", [])) < len(_load_share_links().get("links", [])):
        _save_share_links(data)
    # Report only the roots the caller may actually reach. The inventory spans
    # every root, so without this a user granted one root would still learn which
    # files are shared out of all the others.
    allowed = {root["id"] for root in get_roots()[0]}
    result = {}
    for link in data.get("links", []):
        root = link.get("root", "")
        file = link.get("file", "")
        if root and file and root in allowed:
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

    # Lapsing a link is an owner action on a root the caller must actually hold.
    # The match below is on plain strings, so without this any logged-in user
    # could expire a link for a root they were never granted just by naming it.
    # safe_path() does not require the file to exist, so cleaning up a link whose
    # file was since deleted still works while its root is still registered.
    try:
        safe_path(root_id, file_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

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
        _, target, safe_rel = _shared_path(link, link["file"])
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
        root_path, _, safe_rel = _shared_path(link, link["file"])
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
            "action": str(selection.get("action") or "other").strip(),
            "scope": str(selection.get("scope") or "document").strip(),
            "task_id": str(selection.get("task_id") or "").strip(),
            "source": "share", "author": nickname,
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
        root_path, _, safe_rel = _shared_path(link, link["file"])
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
    fields = ("id", "status", "created", "updated", "action", "scope", "task_id", "content", "note")
    visible = []
    for item in items:
        if not (item.get("share_token_id") == token_id
                and _feedback_paths_match(safe_rel, item.get("file", ""))):
            continue
        # `position` is canonical. Older records can contain only `location`,
        # so normalize it while retaining a populated legacy alias for clients
        # that still read it. Do not emit an empty alias for current records.
        position = item.get("position") or item.get("location") or ""
        response_item = {field: item.get(field, "") for field in fields}
        response_item["position"] = position
        if item.get("location"):
            response_item["location"] = item["location"]
        visible.append(response_item)
    return {"items": visible}


@router.post("/api/clawmate/share/{token}/feedback/delete")
async def share_feedback_delete(token: str, request: Request):
    """Delete one feedback item submitted through this exact share capability."""
    link = _find_link(token)
    if not link:
        raise HTTPException(status_code=410, detail="链接已过期或不存在")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    feedback_id = str(body.get("id", "")).strip()
    if not feedback_id:
        raise HTTPException(status_code=422, detail="Missing id")
    try:
        root_path, _, safe_rel = _shared_path(link, link["file"])
        project = find_project_marker(root_path, safe_rel)
    except Exception:
        project = ""
    if not project:
        raise HTTPException(status_code=422, detail="共享文件不属于已初始化项目")
    from store import _feedback_paths_match, delete_item, list_items
    token_id = hashlib.sha256(token.encode()).hexdigest()[:16]
    try:
        items, _ = list_items(link["root"], project, file=safe_rel)
    except (FileNotFoundError, ValueError):
        items = []
    allowed = any(item.get("id") == feedback_id
                  and item.get("share_token_id") == token_id
                  and _feedback_paths_match(safe_rel, item.get("file", ""))
                  for item in items)
    if not allowed:
        raise HTTPException(status_code=404, detail="Feedback not found")
    delete_item(link["root"], project, feedback_id)
    return {"ok": True, "id": feedback_id}


@router.get("/api/clawmate/share/{token}/raw")
async def share_raw(token: str):
    """返回原始文件内容（用于图片/音频/视频播放）"""
    link = _find_link(token)
    if not link:
        raise HTTPException(status_code=410, detail="链接已过期或不存在")

    try:
        _, target, _ = _shared_path(link, link["file"])
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
    # root. Permit only assets the document actually references.
    #
    # The recipient's browser rewrites a relative image src against the shared
    # file's own directory, so the request has to be read relative to that
    # directory before comparing: the document writes `img/foo.png`, the request
    # arrives as `notes/img/foo.png`. Comparing the bare basename instead -- as
    # this did -- let a recipient fetch any file whose name merely appeared
    # somewhere in the text, so one mention of `README.md` exposed every
    # README.md under the root.
    try:
        _, shared_file, shared_rel = _shared_path(link, link["file"])
        source = shared_file.read_text(encoding="utf-8", errors="replace")
        base = posixpath.dirname(shared_rel)
        rel_to_doc = posixpath.relpath(path.replace("\\", "/"), base or ".")
        if rel_to_doc.startswith("..") or rel_to_doc not in source:
            raise HTTPException(status_code=403, detail="Asset is not referenced by the shared file")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=403, detail="Cannot validate shared asset")

    # `root` was pinned to the link's own root above, so the recipient principal
    # resolves it the same way.
    try:
        _, target, _ = _shared_path(link, path)
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
