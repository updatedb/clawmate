"""
Feedback API — 标准 .feedback.json 增删改查 + 实时唤醒 + cron-tick。

v1.26: 内部改用 store.* + config.load()，删除全部散装工具函数。

Routes:
    GET  /api/clawmate/feedback/list   — 列出条目（支持过滤）
    POST /api/clawmate/feedback        — 创建反馈
    POST /api/clawmate/feedback/update — 按 ID 更新状态
    POST /api/clawmate/feedback/cron-tick — 兜底扫描 + 唤醒
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta


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
from store import update_item, list_items, batch_update_items
from service import resolve_root

# ── 常量 ────────────────────────────────────────────────────────────

CST = timezone(timedelta(hours=8))

router = APIRouter()



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
    """列出 .feedback.json 中的条目。

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
            fb_path = entry / ".clawmate" / "feedback.json"
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
        raise HTTPException(status_code=404, detail=".feedback.json not found")
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


@router.post("/api/clawmate/feedback/batch-update", response_class=JSONResponse)
async def feedback_batch_update(request: Request):
    """
    批量更新 feedback item 状态。
    Body: { "root": "...", "project": "...", "items": [{id, status, result}, ...] }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    root_id = str(body.get("root", "")).strip()
    project = str(body.get("project", "")).strip()
    updates = body.get("items", [])

    if not root_id or not project:
        raise HTTPException(status_code=422, detail="Missing root/project")
    if not updates or not isinstance(updates, list):
        raise HTTPException(status_code=422, detail="Missing items")

    try:
        result = batch_update_items(root_id, project, updates)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        logger.exception("[batch-update] unhandled error root=%s project=%s", root_id, project)
        raise HTTPException(status_code=500, detail="Internal server error — check server logs")
    return {"ok": True, "updated": len(result), "items": [{"id": it["id"], "status": it["status"]} for it in result]}


