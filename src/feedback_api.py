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

import logging
from datetime import datetime


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
from store import (
    CST, update_item, list_items, batch_update_items, create_items, review_items,
    create_execution_plan, confirm_execution_plan, create_execution_task, record_execution_result, delete_item,
)
from service import resolve_root

router = APIRouter()


def _callback_source(request: Request) -> str:
    """Return a safe origin class for operational diagnostics, never an IP/token."""
    host = request.client.host if request.client else ""
    return "loopback" if host in {"127.0.0.1", "::1", "localhost"} else "non_loopback"


def _callback_log(status: int, request: Request, *, task_id: str = "",
                  missing_ids: list[str] | None = None, extra_ids: list[str] | None = None,
                  field_errors: list[str] | None = None) -> None:
    logger.warning("[review.result] status=%d task_id=%s source=%s missing_ids=%s extra_ids=%s field_errors=%s",
                   status, task_id or "unknown", _callback_source(request),
                   missing_ids or [], extra_ids or [], field_errors or [])


@router.post("/api/clawmate/feedback", response_class=JSONResponse)
async def feedback_create(request: Request):
    """Create review suggestions only. Creation never wakes an agent."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    root_id = str(body.get("root", "")).strip()
    project = str(body.get("project", "")).strip()
    path = str(body.get("path") or body.get("file") or "").strip()
    selections = body.get("selections", [])
    if not project and "/" in path:
        project = path.split("/", 1)[0]
    if not root_id or not project or not path or not isinstance(selections, list) or not selections:
        raise HTTPException(status_code=422, detail="Missing root/project/path/selections")
    try:
        items = create_items(root_id, project, path, selections)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project is not initialized")
    if not items:
        raise HTTPException(status_code=409, detail="Feedback already exists")
    return {"ok": True, "ids": [i["id"] for i in items], "items": items}


@router.post("/api/clawmate/review/decision", response_class=JSONResponse)
async def review_decision(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    root_id, project = str(body.get("root", "")).strip(), str(body.get("project", "")).strip()
    ids, decision = body.get("ids", []), str(body.get("decision", "")).strip()
    if not root_id or not project or not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=422, detail="Missing root/project/ids")
    try:
        items = review_items(root_id, project, [str(i) for i in ids], decision, str(body.get("reason", "")).strip())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"ok": True, "items": items}


@router.post("/api/clawmate/review/plan", response_class=JSONResponse)
async def review_plan(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    try:
        task = create_execution_plan(str(body.get("root", "")).strip(), str(body.get("project", "")).strip(),
                                     [str(i) for i in body.get("ids", [])])
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"ok": True, "task": task}


@router.post("/api/clawmate/review/confirm", response_class=JSONResponse)
async def review_confirm(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    try:
        task = confirm_execution_plan(str(body.get("root", "")).strip(), str(body.get("project", "")).strip(),
                                      str(body.get("task_id", "")).strip())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"ok": True, "task": task}


@router.post("/api/clawmate/review/execute", response_class=JSONResponse)
async def review_execute(request: Request):
    """Atomically reserve approved feedback and wake exactly one task agent."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    root_id = str(body.get("root", "")).strip()
    project = str(body.get("project", "")).strip()
    ids = [str(i) for i in body.get("ids", [])]
    if not root_id or not project or not ids:
        raise HTTPException(status_code=422, detail="Missing root/project/ids")
    try:
        task = create_execution_task(root_id, project, ids)
        from task_runner import wake_review_task
        wake_review_task(root_id, project, task["id"])
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": True, "task": task}


@router.post("/api/clawmate/review/result", response_class=JSONResponse)
async def review_result(request: Request):
    """Internal executor callback with actual diff/artifact/check evidence."""
    try:
        body = await request.json()
    except Exception:
        _callback_log(400, request, field_errors=["body: invalid JSON"])
        raise HTTPException(status_code=400, detail="Invalid JSON; submit a JSON object matching the review result contract")
    if not isinstance(body, dict):
        _callback_log(422, request, field_errors=["body: expected object"])
        raise HTTPException(status_code=422, detail="JSON body must be an object")
    task_id = str(body.get("task_id", "")).strip()
    type_errors = []
    for field in ("root", "project", "task_id", "summary", "diff"):
        if field not in body or not isinstance(body.get(field), str):
            type_errors.append(f"{field}: expected string")
    if not isinstance(body.get("success"), bool):
        type_errors.append("success: expected boolean")
    if type_errors:
        _callback_log(422, request, task_id=task_id, field_errors=type_errors)
        raise HTTPException(status_code=422, detail="Invalid review result fields: " + "; ".join(type_errors))
    artifacts = body.get("artifacts", [])
    checks = body.get("checks", [])
    outcomes = body.get("outcomes")
    if not isinstance(artifacts, list) or not isinstance(checks, list):
        errors = (["artifacts: expected array"] if not isinstance(artifacts, list) else []) + (["checks: expected array"] if not isinstance(checks, list) else [])
        _callback_log(422, request, task_id=task_id, field_errors=errors)
        raise HTTPException(status_code=422, detail="artifacts and checks must be arrays; correct their JSON types and retry once")
    if not isinstance(outcomes, list):
        _callback_log(422, request, task_id=task_id, field_errors=["outcomes: expected array"])
        raise HTTPException(status_code=422, detail="outcomes must be an array with exactly one entry for every feedback_id")
    try:
        task = record_execution_result(
            str(body.get("root", "")).strip(), str(body.get("project", "")).strip(),
            task_id, success=bool(body.get("success")),
            summary=str(body.get("summary", "")).strip(), diff=str(body.get("diff", "")),
            artifacts=artifacts, checks=checks, outcomes=outcomes)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        missing_ids = getattr(exc, "missing_ids", [])
        extra_ids = getattr(exc, "extra_ids", [])
        field_errors = getattr(exc, "field_errors", [])
        _callback_log(422, request, task_id=task_id, missing_ids=missing_ids,
                      extra_ids=extra_ids, field_errors=field_errors)
        detail = str(exc)
        if missing_ids:
            detail += "; missing feedback_ids: " + ", ".join(missing_ids)
        if extra_ids:
            detail += "; unexpected feedback_ids: " + ", ".join(extra_ids)
        if field_errors:
            detail += "; field errors: " + "; ".join(field_errors)
        raise HTTPException(status_code=422, detail=detail)
    return {"ok": True, "task": task}



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
            except (ValueError, PermissionError):
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
            except (ValueError, PermissionError):
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
    if new_status in ("pending_review", "approved", "rejected", "planned"):
        raise HTTPException(status_code=409, detail="Use the review decision/plan endpoints for review state transitions")

    try:
        update_item(root_id, project, feedback_id, new_status, result=result_text)
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


@router.post("/api/clawmate/feedback/delete", response_class=JSONResponse)
async def feedback_delete(request: Request):
    """Permanently delete one feedback item (distinct from review cancellation)."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    root_id = str(body.get("root", "")).strip()
    project = str(body.get("project", "")).strip()
    feedback_id = str(body.get("id", "")).strip()
    if not root_id or not project or not feedback_id:
        raise HTTPException(status_code=422, detail="Missing root/project/id")
    try:
        delete_item(root_id, project, feedback_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=".feedback.json not found")
    except LookupError:
        raise HTTPException(status_code=404, detail=f"Item {feedback_id} not found")
    return {"ok": True, "id": feedback_id}


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
    forbidden = {"pending_review", "approved", "rejected", "planned"}
    if any(str(update.get("status", "")) in forbidden for update in updates if isinstance(update, dict)):
        raise HTTPException(status_code=409, detail="Use review endpoints for review state transitions")

    try:
        result = batch_update_items(root_id, project, updates)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        logger.exception("[batch-update] unhandled error root=%s project=%s", root_id, project)
        raise HTTPException(status_code=500, detail="Internal server error — check server logs")
    return {"ok": True, "updated": len(result), "items": [{"id": it["id"], "status": it["status"]} for it in result]}
