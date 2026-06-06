"""
Feedback API — 标准 feedback.json 增删改查 + 实时唤醒 + cron-tick。

v1.26: 内部改用 store.* + config.load()，删除全部散装工具函数。

Routes:
    GET  /api/clawmate/feedback/list   — 列出条目（支持过滤）
    POST /api/clawmate/feedback        — 创建反馈
    GET  /api/clawmate/feedback/status — 查询状态统计
    POST /api/clawmate/feedback/update — 按 ID 更新状态
    POST /api/clawmate/feedback/cron-tick — 兜底扫描 + 唤醒
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time as time_module
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx

logger = logging.getLogger("clawmate.feedback")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setLevel(logging.INFO)
    _h.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from feedback_schema import FEEDBACK_STATUSES
from config import load as config
from store import create_items, update_item, list_items, status_count, scan_all, project_abbr
from service import resolve_root, get_public_base_url

# ── 常量 ────────────────────────────────────────────────────────────

CST = timezone(timedelta(hours=8))

router = APIRouter()


# ── Webhook wake 工具 ───────────────────────────────────────────
# v1.26: message 内联（不加载任何模板）

_last_wake: dict[str, float] = {}
_DEBOUNCE_SECONDS = 60


def _wake_agent_for_root(root_id: str, project: str = "", file: str = "") -> None:
    """读取 config，直接 POST OpenClaw /hooks/agent（后台线程 fire-and-forget）。

    内联 message（不加载模板），防抖 60s 同 root 跳过。
    可传 project + file 缩小 agent 查询范围。
    """
    cfg = config()
    oc = cfg.openclaw
    hook_token = oc.hook_token
    gateway_url = oc.gateway_url

    if not hook_token:
        logger.warning("[feedback] wake skipped: openclaw.hook_token not configured in config.json")
        return

    # 解析 agent_id
    agent_id = cfg.root_agent(root_id)

    logger.info("[feedback] waking agent: root_id=%s, agent_id=%s", root_id, agent_id)

    # 防抖检查
    now = time_module.time()
    last = _last_wake.get(root_id, 0.0)
    if now - last < _DEBOUNCE_SECONDS:
        logger.info("[feedback] wake skipped (debounced %ds): root_id=%s", int(now - last), root_id)
        return
    _last_wake[root_id] = now

    # 内联 message
    base_url = cfg.public_base_url or "http://localhost:5533"
    scope = f"root={root_id}"
    if project:
        scope += f"&project={project}"
    if file:
        scope += f"&file={file}"
    message = (
        f"ClawMate 反馈通知：{scope} 有待处理反馈。\n"
        f"处理步骤：\n"
        f"1. GET {base_url}/api/clawmate/feedback/list?{scope}&status=pending 获取待处理列表\n"
        f"2. 加载 {root_id}/{project if project else '?'} 项目上下文，逐条读取 note/content 理解改进需求\n"
        f"3. 综合考虑后执行改动\n"
        f"4. 完成后检查是否有不恰当的项，并更新反馈状态"
    )
    run_name = f"clawmate-fb-{root_id}"

    def _do_wake_sync():
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
                data = r.json()
                logger.info(
                    "[feedback] wake success: root_id=%s, agent_id=%s, run_name=%s, run_id=%s",
                    root_id, agent_id, run_name, data.get("runId", ""),
                )
            else:
                logger.warning(
                    "[feedback] wake failed: root_id=%s, agent_id=%s, HTTP=%d, body=%s",
                    root_id, agent_id, r.status_code, r.text[:200],
                )
        except Exception as e:
            logger.warning(
                "[feedback] wake HTTP error: root_id=%s, agent_id=%s: %s",
                root_id, agent_id, e,
            )

    threading.Thread(target=_do_wake_sync, daemon=True).start()


# ── 路由 ─────────────────────────────────────────────────────────────

@router.get("/api/clawmate/feedback/list", response_class=JSONResponse)
async def feedback_list(
    request: Request,
    root: str = Query(..., description="逗号分隔的 root_id"),
    project: str = Query("", description="项目名，省略时自动扫描"),
    status: str = Query("", description="pending|in_progress|done|failed"),
    file: str = Query("", description="文件名模糊匹配"),
    since: str = Query("", description="today 或 YYYY-MM-DD"),
):
    """列出 feedback.json 中的条目。

    两种模式:
    - project 指定: 单项目查询
    - project 省略: 自动扫描所有 root 下的项目，聚合结果
    """
    if not root:
        raise HTTPException(status_code=422, detail="Missing root")

    root_ids = [r.strip() for r in root.split(",") if r.strip()]
    _ts = datetime.now(CST).isoformat(timespec="seconds")
    _user = request.client.host if request.client else "unknown"
    _list_params = {"status": status, "file": file, "since": since, "n_roots": len(root_ids)}

    if project:
        results = []
        total_pending = 0
        for rid in root_ids:
            try:
                items, pending = list_items(rid, project, status=status, file=file, since=since)
            except ValueError:
                continue
            total_pending += pending
            results.append({
                "root": rid, "project": project,
                "total": len(items),
                "pending": pending,
                "items": items,
            })
        for rid in root_ids:
            logger.info(
                "[feedback.list] %s root=%s project=%s user=%s params=%s result=%s",
                _ts, rid, project, _user, _list_params, "ok",
            )
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

    # 自动扫描模式
    results = []
    total_pending = 0
    scanned_roots: set[str] = set()
    for root_id in root_ids:
        try:
            root_dir = resolve_root(root_id)
        except Exception:
            continue
        if not root_dir.exists() or not root_dir.is_dir():
            continue
        scanned_roots.add(root_id)
        for entry in sorted(root_dir.iterdir()):
            if not entry.is_dir():
                continue
            proj = entry.name
            fb_path = entry / "feedback.json"
            if not fb_path.exists():
                continue
            try:
                items, pending = list_items(root_id, proj, status=status, file=file, since=since)
            except ValueError:
                continue
            if items:
                results.append({
                    "root": root_id, "project": proj,
                    "pending_count": pending,
                    "items": items,
                })
                total_pending += pending

    for rid in scanned_roots:
        logger.info(
            "[feedback.list] %s root=%s project=%s user=%s params=%s result=%s",
            _ts, rid, "", _user, _list_params, "ok",
        )

    return JSONResponse(content={
        "total_pending": total_pending,
        "results": results,
    })


@router.post("/api/clawmate/feedback", response_class=JSONResponse)
async def feedback_create(request: Request):
    """统一反馈入口 — 写入 feedback.json + 实时唤醒 agent。"""
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

    if not preview_url:
        public_base = get_public_base_url(request)
        preview_url = f"{public_base}/clawmate/preview.html?root={quote(root_id)}&file={quote(file_path)}"

    new_items = create_items(root_id, project, file_path, selections, preview_url=preview_url)

    ids = [i["id"] for i in new_items if i.get("id")]

    # 实时唤醒 agent
    if ids:
        _wake_agent_for_root(root_id, project=project, file=file_path)

    # 预览文本
    lines = ["## 📋 ClawMate 反馈"]
    lines.append(f"**项目**: `{project}`")
    lines.append(f"**文件**: `{file_path}` | **ID**: {', '.join(ids)}")
    lines.append(f"**预览**: {preview_url}")
    for sel in selections:
        t = str(sel.get("text", "")).strip()
        n = str(sel.get("note", "")).strip()
        if t:
            lines.append(f"> {t[:300]}")
        if n:
            lines.append(f"📝 {n}")

    _ts = datetime.now(CST).isoformat(timespec="seconds")
    _user = request.client.host if request.client else "unknown"
    logger.info(
        "[feedback.create] %s root=%s project=%s user=%s ids=%s file=%s result=%s",
        _ts, root_id, project, _user, ids, file_path, "ok",
    )

    fb_path = resolve_root(root_id) / project / "feedback.json"
    return JSONResponse(content={
        "ok": True, "ids": ids,
        "feedbackFile": str(fb_path),
        "feedbackText": "\n".join(lines),
        "previewUrl": preview_url,
    })


@router.get("/api/clawmate/feedback/status", response_class=JSONResponse)
async def feedback_status(request: Request, root: str = "", project: str = ""):
    """查询 feedback.json 状态统计。"""
    if not root or not project:
        raise HTTPException(status_code=422, detail="Missing root or project")

    counts = status_count(root, project)

    # 同时获取 items 概要
    items, _ = list_items(root, project)

    _ts = datetime.now(CST).isoformat(timespec="seconds")
    _user = request.client.host if request.client else "unknown"
    logger.info(
        "[feedback.status] %s root=%s project=%s user=%s counts=%s result=%s",
        _ts, root, project, _user, counts, "ok",
    )

    fb_path = resolve_root(root) / project / "feedback.json"
    return JSONResponse(content={
        "feedbackFile": str(fb_path),
        "exists": fb_path.exists(),
        "counts": counts,
        "items": [{
            "id": i["id"], "note": i["note"], "status": i["status"],
            "file": i["file"], "result": i.get("result", ""),
        } for i in items],
    })


@router.post("/api/clawmate/feedback/update", response_class=JSONResponse)
async def feedback_update(request: Request):
    """按 ID 更新反馈项状态。"""
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
    if new_status not in FEEDBACK_STATUSES and new_status != "deleted":
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of {FEEDBACK_STATUSES} or deleted",
        )
    if new_status in ("done", "failed") and not result_text:
        raise HTTPException(status_code=422, detail="Missing result summary (required for done/failed)")

    try:
        item = update_item(root_id, project, feedback_id, new_status, result=result_text)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="feedback.json not found")
    except LookupError:
        raise HTTPException(status_code=404, detail=f"Item {feedback_id} not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    _ts = datetime.now(CST).isoformat(timespec="seconds")
    _user = request.client.host if request.client else "unknown"
    logger.info(
        "[feedback.update] %s root=%s project=%s user=%s id=%s new_status=%s result=%s",
        _ts, root_id, project, _user, feedback_id, new_status, "ok",
    )

    return JSONResponse(content={"ok": True, "id": feedback_id, "newStatus": new_status})


@router.post("/api/clawmate/feedback/cron-tick")
async def cron_tick():
    """cron 入口：扫所有 root 的 pending feedback，逐 root 唤醒 agent。"""
    result = scan_all()
    for root_id in result.pending_roots:
        _wake_agent_for_root(root_id)
    logger.info(
        "[cron-tick] checked=%d pending=%d woken=%d errors=%d",
        result.checked_roots, result.pending_total, len(result.pending_roots), len(result.errors),
    )
    return {"ok": True}


