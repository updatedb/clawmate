"""
搜索 API 路由 — 文件名搜索、链接生成、内容搜索。

端点:
    GET /api/clawmate/search         文件名搜索
    GET /api/clawmate/link           搜索 + 预览链接生成
    GET /api/clawmate/search/content 内容搜索（Phase 1）
"""
from __future__ import annotations

from fastapi import APIRouter, Query, HTTPException, Request
from fastapi.responses import JSONResponse
from urllib.parse import quote
from pathlib import Path

from search_service import search_media, search_content
from service import get_public_base_url
from config import load as load_config
import logging

_logger = logging.getLogger("clawmate.search_routes")

router = APIRouter()


@router.get("/api/clawmate/search", response_class=JSONResponse)
async def clawmate_search(
    q: str,
    root: str = "",
    dir: str = "",
    recursive: bool = True,
    limit: int = Query(200, ge=1, le=500),
    max_depth: int = Query(8, ge=1, le=20),
    timeout: float = Query(10.0, ge=1.0, le=30.0),
):
    from config import load as _load_config
    _cfg = _load_config()
    try:
        return JSONResponse(content=search_media(
            q, root_id=root, rel_dir=dir, recursive=recursive,
            limit=limit, max_depth=max_depth, timeout=timeout,
            exclude_dir=_cfg.search.content.exclude_dir,
        ))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Directory not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except OSError as e:
        _logger.error("search_media OSError for q=%s root=%s dir=%s: %s", q, root, dir, e)
        raise HTTPException(status_code=500, detail="Error reading directory")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")


@router.get("/api/clawmate/link", response_class=JSONResponse)
async def clawmate_link(
    q: str,
    root: str = "",
    ext: str = "",
    limit: int = Query(50, ge=1, le=200),
    request: Request = None,
):
    """一站式搜索并生成预览链接。

    参数：
        q:     搜索关键词（必填）
        root:  root ID（必填）
        ext:   文件扩展名过滤，多个用逗号分隔，如 "md,py"（可选）
        limit: 返回数量上限（默认 50）

    返回每个结果的 preview_url，可直接生成 Markdown 可点击链接。
    """
    from config import load as _load_config
    _cfg = _load_config()
    try:
        results = search_media(q, root_id=root, limit=limit,
                                exclude_dir=_cfg.search.content.exclude_dir)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Directory not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except OSError as e:
        _logger.error("search_media(link) OSError for q=%s root=%s: %s", q, root, e)
        raise HTTPException(status_code=500, detail="Error reading directory")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    base_url = get_public_base_url(request).rstrip("/")

    # Extension filter
    if ext:
        exts = set(e.strip().lstrip(".").lower() for e in ext.split(",") if e.strip())
    else:
        exts = None

    items = []
    for r in results.get("results", []):
        if r.get("is_dir"):
            continue
        file_ext = (r.get("ext") or "").lstrip(".").lower()
        if exts and file_ext not in exts:
            continue
        path = r.get("path", "")
        preview_url = f"{base_url}/clawmate/preview.html?root={quote(root, safe='')}&file={quote(path, safe='')}"
        items.append({
            "name": r.get("name", ""),
            "path": path,
            "ext": file_ext,
            "preview_url": preview_url,
        })

    return JSONResponse(content={
        "query": q,
        "root": root,
        "ext": ext,
        "base_url": base_url,
        "results": items,
    })


@router.get("/api/clawmate/search/content", response_class=JSONResponse)
async def clawmate_search_content(
    q: str,
    root: str = "",
    dir: str = "",
    ext: str = "",
    request: Request = None,
):
    """内容搜索 — 使用 ripgrep 搜索文件内容（project 目录内）。

    参数：
        q:       搜索关键词（必填）
        root:    root ID（必填）
        dir:     限定子目录（可选）
        ext:     扩展名过滤，逗号分隔，如 "md,py"（可选）
    """
    cfg = load_config()
    sc = cfg.search.content

    if not sc.enabled:
        raise HTTPException(status_code=503, detail="Content search is disabled")

    # Apply config defaults
    context_lines = sc.context_lines
    max_depth = sc.max_depth
    max_filesize_mb = sc.max_filesize_mb
    exclude_ext = list(sc.exclude_ext)
    exclude_dir = list(sc.exclude_dir)

    # Apply URL param extension filter (additive — only search specified exts)
    if ext:
        url_exts = set(e.strip().lstrip(".").lower() for e in ext.split(",") if e.strip())
        # If user specifies exts, only search those (override exclude logic)
        exclude_ext = None
    else:
        url_exts = None

    try:
        result = search_content(
            q, root_id=root, rel_dir=dir,
            context_lines=context_lines, max_depth=max_depth,
            max_filesize_mb=max_filesize_mb,
            exclude_ext=exclude_ext, exclude_dir=exclude_dir,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Directory not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    # Apply extension filter if user specified exts
    if url_exts:
        filtered = []
        for r in result.get("results_by_file", []):
            file_ext = Path(r["file"]).suffix.lower().lstrip(".")
            if file_ext in url_exts:
                filtered.append(r)
        result["results_by_file"] = filtered
        result["total_files"] = len(filtered)
        result["total_matches"] = sum(r["match_count"] for r in filtered)

    # Add full preview_urls (with base_url)
    base_url = get_public_base_url(request).rstrip("/")
    for r in result.get("results_by_file", []):
        r["preview_url"] = (
            f"{base_url}/clawmate/preview.html"
            f"?root={quote(root, safe='')}"
            f"&file={quote(r['file'], safe='')}"
        )

    # Remove summary key (feature removed)
    result.pop("summary", None)

    return JSONResponse(content=result)
