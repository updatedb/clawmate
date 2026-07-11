"""
Task Runner — 统一 AI 任务执行入口。

将 feedback 和 AI 自定义任务（字幕纠错等）统一到 task_templates 体系管理。

Routes:
    POST /api/clawmate/task/run — 执行任务（支持单条/批量 selections）
"""

from __future__ import annotations

import logging
import shlex
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


def _render_prompt_text(text: str, variables: dict) -> str:
    """替换文本中的 {var} 占位符。"""
    for key, value in variables.items():
        text = text.replace("{" + key + "}", str(value))
    return text


@router.post("/api/clawmate/task/run", response_class=JSONResponse)
async def task_run(request: Request):
    """执行一个或多个 AI 任务。

    统一入参格式（selections 数组）:
      {
        "root": "writer",
        "file": "project/path/file.mp3",
        "project": "",                    // 可选，省略时从 file 推断
        "selections": [
          {
            "task_id": "subtitle_correct",
            "content": "原始 SRT",
            "srt_path": "path/to/file.srt",
            "note": "",                    // 可选，有则覆盖模板 agent_prompt
            "position": ""
          },
          {
            "task_id": "review_modify",
            "content": "需要修改的文本",
            "note": "用户修改说明",
            "position": "Section #xxx"
          }
        ]
      }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    root_id = str(body.get("root", "")).strip()
    file_path = str(body.get("file", "")).strip()
    project = str(body.get("project", "")).strip()
    raw_selections = body.get("selections", [])

    if not root_id or not file_path:
        raise HTTPException(status_code=422, detail="Missing root/file")
    if not raw_selections or not isinstance(raw_selections, list):
        raise HTTPException(status_code=422, detail="Missing selections")

    # 校验 root_id 合法性（是否在 config.json 中注册）
    from config import load as _cfg
    try:
        _cfg().root_dir(root_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=f"Root not found: {root_id}")

    # 校验 file_path 合法性（文件必须存在）
    from pathlib import Path as _Path
    full_path = _cfg().root_dir(root_id).expanduser().resolve() / file_path.lstrip("/")
    # 禁止路径遍历
    try:
        full_path = full_path.resolve()
        root_path = _cfg().root_dir(root_id).expanduser().resolve()
        if not str(full_path).startswith(str(root_path)):
            raise HTTPException(status_code=422, detail=f"File path traversal detected: {file_path}")
    except Exception:
        raise HTTPException(status_code=422, detail=f"Invalid file path: {file_path}")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    if not project:
        project = file_path.split("/")[0] if "/" in file_path else ""

    # 文件扩展名校验
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""

    # 全局模板变量（body 顶层所有非标准字段）
    global_vars = {"file": file_path}
    for k, v in body.items():
        if k not in ("root", "project", "file", "path", "selections", "sessionKey"):
            global_vars[k] = str(v)

    from store import create_items

    parsed = []
    for sel in raw_selections:
        tid = str(sel.get("task_id", "")).strip()
        if not tid:
            raise HTTPException(status_code=422, detail="Missing task_id in selection")

        template = _get_template(tid)
        if not template:
            raise HTTPException(status_code=404, detail=f"Task template not found: {tid}")

        # 校验文件扩展名
        match_exts = template.match_ext
        if "*" not in match_exts and ext not in match_exts:
            raise HTTPException(
                status_code=422,
                detail=f"File type .{ext} not supported for task {tid}",
            )

        # 标准字段
        content = str(sel.get("content", ""))
        note = str(sel.get("note", ""))
        position = str(sel.get("position", ""))

        # 构建模板变量：全局变量 + 本 selection 的所有非标准字段
        sel_vars = dict(global_vars)
        sel_vars["content"] = content
        sel_vars["position"] = position
        for k, v in sel.items():
            if k not in ("task_id", "content", "note", "position"):
                sel_vars[k] = str(v)

        # note：用户提供则渲染用户输入，否则渲染模板 agent_prompt
        if note.strip():
            rendered_note = _render_prompt_text(note, sel_vars)
        else:
            rendered_note = _render_prompt_text(template.agent_prompt, sel_vars)

        parsed.append({
            "text": content or file_path,  # store 中字段名为 text
            "note": rendered_note,
            "action": template.action,
            "scope": template.scope,
            "task_id": tid,
            "position": position,
        })

    new_items = create_items(root_id, project, file_path, parsed)
    if not new_items:
        raise HTTPException(status_code=409, detail="Task already exists (dedup)")

    ids = [i["id"] for i in new_items]

    # 唤醒 agent
    _wake_agent_for_root(root_id, project=project, file=file_path)

    _ts = datetime.now(CST).isoformat(timespec="seconds")
    logger.info("[task.run] %s root=%s file=%s items=%s", _ts, root_id, file_path, ids)

    return JSONResponse(content={"ok": True, "ids": ids})

# ── Webhook wake 工具 ───────────────────────────────────────────

import threading
import time as time_module
import httpx

from config import load as _config
from store import list_items, scan_all
from pathlib import Path


_action_desc_cache: dict[str, str] | None = None


def _action_desc(task_id: str, fallback_action: str = "") -> str:
    """从 task_template.desc 获取操作描述（模块级缓存，仅首次加载模板）。"""
    global _action_desc_cache
    if _action_desc_cache is None:
        _action_desc_cache = {}
        for t in load_task_templates():
            if t.desc:
                _action_desc_cache[t.id] = t.desc
    return _action_desc_cache.get(task_id, "根据 note 处理")


_last_wake: dict[str, float] = {}
_DEBOUNCE_SECONDS = 60


def _wake_agent_for_root(root_id: str, project: str = "", file: str = "") -> None:
    """读取 config，直接 POST OpenClaw /hooks/agent（后台线程 fire-and-forget）。

    内联 message（不加载模板），防抖 60s 同 root 跳过。
    可传 project + file 缩小 agent 查询范围。
    """
    cfg = _config()
    oc = cfg.openclaw
    hook_token = oc.hook_token
    gateway_url = oc.gateway_url

    if not hook_token:
        logger.warning("[feedback] wake skipped: openclaw.hook_token not configured in config.json")
        return

    # 解析 agent_id
    agent_id = cfg.root_agent(root_id)

    _ts_wake = datetime.now(CST).isoformat(timespec="seconds")
    logger.info("[task.wake] %s start root_id=%s agent_id=%s", _ts_wake, root_id, agent_id)

    # 防抖检查
    now = time_module.time()
    last = _last_wake.get(root_id, 0.0)
    if now - last < _DEBOUNCE_SECONDS:
        logger.info("[task] wake skipped (debounced %ds): root_id=%s", int(now - last), root_id)
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

    # ── 前置验证：按 scope 逐条检查 root/project/file 存在性，失败项直接标记 failed ──
    if items:
        try:
            _root_dir = cfg.root_dir(root_id)
            _failed_updates = []
            _valid_items = []
            for it in items:
                _scope = it.get("scope", "document")
                _item_file = it.get("file", file or "")
                _reason = ""
                if _scope == "document":
                    if _item_file:
                        _full = (_root_dir / _item_file).resolve()
                        if not _full.exists():
                            _reason = f"file={_item_file} 不存在"
                    else:
                        _reason = "缺少 file 字段"
                elif _scope == "project":
                    if project:
                        _proj = _root_dir / project
                        if not _proj.is_dir():
                            _reason = f"project={project} 目录不存在"
                if _reason:
                    _failed_updates.append({"id": it["id"], "status": "failed", "result": _reason})
                else:
                    _valid_items.append(it)
            if _failed_updates:
                from store import batch_update_items as _bui
                _bui(root_id, project, _failed_updates)
                logger.warning("[task.wake] %d items marked failed", len(_failed_updates))
            if not _valid_items:
                return
            items = _valid_items
        except Exception as e:
            logger.warning("[task.wake] validation error, items skipped: %s", e)
            return
        lines = [f"ClawMate 反馈通知：root={root_id}  project={project}  有以下 {len(items)} 条待处理 feedback 需要你执行：", ""]
        for idx, item in enumerate(items):
            item_id = item.get("id", "?")
            task_id = item.get("task_id", "") or item.get("action", "other")
            scope_val = item.get("scope", "document")
            item_file = item.get("file", file or "?")
            content_val = (item.get("content", "") or "")
            note_val = (item.get("note", "") or "")
            position_val = item.get("position", "") or "无"

            lines.append(f"{idx+1}. [{item_id}] task_id={task_id} action={item.get('action','?')} scope={scope_val}")
            _display_file = str((_root_dir / item_file).resolve()) if item_file and item_file != '?' else item_file
            lines.append(f"   file: {_display_file}")
            lines.append(f"   position: {position_val}")
            lines.append(f"   content: {content_val}")
            lines.append(f"   note: {note_val}")
            _desc = _action_desc(task_id, item.get("action", "other"))
            lines.append(f"   操作：{_desc}")
            lines.append("")
        lines.append(f"步骤：")
        lines.append(f"0. 【效率优先】position 已标注目标位置（Section xxx / Line xxx），先用 grep 定位 position 得到行号范围，仅读取该范围内的内容匹配 content，避免全文件读取")
        lines.append(f"1. 开始执行前，POST {base_url}/api/clawmate/feedback/batch-update 将所有 items 的 status 设为 in_progress，result 留空")
        lines.append(f"   认证: Header X-Internal-Token: {hook_token}")
        lines.append(f"2. 逐个执行 item，冲突或重复项标记 status=failed")
        lines.append(f"3. 执行完成后，再次 POST batch-update 更新最终 status（done/failed）和 result（同样带上认证 Header）")
        lines.append(f"请求体格式: root={root_id}, project={project}, items=[{{id, status, result}}]")
        lines.append(f"")
        lines.append(f"⚠️ 安全约束：")
        lines.append(f"- 所有操作只在本地文件系统完成（不访问远程目录 / 远程系统）")
        lines.append(f"- 所有操作基于 {root_id} 指向的目录；file 已给出绝对路径（已验证存在），scope=project 时 project 必须存在，不存在直接标记 status=failed")
        lines.append(f"- 禁止创建或删除任何文件/目录（包括临时文件）")
        lines.append(f"- 禁止修改配置文件和项目配置（config.json, config.example.json, .gitignore 等）")
        message = "\n".join(lines)
    else:
        message = f"ClawMate 反馈通知：{scope} 目前无待处理 feedback。"
    run_name = f"clawmate-fb-{root_id}"

    # ── 优先后台子进程执行 ──
    if items:
        try:
            from agent_routes import spawn_background_agent, resolve_session_cwd

            cwd = resolve_session_cwd(root_id, file)
            ok = spawn_background_agent(
                message=message,
                cwd=cwd,
                backend="claude",
                extra_env=cfg.agent.env,
            )
            if ok:
                _ts_end = datetime.now(CST).isoformat(timespec="seconds")
                logger.info(
                    "[task.wake] %s background agent spawned root_id=%s agent_id=%s items=%d",
                    _ts_end, root_id, agent_id, len(items),
                )
                return
        except ImportError:
            pass  # agent_routes not available (e.g. test context)
        except Exception as e:
            logger.warning("[task.wake] background agent spawn failed, falling back to webhook: %s", e)

    # ── 回退：通过 webhook 发送给 OpenClaw gateway ──
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
                    "[task.wake] %s success root_id=%s agent_id=%s run_name=%s run_id=%s",
                    _ts_end, root_id, agent_id, run_name, data.get("runId", ""),
                )
            else:
                _ts_end = datetime.now(CST).isoformat(timespec="seconds")
                logger.warning(
                    "[task.wake] %s failed root_id=%s agent_id=%s HTTP=%d body=%s",
                    _ts_end, root_id, agent_id, r.status_code, r.text[:200],
                )
        except Exception as e:
            _ts_end = datetime.now(CST).isoformat(timespec="seconds")
            logger.warning(
                "[task.wake] %s error root_id=%s agent_id=%s: %s",
                _ts_end, root_id, agent_id, e,
            )

    threading.Thread(target=_do_wake_sync, daemon=True).start()


# ── 路由 ─────────────────────────────────────────────────────────────

@router.post("/api/clawmate/feedback/cron-tick")
async def cron_tick():
    """cron 入口：扫所有 root 下各 project 的 pending feedback，逐 project 唤醒 agent。

    scan_all() 只统计 pending 总数，但 _wake_agent_for_root() 需要 project 参数
    才能读到正确的 project 级 .clawmate/feedback.json。这里走逐 project 扫描。
    """
    cfg = _config()
    total_pending = 0
    total_woken = 0
    errors = 0
    for root in cfg.roots:
        root_dir = Path(root.dir).expanduser().resolve()
        if not root_dir.is_dir():
            continue
        for entry in sorted(root_dir.iterdir()):
            if not entry.is_dir():
                continue
            fb_path = entry / ".clawmate" / "feedback.json"
            if not fb_path.exists():
                continue
            proj = entry.name
            try:
                _, pending = list_items(root.id, proj, status="pending")
            except (ValueError, FileNotFoundError):
                continue
            if pending > 0:
                total_pending += pending
                _wake_agent_for_root(root.id, project=proj)
                total_woken += 1
    logger.info(
        "[cron-tick] pending=%d woken=%d roots=%d errors=%d",
        total_pending, total_woken, len(cfg.roots), errors,
    )
    return {"ok": True}
