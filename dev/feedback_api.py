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
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote

logger = logging.getLogger("clawmate.feedback")
# v1.21: 显式设 INFO level + StreamHandler，确保 waking/wake success 日志在 journalctl 中可见
# (uvicorn 默认 root=WARNING，clawmate.feedback 需独立 handler 才能输出 INFO)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setLevel(logging.INFO)
    _h.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from cron_manager import run_cron
from feedback_schema import FEEDBACK_STATUSES
from service import resolve_root, get_public_base_url
from constants import CONFIG_PATH_ENV

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
        config_path = Path(os.environ.get(CONFIG_PATH_ENV, "config.json"))
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

    if status and status != "all":
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
    config_path = Path(os.environ.get(CONFIG_PATH_ENV,
                        str(Path(__file__).parent / "config.json")))
    agent_id = "default"
    try:
        with open(config_path) as f:
            cfg = json.load(f)
        for r in cfg.get("roots", []):
            if r.get("id") == root_id:
                agent_id = r.get("agent_id", "default")
                break
    except Exception as e:
        # v1.8 B1: 静默失败改日志 (wake 失败不应阻塞 feedback 创建)
        logger.warning(
            "[feedback] wake failed: cannot resolve agent for root_id=%s (config_path=%s): %s",
            root_id, config_path, e,
        )

    # v1.21: 进入唤醒流程 INFO 日志（强哥排查 FD-SRT-0007 时确认 wake 是否真触发）
    logger.info(
        "[feedback] waking agent: root_id=%s, agent_id=%s, cron_name=clawmate-fb-%s",
        root_id, agent_id, agent_id,
    )
    try:
        run_cron(None, f"clawmate-fb-{agent_id}")
        # v1.21: 唤醒成功 INFO 日志（之前只有失败时 warning）
        logger.info(
            "[feedback] wake success: root_id=%s, agent_id=%s, cron_name=clawmate-fb-%s",
            root_id, agent_id, agent_id,
        )
    except Exception as e:
        # v1.8 B1: 静默失败改日志
        logger.warning(
            "[feedback] wake failed: run_cron('clawmate-fb-%s') for root_id=%s: %s",
            agent_id, root_id, e,
        )


# v1.8 B5: 归档/清理 feedback.json 中 status="done" 且 updated 超过 N 天的条目
# 推荐：归档到 feedback.archive.json (append-only, 保留可追溯性)
# - days=90: 默认保留 90 天 (dev 可调)
# - archive_to=None: 直接删除 (不推荐)
# - 启动时调用 cleanup_old_feedback() 一次 (主线程 + 快速超时，不阻塞 server)
# - 手动 API: POST /api/clawmate/feedback/cleanup (需登录, AuthMiddleware 拦截)


def _archive_feedback_items(fb_path: Path, items_to_archive: list) -> bool:
    """将待归档条目 append 到 feedback.archive.json (同目录下). 失败返回 False."""
    try:
        archive_path = fb_path.parent / "feedback.archive.json"
        # 读取已有归档
        if archive_path.exists():
            try:
                with open(archive_path, "r", encoding="utf-8") as f:
                    archive_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                archive_data = {"items": []}
        else:
            archive_data = {"items": []}
        archive_items = archive_data.get("items", [])
        archive_items.extend(items_to_archive)
        archive_data["items"] = archive_items
        # 写回 (原子: 先写 .tmp 再 rename)
        tmp_path = archive_path.with_suffix(".archive.json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(archive_data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, archive_path)
        return True
    except Exception as e:
        logger.warning("[feedback] archive failed for %s: %s", fb_path, e)
        return False


def cleanup_old_feedback(days: int = 90, archive: bool = True) -> dict:
    """
    清理 feedback.json 中 status="done" 且 updated 超过 N 天的条目。

    策略 (推荐):
    - archive=True: 归档到 feedback.archive.json (同目录, append-only)
    - archive=False: 直接删除 (不推荐, 失去可追溯性)

    扫描范围: 遍历 config.json 中所有 root 下的 project 目录里的 feedback.json

    Returns:
        dict: {scanned_files, archived_count, removed_count, errors}
        不抛异常 (用于启动时调用, 避免阻塞)
    """
    from service import _load_config  # 避免循环导入

    stats = {"scanned_files": 0, "archived_count": 0, "removed_count": 0, "errors": []}

    try:
        cfg = _load_config()
        roots = cfg.get("roots", []) or []
    except Exception as e:
        stats["errors"].append(f"load config: {e}")
        return stats

    cutoff = datetime.now(CST) - timedelta(days=days)

    # 1) 收集所有 feedback.json 路径
    fb_paths: list[Path] = []
    for r in roots:
        if not isinstance(r, dict):
            continue
        root_dir_str = str(r.get("dir", "")).strip()
        if not root_dir_str:
            continue
        try:
            root_dir = Path(root_dir_str).expanduser().resolve()
        except Exception:
            continue
        if not root_dir.exists() or not root_dir.is_dir():
            continue
        # 遍历下一级目录 (project)
        try:
            for entry in root_dir.iterdir():
                if not entry.is_dir():
                    continue
                fb = entry / "feedback.json"
                if fb.exists():
                    fb_paths.append(fb)
        except Exception as e:
            stats["errors"].append(f"scan {root_dir}: {e}")

    # 2) 处理每个 feedback.json
    for fb_path in fb_paths:
        stats["scanned_files"] += 1
        try:
            data = _read_feedback_json(fb_path)
            items = _parse_items(data)
            if not items:
                continue

            to_archive = []
            keep = []
            for item in items:
                if item.get("status") != "done":
                    keep.append(item)
                    continue
                try:
                    ts = datetime.strptime(
                        item.get("updated", ""), "%Y-%m-%d %H:%M:%S"
                    ).replace(tzinfo=CST)
                except Exception:
                    keep.append(item)  # 解析失败保留
                    continue
                if ts < cutoff:
                    to_archive.append(item)
                else:
                    keep.append(item)

            if not to_archive:
                continue

            if archive:
                if _archive_feedback_items(fb_path, to_archive):
                    stats["archived_count"] += len(to_archive)
                    # 写回 (移除已归档的)
                    root_id = data.get("root", "")
                    project = data.get("project", "")
                    fb_path.write_text(
                        _build_feedback_json(root_id, project, keep),
                        encoding="utf-8",
                    )
                else:
                    stats["errors"].append(f"archive failed: {fb_path}")
            else:
                # 直接删除
                root_id = data.get("root", "")
                project = data.get("project", "")
                fb_path.write_text(
                    _build_feedback_json(root_id, project, keep),
                    encoding="utf-8",
                )
                stats["removed_count"] += len(to_archive)
        except Exception as e:
            stats["errors"].append(f"{fb_path}: {e}")
            logger.warning("[feedback] cleanup error for %s: %s", fb_path, e)

    if stats["archived_count"] or stats["removed_count"] or stats["errors"]:
        logger.info(
            "[feedback] cleanup: scanned=%d archived=%d removed=%d errors=%d",
            stats["scanned_files"], stats["archived_count"],
            stats["removed_count"], len(stats["errors"]),
        )
    return stats

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


# v1.8 B5: 手动 cleanup API (需登录, AuthMiddleware 自动拦截)
# - days: 清理阈值天数 (默认 90)
# - archive: True 归档到 feedback.archive.json / False 直接删除
@router.post("/api/clawmate/feedback/cleanup", response_class=JSONResponse)
async def feedback_cleanup(
    request: Request,
    days: int = Query(90, ge=1, le=3650, description="保留天数阈值"),
    archive: bool = Query(True, description="True=归档, False=删除"),
):
    """手动触发 feedback 归档/清理 (需登录)."""
    result_holder = {}

    def _run():
        try:
            result_holder["stats"] = cleanup_old_feedback(days=days, archive=archive)
        except Exception as e:
            result_holder["error"] = str(e)

    # 手动 API 同步运行 (用户期望立即看到结果)
    _run()
    if "error" in result_holder:
        raise HTTPException(status_code=500, detail=f"cleanup failed: {result_holder['error']}")
    return JSONResponse(content={
        "ok": True,
        "days": days,
        "archive": archive,
        "stats": result_holder["stats"],
    })


