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
import hashlib
import uuid
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


class ExecutionResultValidationError(ValueError):
    """A callback contract error with safe, caller-actionable diagnostics."""

    def __init__(self, detail: str, *, expected_ids: set[str] | None = None,
                 received_ids: set[str] | None = None, field_errors: list[str] | None = None):
        super().__init__(detail)
        expected_ids = expected_ids or set()
        received_ids = received_ids or set()
        self.missing_ids = sorted(expected_ids - received_ids)
        self.extra_ids = sorted(received_ids - expected_ids)
        self.field_errors = field_errors or []

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


def _get_audit_path(feedback_path: Path) -> Path:
    """The append-only audit is deliberately independent of feedback.json."""
    return feedback_path.with_name("feedback.audit.jsonl")


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

    # Read compatibility: old files used pending/done. Do not mutate the file
    # merely by reading it; every writer persists the normalized vocabulary.
    for item in data.get("items", []):
        if item.get("status") == "pending":
            item["status"] = "pending_review"
        elif item.get("status") == "done":
            item["status"] = "executed"
    data.setdefault("tasks", [])
    # Read compatibility only: older callers may inspect an empty audit list.
    # Writers never persist this key unless journal I/O is degraded.
    data.setdefault("audit", [])
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
    # Normalize old on-disk records at the API boundary as well as on create:
    # callers always receive the canonical `position` field.
    items = [
        {**item, "position": str(item.get("position") or item.get("location") or "").strip()}
        for item in data.get("items", [])
    ]

    if status and status != "all":
        items = [i for i in items if i.get("status") == status]
    if file:
        query_path = _normalize_feedback_path(file)
        items = [i for i in items if _feedback_paths_match(query_path, i.get("file", ""))]
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

    pending = sum(1 for i in items if i.get("status") in ("pending_review", "pending"))
    return items, pending


def _normalize_feedback_path(value: str) -> str:
    """Normalize UI and stored paths before comparing feedback targets."""
    return "/".join(part for part in str(value or "").replace("\\", "/").split("/") if part and part != ".")


def _feedback_paths_match(query_path: str, stored_path: str) -> bool:
    """Match equivalent root-relative paths even when one side has a project prefix."""
    stored = _normalize_feedback_path(stored_path)
    if not query_path or not stored:
        return not query_path
    return query_path == stored or query_path.endswith("/" + stored) or stored.endswith("/" + query_path)


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
        _append_audit(data, "batch_status_update", item_ids=[i["id"] for i in updated])
        _atomic_write(path, root_id, project, items, data.get("last_id", 0), data)
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
        text = str(sel.get("text") or sel.get("content") or "").strip()
        note = str(sel.get("note", "")).strip()
        _action_from_sel = str(sel.get("action", "")).strip()
        _scope_from_sel = str(sel.get("scope", "")).strip()
        # `position` is canonical; accept legacy `location` so a field-name
        # migration cannot silently discard a locator.
        position = str(sel.get("position") or sel.get("location") or "").strip()

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
            "status": "pending_review",
            "file": file_path,
            "note": note,
            "content": text,
            "content_hash": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "position": position,
            "action": _action,
            "scope": _scope,
            "task_id": str(sel.get("task_id", "")).strip(),
            "updated": ts,
            "created": ts,
            "result": "",
            "source": str(sel.get("source", "internal")),
            "author": str(sel.get("author", "")),
            "share_token_id": str(sel.get("share_token_id", "")),
        })
        existing_keys.add(dedup_key)

    if not new_items:
        return []

    items.extend(new_items)
    _append_audit(data, "feedback_created", item_ids=[i["id"] for i in new_items])
    _atomic_write(path, root_id, project, items, max(last_id, new_id_num), data)

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


def delete_item(root_id: str, project: str, item_id: str) -> None:
    """Permanently remove one feedback item while retaining its audit trail."""
    with _feedback_write_lock:
        path = _get_feedback_path(root_id, project)
        if not path.exists():
            raise FileNotFoundError(f".feedback.json not found: {path}")
        data = _read_feedback(path)
        items = list(data.get("items", []))
        kept = [item for item in items if item.get("id") != item_id]
        if len(kept) == len(items):
            raise LookupError(f"Item {item_id} not found")
        _append_audit(data, "feedback_deleted", item_ids=[item_id])
        _atomic_write(path, root_id, project, kept, data.get("last_id", 0), data)
        logger.info("[store.delete] %s root=%s project=%s id=%s",
                    datetime.now(CST).isoformat(timespec="seconds"), root_id, project, item_id)


def _update_item_locked(
    root_id: str,
    project: str,
    item_id: str,
    new_status: str,
    result: str = "",
) -> dict:
    if new_status == "pending":
        new_status = "pending_review"
    elif new_status == "done":
        new_status = "executed"
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

    _append_audit(data, f"status_{new_status}", item_ids=[item_id], detail={"result": result} if result else None)
    _atomic_write(path, root_id, project, items, data.get("last_id", 0), data)

    _ts = datetime.now(CST).isoformat(timespec="seconds")
    logger.info(
        "[store.update] %s root=%s project=%s id=%s status=%s",
        _ts, root_id, project, item_id, new_status,
    )
    return updated_item


# ── Review workflow ──────────────────────────────────────────────

def review_items(root_id: str, project: str, item_ids: list[str], decision: str,
                 reason: str = "") -> list[dict]:
    """Approve or reject pending review items; no execution happens here."""
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be approved or rejected")
    with _feedback_write_lock:
        path = _get_feedback_path(root_id, project)
        data = _read_feedback(path)
        wanted = set(item_ids)
        changed = []
        for item in data["items"]:
            if item.get("id") not in wanted:
                continue
            if item.get("status") != "pending_review":
                raise ValueError(f"{item.get('id')} is not pending review")
            item["status"] = decision
            item["updated"] = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
            if reason:
                item["review_reason"] = reason
            changed.append(dict(item))
        if len(changed) != len(wanted):
            raise LookupError("one or more review items were not found")
        _append_audit(data, "review_approved" if decision == "approved" else "review_rejected",
                      item_ids=item_ids, detail={"reason": reason} if reason else None)
        _atomic_write(path, root_id, project, data["items"], data.get("last_id", 0), data)
        return changed


def create_execution_plan(root_id: str, project: str, item_ids: list[str]) -> dict:
    """Persist a review-approved execution plan. Confirmation is separate."""
    if not item_ids:
        raise ValueError("missing approved review ids")
    with _feedback_write_lock:
        path = _get_feedback_path(root_id, project)
        data = _read_feedback(path)
        by_id = {i.get("id"): i for i in data["items"]}
        selected = []
        for item_id in item_ids:
            item = by_id.get(item_id)
            if not item:
                raise LookupError(f"Item {item_id} not found")
            if item.get("status") != "approved":
                raise ValueError(f"{item_id} is not approved")
            selected.append(item)
        task_id = f"RV-{uuid.uuid4().hex[:10]}"
        files = sorted({str(i.get("file", "")) for i in selected})
        operations = [{"item_id": i["id"], "task_id": i.get("task_id", ""),
                       "action": i.get("action", "modify"), "file": i.get("file", ""),
                       "content": i.get("content", ""), "content_hash": i.get("content_hash", ""),
                       "position": i.get("position") or i.get("location", ""),
                       "note": i.get("note", "")} for i in selected]
        task = {"id": task_id, "status": "planned", "item_ids": item_ids,
                "files": files, "operations": operations,
                "plan": "Apply the approved review suggestions only to the listed files.",
                "created": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
                "confirmed": False, "result": {"diff": "", "artifacts": [], "checks": [], "summary": ""}}
        data.setdefault("tasks", []).append(task)
        for item in selected:
            item["status"] = "planned"
            item["execution_task_id"] = task_id
            item["updated"] = task["created"]
        _append_audit(data, "execution_plan_created", item_ids=item_ids, task_id=task_id,
                      detail={"files": files, "operations": operations})
        _atomic_write(path, root_id, project, data["items"], data.get("last_id", 0), data)
        return task


def confirm_execution_plan(root_id: str, project: str, task_id: str) -> dict:
    """Internal confirmation gate. Rechecks anchors immediately before run."""
    with _feedback_write_lock:
        path = _get_feedback_path(root_id, project)
        data = _read_feedback(path)
        task = next((t for t in data.get("tasks", []) if t.get("id") == task_id), None)
        if not task:
            raise LookupError(f"Task {task_id} not found")
        if task.get("status") != "planned":
            raise ValueError("task is not awaiting confirmation")
        now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
        task["confirmed"] = True
        task["confirmed_at"] = now
        task["status"] = "confirmed"
        _append_audit(data, "execution_confirmed", item_ids=task["item_ids"], task_id=task_id)
        _atomic_write(path, root_id, project, data["items"], data.get("last_id", 0), data)
        return dict(task)


def create_execution_task(root_id: str, project: str, item_ids: list[str]) -> dict:
    """Atomically reserve approved feedback and start one internal task."""
    if not item_ids or len(set(item_ids)) != len(item_ids):
        raise ValueError("missing or duplicate approved review ids")
    with _feedback_write_lock:
        path = _get_feedback_path(root_id, project)
        data = _read_feedback(path)
        by_id = {i.get("id"): i for i in data.get("items", [])}
        selected = []
        for item_id in item_ids:
            item = by_id.get(item_id)
            if not item:
                raise LookupError(f"Item {item_id} not found")
            if item.get("status") != "approved":
                if item.get("execution_task_id"):
                    raise ValueError(f"{item_id} is already reserved by {item['execution_task_id']}")
                raise ValueError(f"{item_id} is not approved")
            selected.append(item)
        now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
        task_id = f"RV-{uuid.uuid4().hex[:10]}"
        files = sorted({str(i.get("file", "")) for i in selected})
        operations = [{"item_id": i["id"], "feedback_id": i["id"], "task_id": i.get("task_id", ""),
                       "action": i.get("action", "modify"), "file": i.get("file", ""),
                       "content": i.get("content", ""), "content_hash": i.get("content_hash", ""),
                       "position": i.get("position") or i.get("location", ""),
                       "note": i.get("note", "")} for i in selected]
        task = {"id": task_id, "status": "in_progress", "item_ids": list(item_ids), "files": files,
                "operations": operations, "plan": "Internal audit plan; executor relocates and merges feedback.",
                "created": now, "started_at": now, "confirmed": True,
                "result": {"diff": "", "artifacts": [], "checks": [], "summary": ""}}
        data.setdefault("tasks", []).append(task)
        for item in selected:
            item["status"] = "in_progress"
            item["execution_task_id"] = task_id
            item["updated"] = now
        _append_audit(data, "execution_task_created", item_ids=list(item_ids), task_id=task_id,
                      detail={"files": files})
        _atomic_write(path, root_id, project, data["items"], data.get("last_id", 0), data)
        return dict(task)


def execution_task(root_id: str, project: str, task_id: str) -> dict:
    path = _get_feedback_path(root_id, project)
    data = _read_feedback(path)
    task = next((t for t in data.get("tasks", []) if t.get("id") == task_id), None)
    if not task:
        raise LookupError(f"Task {task_id} not found")
    return dict(task)


def mark_execution_started(root_id: str, project: str, task_id: str) -> dict:
    with _feedback_write_lock:
        path = _get_feedback_path(root_id, project)
        data = _read_feedback(path)
        task = next((t for t in data.get("tasks", []) if t.get("id") == task_id), None)
        if not task:
            raise LookupError(f"Task {task_id} not found")
        if task.get("status") != "confirmed":
            raise ValueError("task is not confirmed")
        task["status"] = "in_progress"
        task["started_at"] = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
        for item in data["items"]:
            if item.get("id") in set(task.get("item_ids", [])):
                item["status"] = "in_progress"
                item["updated"] = task["started_at"]
        _append_audit(data, "execution_started", item_ids=task["item_ids"], task_id=task_id)
        _atomic_write(path, root_id, project, data["items"], data.get("last_id", 0), data)
        return dict(task)


def record_execution_result(root_id: str, project: str, task_id: str, *, success: bool,
                            summary: str, diff: str = "", artifacts: list | None = None,
                            checks: list | None = None, outcomes: list | None = None) -> dict:
    """Persist real execution evidence supplied by the executor; never invent it."""
    with _feedback_write_lock:
        path = _get_feedback_path(root_id, project)
        data = _read_feedback(path)
        task = next((t for t in data.get("tasks", []) if t.get("id") == task_id), None)
        if not task:
            raise LookupError(f"Task {task_id} not found")
        if task.get("status") != "in_progress":
            raise ValueError("task is not executing")
        expected = set(task.get("item_ids", []))
        if not isinstance(outcomes, list):
            raise ExecutionResultValidationError("outcomes must be an array with one entry per feedback_id",
                                                 expected_ids=expected,
                                                 field_errors=["outcomes: expected array"])
        field_errors = []
        outcome_map = {}
        received_ids = set()
        for index, outcome in enumerate(outcomes):
            prefix = f"outcomes[{index}]"
            if not isinstance(outcome, dict):
                field_errors.append(f"{prefix}: expected object")
                continue
            feedback_id = outcome.get("feedback_id", outcome.get("id"))
            if not isinstance(feedback_id, str) or not feedback_id.strip():
                field_errors.append(f"{prefix}.feedback_id: expected non-empty string")
                continue
            feedback_id = feedback_id.strip()
            if feedback_id in received_ids:
                field_errors.append(f"{prefix}.feedback_id: duplicate {feedback_id}")
                continue
            received_ids.add(feedback_id)
            status = outcome.get("status")
            if status not in ("executed", "failed", "needs_attention"):
                field_errors.append(f"{prefix}.status: expected executed, failed, or needs_attention")
            for field in ("impact", "result", "failure_reason", "failure_stage"):
                if field in outcome and not isinstance(outcome[field], str):
                    field_errors.append(f"{prefix}.{field}: expected string")
            outcome_map[feedback_id] = outcome
        if field_errors or received_ids != expected:
            raise ExecutionResultValidationError(
                "outcomes must contain exactly one valid result for every feedback_id",
                expected_ids=expected, received_ids=received_ids, field_errors=field_errors)
        task["status"] = "executed" if success else "failed"
        task["completed_at"] = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
        task["result"] = {"diff": diff or "", "artifacts": artifacts or [], "checks": checks or [],
                          "summary": summary or ""}
        for item in data["items"]:
            if item.get("id") in set(task.get("item_ids", [])):
                outcome = outcome_map.get(item["id"], {})
                item_status = str(outcome.get("status", task["status"]))
                item["status"] = item_status
                item["impact"] = str(outcome.get("impact", ""))
                item["result"] = str(outcome.get("result", summary or ""))
                item["failure_reason"] = str(outcome.get("failure_reason", ""))
                item["failure_stage"] = str(outcome.get("failure_stage", ""))
                item["updated"] = task["completed_at"]
        _append_audit(data, "execution_completed" if success else "execution_failed",
                      item_ids=task["item_ids"], task_id=task_id,
                      detail={"has_diff": bool(diff), "artifact_count": len(artifacts or []), "checks": checks or []})
        _atomic_write(path, root_id, project, data["items"], data.get("last_id", 0), data)
        return dict(task)


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
    # Review records are evidence.  Never remove review/execution items from
    # the authoritative file; audit history is append-only and must remain
    # explainable even after an execution fails. Cancelled (deleted) items are
    # also kept so they remain visible as 已取消 in the 已拒绝 list.
    if any(i.get("status") in ("pending_review", "approved", "rejected", "planned", "executed", "deleted") for i in items):
        return items
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

def _append_audit(data: dict, event: str, item_ids: list[str] | None = None,
                  task_id: str = "", detail: dict | None = None) -> dict:
    """Append-only audit. Events are never edited or removed by normal writes."""
    record = {
        "id": f"AU-{uuid.uuid4().hex[:12]}",
        "event": event,
        "at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "item_ids": item_ids or [],
        "task_id": task_id,
    }
    if detail:
        record["detail"] = detail
    # Queue under the existing writer lock; _atomic_write flushes this to the
    # independent JSONL journal without making it a feedback availability
    # dependency.
    data.setdefault("_audit_events", []).append(record)
    return record


def _append_audit_records(path: Path, records: list[dict]) -> bool:
    """Best-effort O_APPEND JSONL; bad historic rows are logged and ignored."""
    if not records:
        return True
    try:
        seen: set[str] = set()
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                for number, line in enumerate(f, 1):
                    if not line.strip():
                        continue
                    try:
                        value = json.loads(line)
                        if isinstance(value, dict) and value.get("id"):
                            seen.add(str(value["id"]))
                    except json.JSONDecodeError:
                        logger.warning("[audit.read] bad JSONL line path=%s line=%d", path, number)
        payload = b"".join(
            (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            for record in records if str(record.get("id", "")) not in seen
        )
        if payload:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            try:
                os.write(fd, payload)
                os.fsync(fd)
            finally:
                os.close(fd)
        return True
    except Exception:
        logger.exception("[audit.write] failed path=%s; feedback write continues", path)
        return False


def _atomic_write(path: Path, root_id: str, project: str, items: list, last_id: int,
                  existing: dict | None = None) -> None:
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
    audit_records = []
    if existing:
        # Preserve tasks. Legacy top-level audit is migrated below and omitted
        # from the newly written canonical feedback.json.
        data["tasks"] = existing.get("tasks", [])
        audit_records.extend(existing.get("audit", []) if isinstance(existing.get("audit", []), list) else [])
        audit_records.extend(existing.get("_audit_events", []))
    # Migrate legacy records before dropping their old envelope. If the journal
    # cannot be written, retain them as a degraded compatibility fallback so
    # a transient audit failure never discards history or blocks feedback.
    if not _append_audit_records(_get_audit_path(path), audit_records):
        data["audit"] = audit_records
        logger.warning("[audit.write] retaining compatibility audit in %s", path)
    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)
    # 写后失效缓存，下一次读取会重新解析
    _invalidate_cache(path)
