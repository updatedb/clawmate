"""
Feedback Schema — 标准数据结构定义。

feedback.json 是唯一权威存储，所有 API 层直接透传字段，
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

# ── 标准字段名（feedback.json 唯一权威）────────────────────────────

# 顶层字段
FEEDBACK_TOP_FIELDS = ("root", "project", "updated", "last_id", "items")

# item 级字段（API 响应、cron 模板、feedback.json 全部统一）
FEEDBACK_ITEM_FIELDS = (
    "id",       # FD-{abbr}-{NNNN}
    "status",   # pending | in_progress | done | failed
    "file",     # 相对路径
    "note",     # 用户备注/指令
    "content",  # 选中原文
    "position", # 定位信息（L20-30 / 时间戳）
    "updated",  # 更新时间 YYYY-MM-DD HH:MM:SS
    "result",   # 处理结果摘要
)

# 合法状态值
FEEDBACK_STATUSES = ("pending", "in_progress", "done", "failed")

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
    updated: str
    result: str
