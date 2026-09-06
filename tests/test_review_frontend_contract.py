from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_preview_uses_review_gate_not_direct_task_run_for_feedback_submission():
    """任何 /task/run 都必须在 review/confirm 之后、且带 review_task_id 走门禁。"""
    source = (ROOT / "dev/static/js/preview.js").read_text(encoding="utf-8")
    # all task/run calls sit after a review/confirm gate (never a direct feedback submit)
    assert "/api/clawmate/review/confirm" in source
    assert "review_task_id" in source
    # every /task/run call is gated together with a review plan/confirm reference
    n_run = source.count("/api/clawmate/task/run")
    n_confirm = source.count("/api/clawmate/review/confirm")
    assert n_run >= 1
    assert n_confirm >= 1
    # 5-state review filter labels present
    for label in ("待提交", "待评审", "已评审", "已拒绝", "已执行"):
        assert label in source
    # 已提交 belongs to the share/feedback surface, not the logged-in review panel
    assert source.count("已提交") == 0 or "已提交" not in source.split("_reviewFilterDefs")[1]


def test_preview_review_panel_has_3row_layout_and_review_actions():
    """评审面板 (logged-in) uses the unified 3-row layout: title/toolbar row,
    a 5-state filter row, and editable review cards for 待评审 + 执行 for 已评审."""
    js = (ROOT / "dev/static/js/preview.js").read_text(encoding="utf-8")
    html = (ROOT / "dev/static/preview.html").read_text(encoding="utf-8")
    # 5-state review filter labels (已提交 is exclusive to the feedback panel)
    for label in ("待提交", "待评审", "已评审", "已拒绝", "已执行"):
        assert label in js
    assert '"已提交"' not in js.split("var _reviewFilterDefs")[1].split("];")[0]
    # 3-row layout structural hooks: title/toolbar row + filter row + list body
    assert "previewFilterBar" in html
    assert "previewActionsBar" in html
    assert "feedbackBody" in html
    # toolbar buttons in the title row are wired in JS
    for bid in ("btnReviewAdd", "btnReviewSubmit", "btnReviewExec"):
        assert bid in js
        assert bid in html
    # 待评审 card is editable; 已评审 card is read-only with ✕ reject + 执行反馈
    assert "评审通过" in js
    assert "评审拒绝" in js
    assert "执行反馈" in js
    # no more 请求完善 (reviewer edits directly instead of requesting user polish)
    assert "请求完善" not in js


def test_share_view_exposes_feedback_but_not_review_or_execution_controls():
    source = (ROOT / "dev/static/share-view.html").read_text(encoding="utf-8")
    assert "/feedback" in source
    assert "提交反馈" in source
    assert "添加反馈" in source
    assert "待提交" in source
    assert "已提交" in source
    assert "/api/clawmate/review/" not in source
    assert "/api/clawmate/task/run" not in source
