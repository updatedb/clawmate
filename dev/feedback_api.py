"""
Feedback API — 标准 feedback.json 增删改查 + 实时唤醒。

全部接口统一使用标准字段名（见 feedback_schema.py），
不做任何字段重命名翻译。

Routes:
    GET  /api/clawmate/feedback/list   — 列出条目（支持过滤）
    POST /api/clawmate/feedback        — 创建反馈
    GET  /api/clawmate/feedback/status — 查询状态统计
    POST /api/clawmate/feedback/update — 按 ID 更新状态
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from cron_manager import run_cron
from feedback_schema import FEEDBACK_STATUSES
from service import resolve_root, get_public_base_url

# ── 常量 ────────────────────────────────────────────────────────────

CST = timezone(timedelta(hours=8))
STATUS_LABELS = {
    "pending": "待处理", "in_progress": "处理中",
    "done": "已完成", "failed": "失败", "deleted": "已删除",
}

router = APIRouter()


# ── 内部工具 ─────────────────────────────────────────────────────────

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
    """生成 2 字符项目缩写."""
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


def _parse_items(raw) -> list:
    if isinstance(raw, dict):
        return raw.get("items", [])
    return []


def _build_feedback_json(root: str, project: str, items: list) -> str:
    ts = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    max_id = 0
    for item in items:
        m = re.search(r'FD-\w+-(\d+)', item.get("id", ""))
        if m:
            max_id = max(max_id, int(m.group(1)))
    data = {
        "root": root, "project": project, "updated": ts,
        "last_id": max_id, "items": items,
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def _filter_items(fb_path: Path, status: str, file: str, since: str) -> list:
    """从 feedback.json 读取条目并过滤，返回统一格式."""
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
            def _parse_ts(ts: str):
                try:
                    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CST)
                except Exception:
                    return datetime.min.replace(tzinfo=CST)
            items = [i for i in items if _parse_ts(i.get("updated", "")) >= cutoff]

    result = []
    for item in items:
        entry = {
            "id": item.get("id", ""),
            "status": item.get("status", "pending"),
            "note": item.get("note", ""),
            "file": item.get("file", ""),
            "content": item.get("content", "") or item.get("selection", ""),
            "updated": item.get("updated", ""),
            "result": item.get("result", ""),
            "position": item.get("position", ""),
        }
        result.append(entry)
    return result


def _wake_agent_for_root(root_id: str) -> None:
    """读取 config.json，找到 root 对应的 agent 并用 run_cron 唤醒."""
    config_path = Path(os.environ.get("CLAWMATE_CONFIG",
                        str(Path(__file__).parent / "config.json")))
    agent_id = "default"
    try:
        with open(config_path) as f:
            cfg = json.load(f)
        for r in cfg.get("roots", []):
            if r.get("id") == root_id:
                agent_id = r.get("agent_id", "default")
                break
    except Exception:
        pass
    try:
        run_cron(None, f"clawmate-fb-{agent_id}")
    except Exception:
        pass

# ── 路由 ─────────────────────────────────────────────────────────────

@router.get("/api/clawmate/feedback/list", response_class=JSONResponse)
async def feedback_list(
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

    if project:
        results = []
        total_pending = 0
        for rid in root_ids:
            try:
                fb_path = _get_feedback_path(rid, project)
            except (PermissionError, FileNotFoundError):
                continue
            items = _filter_items(fb_path, status, file, since)
            total_pending += sum(1 for i in items if i.get("status") == "pending")
            results.append({
                "root": rid, "project": project,
                "total": len(items),
                "pending": sum(1 for i in items if i.get("status") == "pending"),
                "items": items,
            })
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
    for root_id in root_ids:
        try:
            root_dir = resolve_root(root_id)
        except Exception:
            continue
        if not root_dir.exists() or not root_dir.is_dir():
            continue
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
                    "root": root_id, "project": proj,
                    "pending_count": pending,
                    "items": items,
                })
                total_pending += pending

    return JSONResponse(content={
        "total_pending": total_pending,
        "results": results,
    })


@router.post("/api/clawmate/feedback", response_class=JSONResponse)
async def feedback_create(request: Request):
    """统一反馈入口 — 写入 feedback.json + 实时唤醒 agent."""
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
        public_base = get_public_base_url(request)
        preview_url = f"{public_base}/clawmate/preview.html?root={quote(root_id)}&file={quote(file_path)}"

    existing_data = _read_feedback_json(fb_path)
    existing_items = _parse_items(existing_data)
    last_id = existing_data.get("last_id", 0) if isinstance(existing_data, dict) else 0
    ts = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

    existing_keys = {(item.get("content", ""), item.get("file", "")) for item in existing_items}

    new_items = []
    for idx, sel in enumerate(selections):
        text = str(sel.get("text", "")).strip()
        if not text:
            continue
        note = str(sel.get("note", "")).strip()
        if (text, file_path) in existing_keys:
            continue
        position = str(sel.get("position", "") or "").strip()
        if not position:
            start_line = sel.get("startLine")
            end_line = sel.get("endLine")
            if start_line and end_line:
                position = f"L{start_line}-{end_line}"

        new_id_num = last_id + idx + 1
        item_id = f"FD-{_project_abbr(project)}-{new_id_num:04d}"
        new_items.append({
            "id": item_id, "status": "pending",
            "file": file_path, "note": note or text[:80],
            "content": text, "position": position,
            "updated": ts, "result": "",
        })
        existing_keys.add((text, file_path))

    existing_items.extend(new_items)
    fb_path.write_text(_build_feedback_json(root_id, project, existing_items), encoding="utf-8")

    ids = [i["id"] for i in new_items if i["id"]]

    # 实时唤醒 agent
    _wake_agent_for_root(root_id)

    # 构建预览文本
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

    return JSONResponse(content={
        "ok": True, "ids": ids,
        "feedbackFile": str(fb_path),
        "feedbackText": "\n".join(lines),
        "previewUrl": preview_url,
    })


@router.get("/api/clawmate/feedback/status", response_class=JSONResponse)
async def feedback_status(root: str = "", project: str = ""):
    """查询 feedback.json 状态统计."""
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
        "items": [{
            "id": i["id"], "note": i["note"], "status": i["status"],
            "file": i["file"], "result": i.get("result", ""),
        } for i in items],
    })


@router.post("/api/clawmate/feedback/update", response_class=JSONResponse)
async def feedback_update(request: Request):
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
    if new_status not in FEEDBACK_STATUSES and new_status != "deleted":
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of {FEEDBACK_STATUSES} or deleted",
        )
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

    fb_path.write_text(_build_feedback_json(root_id, project, items), encoding="utf-8")
    return JSONResponse(content={"ok": True, "id": feedback_id, "newStatus": new_status})


