"""
Feedback API — 标准 feedback.json 增删改查 + 实时唤醒 + cron-tick。

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
import threading
import time as time_module
from datetime import datetime, timezone, timedelta
from pathlib import Path

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
from config import load as config, load_task_templates
from store import create_items, update_item, list_items, scan_all, batch_update_items
from service import resolve_root

# ── 常量 ────────────────────────────────────────────────────────────

CST = timezone(timedelta(hours=8))

router = APIRouter()


# ── Webhook wake 工具 ───────────────────────────────────────────
# v1.26: message 内联（不加载任何模板）

_last_wake: dict[str, float] = {}
_DEBOUNCE_SECONDS = 60


def _get_action_desc(task_id: str, fallback_action: str) -> str:
    """从 task_template 的 desc 字段获取操作描述。"""
    _tmpl = next((t for t in load_task_templates() if t.id == task_id), None)
    if _tmpl and _tmpl.desc:
        return _tmpl.desc
    # 降级：按 action 返回默认描述
    _fallback = {
        "other": "根据 note 描述处理",
        "delete": "删除匹配内容",
        "modify": "修改匹配内容",
        "explain": "补充说明",
        "simplify": "简化描述",
        "translate": "翻译",
        "add": "追加内容",
        "execute": "执行方案（project 范围）",
    }
    return _fallback.get(fallback_action, "根据 note 描述处理")


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

    _ts_wake = datetime.now(CST).isoformat(timespec="seconds")
    logger.info("[feedback.wake] %s start root_id=%s agent_id=%s", _ts_wake, root_id, agent_id)

    # 防抖检查
    now = time_module.time()
    last = _last_wake.get(root_id, 0.0)
    if now - last < _DEBOUNCE_SECONDS:
        logger.info("[feedback] wake skipped (debounced %ds): root_id=%s", int(now - last), root_id)
        return
    _last_wake[root_id] = now

    # 内联 message — 从 store 读取所有 pending items 拼入 prompt
    base_url = cfg.public_base_url or "http://localhost:5533"
    scope = f"root={root_id}"
    if project:
        scope += f"&project={project}"
    if file:
        scope += f"&file={file}"

    # 读取所有 pending items
    items, _ = list_items(root_id, project, status="pending", file=file)
    
    if items:
        lines = [f"ClawMate 反馈通知：root={root_id}  project={project}  有以下 {len(items)} 条待处理 feedback 需要你执行：", ""]
        for idx, item in enumerate(items):
            item_id = item.get("id", "?")
            task_id = item.get("task_id", "") or item.get("action", "other")
            scope_val = item.get("scope", "document")
            item_file = item.get("file", file or "?")
            content_val = (item.get("content", "") or "")[:200]
            note_val = (item.get("note", "") or "")[:300]
            position_val = item.get("position", "") or "无"
            
            action_desc = _get_action_desc(task_id, item.get("action", "other"))
            lines.append(f"{idx+1}. [{item_id}] task_id={task_id} action={item.get('action','?')} scope={scope_val}")
            lines.append(f"   file: {item_file}")
            lines.append(f"   position: {position_val}")
            lines.append(f"   content: {content_val}")
            lines.append(f"   note: {note_val}")
            lines.append(f"   操作：{action_desc}")
            lines.append("")
        lines.append(f"规则：执行成功 → status=done，执行失败或冲突 → status=failed，处理中 → status=in_progress")
        lines.append(f"执行完成后，批量 POST {base_url}/api/clawmate/feedback/batch-update 更新状态。")
        lines.append(f"请求体 JSON: root={root_id}, project={project}, items=[{{id, status, result}}]")
        message = "\n".join(lines)
    else:
        message = f"ClawMate 反馈通知：{scope} 目前无待处理 feedback。"
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
                _ts_end = datetime.now(CST).isoformat(timespec="seconds")
                logger.info(
                    "[feedback.wake] %s success root_id=%s agent_id=%s run_name=%s run_id=%s",
                    _ts_end, root_id, agent_id, run_name, data.get("runId", ""),
                )
            else:
                _ts_end = datetime.now(CST).isoformat(timespec="seconds")
                logger.warning(
                    "[feedback.wake] %s failed root_id=%s agent_id=%s HTTP=%d body=%s",
                    _ts_end, root_id, agent_id, r.status_code, r.text[:200],
                )
        except Exception as e:
            _ts_end = datetime.now(CST).isoformat(timespec="seconds")
            logger.warning(
                "[feedback.wake] %s error root_id=%s agent_id=%s: %s",
                _ts_end, root_id, agent_id, e,
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
    if not root_id or not project or not file_path:
        raise HTTPException(status_code=422, detail="Missing root/project/path")
    if not selections or not isinstance(selections, list):
        raise HTTPException(status_code=422, detail="Missing selections")

    new_items = create_items(root_id, project, file_path, selections)

    ids = [i["id"] for i in new_items if i.get("id")]

    # 实时唤醒 agent
    if ids:
        _wake_agent_for_root(root_id, project=project, file=file_path)

    _ts = datetime.now(CST).isoformat(timespec="seconds")
    _user = request.client.host if request.client else "unknown"
    logger.info(
        "[feedback.create] %s root=%s project=%s user=%s ids=%s file=%s result=%s",
        _ts, root_id, project, _user, ids, file_path, "ok",
    )

    return JSONResponse(content={
        "ok": True, "ids": ids,
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


@router.post("/api/clawmate/feedback/batch-process", response_class=JSONResponse)
async def feedback_batch_process(request: Request):
    """
    批处理入口：收集同一文件的所有 pending item，
    去重 + 冲突检测后返回操作列表给 agent。
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    root_id = str(body.get("root", "")).strip()
    project = str(body.get("project", "")).strip()
    file_path = str(body.get("file", "")).strip()

    if not root_id or not project or not file_path:
        raise HTTPException(status_code=422, detail="Missing root/project/file")

    # 1. 收集所有 pending item
    items, _ = list_items(root_id, project, status="pending", file=file_path)
    if not items:
        return {"ok": True, "file": file_path, "current_content": "", "operations": [], "conflicts": [], "dedup_count": 0, "conflict_count": 0, "total": 0}

    # 2. 读取文件内容
    from service import resolve_root
    rcfg = resolve_root(root_id)
    if not rcfg:
        raise HTTPException(status_code=404, detail=f"Root not found: {root_id}")
    full_path = rcfg / file_path
    current_content = ""
    try:
        current_content = full_path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, OSError):
        pass

    # 3. 去重（同 content 只保留一条）
    seen_content = set()
    dedup_count = 0
    deduped = []
    for item in items:
        content = (item.get("content", "") or "").strip()
        if not content:
            continue
        key = content
        if key in seen_content:
            dedup_count += 1
            continue
        seen_content.add(key)
        deduped.append(item)

    # 4. 直接从 item 读取 action + scope（创建时已写入）
    doc_operations = []
    proj_operations = []
    for item in deduped:
        scope = item.get("scope", "document")
        op = {
            "id": item.get("id", ""),
            "note": item.get("note", ""),
            "content": item.get("content", ""),
            "action": item.get("action", "other"),
            "scope": scope,
        }
        if scope == "project":
            proj_operations.append(op)
        else:
            doc_operations.append(op)

    # 6. 冲突检测（仅作用于 scope=document 的 operations）
    conflicts = []
    for i, a in enumerate(doc_operations):
        for b in doc_operations[i + 1:]:
            a_content = (a.get("content", "") or "").strip()
            b_content = (b.get("content", "") or "").strip()
            if not a_content or not b_content:
                continue
            overlap = a_content in b_content or b_content in a_content
            if not overlap:
                continue
            if a["action"] == b["action"] == "delete":
                conflicts.append({
                    "ids": [a["id"], b["id"]],
                    "type": "mergeable_delete",
                    "detail": f"两个 delete 内容重叠「{a_content[:20]}」vs「{b_content[:20]}」，自动合并为一条删除",
                })
            elif set([a["action"], b["action"]]) <= {"delete", "replace"}:
                conflicts.append({
                    "ids": [a["id"], b["id"]],
                    "type": "conflict_delete_replace",
                    "detail": f"delete 与 {b['action']} 作用于同一段文本，需 agent 决策 which operation wins",
                })

    return {
        "ok": True,
        "file": file_path,
        "current_content": current_content,
        "operations": doc_operations,
        "project_actions": proj_operations,
        "conflicts": conflicts,
        "dedup_count": dedup_count,
        "conflict_count": len(conflicts),
        "total": len(items),
    }


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
    return {"ok": True, "updated": len(result), "items": [{"id": it["id"], "status": it["status"]} for it in result]}


