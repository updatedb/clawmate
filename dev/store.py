"""
FeedbackStore — .feedback.json CRUD 纯函数集，无状态。

所有写操作原子化（tmp + os.replace），读不缓存。
所有函数写 journalctl INFO 日志。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
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

# ── 并发写保护 ─────────────────────────────────────────────────────
# 所有读-改-写操作共用此锁，防止并发请求导致 .feedback.json 数据丢失。
_feedback_write_lock = threading.Lock()

# ── 读缓存 ─────────────────────────────────────────────────────────
# key: str(path) → (mtime_ns, parsed_dict)
# 分离锁：读缓存不与写锁竞争，允许并发读。
_feedback_read_cache: dict[str, tuple[int, dict]] = {}
_cache_lock = threading.Lock()
_CACHE_MAX_ENTRIES = 256  # 安全上限，超过则 LRU 淘汰最旧条目


# ── 读 ─────────────────────────────────────────────────────────

def _get_feedback_path(root_id: str, project: str) -> Path:
    """构造 feedback.json 完整路径（存储在 .clawmate/ 目录下）。

    root_id+project 目录存在且包含 .clawmate/ marker → 返回其下 feedback.json
    root_id+project 目录存在但缺少 .clawmate/ marker → 抛出 FileNotFoundError
    root_id+project 目录不存在 → 抛出 FileNotFoundError
    """
    cfg = load_config()
    root_dir = cfg.root_dir(root_id)
    project_dir = root_dir / project
    if not project_dir.is_dir():
        raise FileNotFoundError(f"项目目录不存在: {project_dir}")
    marker = project_dir / ".clawmate"
    if not marker.is_dir():
        raise FileNotFoundError(f"未找到项目 marker，请先运行 'clawmate init': {marker}")
    return marker / "feedback.json"


def _read_feedback(path: Path) -> dict:
    """读取 .feedback.json，优先命中内存缓存（基于 mtime_ns 校验）。"""
    cache_key = str(path)
    _now_ns = path.stat().st_mtime_ns if path.exists() else 0

    with _cache_lock:
        if cache_key in _feedback_read_cache:
            cached_mtime, cached_data = _feedback_read_cache[cache_key]
            if cached_mtime == _now_ns:
                return cached_data

    # 缓存未命中或已过期 → 解析文件
    if not path.exists():
        data = {"items": []}
    else:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            data = {"items": []}

    # 写入缓存
    with _cache_lock:
        # LRU 淘汰：超上限时删除最旧的条目
        if len(_feedback_read_cache) >= _CACHE_MAX_ENTRIES:
            oldest_key = min(
                _feedback_read_cache,
                key=lambda k: _feedback_read_cache[k][0],
            )
            del _feedback_read_cache[oldest_key]
        _feedback_read_cache[cache_key] = (_now_ns, data)

    return data


def _invalidate_cache(path: Path) -> None:
    """写操作后清除指定文件的读缓存。"""
    cache_key = str(path)
    with _cache_lock:
        _feedback_read_cache.pop(cache_key, None)


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
    with _feedback_write_lock:
        return _batch_update_items_locked(root_id, project, updates)


def _batch_update_items_locked(root_id: str, project: str, updates: list[dict]) -> list[dict]:
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
    _ts = datetime.now(CST).isoformat(timespec="seconds")
    if updated:
        _atomic_write(path, root_id, project, items, data.get("last_id", 0))
    logger.info("[batch_update] %s root=%s proj=%s count=%d", _ts, root_id, project, len(updated))
    return updated


def project_abbr(project: str) -> str:
    """从 project 名生成 2 字符缩写。"""
    if not project:
        return "RT"  # 根级文件 fallback
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


def create_items(
    root_id: str,
    project: str,
    file_path: str,
    selections: list[dict],
) -> list[dict]:
    """写入新反馈条目（带并发写锁）。

    selections 每项字段：
    - text (str, 必填) → item.content
    - note (str, 可选) → item.note
    - position (str, 可选) → 直接作为 item.position
    - action (str, 可选) → item.action（由前端根据标签确定）
    - scope (str, 可选) → item.scope（由前端根据标签确定）

    内部去重（同 content + file + note + action 跳过），自增 ID，原子写。
    """
    with _feedback_write_lock:
        return _create_items_locked(root_id, project, file_path, selections)


def _create_items_locked(
    root_id: str,
    project: str,
    file_path: str,
    selections: list[dict],
) -> list[dict]:
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
        note = str(sel.get("note", "")).strip()
        _action_from_sel = str(sel.get("action", "")).strip()
        _scope_from_sel = str(sel.get("scope", "")).strip()
        position = str(sel.get("position", "") or "").strip()

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

        # 去重 key 使用解析后的 action（而非原始可能为空的 selection.action）
        dedup_key = (text, file_path, note, _action)
        if dedup_key in existing_keys:
            continue

        new_id_num = last_id + idx + 1
        item_id = f"FD-{abbr}-{new_id_num:04d}"

        new_items.append({
            "id": item_id,
            "status": "pending",
            "file": file_path,
            "note": note,
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
    """更新反馈条目状态（带并发写锁）。

    Raises:
        ValueError: new_status 不合法
        FileNotFoundError: .feedback.json 不存在
        LookupError: item_id 不存在
    """
    with _feedback_write_lock:
        return _update_item_locked(root_id, project, item_id, new_status, result)


def _update_item_locked(
    root_id: str,
    project: str,
    item_id: str,
    new_status: str,
    result: str = "",
) -> dict:
    if new_status not in FEEDBACK_STATUSES and new_status != "deleted":
        raise ValueError(f"status must be one of {FEEDBACK_STATUSES} or deleted")

    path = _get_feedback_path(root_id, project)
    if not path.exists():
        raise FileNotFoundError(f".feedback.json not found: {path}")

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
    扫描所有 root 下所有 project 的 .feedback.json。
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
                fb_path = entry / ".clawmate" / "feedback.json"
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


def _cleanup_expired(items: list[dict]) -> list[dict]:
    """移除超过阈值的 done/failed/deleted 条目。

    - pending / in_progress 的条目永不清理
    - cleanup_done_after_days ≤ 0 时跳过清理

    Returns: 保留的 items 列表
    """
    cfg = load_config()
    threshold_days = cfg.feedback.cleanup_done_after_days
    if threshold_days <= 0:
        return items  # 禁用清理

    cutoff = datetime.now(CST) - timedelta(days=threshold_days)

    def _parse_ts(ts: str):
        try:
            return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CST)
        except Exception:
            return datetime.min.replace(tzinfo=CST)

    kept = []
    removed = 0
    for item in items:
        status = item.get("status", "")
        if status in ("pending", "in_progress"):
            kept.append(item)  # 永不清理未完成的工作
        elif _parse_ts(item.get("updated", "")) >= cutoff:
            kept.append(item)  # 在阈值内保留
        else:
            removed += 1  # 过期，丢弃

    if removed:
        _ts = datetime.now(CST).isoformat(timespec="seconds")
        logger.info(
            "[cleanup] %s removed=%d kept=%d threshold=%dd",
            _ts, removed, len(kept), threshold_days,
        )

    return kept


# ── 内部工具 ───────────────────────────────────────────────────────

def _atomic_write(path: Path, root_id: str, project: str, items: list, last_id: int) -> None:
    """原子写 feedback.json（tmp + os.replace），写入前清理过期条目。"""
    # Ensure parent .clawmate/ directory exists
    path.parent.mkdir(parents=True, exist_ok=True)
    # 清理过期 done/failed/deleted
    items = _cleanup_expired(items)

    ts = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    data = {
        "root": root_id,
        "project": project,
        "updated": ts,
        "last_id": last_id,
        "items": items,
    }
    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)
    # 写后失效缓存，下一次读取会重新解析
    _invalidate_cache(path)
