from __future__ import annotations

from fastapi import APIRouter, Query, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from urllib.parse import quote, unquote_to_bytes
import base64
import hashlib
import hmac
import json
import os
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
)


router = APIRouter()

ONLYOFFICE_SECRET_ENV = "CLAWMATE_ONLYOFFICE_JWT_SECRET"
PUBLIC_BASE_URL_ENV = "CLAWMATE_PUBLIC_BASE_URL"
CONFIG_PATH_ENV = "CLAWMATE_CONFIG"


@router.get("/api/clawmate/config", response_class=JSONResponse)
async def public_config():
    """返回前端安全的公开配置（不含 JWT secret 等敏感字段）。"""
    from pathlib import Path
    config_path = Path(os.environ.get(CONFIG_PATH_ENV, "config.json"))
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    return {
        "roots": data.get("roots", []),
        "defaultRootId": data.get("defaultRootId", ""),
    }
ONLYOFFICE_TOKEN_TTL = 3600


def _get_onlyoffice_secret() -> str:
    secret = os.getenv(ONLYOFFICE_SECRET_ENV)
    if not secret:
        raise HTTPException(status_code=500, detail=f"{ONLYOFFICE_SECRET_ENV} is not set")
    return secret


def _get_public_base_url(request: Request) -> str:
    env_base_url = os.getenv(PUBLIC_BASE_URL_ENV)
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


@router.get("/api/clawmate/preview")
async def clawmate_preview(root: str = "", path: str = ""):
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

    Request body: {root, path, content}
    Returns: {ok: true, size: N}
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    root_id = str(body.get("root", "")).strip()
    rel_path = str(body.get("path", "")).strip()
    content = body.get("content", "")

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
        # fallback: read from config.json
        try:
            import json
            from pathlib import Path
            config_path = Path(os.environ.get("CLAWMATE_CONFIG", str(Path(__file__).parent / "config.json")))
            with open(config_path) as f:
                cfg = json.load(f)
            onlyoffice_url = (cfg.get("onlyoffice") or {}).get("api_js_url", "")
        except Exception:
            onlyoffice_url = ""
    return JSONResponse(content={"url": onlyoffice_url or ""})


@router.get("/api/clawmate/feedback/list", response_class=JSONResponse)
async def clawmate_feedback_list(
    root: str = "",
    project: str = "",
    status: str = "",
    file: str = "",
    since: str = "today",
):
    """列出 FEEDBACK.md 中的条目，支持 status/file/since 过滤.

    Args:
        status: 单值过滤，如 wait/doing/done/failed（不传=全部）
        file:   文件名模糊匹配（不传=全部）
        since:  today=当天 00:00 CST，或 YYYY-MM-DD 格式日期（不传=today）
    """
    if not root or not project:
        raise HTTPException(status_code=422, detail="Missing root or project")
    try:
        fb_path = _get_feedback_path(root, project)
    except (PermissionError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    content = _read_feedback_md(fb_path)
    items = _parse_items(content)

    # status filter
    if status:
        items = [i for i in items if i.get("status") == status]

    # file filter: fuzzy match
    if file:
        items = [i for i in items if file in i.get("file", "")]

    # since filter
    if since == "today":
        cutoff = datetime.now(CST).replace(hour=0, minute=0, second=0, microsecond=0)
    elif since:
        try:
            cutoff = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=CST)
        except ValueError:
            cutoff = None
    else:
        cutoff = None

    if cutoff:
        def _parse_updated(ts: str):
            try:
                return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CST)
            except Exception:
                return datetime.min.replace(tzinfo=CST)
        items = [i for i in items if _parse_updated(i.get("updated", "")) >= cutoff]

    # Return structured data (no type field)
    result = []
    for item in items:
        entry = {
            "id": item.get("id", ""),
            "status": item.get("status", "pending"),
            "user_note": item.get("note", ""),
            "file": item.get("file", ""),
            "content": item.get("selection", ""),
            "updated": item.get("updated", ""),
            "result": item.get("result", ""),
        }
        if item.get("position"):
            entry["location"] = item["position"]
        result.append(entry)

    return JSONResponse(content={
        "feedbackPath": str(fb_path),
        "total": len(result),
        "items": result,
    })


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

    # Load onlyoffice config from config.json
    config_path = Path(os.environ.get(CONFIG_PATH_ENV, "config.json"))
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cfg_data = {}
    onlyoffice_cfg = cfg_data.get("onlyoffice", {})

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
    public_base_url = _get_public_base_url(request)
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

    # callback_url: config.json > constructed from public_base_url
    cfg_callback = onlyoffice_cfg.get("callback_url", "") or ""
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


# ── ClawMate feedback (FEEDBACK.md 单列表 + 内联状态) ──────────────

CST = timezone(timedelta(hours=8))

STATUS_LABELS = {"pending": "待处理", "in_progress": "处理中", "done": "已完成", "failed": "失败", "deleted": "已删除"}
def _get_feedback_path(root_id: str, project: str) -> Path:
    root_dir = resolve_root(root_id)
    project_dir = root_dir / project
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir / "FEEDBACK.md"


def _read_feedback_md(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _project_abbr(project: str) -> str:
    """Generate 2-char project abbreviation."""
    import re
    try:
        config_path = Path(os.environ.get("CLAWMATE_CONFIG", "config.json"))
        data = json.loads(config_path.read_text())
        custom = (data.get("projects") or {}).get(project, {}).get("abbr", "")
        if len(custom) >= 2:
            return custom[:2].upper()
    except Exception:
        pass
    parts = re.split(r"[-_]", project)
    if len(parts) >= 2:
        return "".join(p[0].upper() for p in parts[:2])
    camel = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|$)", project)
    if len(camel) >= 2:
        return "".join(c[0].upper() for c in camel[:2])
    n = len(project)
    return (project[0] + project[n // 2]).upper()


def _next_id(content: str, project: str) -> str:
    import re
    abbr = _project_abbr(project)
    pattern = rf"#FD-{abbr}-(\d+)"
    ids = re.findall(pattern, content)
    n = max(int(x) for x in ids) + 1 if ids else 1
    return f"FD-{abbr}-{n:03d}"


def _parse_items(content: str) -> list:
    """Parse FEEDBACK.md (new file-centric flat format) into structured item list.

    New format (flat, list-bullet-free, file-first):

        文件: clawmate/test/短篇小说-黄昏图书馆.md
        编号：#FD-CM-001
        状态：已完成
        用户备注：扩展这一段，引入她已经过世的媳妇
        选区内容: ''内容...'
        选中位置: L2-4              ← 可选字段，无选中位置时不出现
        更新: 2026-05-30 19:57:21
    """
    if not content.strip():
        return []
    items = []
    current = None
    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped:
            # empty line = item separator
            if current and current.get("id"):
                items.append(current)
                current = None
            continue
        # skip headers
        if stripped.startswith("#") or stripped.startswith("##"):
            continue
        if stripped.startswith("- 最后活跃") or stripped.startswith("- 会话"):
            continue
        if stripped == "## FEEDBACK列表" or "_暂无反馈_" in stripped:
            continue

        # Normalize Chinese colon to ASCII
        normalized = stripped.replace("\uff1a", ": ", 1)

        # Detect item start: "文件: filename"
        if normalized.startswith("文件:") or stripped.startswith("文件:"):
            if current and current.get("id"):
                items.append(current)
            _, val = (normalized.split(": ", 1) if ": " in normalized else ["", ""])
            current = {
                "file": val.strip(),
                "id": "", "note": "", "status": "pending", "selection": "",
                "position": "", "updated": "", "result": "",
            }
            continue

        if current is None:
            continue

        if ": " in normalized:
            key, val = normalized.split(": ", 1)
            v = val.strip()
            if key == "编号":
                current["id"] = v.lstrip("#")
            elif key == "状态":
                rev = {label: k for k, label in STATUS_LABELS.items()}
                current["status"] = rev.get(v, "pending")
            elif key == "用户备注":
                # Decode \\n → newline, \\\\ → \\
                current["note"] = v.replace("\\n", "\n").replace("\\\\", "\\")
            elif key == "选区内容":
                if len(v) >= 2 and ((v.startswith('"') and v.endswith('"')) or                                     (v.startswith("'") and v.endswith("'"))):
                    v = v[1:-1]
                # Decode \\n → newline, \\\\ → \\ (stored escaped in FEEDBACK.md)
                v = v.replace("\\n", "\n").replace("\\\\", "\\")
                current["selection"] = v
            elif key == "选中位置":
                current["position"] = v
            elif key == "更新":
                current["updated"] = v
            elif key == "处理结果":
                current["result"] = v

    # finalize last item
    if current and current.get("id"):
        items.append(current)
    return items


def _format_item(item: dict) -> list:
    """Format a single feedback item as file-first flat markdown.

    - 选区内容/用户备注 完整保留（换行转 \\n 编码，反斜杠转 \\\\）
    - 内容 >200 chars 截断为前 197 + …
    - 条目间空行分隔
    """
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    lines = []
    if item.get("file"):
        lines.append(f"文件: {item['file']}")
    lines.append(f"编号：# {item['id']}".replace("# ", "#"))
    status_label = STATUS_LABELS.get(item.get("status", "pending"), "待处理")
    lines.append(f"状态：{status_label}")
    # 用户备注：换行 → \\n，\\ → \\\\，软上限 200
    note_raw = item.get('note', '')
    note_escaped = note_raw.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "")
    note_display = (note_escaped[:197] + "...") if len(note_escaped) > 200 else note_escaped
    lines.append(f"用户备注：{note_display}")
    if item.get("position"):
        lines.append(f"选中位置: {item['position']}")
    if item.get("selection"):
        sel = item["selection"]
        # 保留完整内容：换行 → \\n, 反斜杠 → \\\\
        escaped = sel.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "")
        # 过长的内容截断（200 char 软上限，避免 FEEDBACK.md 过大）
        MAX_SEL = 200
        display = (escaped[:MAX_SEL - 3] + "...") if len(escaped) > MAX_SEL else escaped
        lines.append(f'选区内容: "{display}"')
    lines.append(f"更新: {item.get('updated', now)}")
    if item.get("result"):
        lines.append(f"处理结果: {item['result']}")
    lines.append("")
    return lines


def _build_feedback_md(session_key: str, items: list) -> str:
    """Build complete FEEDBACK.md flat list."""
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M")
    lines = ["# 反馈清单", ""]
    lines.append("## 会话")
    # Preserve existing session when new one is empty
    session_display = session_key or "(未关联)"
    lines.append(f"- 最后活跃会话: `{session_display}`")
    lines.append(f"- 最后活跃时间: {now}")
    lines.append("")
    lines.append("## FEEDBACK列表")
    for item in items:
        if item.get("status") == "deleted":
            continue  # skip deleted items
        lines.extend(_format_item(item))
    if not items:
        lines.append("_暂无反馈_")
    return "\n".join(lines)


@router.post("/api/clawmate/feedback", response_class=JSONResponse)
async def clawmate_feedback(request: Request):
    """统一反馈入口 — FEEDBACK.md 单列表 + 内联状态."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    root_id = str(body.get("root", "")).strip()
    project = str(body.get("project", "")).strip()
    file_path = str(body.get("path", "")).strip()
    selections = body.get("selections", [])
    preview_url = str(body.get("previewUrl", "")).strip()
    session_key = str(body.get("sessionKey", "")).strip()

    if not root_id or not project or not file_path:
        raise HTTPException(status_code=422, detail="Missing root/project/path")
    if not selections or not isinstance(selections, list):
        raise HTTPException(status_code=422, detail="Missing selections")

    try:
        fb_path = _get_feedback_path(root_id, project)
    except (PermissionError, FileNotFoundError) as e:
        raise HTTPException(status_code=403, detail=str(e))

    if not preview_url:
        public_base = _get_public_base_url(request)
        preview_url = f"{public_base}/clawmate/preview.html?root={quote(root_id)}&file={quote(file_path)}"

    existing = _read_feedback_md(fb_path)
    existing_items = _parse_items(existing)
    ts = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

    for sel in selections:
        text = str(sel.get("text", "")).strip()
        if not text:
            continue
        note = str(sel.get("note", "")).strip()
        # position 语义灵活：文本=行号，音频=时间，PDF=页码
        # 优先直接取 position，fallback 到 startLine/endLine 兼容旧前端
        position = str(sel.get("position", "") or "").strip()
        if not position:
            start_line = sel.get("startLine")
            end_line = sel.get("endLine")
            if start_line and end_line:
                position = f"L{start_line}-{end_line}"

        nid = _next_id(existing, project)
        existing_items.append({
            "id": nid,
            "note": note or text[:80],
            "status": "pending",
            "file": file_path,
            "selection": text,
            "position": position,
            "updated": ts,
        })
        existing += f"\n#FD-{_project_abbr(project)}-{nid.split('-')[-1]}"

    new_content = _build_feedback_md(session_key, existing_items)
    fb_path.write_text(new_content, encoding="utf-8")

    ids = [i["id"] for i in existing_items[-len(selections):] if i["id"]]
    new_id = ids[0] if ids else ""

    # Wake agent immediately (non-blocking)
    import subprocess, shutil
    openclaw_bin = shutil.which("openclaw") or "openclaw"
    try:
        subprocess.run(
            [openclaw_bin, "system", "event", "--text", f"ClawMate 新反馈: {new_id}", "--mode", "now"],
            timeout=10, capture_output=True
        )
    except Exception:
        pass  # 静默失败，不影响 feedback 创建
    lines = ["## 📋 ClawMate 反馈"]
    lines.append(f"**项目**: `{project}`")
    lines.append(f"**文件**: `{file_path}` | **ID**: {', '.join(ids)}")
    lines.append(f"**预览**: {preview_url}")
    for sel in selections:
        t = str(sel.get("text", "")).strip()
        n = str(sel.get("note", "")).strip()
        if t: lines.append(f"> {t[:300]}")
        if n: lines.append(f"📝 {n}")

    return JSONResponse(content={
        "ok": True, "ids": ids,
        "feedbackPath": str(fb_path),
        "feedbackText": "\n".join(lines),
        "previewUrl": preview_url,
    })


@router.get("/api/clawmate/feedback/status", response_class=JSONResponse)
async def clawmate_feedback_status(root: str = "", project: str = ""):
    """查询 FEEDBACK.md 状态."""
    if not root or not project:
        raise HTTPException(status_code=422, detail="Missing root or project")
    try:
        fb_path = _get_feedback_path(root, project)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Root not allowed")

    content = _read_feedback_md(fb_path)
    items = _parse_items(content)

    counts = {"pending": 0, "in_progress": 0, "done": 0, "failed": 0}
    for item in items:
        s = item.get("status", "pending")
        if s in counts:
            counts[s] += 1

    session_info = []
    for line in content.split("\n"):
        if line.strip().startswith("- 最后活跃"):
            session_info.append(line.strip())

    return JSONResponse(content={
        "feedbackPath": str(fb_path),
        "exists": fb_path.exists(),
        "counts": counts,
        "items": [{"id": i["id"], "note": i["note"], "status": i["status"], "file": i["file"], "result": i.get("result", "")} for i in items],
        "sessionInfo": session_info,
    })


@router.post("/api/clawmate/feedback/update", response_class=JSONResponse)
async def clawmate_feedback_update(request: Request):
    """按 ID 更新反馈项状态."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    root_id = str(body.get("root", "")).strip()
    project = str(body.get("project", "")).strip()
    feedback_id = str(body.get("id", "")).strip()
    new_status = str(body.get("status", "")).strip()
    result_text = str(body.get("result", "")).strip()

    if not root_id or not project or not feedback_id:
        raise HTTPException(status_code=422, detail="Missing root/project/id")
    if new_status not in ("pending", "in_progress", "done", "failed", "deleted"):
        raise HTTPException(status_code=422, detail="status must be pending|in_progress|done|failed|deleted")
    # Require result summary when marking as done/failed
    if new_status in ("done", "failed") and not result_text:
        raise HTTPException(status_code=422, detail="Missing result summary (required for done/failed)")

    try:
        fb_path = _get_feedback_path(root_id, project)
    except (PermissionError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="FEEDBACK.md not found")

    content = _read_feedback_md(fb_path)
    items = _parse_items(content)

    updated = False
    for item in items:
        if item["id"] == feedback_id:
            item["status"] = new_status
            item["updated"] = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
            if result_text:
                item["result"] = result_text
            updated = True
            break

    if not updated:
        raise HTTPException(status_code=404, detail=f"Item {feedback_id} not found")

    # Rebuild: extract session block, rebuild list
    session_key = ""
    for line in content.split("\n"):
        if line.startswith("- 最后活跃会话: "):
            session_key = line.split("`")[1] if "`" in line else ""
            break

    new_content = _build_feedback_md(session_key, items)
    fb_path.write_text(new_content, encoding="utf-8")

    return JSONResponse(content={"ok": True, "id": feedback_id, "newStatus": new_status})