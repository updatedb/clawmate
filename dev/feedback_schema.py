"""
Feedback Schema — 标准数据结构定义。

.feedback.json 是唯一权威存储，所有 API 层直接透传字段，
不做重命名翻译。

Usage:
    from feedback_schema import (
        FEEDBACK_ITEM_FIELDS,    # item 标准字段
        FEEDBACK_TOP_FIELDS,     # 顶层字段
        FEEDBACK_STATUSES,       # 合法状态值
        FEEDBACK_CREATE_FIELDS,  # 创建请求字段
        FEEDBACK_UPDATE_FIELDS,  # 更新请求字段
        FeedbackItem,            # TypedDict
    )
"""

from __future__ import annotations

from typing import TypedDict

# ── 标准字段名（.feedback.json 唯一权威）────────────────────────────

# 顶层字段
FEEDBACK_TOP_FIELDS = ("root", "project", "updated", "last_id", "items", "tasks", "audit")

# item 级字段（API 响应、cron 模板、.feedback.json 全部统一）
FEEDBACK_ITEM_FIELDS = (
    "id",       # FD-{abbr}-{NNNN}
    "status",   # pending_review | approved | rejected | planned | in_progress | executed | failed
    "file",     # 相对路径
    "note",     # 用户备注/指令
    "content",  # 选中原文
    "position", # 定位信息（Line {start}-{end} / Time {HH:MM:SS} 等标准化格式）
    "action",   # delete | modify | explain | simplify | execute | other
    "scope",    # document | project
    "task_id",  # 任务模板标识（如 subtitle_correct, review_delete）
    "updated",  # 更新时间 YYYY-MM-DD HH:MM:SS
    "result",   # 处理结果摘要
    "anchor",   # line + selected text hash + surrounding context
    "audit",    # append-only item event ids (the full log is top-level)
)

# 合法状态值
FEEDBACK_STATUSES = (
    "pending_review", "approved", "rejected", "planned",
    "in_progress", "executed", "failed", "needs_attention",
    # Legacy values remain readable and are normalized on read.
    "pending", "done",
)

# 创建请求字段
FEEDBACK_CREATE_FIELDS = ("root", "project", "path", "selections", "previewUrl")

# 更新请求字段
FEEDBACK_UPDATE_FIELDS = ("root", "project", "id", "status", "result")


# ── TypedDict 定义 ────────────────────────────────────────────────

class FeedbackItem(TypedDict, total=False):
    id: str
    status: str
    file: str
    note: str
    content: str
    position: str
    action: str
    scope: str
    task_id: str
    updated: str
    result: str
    impact: str
    failure_reason: str
    failure_stage: str
    anchor: dict
    source: str
    author: str
    share_token_id: str
