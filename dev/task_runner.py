"""
Task Runner — 统一 AI 任务执行入口。

将 feedback 标签、AI 自定义任务（字幕纠错、图片编辑等）
统一到 task_templates 体系管理。

Routes:
    POST /api/clawmate/task/run — 执行任务
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from config import load_task_templates, TaskTemplate

router = APIRouter()
logger = logging.getLogger("clawmate.task")
CST = timezone(timedelta(hours=8))


def _get_template(task_id: str) -> TaskTemplate | None:
    """按 task_id 查找模板。"""
    for t in load_task_templates():
        if t.id == task_id:
            return t
    return None


def _render_prompt(template: TaskTemplate, variables: dict) -> str:
    """渲染 agent_prompt，替换 {var} 占位符。"""
    prompt = template.agent_prompt
    for key, value in variables.items():
        prompt = prompt.replace("{" + key + "}", str(value))
    return prompt


@router.post("/api/clawmate/task/run", response_class=JSONResponse)
async def task_run(request: Request):
    """执行一个 AI 任务。"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    root_id = str(body.get("root", "")).strip()
    project = str(body.get("project", "")).strip()
    task_id = str(body.get("task_id", "")).strip()
    file_path = str(body.get("file", "")).strip()

    if not root_id or not task_id or not file_path:
        raise HTTPException(status_code=422, detail="Missing root/task_id/file")

    template = _get_template(task_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Task template not found: {task_id}")

    # 校验文件扩展名
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    match_exts = template.match_ext
    if "*" not in match_exts and ext not in match_exts:
        raise HTTPException(
            status_code=422,
            detail=f"File type .{ext} not supported for task {task_id}",
        )

    if not project:
        project = file_path.split("/")[0]

    # 渲染 agent_prompt
    note = _render_prompt(template, {
        "file": file_path,
        "content": str(body.get("content", "")),
        "note": str(body.get("note", "")),
        "position": str(body.get("position", "")),
    })

    # 创建 feedback card
    from store import create_items
    selections = [{
        "text": str(body.get("content", "")),
        "note": note,
        "action": template.action,
        "scope": template.scope,
    }]

    new_items = create_items(root_id, project, file_path, selections)
    if not new_items:
        raise HTTPException(status_code=409, detail="Task already exists (dedup)")

    item_id = new_items[0]["id"]

    # 唤醒 agent
    from feedback_api import _wake_agent_for_root
    _wake_agent_for_root(root_id, project=project, file=file_path)

    _ts = datetime.now(CST).isoformat(timespec="seconds")
    logger.info("[task.run] %s root=%s task=%s file=%s item=%s", _ts, root_id, task_id, file_path, item_id)

    return JSONResponse(content={"ok": True, "id": item_id})
