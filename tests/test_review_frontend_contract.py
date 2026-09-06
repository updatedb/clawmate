from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_preview_uses_review_gate_not_direct_task_run_for_feedback_submission():
    source = (ROOT / "dev/static/js/preview.js").read_text(encoding="utf-8")
    assert source.count("/api/clawmate/task/run") == 1
    assert "review_task_id" in source
    assert "待评审" in source
    assert "已评审" in source
    assert "已拒绝" in source
    assert "已执行" in source
    assert "/api/clawmate/review/confirm" in source


def test_preview_review_panel_has_3row_layout_and_review_actions():
    """评审面板 (logged-in) must use the unified 3-row layout: title/toolbar row,
    a 6-state filter row, and a card list with per-card 评审通过/评审拒绝."""
    js = (ROOT / "dev/static/js/preview.js").read_text(encoding="utf-8")
    html = (ROOT / "dev/static/preview.html").read_text(encoding="utf-8")
    for label in ("待提交", "已提交", "待评审", "已评审", "已拒绝", "已执行"):
        assert label in js
    # 3-row layout structural hooks: title/toolbar row + filter row + list body
    assert "previewFilterBar" in html
    assert "previewActionsBar" in html
    assert "feedbackBody" in html
    # toolbar buttons live in the title row and are wired in JS
    assert "btnReviewAdd" in js
    assert "btnReviewSubmit" in js
    assert "btnReviewExec" in js
    assert "btnReviewAdd" in html
    assert "btnReviewSubmit" in html
    assert "btnReviewExec" in html
    # per-card review actions
    assert "评审通过" in js
    assert "评审拒绝" in js
    assert "请求完善" in js
    # reviewer may only complete the requested items, not alter selected content/scope
    assert "仅完善请求事项" in js or "不改动选中内容" in js or "不能修改选中的内容" in js


def test_share_view_exposes_feedback_but_not_review_or_execution_controls():
    source = (ROOT / "dev/static/share-view.html").read_text(encoding="utf-8")
    assert "/feedback" in source
    assert "提交反馈" in source
    assert "添加反馈" in source
    assert "待提交" in source
    assert "已提交" in source
    assert "/api/clawmate/review/" not in source
    assert "/api/clawmate/task/run" not in source
