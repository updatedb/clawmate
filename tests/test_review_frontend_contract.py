from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_preview_uses_review_gate_not_direct_task_run_for_feedback_submission():
    """任何 /task/run 都必须在 review/confirm 之后、且带 review_task_id 走门禁。"""
    source = (ROOT / "dev/static/js/preview.js").read_text(encoding="utf-8")
    assert "/api/clawmate/review/confirm" in source
    assert "review_task_id" in source
    assert source.count("/api/clawmate/task/run") >= 1
    assert source.count("/api/clawmate/review/confirm") >= 1
    for label in ("待提交", "待评审", "已评审", "已拒绝", "已执行"):
        assert label in source


def test_preview_review_panel_has_3row_layout_and_review_actions():
    """评审面板：3-row layout, 5-state filter, 已取消(deleted) in 已执行, editable 待评审,
    read-only 已评审 with ✕ delete + 执行反馈, no multi-select checkboxes."""
    js = (ROOT / "dev/static/js/preview.js").read_text(encoding="utf-8")
    html = (ROOT / "dev/static/preview.html").read_text(encoding="utf-8")
    for label in ("待提交", "待评审", "已评审", "已拒绝", "已执行"):
        assert label in js
    assert "previewFilterBar" in html
    assert "previewActionsBar" in html
    assert "feedbackBody" in html
    for bid in ("btnReviewAdd", "btnReviewSubmit", "btnReviewExec"):
        assert bid in js and bid in html
    # 已取消 = deleted; deleted is grouped under 已执行
    assert "已取消" in js
    assert "deleted" in js
    # 待评审 editable; 已评审 read-only + ✕ delete + 执行反馈; no multi-select
    assert "评审通过" in js
    assert "评审拒绝" in js
    assert "执行反馈" in js
    # 需求7: no checkbox multi-select in the review panel
    assert "type = 'checkbox'" not in js.split("buildReviewCard")[1].split("return card")[0]


def test_share_view_exposes_feedback_but_not_review_or_execution_controls():
    """分享页反馈面板：图标反馈按钮(在大纲后), 图标操作按钮, 无独立 note 输入框,
    浮窗 加入待办/提交评审; 不暴露 review/task 控制."""
    source = (ROOT / "dev/static/share-view.html").read_text(encoding="utf-8")
    assert "/feedback" in source
    assert "提交评审" in source
    assert "加入待办" in source
    assert "待提交" in source
    assert "已提交" in source
    # 反馈按钮是图标且在大纲之后
    assert 'id="btnShareFeedback"' in source
    assert 'id="btnToggleToc"' in source
    assert source.index('id="btnToggleToc"') < source.index('id="btnShareFeedback"')
    # 独立 note 输入框已移除
    assert "shareFbNote" not in source
    assert "share-fb-toolbar" not in source
    assert "/api/clawmate/review/" not in source
    assert "/api/clawmate/task/run" not in source
