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
import threading
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
    try:
        return JSONResponse(content=search_media(
            q, root_id=root, rel_dir=dir, recursive=recursive,
            limit=limit, max_depth=max_depth, timeout=timeout,
        ))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Directory not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
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
    try:
        results = search_media(q, root_id=root, limit=limit)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Directory not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
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
    summary: bool = False,
    request: Request = None,
):
    """内容搜索 — 使用 ripgrep 搜索文件内容（project 目录内）。

    参数：
        q:       搜索关键词（必填）
        root:    root ID（必填）
        dir:     限定子目录（可选）
        ext:     扩展名过滤，逗号分隔，如 "md,py"（可选）
        summary: 是否生成 AI 摘要（默认 false）
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

    # Add summary if requested
    if summary:
        ai_cfg = cfg.search.ai_summary
        results_copy = list(result.get("results_by_file", []))

        if ai_cfg.enabled and results_copy:
            # Phase 1: return immediately; spawn background AI generation
            result["summary"] = None  # frontend will poll /summary

            # Pre-compute cache key and store "generating" marker
            from search_service import (
                _summary_cache_key, set_cached_ai_summary,
                generate_ai_summary, summarize_search,
                _ai_summary_cache, _ai_summary_lock,
            )
            key = _summary_cache_key(root, q)
            with _ai_summary_lock:
                _ai_summary_cache[key] = {"summary": None, "ts": __import__("time").time()}

            _root_path = str(cfg.root_dir(root)) if root else ""

            def _bg_generate():
                backend = cfg.agent.backend

                # ── openclaw: send via webhook (same pattern as feedback) ──
                if backend == "openclaw":
                    _send_openclaw_summary_webhook(
                        cfg=cfg, root=root, query=q, results=results_copy,
                        base_url=get_public_base_url(request).rstrip("/"),
                    )
                    return

                # ── claude / codex: direct subprocess ──
                try:
                    from agent_routes import _find_claude_binary, _find_codex_binary
                    if backend == "codex":
                        binary = _find_codex_binary()
                    else:
                        binary = _find_claude_binary()
                except Exception as e:
                    _logger.warning("[ai-summary] %s binary not found: %s", backend, e)
                    try:
                        fallback = summarize_search(q, results_copy, root)
                        set_cached_ai_summary(root, q, fallback)
                    except Exception:
                        pass
                    return

                try:
                    ai_summary = generate_ai_summary(
                        query=q,
                        results_by_file=results_copy,
                        binary_path=binary,
                        backend=backend,
                        cwd=_root_path,
                        timeout=ai_cfg.timeout_seconds,
                        max_files=ai_cfg.max_input_files,
                        max_snippets=ai_cfg.max_snippets_per_file,
                        extra_env=cfg.agent.env if cfg.agent.env else None,
                    )
                    if ai_summary is None:
                        ai_summary = summarize_search(q, results_copy, root)
                    set_cached_ai_summary(root, q, ai_summary)
                except Exception as e:
                    _logger.warning("[ai-summary] background generation failed: %s", e)
                    try:
                        fallback = summarize_search(q, results_copy, root)
                        set_cached_ai_summary(root, q, fallback)
                    except Exception:
                        pass

            threading.Thread(target=_bg_generate, daemon=True).start()
        else:
            # AI disabled or no results; use algorithmic summary synchronously
            try:
                from search_service import summarize_search
                result["summary"] = summarize_search(q, results_copy, root)
            except Exception:
                result["summary"] = None

    return JSONResponse(content=result)


@router.get("/api/clawmate/search/summary", response_class=JSONResponse)
async def clawmate_search_summary(
    q: str,
    root: str = "",
):
    """Poll for AI-generated search summary.

    Returns:
        {"status": "ready", "summary": {"overview": "...", "findings": "..."}}
        {"status": "generating"}
        {"status": "not_found"}
    """
    if not q.strip():
        return JSONResponse(content={"status": "not_found"})

    from search_service import _ai_summary_cache, _ai_summary_lock, _summary_cache_key

    key = _summary_cache_key(root, q)
    with _ai_summary_lock:
        entry = _ai_summary_cache.get(key)

    if entry is None:
        return JSONResponse(content={"status": "not_found"})

    summary = entry.get("summary")
    if summary is None:
        return JSONResponse(content={"status": "generating"})

    return JSONResponse(content={"status": "ready", "summary": summary})


# ── OpenClaw webhook helper (same pattern as feedback _wake_agent_for_root) ──

def _send_openclaw_summary_webhook(
    cfg, root: str, query: str, results: list, base_url: str,
) -> None:
    """Send search summary prompt to OpenClaw Gateway via webhook.

    The agent receives the prompt, generates the summary, and POSTs the
    result back to /api/clawmate/search/callback with X-Internal-Token.
    If the webhook fails, falls back to algorithmic summary.
    """
    import httpx

    oc = cfg.openclaw
    gateway_url = oc.gateway_url
    hook_token = oc.hook_token
    agent_id = cfg.root_agent(root) if root else "default"

    if not hook_token or not gateway_url:
        _logger.warning("[ai-summary] openclaw webhook not configured, using algorithmic")
        from search_service import summarize_search, set_cached_ai_summary
        try:
            fallback = summarize_search(query, results, root)
            set_cached_ai_summary(root, query, fallback)
        except Exception:
            pass
        return

    # Build the message prompt (reuse search_service prompt builder)
    from search_service import _build_ai_summary_prompt
    prompt = _build_ai_summary_prompt(
        query=query,
        results_by_file=results,
        max_files=cfg.search.ai_summary.max_input_files,
        max_snippets=cfg.search.ai_summary.max_snippets_per_file,
    )

    callback_url = f"{base_url}/api/clawmate/search/callback?root={__import__('urllib.parse').quote(root, safe='')}&q={__import__('urllib.parse').quote(query, safe='')}"

    message = (
        f"{prompt}\n\n"
        f"───\n"
        f"完成上述分析后，将结果通过以下方式回传：\n"
        f"POST {callback_url}\n"
        f"Header: X-Internal-Token: {hook_token}\n"
        f"Content-Type: application/json\n"
        f"Body: 与 output_format 一致的 JSON {{\"overview\": \"...\", \"findings\": \"...\"}}\n"
    )

    run_name = f"clawmate-summary-{root}"

    def _do_webhook():
        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.post(
                    f"{gateway_url}/hooks/agent",
                    headers={"Authorization": f"Bearer {hook_token}"},
                    json={
                        "message": message,
                        "agentId": agent_id,
                        "name": run_name,
                        "wakeMode": "now",
                        "deliver": False,
                    },
                )
            if r.status_code == 200:
                data = r.json() if r.text else {}
                _logger.info(
                    "[ai-summary] webhook sent root=%s agent=%s run_id=%s",
                    root, agent_id, data.get("runId", ""),
                )
            else:
                _logger.warning(
                    "[ai-summary] webhook failed root=%s HTTP=%d body=%s",
                    root, r.status_code, r.text[:200],
                )
                # Fallback to algorithmic on webhook failure
                from search_service import summarize_search, set_cached_ai_summary
                try:
                    fallback = summarize_search(query, results, root)
                    set_cached_ai_summary(root, query, fallback)
                except Exception:
                    pass
        except Exception as e:
            _logger.warning("[ai-summary] webhook error root=%s: %s", root, e)
            # Fallback to algorithmic on error
            from search_service import summarize_search, set_cached_ai_summary
            try:
                fallback = summarize_search(query, results, root)
                set_cached_ai_summary(root, query, fallback)
            except Exception:
                pass

    threading.Thread(target=_do_webhook, daemon=True).start()


# ── Callback endpoint for OpenClaw agent to store summary ──────────────

@router.post("/api/clawmate/search/callback", response_class=JSONResponse)
async def clawmate_search_callback(
    q: str,
    root: str = "",
    request: Request = None,
):
    """Callback endpoint for OpenClaw agent to store generated summary.

    The agent POSTs the summary JSON here after generating it via webhook.
    Authenticated via X-Internal-Token header (same as feedback API).
    """
    from auth import verify_internal_token
    if not verify_internal_token(request):
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    overview = str(body.get("overview", "")).strip()
    findings = str(body.get("findings", "")).strip()

    if not overview and not findings:
        raise HTTPException(status_code=400, detail="Missing overview and findings")

    from search_service import set_cached_ai_summary
    set_cached_ai_summary(root, q, {"overview": overview, "findings": findings})

    _logger.info(
        "[ai-summary] callback stored root=%s q=%s overview_len=%d findings_len=%d",
        root, q, len(overview), len(findings),
    )
    return JSONResponse(content={"status": "ok"})
