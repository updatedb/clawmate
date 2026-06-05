from __future__ import annotations

from fastapi import APIRouter, Query, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse, StreamingResponse
from urllib.parse import quote, unquote_to_bytes
import base64
import hashlib
import hmac
import json
import os
import re
import time
import zipfile
import httpx
from datetime import datetime, timezone, timedelta
from pathlib import Path

from service import (
    list_dir,
    safe_path,
    search_media,
    preview_text,
    guess_category,
    file_info,
    delete_file,
    delete_dir,
    resolve_root,
    _root_map,
)
from validators import VALIDATORS
from feedback_api import router as feedback_router, _wake_agent_for_root
from config import load as config
from store import create_items as store_create_items, list_items as store_list_items, project_abbr as store_project_abbr


router = APIRouter()

# Feedback routes (extracted to feedback_api.py)
router.include_router(feedback_router)

from constants import PUBLIC_BASE_URL_ENV, CONFIG_PATH_ENV, ONLYOFFICE_JWT_SECRET_ENV


@router.get("/api/clawmate/config", response_class=JSONResponse)
async def public_config():
    """返回前端安全的公开配置（不含 JWT secret 等敏感字段）。"""
    cfg = config()
    return {
        "roots": [{"id": r.id, "label": r.label, "dir": r.dir, "agent_id": r.agent_id} for r in cfg.roots],
        "defaultRootId": cfg.default_root_id,
        "feedback_tags": [{"label": t.label, "prompt": t.prompt} for t in cfg.feedback.tags],
    }
ONLYOFFICE_TOKEN_TTL = 3600


def _get_onlyoffice_secret() -> str:
    secret = os.getenv(ONLYOFFICE_JWT_SECRET_ENV)
    if not secret:
        raise HTTPException(status_code=500, detail=f"{ONLYOFFICE_JWT_SECRET_ENV} is not set")
    return secret



def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _encode_jwt(payload: dict, secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url_encode(signature)}"


def _decode_jwt(token: str, secret: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid token")
    signing_input = f"{parts[0]}.{parts[1]}".encode("utf-8")
    signature = _b64url_decode(parts[2])
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid signature")
    payload = json.loads(_b64url_decode(parts[1]))
    exp = payload.get("exp")
    if exp is None:
        raise ValueError("Missing exp")
    if int(exp) < int(time.time()):
        raise PermissionError("Token expired")
    return payload


@router.get("/api/clawmate/list", response_class=JSONResponse)
async def clawmate_list(root: str = "", dir: str = ""):
    try:
        return JSONResponse(content=list_dir(root, dir))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Directory not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")


@router.get("/api/clawmate/list/navigation", response_class=JSONResponse)
async def clawmate_list_navigation(root: str = "", path: str = ""):
    """Return prev/next navigation for the given image file in the same directory.

    Response: {prev: {name, path}|null, next: {name, path}|null, current: {name, path}, total: int}
    """
    try:
        dir_path = str(Path(path).parent) if "/" in path else ""
        result = list_dir(root, dir_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Directory not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    # list_dir returns {path, name, entries: [...]}
    entries = result.get("entries", [])

    # Filter to images only (category == "image")
    images = sorted(
        [e for e in entries if e.get("category") == "image"],
        key=lambda e: e.get("name", ""),
    )
    if not images:
        return JSONResponse(content={"prev": None, "next": None, "current": None, "total": 0})

    current_name = path.split("/")[-1]
    idx = next((i for i, e in enumerate(images) if e["name"] == current_name), -1)
    if idx < 0:
        idx = 0

    prev_entry = images[idx - 1] if idx > 0 else None
    next_entry = images[idx + 1] if idx < len(images) - 1 else None

    return JSONResponse(content={
        "prev": {"name": prev_entry["name"], "path": prev_entry["path"]} if prev_entry else None,
        "next": {"name": next_entry["name"], "path": next_entry["path"]} if next_entry else None,
        "current": {"name": images[idx]["name"], "path": images[idx]["path"]},
        "total": len(images),
    })


@router.get("/api/clawmate/search", response_class=JSONResponse)
async def clawmate_search(
    q: str,
    root: str = "",
    dir: str = "",
    recursive: bool = True,
    limit: int = Query(200, ge=1, le=500),
):
    try:
        return JSONResponse(content=search_media(q, root_id=root, rel_dir=dir, recursive=recursive, limit=limit))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Directory not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")


import hmac, hashlib, time as time_module

_PREVIEW_TOKEN_TTL_SECONDS = 3600  # 1 hour
_PREVIEW_TOKEN_SECRET = os.environ.get("CLAWMATE_PREVIEW_TOKEN_SECRET", "dev-secret-change-me")


def generate_preview_token(root_id: str, rel_path: str) -> str:
    """Generate a time-limited HMAC-signed preview token for root_id:rel_path."""
    expires = int(time_module.time()) + _PREVIEW_TOKEN_TTL_SECONDS
    msg = f"{root_id}:{rel_path}:{expires}"
    sig = hmac.new(_PREVIEW_TOKEN_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return f"{expires}:{sig}"


def verify_preview_token(root_id: str, rel_path: str, token: str) -> bool:
    """Verify a preview token. Returns True if valid and not expired."""
    try:
        expires_str, sig = token.split(":", 1)
        expires = int(expires_str)
        if time_module.time() > expires:
            return False
        msg = f"{root_id}:{rel_path}:{expires}"
        expected = hmac.new(_PREVIEW_TOKEN_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


@router.get("/api/clawmate/preview")
async def clawmate_preview(root: str = "", path: str = ""):
    if not root or not root.strip():
        return RedirectResponse(url="/clawmate/", status_code=302)
    try:
        root_path, target, safe_rel = safe_path(root, path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="File not found")

    category = guess_category(target)
    if category in ("image", "audio", "video"):
        return FileResponse(target)

    meta = file_info(target, safe_rel)
    if category == "text":
        content, truncated = preview_text(target)
        return JSONResponse(content={
            "meta": meta,
            "content": content,
            "truncated": truncated,
        })

    return JSONResponse(content={
        "meta": meta,
        "download_url": f"/api/clawmate/download?root={quote(root)}&path={quote(meta['path'])}",
    })


@router.get("/api/clawmate/download")
async def clawmate_download(root: str = "", path: str = ""):
    try:
        _, target, _ = safe_path(root, path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(target, filename=target.name)


@router.get("/api/clawmate/raw")
async def clawmate_raw(root: str = "", path: str = ""):
    """Serve a file inline (for browser rendering, no Content-Disposition: attachment)."""
    try:
        _, target, _ = safe_path(root, path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="File not found")

    import mimetypes
    media_type, _ = mimetypes.guess_type(str(target))
    # Explicitly set PDF media type for pdf.js compatibility
    if target.suffix.lower() == '.pdf':
        media_type = 'application/pdf'
    return FileResponse(target, media_type=media_type or "application/octet-stream")


@router.get("/api/clawmate/batch-download")
async def clawmate_batch_download(request: Request, root: str = "", path: str = "", paths: str = ""):
    from starlette.background import BackgroundTask
    import tempfile

    try:
        root_path, _, _ = safe_path(root, "")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    tmp_path = tempfile.mktemp(suffix=".zip")

    if paths:
        # Download specific files (comma-separated relative paths)
        file_list = [p.strip() for p in paths.split(",") if p.strip()]
        if not file_list:
            raise HTTPException(status_code=400, detail="No files specified")
        zip_name = f"batch-{len(file_list)}-files.zip"
        tmp_path = tempfile.mktemp(suffix=".zip")
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
            for rel_path in file_list:
                try:
                    _, target, safe_rel = safe_path(root, rel_path)
                    if not target.exists():
                        continue
                    if target.is_dir():
                        # Add directory with its contents
                        for dirpath, _, filenames in os.walk(target):
                            for filename in filenames:
                                filepath = os.path.join(dirpath, filename)
                                arcname = os.path.relpath(filepath, target.parent) if safe_rel else os.path.relpath(filepath, target)
                                # Use safe_rel as the folder prefix in the zip
                                arcname = os.path.join(safe_rel, os.path.relpath(filepath, target))
                                try:
                                    with open(filepath, "rb") as f:
                                        data = f.read()
                                    zf.writestr(arcname, data)
                                except (OSError, PermissionError):
                                    continue
                    else:
                        with open(target, "rb") as f:
                            data = f.read()
                        zf.writestr(safe_rel, data)
                except (OSError, PermissionError, FileNotFoundError, ValueError):
                    continue
        return FileResponse(
            tmp_path,
            filename=zip_name,
            media_type="application/zip",
            background=BackgroundTask(lambda: os.remove(tmp_path) if os.path.exists(tmp_path) else None),
        )

    # Original behavior: download entire directory
    try:
        _, target, safe_rel = safe_path(root, path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")

    folder_name = safe_rel.replace("/", "_") if safe_rel else root
    zip_name = f"{folder_name}.zip"
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for dirpath, _, filenames in os.walk(target):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                arcname = os.path.relpath(filepath, target)
                try:
                    with open(filepath, "rb") as f:
                        data = f.read()
                    zf.writestr(arcname, data)
                except (OSError, PermissionError):
                    continue

    return FileResponse(
        tmp_path,
        filename=zip_name,
        media_type="application/zip",
        background=BackgroundTask(lambda: os.unlink(tmp_path) if os.path.exists(tmp_path) else None),
    )


@router.post("/api/clawmate/rename")
async def clawmate_rename(request: Request):
    """Rename a file.

    Request body: {root, path, newName}
    Returns: {ok: true, newName: "xxx", newPath: "yyy/xxx"}
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    root_id = str(body.get("root", "")).strip()
    rel_path = str(body.get("path", "")).strip()
    new_name = str(body.get("newName", "")).strip()

    if not root_id or not rel_path or not new_name:
        raise HTTPException(status_code=422, detail="Missing root/path/newName")

    # Security checks
    forbidden = ["..", "/", "\\0"]
    for ch in forbidden:
        if ch in new_name:
            raise HTTPException(status_code=400, detail=f"Forbidden character in filename: {ch}")

    if len(new_name) > 255:
        raise HTTPException(status_code=400, detail="Filename exceeds 255 characters")

    try:
        _, target, safe_rel = safe_path(root_id, rel_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root or file not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="File not found")

    new_path = target.parent / new_name
    if new_path.exists():
        raise HTTPException(status_code=409, detail="A file with that name already exists")

    target.rename(new_path)

    # Compute new relative path
    new_safe_rel = str(new_path.relative_to(target.parent.parent)) if hasattr(target.parent, 'parent') else new_name
    # safe_rel is like "dir1/dir2/oldname.ext" — replace old basename
    if "/" in safe_rel:
        new_safe_rel = safe_rel.rsplit("/", 1)[0] + "/" + new_name
    else:
        new_safe_rel = new_name

    return JSONResponse(content={
        "ok": True,
        "newName": new_name,
        "newPath": new_safe_rel,
    })


@router.post("/api/clawmate/save")
async def clawmate_save(request: Request):
    """Save text content back to a file (atomic write).

    Request body: {root, path, content, validate?}
    Returns: {ok: true, size: N}
    On validation failure: 422 + {ok: false, error: "xxx_syntax_error", detail: "..."}
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    root_id = str(body.get("root", "")).strip()
    rel_path = str(body.get("path", "")).strip()
    content = body.get("content", "")
    validate = body.get("validate", True)  # default: validate enabled

    if not root_id or not rel_path:
        raise HTTPException(status_code=422, detail="Missing root/path")

    try:
        _, target, _ = safe_path(root_id, rel_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="File not found")

    # ── Format validation ──
    if validate and isinstance(content, str):
        ext = Path(rel_path).suffix.lower()
        validator = VALIDATORS.get(ext)
        if validator:
            ok, error_msg = validator(content)
            if not ok:
                return JSONResponse(
                    content={
                        "ok": False,
                        "error": f"{ext[1:]}_syntax_error",
                        "detail": error_msg,
                    },
                    status_code=422,
                )

    # Atomic write: temp file + rename
    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, target)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise HTTPException(status_code=500, detail="Failed to write file")

    return JSONResponse(content={"ok": True, "size": len(content.encode("utf-8"))})


@router.delete("/api/clawmate/delete")
async def clawmate_delete(root: str = "", path: str = ""):
    try:
        delete_file(root, path)
        return JSONResponse(content={"success": True, "message": "File deleted"})
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Cannot delete directory")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/clawmate/delete-dir")
async def clawmate_delete_dir(root: str = "", path: str = ""):
    try:
        delete_dir(root, path)
        return JSONResponse(content={"success": True, "message": "Directory deleted"})
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Directory not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid directory")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/clawmate/upload")
async def clawmate_upload(
    request: Request,
    root: str = "",
    dir: str = "",
):
    """Upload a file to the given root/directory."""
    try:
        form = await request.form()
        file_obj = form.get("file")
        if not file_obj:
            raise HTTPException(status_code=400, detail="No file provided")

        filename = file_obj.filename or "unknown"
        content = await file_obj.read()

        from service import upload_file
        dest = upload_file(root, dir, filename, content)
        return JSONResponse(content={
            "success": True,
            "message": f"File saved: {dest.name}",
            "filename": dest.name,
            "path": str(dest),
        })
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Directory not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/clawmate/onlyoffice/script-url")
async def clawmate_onlyoffice_script_url():
    """Return the ONLYOFFICE API JS URL so the frontend can load it dynamically."""
    onlyoffice_url = os.getenv("CLAWMATE_ONLYOFFICE_URL")
    if not onlyoffice_url:
        # fallback: read from config via config.load()
        try:
            onlyoffice_url = config().onlyoffice.api_js_url
        except Exception:
            onlyoffice_url = ""
    return JSONResponse(content={"url": onlyoffice_url or ""})

@router.get("/api/clawmate/onlyoffice/config", response_class=JSONResponse)
async def clawmate_onlyoffice_config(request: Request, root: str = "", path: str = "", mode: str = ""):
    secret = _get_onlyoffice_secret()
    try:
        root_path, target, safe_rel = safe_path(root, path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="File not found")

    # Load onlyoffice config from config.load()
    onlyoffice_cfg = config().onlyoffice

    # Determine mode: query param > config.json > default "edit"
    if not mode:
        mode = onlyoffice_cfg.get("mode", "edit") or "edit"

    payload = {
        "root": root,
        "path": safe_rel,
        "exp": int(time.time()) + ONLYOFFICE_TOKEN_TTL,
    }
    token = _encode_jwt(payload, secret)

    ext = target.suffix.lower().lstrip(".")
    if not ext:
        ext = "bin"

    doc_type = "word"
    if ext in {"xls", "xlsx", "csv", "ods"}:
        doc_type = "cell"
    elif ext in {"ppt", "pptx", "odp"}:
        doc_type = "slide"
    elif ext == "pdf":
        doc_type = "pdf"

    def _safe_key_part(s: str) -> str:
        try:
            decoded = unquote_to_bytes(s).decode("ascii", errors="replace")
        except Exception:
            decoded = s
        allowed = set("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-_=")
        safe = "".join(c if c in allowed else "-" for c in decoded)
        while "--" in safe:
            safe = safe.replace("--", "-")
        return safe.strip("-")

    safe_root_part = (_safe_key_part(root) + "-" + _safe_key_part(safe_rel)).rstrip("-")
    key = f"{safe_root_part}-{int(target.stat().st_mtime)}-{target.stat().st_size}"
    from service import get_public_base_url
    public_base_url = get_public_base_url(request)
    file_url = f"{public_base_url}/api/clawmate/onlyoffice/file?token={quote(token)}"

    permissions = None
    if ext == "pdf":
        permissions = {
            "edit": False,
            "download": True,
            "print": True,
            "copy": True,
            "comment": False,
            "fillForms": False,
        }

    document = {
        "fileType": ext,
        "key": key,
        "title": target.name,
        "url": file_url,
    }
    if permissions:
        document["permissions"] = permissions

    # mode: view or edit. edit only allowed for non-PDF office docs
    editor_mode = "view"
    if mode == "edit" and ext != "pdf":
        editor_mode = "edit"

    # callback_url: config > constructed from public_base_url
    cfg_callback = config().onlyoffice.callback_url or ""
    if cfg_callback:
        callback_url = f"{cfg_callback.rstrip('/')}?token={quote(token)}"
    else:
        callback_url = f"{public_base_url}/api/clawmate/onlyoffice/callback?token={quote(token)}"

    config = {
        "document": document,
        "documentType": doc_type,
        "editorConfig": {
            "mode": editor_mode,
            "lang": "zh-CN",
            "user": {"id": "clawmate", "name": "ClawMate"},
            "callbackUrl": callback_url,
        },
    }

    config_token = _encode_jwt(config, secret)
    config["token"] = config_token

    return JSONResponse(content={"config": config})


@router.get("/api/clawmate/onlyoffice/file")
async def clawmate_onlyoffice_file(token: str = ""):
    secret = _get_onlyoffice_secret()
    if not token:
        raise HTTPException(status_code=403, detail="Missing token")
    try:
        payload = _decode_jwt(token, secret)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Token expired")
    except Exception:
        raise HTTPException(status_code=403, detail="Invalid token")

    root = payload.get("root", "")
    rel_path = payload.get("path", "")
    if not root or not rel_path:
        raise HTTPException(status_code=403, detail="Invalid token")

    try:
        _, target, _ = safe_path(root, rel_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(target, filename=target.name)


@router.post("/api/clawmate/onlyoffice/callback")
async def clawmate_onlyoffice_callback(request: Request, token: str = ""):
    """ONLYOFFICE save callback. Only saves when status == 2 (document ready)."""
    secret = _get_onlyoffice_secret()
    if not token:
        return JSONResponse(content={"error": 1, "message": "Missing token"}, status_code=403)
    try:
        payload = _decode_jwt(token, secret)
    except PermissionError:
        return JSONResponse(content={"error": 1, "message": "Token expired"}, status_code=403)
    except Exception:
        return JSONResponse(content={"error": 1, "message": "Invalid token"}, status_code=403)

    root = payload.get("root", "")
    rel_path = payload.get("path", "")
    if not root or not rel_path:
        return JSONResponse(content={"error": 1, "message": "Invalid token payload"}, status_code=403)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"error": 1, "message": "Invalid JSON body"}, status_code=400)

    status = body.get("status")
    # status: 1=编辑中, 2=文档就绪可保存, 3=保存中, 4=关闭等
    # Only act when document is ready to be saved (status == 2)
    if status != 2:
        return JSONResponse(content={"error": 0})

    download_url = body.get("url")
    if not download_url:
        return JSONResponse(content={"error": 1, "message": "Missing url in callback"}, status_code=400)

    try:
        _, target, _ = safe_path(root, rel_path)
    except FileNotFoundError:
        return JSONResponse(content={"error": 1, "message": "Root not found"}, status_code=404)
    except PermissionError:
        return JSONResponse(content={"error": 1, "message": "Forbidden"}, status_code=403)
    except ValueError:
        return JSONResponse(content={"error": 1, "message": "Invalid path"}, status_code=400)

    if not target.exists() or target.is_dir():
        return JSONResponse(content={"error": 1, "message": "File not found"}, status_code=404)

    # Download the edited file and overwrite the original
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(download_url)
            if resp.status_code != 200:
                return JSONResponse(content={"error": 1, "message": f"Download failed: {resp.status_code}"}, status_code=502)
            content = resp.content
    except Exception as e:
        return JSONResponse(content={"error": 1, "message": f"Download error: {e}"}, status_code=502)

    import mimetypes
    mime_type, _ = mimetypes.guess_type(str(target))
    # Write back to original file
    try:
        with open(target, "wb") as f:
            f.write(content)
    except Exception as e:
        return JSONResponse(content={"error": 1, "message": f"Write error: {e}"}, status_code=500)

    return JSONResponse(content={"error": 0})
# ── Auth endpoints ─────────────────────────────────────────────────────────────

def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/api/clawmate/auth/login")
async def auth_login(request: Request):
    """Verify credentials, issue session, set session cookie."""
    from auth import (
        is_auth_enabled, check_ip_lockout, record_failure, clear_failures,
        create_session, get_session_from_cookie, verify_password,
        load_auth_config, get_session_ttl,
    )

    client_ip = _get_client_ip(request)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_request", "detail": "Invalid JSON"}, status_code=400)

    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))

    if not username or not password:
        return JSONResponse({"error": "invalid_request", "detail": "用户名和密码不能为空"}, status_code=400)

    # Lockout check after we know the username
    locked, remaining = check_ip_lockout(username, client_ip)
    if locked:
        return JSONResponse(
            {"error": "too_many_requests", "detail": f"登录失败次数过多，请 {remaining} 秒后重试"},
            status_code=429,
        )

    config_path = Path(os.environ.get(CONFIG_PATH_ENV, "config.json"))
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        config = {}

    if not is_auth_enabled(config):
        return JSONResponse({"error": "auth_not_configured", "detail": "认证未配置"}, status_code=503)

    ac = config.get("auth") or {}
    expected_user = ac.get("username", "admin")
    stored_hash = ac.get("password_hash", "")

    if username != expected_user or not verify_password(password, stored_hash):
        record_failure(username, client_ip)
        return JSONResponse({"error": "invalid_credentials", "detail": "用户名或密码错误"}, status_code=401)

    # Success
    clear_failures(username, client_ip)
    ttl = get_session_ttl(config)
    sid, _ = await create_session(username, ttl)

    response = JSONResponse({"ok": True, "username": username})
    response.set_cookie(
        key="clawmate_session",
        value=sid,
        max_age=ttl,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/api/clawmate/auth/logout")
async def auth_logout(request: Request):
    """Clear session and cookie."""
    from auth import get_session, delete_session, get_session_from_cookie

    sid = get_session_from_cookie(request)
    if sid:
        await delete_session(sid)
    response = JSONResponse({"ok": True})
    response.delete_cookie(key="clawmate_session", path="/")
    return response


@router.get("/api/clawmate/auth/status")
async def auth_status(request: Request):
    """Return current login state."""
    from auth import get_session, get_session_from_cookie

    sid = get_session_from_cookie(request)
    if not sid:
        return JSONResponse({"logged_in": False})
    session = await get_session(sid)
    if not session:
        return JSONResponse({"logged_in": False})
    return JSONResponse({"logged_in": True, "username": session.get("user", "")})


@router.post("/api/clawmate/auth/change-password")
async def auth_change_password(request: Request):
    """Change password for logged-in user."""
    from auth import get_session, delete_session, get_session_from_cookie
    from auth import verify_password, hash_password, load_auth_config

    sid = get_session_from_cookie(request)
    if not sid:
        return JSONResponse({"error": "unauthorized", "detail": "请先登录"}, status_code=401)
    session = await get_session(sid)
    if not session:
        return JSONResponse({"error": "unauthorized", "detail": "会话已过期，请重新登录"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_request"}, status_code=400)

    old_password = str(body.get("old_password", ""))
    new_password = str(body.get("new_password", ""))

    if not new_password or len(new_password) < 4:
        return JSONResponse({"error": "invalid_request", "detail": "新密码至少4个字符"}, status_code=400)

    config_path = Path(os.environ.get(CONFIG_PATH_ENV, "config.json"))
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return JSONResponse({"error": "server_error", "detail": "配置文件读取失败"}, status_code=500)

    ac = config.get("auth") or {}
    stored_hash = ac.get("password_hash", "")

    # Verify old password if hash exists
    if stored_hash and old_password and not verify_password(old_password, stored_hash):
        return JSONResponse({"error": "invalid_credentials", "detail": "原密码错误"}, status_code=401)

    new_hash = hash_password(new_password)
    if "auth" not in config:
        config["auth"] = {}
    config["auth"]["username"] = ac.get("username", "admin")
    config["auth"]["password_hash"] = new_hash
    config["auth"]["session_ttl_minutes"] = ac.get("session_ttl_minutes", 480)

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    return JSONResponse({"ok": True, "detail": "密码已更新"})


# ── Subtitle extraction ────────────────────────────────────────────────────────

@router.post("/api/clawmate/subtitle/extract")
async def clawmate_subtitle_extract(request: Request):
    """
    从音频/视频文件提取语音并生成 SRT 字幕。
    返回 SSE 事件流，逐段推送进度。
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    root_id = str(body.get("root", "")).strip()
    file_rel_path = str(body.get("path", "")).strip()
    model_size = str(body.get("model", "small")).strip()
    language = body.get("language")  # None = auto

    if not root_id or not file_rel_path:
        raise HTTPException(status_code=422, detail="Missing root or path")

    if model_size not in ("tiny", "small", "medium"):
        model_size = "small"

    # 安全路径解析
    try:
        _, target, _ = safe_path(root_id, file_rel_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="File not found")

    # 只处理音视频格式
    audio_exts = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".wma"}
    video_exts = {".mp4", ".webm", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".m4v"}
    allowed = audio_exts | video_exts
    if target.suffix.lower() not in allowed:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {target.suffix}. Supported: {', '.join(sorted(allowed))}",
        )

    # SRT 输出到同目录同名 .srt
    srt_path = target.with_suffix(".srt")

    # SSE 事件流
    async def event_generator():
        import asyncio
        queue: asyncio.Queue = asyncio.Queue()

        async def progress(phase: str, pct: int, detail: str = ""):
            payload = json.dumps({"phase": phase, "progress": pct, "detail": detail}, ensure_ascii=False)
            await queue.put(f"data: {payload}\n\n")

        try:
            from subtitle import extract_subtitle
            result = await extract_subtitle(
                target, srt_path,
                model_size=model_size,
                language=language,
                progress_callback=progress,
            )
            await queue.put(f"data: {json.dumps({'phase': 'done', **result}, ensure_ascii=False)}\n\n")
        except Exception as e:
            await queue.put(f"data: {json.dumps({'phase': 'error', 'detail': str(e)}, ensure_ascii=False)}\n\n")

        await queue.put(None)  # sentinel: extraction complete
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/api/clawmate/subtitle/status")
async def clawmate_subtitle_status(root: str = "", path: str = ""):
    """查询指定媒体文件是否已有同目录同名 .srt 字幕。"""
    if not root or not path:
        raise HTTPException(status_code=422, detail="Missing root or path")

    try:
        _, target, _ = safe_path(root, path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="File not found")

    srt_path = target.with_suffix(".srt")
    exists = srt_path.exists()
    return JSONResponse(content={
        "has_subtitle": exists,
        "srt_path": str(srt_path) if exists else None,
        "srt_size": srt_path.stat().st_size if exists else None,
    })


@router.post("/api/clawmate/subtitle/correct")
async def clawmate_subtitle_correct(request: Request):
    """通过 OpenClaw agent 纠错 SRT 字幕。

    利用 agent 的 LLM 能力修正转录错误，时间戳不变。
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    root_id = str(body.get("root", "")).strip()
    media_path = str(body.get("media_path", "")).strip()
    srt_path = str(body.get("srt_path", "")).strip()
    if not root_id or not srt_path:
        raise HTTPException(status_code=422, detail="Missing root or srt_path")
    if not media_path:
        raise HTTPException(status_code=422, detail="Missing media_path")

    # 解析 SRT 路径（相对于 root）
    # srt_path 可以是绝对路径或相对于 root 的相对路径
    try:
        root_path, target, safe_rel = safe_path(root_id, srt_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="SRT file not found")

    # 读取 SRT 内容作为 context
    try:
        srt_content = target.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot read SRT: {e}")

    if not srt_content.strip():
        raise HTTPException(status_code=400, detail="SRT file is empty")

    # file = 媒体文件路径（与前端预览上下文一致）
    # note = AI 操作指令（含 SRT 文件路径，供 agent 读取）
    project = media_path.split("/")[0] if "/" in media_path else media_path

    # 使用 store.create_items 写入反馈
    # 避免重复纠错：先检查已有 pending/in_progress
    existing, _ = store_list_items(root_id, project, status="", file=media_path)
    for item in existing:
        if item.get("file") == media_path and item.get("status") in ("pending", "in_progress"):
            raise HTTPException(status_code=409, detail="已有相同的纠错任务在处理中")

    note_text = (
        "【AI 字幕纠错任务】\n"
        "请修正以下 SRT 字幕文件的文字内容，保持所有时间戳不变。\n"
        "SRT 文件路径（写回目标）：" + safe_rel + "\n"
        "修正规则：\n"
        "1. 仅修正文字转录错误、添加标点符号\n"
        "2. 不改变任何时间戳（'--> ' 行保持原样）\n"
        "3. 不合并或拆分字幕段\n"
        "4. 不改变原始段落编号\n"
        "5. 输出必须是合法 SRT 格式\n"
        "6. 用修正后的完整 SRT 内容替换写回源文件"
    )
    new_items = store_create_items(
        root_id, project, media_path,
        [{"text": srt_content.strip(), "note": note_text}],
    )

    if not new_items:
        raise HTTPException(status_code=409, detail="纠错任务已存在")

    item_id = new_items[0]["id"]

    # 立即触发 agent
    _wake_agent_for_root(root_id)

    return JSONResponse(content={
        "ok": True,
        "id": item_id,
        "feedbackFile": str(resolve_root(root_id) / project / "feedback.json"),
        "message": "纠错任务已创建，agent 正在处理中",
    })


# ── Preview token verification (for standalone preview.html) ────────────────────


@router.get("/api/clawmate/preview/verify")
async def verify_preview(root: str = "", path: str = "", token: str = ""):
    """Verify a preview token and return file content if valid. Token TTL = 1 hour."""
    if not token:
        raise HTTPException(status_code=401, detail="缺少预览令牌")
    if not verify_preview_token(root, path, token):
        raise HTTPException(status_code=403, detail="预览链接已过期，请重新生成")
    # Token valid — serve content via existing preview logic (auth required)
    return await clawmate_preview(root=root, path=path)
