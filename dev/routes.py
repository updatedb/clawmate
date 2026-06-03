from __future__ import annotations

from fastapi import APIRouter, Query, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
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
    since: str = "",
):
    """列出 feedback.json 中的条目，支持 status/file/since 过滤.

    两种模式:
    - project 指定: 单项目查询 (root=webprojects&project=clawmate)
    - project 省略: 自动扫描所有 root (root=x,y) 下的项目，聚合结果

    Args:
        root:    逗号分隔的 root_id，如 root=writer,weixin（必填）
        project: 项目名（可选，省略时扫描该 root 下所有项目）
        status:  单值过滤，如 pending/in_progress/done
        file:    文件名模糊匹配
        since:   today=当天 00:00 CST，或 YYYY-MM-DD 格式
    """
    if not root:
        raise HTTPException(status_code=422, detail="Missing root")

    root_ids = [r.strip() for r in root.split(",") if r.strip()]

    if project:
        # 单项目模式 — 传统行为
        results = []
        total_pending = 0
        for rid in root_ids:
            try:
                fb_path = _get_feedback_path(rid, project)
            except (PermissionError, FileNotFoundError) as e:
                continue  # skip missing projects in multi-root mode

            items = _filter_items(fb_path, status, file, since)
            total_pending += sum(1 for i in items if i.get("status") == "pending")
            results.append({
                "root": rid,
                "project": project,
                "total": len(items),
                "pending": sum(1 for i in items if i.get("status") == "pending"),
                "items": items,
            })
        # flatten if single root
        if len(results) == 1:
            return JSONResponse(content={
                "total_pending": total_pending,
                "total": results[0]["total"],
                "items": results[0]["items"],
            })
        return JSONResponse(content={
            "total_pending": total_pending,
            "results": results,
        })

    # 自动扫描模式 — 遍历所有 project
    results = []
    total_pending = 0
    for root_id in root_ids:
        root_dir = resolve_root(root_id)
        for entry in sorted(root_dir.iterdir()):
            if not entry.is_dir():
                continue
            proj = entry.name
            fb_path = entry / "feedback.json"
            if not fb_path.exists():
                continue
            items = _filter_items(fb_path, status, file, since)
            pending = sum(1 for i in items if i.get("status") == "pending")
            if items:
                results.append({
                    "root": root_id,
                    "project": proj,
                    "pending_count": pending,
                    "items": items,
                })
                total_pending += pending

    return JSONResponse(content={
        "total_pending": total_pending,
        "results": results,
    })


def _filter_items(fb_path: Path, status: str, file: str, since: str) -> list:
    """从 feedback.json 读取条目并过滤，返回统一格式的 dict 列表"""
    data = _read_feedback_json(fb_path)
    items = _parse_items(data)

    if status:
        items = [i for i in items if i.get("status") == status]

    if file:
        items = [i for i in items if file in i.get("file", "")]

    if since:
        if since == "today":
            cutoff = datetime.now(CST).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            try:
                cutoff = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=CST)
            except ValueError:
                cutoff = None
        if cutoff:
            def _parse_updated(ts: str):
                try:
                    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CST)
                except Exception:
                    return datetime.min.replace(tzinfo=CST)
            items = [i for i in items if _parse_updated(i.get("updated", "")) >= cutoff]

    result = []
    for item in items:
        entry = {
            "id": item.get("id", ""),
            "status": item.get("status", "pending"),
            "user_note": item.get("note", ""),
            "file": item.get("file", ""),
            "content": item.get("content", "") or item.get("selection", ""),
            "updated": item.get("updated", ""),
            "result": item.get("result", ""),
        }
        if item.get("position"):
            entry["location"] = item["position"]
        result.append(entry)
    return result


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


# ── ClawMate feedback (feedback.json 单列表 + 内联状态) ──────────────

CST = timezone(timedelta(hours=8))

STATUS_LABELS = {"pending": "待处理", "in_progress": "处理中", "done": "已完成", "failed": "失败", "deleted": "已删除"}
def _get_feedback_path(root_id: str, project: str) -> Path:
    root_dir = resolve_root(root_id)
    project_dir = root_dir / project
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir / "feedback.json"


def _read_feedback_json(path: Path) -> dict:
    if not path.exists():
        return {"items": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {"items": []}


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


# _next_id removed — ID generation now uses last_id from feedback.json + 4-digit zero-padding


def _parse_items(raw):
    if isinstance(raw, dict):
        return raw.get("items", [])
    return []



def _build_feedback_json(root: str, project: str, items: list) -> str:
    ts = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    # Extract max ID number from items as last_id
    max_id = 0
    for item in items:
        m = re.search(r'FD-\w+-(\d+)', item.get("id", ""))
        if m:
            max_id = max(max_id, int(m.group(1)))
    data = {
        "root": root,
        "project": project,
        "updated": ts,
        "last_id": max_id,
        "items": items,
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


@router.post("/api/clawmate/feedback", response_class=JSONResponse)
async def clawmate_feedback(request: Request):
    """统一反馈入口 — feedback.json 单列表 + 内联状态."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    root_id = str(body.get("root", "")).strip()
    project = str(body.get("project", "")).strip()
    file_path = str(body.get("path", "")).strip()
    selections = body.get("selections", [])
    preview_url = str(body.get("previewUrl", "")).strip()

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

    existing_data = _read_feedback_json(fb_path)
    existing_items = _parse_items(existing_data)
    last_id = existing_data.get("last_id", 0) if isinstance(existing_data, dict) else 0
    ts = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

    # Deduplication: build set of (content, file) pairs already in existing_items
    existing_keys = {(item.get("content", ""), item.get("file", "")) for item in existing_items}

    new_items = []
    for idx, sel in enumerate(selections):
        text = str(sel.get("text", "")).strip()
        if not text:
            continue
        note = str(sel.get("note", "")).strip()
        # Deduplication check
        if (text, file_path) in existing_keys:
            continue
        # position 语义灵活：文本=行号，音频=时间，PDF=页码
        # 优先直接取 position，fallback 到 startLine/endLine 兼容旧前端
        position = str(sel.get("position", "") or "").strip()
        if not position:
            start_line = sel.get("startLine")
            end_line = sel.get("endLine")
            if start_line and end_line:
                position = f"L{start_line}-{end_line}"

        new_id_num = last_id + idx + 1
        item_id = f"FD-{_project_abbr(project)}-{new_id_num:04d}"
        new_items.append({
            "id": item_id,
            "status": "pending",
            "file": file_path,
            "note": note or text[:80],
            "content": text,
            "position": position,
            "updated": ts,
            "result": "",
        })
        existing_keys.add((text, file_path))

    existing_items.extend(new_items)

    new_content = _build_feedback_json(root_id, project, existing_items)
    fb_path.write_text(new_content, encoding="utf-8")

    ids = [i["id"] for i in new_items if i["id"]]

    # Wake agent via cron run (resolve name → UUID then trigger)
    import subprocess, shutil
    openclaw_bin = shutil.which("openclaw") or "openclaw"
    config_path = Path(os.environ.get("CLAWMATE_CONFIG", str(Path(__file__).parent / "config.json")))
    cron_name = "clawmate-feedback-inbox-check"  # default fallback
    try:
        with open(config_path) as f:
            cfg = json.load(f)
        for r in cfg.get("roots", []):
            if r.get("id") == root_id:
                aid = r.get("agent_id", "work")
                cron_name = f"clawmate-feedback-inbox-{aid}"
                break
    except Exception:
        pass
    try:
        # Resolve cron name to UUID (cron run requires UUID, not name)
        result = subprocess.run(
            [openclaw_bin, "cron", "list"],
            timeout=10, capture_output=True, text=True
        )
        cron_id = None
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if cron_name in line:
                    cron_id = line.split()[0] if line.strip() else None
                    break
        if cron_id:
            subprocess.run(
                [openclaw_bin, "cron", "run", cron_id],
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
        "feedbackFile": str(fb_path),
        "feedbackText": "\n".join(lines),
        "previewUrl": preview_url,
    })


@router.get("/api/clawmate/feedback/status", response_class=JSONResponse)
async def clawmate_feedback_status(root: str = "", project: str = ""):
    """查询 feedback.json 状态."""
    if not root or not project:
        raise HTTPException(status_code=422, detail="Missing root or project")
    try:
        fb_path = _get_feedback_path(root, project)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Root not allowed")

    content = _read_feedback_json(fb_path)
    items = _parse_items(content)

    counts = {"pending": 0, "in_progress": 0, "done": 0, "failed": 0}
    for item in items:
        s = item.get("status", "pending")
        if s in counts:
            counts[s] += 1

    return JSONResponse(content={
        "feedbackFile": str(fb_path),
        "exists": fb_path.exists(),
        "counts": counts,
        "items": [{"id": i["id"], "note": i["note"], "status": i["status"], "file": i["file"], "result": i.get("result", "")} for i in items],
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
        raise HTTPException(status_code=404, detail="feedback.json not found")

    content = _read_feedback_json(fb_path)
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

    new_content = _build_feedback_json(root_id, project, items)
    fb_path.write_text(new_content, encoding="utf-8")

    return JSONResponse(content={"ok": True, "id": feedback_id, "newStatus": new_status})


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
    locked, remaining = check_ip_lockout(client_ip)
    if locked:
        return JSONResponse(
            {"error": "too_many_requests", "detail": f"登录失败次数过多，请 {remaining} 秒后重试"},
            status_code=429,
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_request", "detail": "Invalid JSON"}, status_code=400)

    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))

    if not username or not password:
        return JSONResponse({"error": "invalid_request", "detail": "用户名和密码不能为空"}, status_code=400)

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
        record_failure(client_ip)
        return JSONResponse({"error": "invalid_credentials", "detail": "用户名或密码错误"}, status_code=401)

    # Success
    clear_failures(client_ip)
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
