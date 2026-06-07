"""
FeedbackStore — feedback.json CRUD 纯函数集，无状态。

所有写操作原子化（tmp + os.replace），读不缓存。
所有函数写 journalctl INFO 日志。
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from feedback_schema import FEEDBACK_STATUSES
from config import load as load_config

logger = logging.getLogger("clawmate.feedback")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setLevel(logging.INFO)
    _h.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

CST = timezone(timedelta(hours=8))


# ── 读 ─────────────────────────────────────────────────────────

def _get_feedback_path(root_id: str, project: str) -> Path:
    """构造 feedback.json 完整路径。"""
    cfg = load_config()
    root_dir = cfg.root_dir(root_id)
    project_dir = root_dir / project
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir / "feedback.json"


def _read_feedback(path: Path) -> dict:
    """读取 feedback.json，返回标准 dict。"""
    if not path.exists():
        return {"items": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {"items": []}


def list_items(
    root_id: str,
    project: str,
    status: str = "",
    file: str = "",
    since: str = "",
) -> tuple[list[dict], int]:
    """
    列出指定 project 的反馈条目。

    Args:
        status: ""=全部 | "all"=全部 | "pending"/"done" 等
        file: 文件名模糊匹配
        since: "today" | "YYYY-MM-DD"

    Returns:
        (items[], total_pending)
    """
    path = _get_feedback_path(root_id, project)
    data = _read_feedback(path)
    items = list(data.get("items", []))

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

    pending = sum(1 for i in items if i.get("status") == "pending")
    return items, pending


# ── 写 ─────────────────────────────────────────────────────────

def batch_update_items(root_id: str, project: str, updates: list[dict]) -> list[dict]:
    """批量更新 feedback item 状态。

    updates: [{id, status, result}, ...]
    逐项更新，失败项不阻断后续。
    返回实际更新的 items 列表。
    """
    path = _get_feedback_path(root_id, project)
    data = _read_feedback(path)
    items = data.get("items", [])
    id_map = {item.get("id"): item for item in items}
    updated = []
    now = str(datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"))
    for upd in updates:
        item_id = upd.get("id", "")
        if item_id not in id_map:
            logger.warning("[batch_update] item not found: %s", item_id)
            continue
        item = id_map[item_id]
        new_status = upd.get("status", "")
        if new_status and new_status in FEEDBACK_STATUSES:
            item["status"] = new_status
        if "result" in upd:
            item["result"] = upd["result"]
        item["updated"] = now
        updated.append(item)
    if updated:
        _atomic_write(path, root_id, project, items, data.get("last_id", 0))
        _ts = datetime.now(CST).isoformat(timespec="seconds")
    logger.info("[batch_update] %s root=%s proj=%s count=%d", _ts, root_id, project, len(updated))
    return updated


def project_abbr(project: str) -> str:
    """从 project 名生成 2 字符缩写。"""
    # 先查 config.json 自定义缩写
    try:
        cfg = load_config()
        raw = json.loads(Path(cfg.root_dir("webprojects")).read_bytes())
    except Exception:
        raw = {}
    custom = (raw.get("projects") or {}).get(project, {}).get("abbr", "")
    if len(custom) >= 2:
        return custom[:2].upper()
    # 自动生成
    parts = re.split(r"[-_]", project)
    if len(parts) >= 2:
        return "".join(p[0].upper() for p in parts[:2])
    camel = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|$)", project)
    if len(camel) >= 2:
        return "".join(c[0].upper() for c in camel[:2])
    n = len(project)
    return (project[0] + project[n // 2]).upper()


def _detect_position_prefix(file_path: str) -> str:
    """根据文件扩展名返回 position 格式前缀。"""
    ext = file_path.rsplit('.', 1)[-1].lower() if '.' in file_path else ''
    if ext in ('txt', 'py', 'js', 'ts', 'jsx', 'tsx', 'html', 'css', 'scss', 'less',
               'json', 'xml', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf',
               'sh', 'bash', 'zsh', 'fish', 'bat', 'ps1',
               'c', 'cpp', 'h', 'hpp', 'java', 'go', 'rs', 'rb', 'php',
               'sql', 'r', 'lua', 'pl', 'swift', 'kt', 'dart', 'scala',
               'vue', 'svelte', 'astro', 'ejs', 'hbs', 'mdx'):
        return 'Line'
    if ext in ('md', 'rmd'):
        return 'Section'
    if ext in ('docx', 'doc', 'pptx', 'ppt', 'pdf', 'odt', 'odp'):
        return 'Page'
    if ext in ('xlsx', 'xls', 'csv', 'tsv'):
        return 'Range'
    if ext in ('srt', 'vtt', 'ass', 'ssa', 'sub'):
        return 'Time'
    if ext in ('mp3', 'mp4', 'wav', 'webm', 'ogg', 'flac', 'aac',
               'm4a', 'mov', 'avi', 'mkv', 'wmv', 'flv'):
        return 'Time'
    if ext in ('png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'svg', 'ico'):
        return 'Area'
    return 'Line'


def create_items(
    root_id: str,
    project: str,
    file_path: str,
    selections: list[dict],
) -> list[dict]:
    """
    写入新反馈条目。

    selections 每项字段：
    - text (str, 必填) → item.content
    - note (str, 可选) → item.note
    - startLine/endLine (int, 可选) → 根据文件类型拼成标准化 position
    - position (str, 可选) → 直接作为 item.position
    - action (str, 可选) → item.action（由前端根据标签确定）
    - scope (str, 可选) → item.scope（由前端根据标签确定）

    内部去重（同 content + file + note + action 跳过），自增 ID，原子写。
    """
    path = _get_feedback_path(root_id, project)
    data = _read_feedback(path)
    items = list(data.get("items", []))
    last_id = data.get("last_id", 0) if isinstance(data, dict) else 0
    ts = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    abbr = project_abbr(project)

    # 去重：content + file + note + action 都相同才算重复
    existing_keys = {
        (item.get("content", ""), item.get("file", ""), item.get("note", ""), item.get("action", ""))
        for item in items
        if item.get("status") != "deleted"
    }

    new_items = []
    for idx, sel in enumerate(selections):
        text = str(sel.get("text", "")).strip()
        if not text:
            continue
        note = str(sel.get("note", "")).strip()
        _action_from_sel = str(sel.get("action", "")).strip()
        _scope_from_sel = str(sel.get("scope", "")).strip()
        dedup_key = (text, file_path, note, _action_from_sel)
        if dedup_key in existing_keys:
            continue
        position = str(sel.get("position", "") or "").strip()
        if not position:
            start_line = sel.get("startLine")
            end_line = sel.get("endLine")
            if start_line and end_line:
                position = f"{prefix} {start_line}-{end_line}"

        new_id_num = last_id + idx + 1
        item_id = f"FD-{abbr}-{new_id_num:04d}"

        # action/scope：优先使用前端传入值，降级到从 note 匹配标签
        _action, _scope = _action_from_sel, _scope_from_sel
        if not _action or not _scope:
            if note:
                try:
                    from config import load_task_templates
                    for tt in load_task_templates():
                        if note.strip().startswith(tt.agent_prompt):
                            _action = _action or tt.action
                            _scope = _scope or tt.scope
                            break
                except Exception:
                    pass
            if not _action:
                _action = "other"
            if not _scope:
                _scope = "document"

        new_items.append({
            "id": item_id,
            "status": "pending",
            "file": file_path,
            "note": note or text[:80],
            "content": text,
            "position": position,
            "action": _action,
            "scope": _scope,
            "task_id": str(sel.get("task_id", "")).strip(),
            "updated": ts,
            "result": "",
        })
        existing_keys.add(dedup_key)

    if not new_items:
        return []

    items.extend(new_items)
    _atomic_write(path, root_id, project, items, max(last_id, new_id_num))

    _ts = datetime.now(CST).isoformat(timespec="seconds")
    logger.info(
        "[store.create] %s root=%s project=%s file=%s new=%d total=%d",
        _ts, root_id, project, file_path, len(new_items), len(items),
    )
    return new_items


def update_item(
    root_id: str,
    project: str,
    item_id: str,
    new_status: str,
    result: str = "",
) -> dict:
    """
    更新反馈条目状态。

    Raises:
        ValueError: new_status 不合法
        FileNotFoundError: feedback.json 不存在
        LookupError: item_id 不存在
    """
    if new_status not in FEEDBACK_STATUSES and new_status != "deleted":
        raise ValueError(f"status must be one of {FEEDBACK_STATUSES} or deleted")

    path = _get_feedback_path(root_id, project)
    if not path.exists():
        raise FileNotFoundError(f"feedback.json not found: {path}")

    data = _read_feedback(path)
    items = list(data.get("items", []))
    ts = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

    updated_item = None
    for item in items:
        if item.get("id") == item_id:
            item["status"] = new_status
            item["updated"] = ts
            if result:
                item["result"] = result
            updated_item = dict(item)
            break

    if updated_item is None:
        raise LookupError(f"Item {item_id} not found")

    _atomic_write(path, root_id, project, items, data.get("last_id", 0))

    _ts = datetime.now(CST).isoformat(timespec="seconds")
    logger.info(
        "[store.update] %s root=%s project=%s id=%s status=%s",
        _ts, root_id, project, item_id, new_status,
    )
    return updated_item


# ── 扫描 ──────────────────────────────────────────────────────────


class ScanResult:
    checked_roots: int = 0
    pending_total: int = 0
    pending_roots: list[str] = []
    errors: list[str] = []


def scan_all() -> ScanResult:
    """
    扫描所有 root 下所有 project 的 feedback.json。
    不抛异常（错误收集到 return.errors）。
    """
    result = ScanResult()
    try:
        cfg = load_config()
    except Exception as e:
        result.errors.append(f"load config: {e}")
        return result

    for root in cfg.roots:
        root_dir = Path(root.dir).expanduser().resolve()
        if not root_dir.is_dir():
            continue
        try:
            for entry in root_dir.iterdir():
                if not entry.is_dir():
                    continue
                fb_path = entry / "feedback.json"
                if not fb_path.exists():
                    continue
                result.checked_roots += 1
                data = _read_feedback(fb_path)
                items = data.get("items", [])
                pending = sum(1 for i in items if i.get("status") == "pending")
                if pending > 0:
                    result.pending_total += pending
                    if root.id not in result.pending_roots:
                        result.pending_roots.append(root.id)
        except Exception as e:
            result.errors.append(f"scan {root.id}: {e}")

    return result


# ── 内部工具 ───────────────────────────────────────────────────────

def _atomic_write(path: Path, root_id: str, project: str, items: list, last_id: int) -> None:
    """原子写 feedback.json（tmp + os.replace）。"""
    ts = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    data = {
        "root": root_id,
        "project": project,
        "updated": ts,
        "last_id": last_id,
        "items": items,
    }
    tmp_path = path.with_suffix(".feedback.json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)
