"""
Feedback Schema — 标准数据结构定义。

.feedback.json 保存反馈和任务；不可变审计事件保存在并列的
.feedback.audit.jsonl。API 层使用 canonical 字段，不做位置字段翻译。
"""

from __future__ import annotations

# 合法状态值
FEEDBACK_STATUSES = (
    "pending_review", "approved", "rejected", "planned",
    "in_progress", "executed", "failed", "needs_attention",
    # Legacy values remain readable and are normalized on read.
    "pending", "done",
)
