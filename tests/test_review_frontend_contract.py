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


def test_share_and_review_share_dynamic_action_templates_and_readonly_views():
    """本轮需求：action 动态取后台 task_templates（不写死）、已提交/只读视图压缩、
    已提交隐藏提交评审按钮。"""
    share = (ROOT / "dev/static/share-view.html").read_text(encoding="utf-8")
    js = (ROOT / "dev/static/js/preview.js").read_text(encoding="utf-8")
    # 分享页动态加载 /api/clawmate/config 的 task_templates
    assert "_shareLoadTemplates" in share
    assert "/config" in share
    assert "_shareSelectionTemplates" in share
    # 分享页已提交只读（fb-card-completed + 只读字段），且提交评审按钮按视图显隐
    assert "fb-card-completed" in share
    assert "shareFbSubmit" in share
    assert "classList.toggle('hidden', shareFbFilter" in share
    # 评审面板：待提交/待评审共享统一 action 标签组（动态），只读视图无 textarea
    assert "_buildActionTags" in js
    assert "_taskTemplates" in js
    assert "review-card-content" in js  # 只读视图用 div 展示，非 textarea
    assert "review-card-note" in js
    # 浮窗 action 来源动态，不再写死列表
    assert "match_ext" in js


def test_feedback_cards_follow_status_visibility_order_sorting_and_manual_refresh():
    """Pending cards expose tags; completed cards expose their selected action.
    Lists are newest-first and no feedback list is background-polled."""
    js = (ROOT / "dev/static/js/preview.js").read_text(encoding="utf-8")
    share = (ROOT / "dev/static/share-view.html").read_text(encoding="utf-8")
    css = (ROOT / "dev/static/css/preview.css").read_text(encoding="utf-8")

    assert "var isPendingReview = (item.status === 'pending_review');" in js
    assert "if (!isReadOnly)" in share
    assert "if (isReadOnly)" in share
    assert ".sort(function(a, b)" in js
    assert ".sort(function(a, b)" in share
    assert "setInterval" not in js
    assert "拒绝理由" not in js
    assert "确认删除该反馈" not in js
    assert "closeRightSidebar();" in js
    assert "position: static;" in css


def test_feedback_position_contract_uses_canonical_position_and_visible_fallback():
    """All client submissions normalize legacy location and every card labels an empty locator."""
    js = (ROOT / "dev/static/js/preview.js").read_text(encoding="utf-8")
    share = (ROOT / "dev/static/share-view.html").read_text(encoding="utf-8")
    store = (ROOT / "dev/store.py").read_text(encoding="utf-8")
    share_routes = (ROOT / "dev/share_routes.py").read_text(encoding="utf-8")

    assert "function _feedbackPosition(item)" in js
    assert "return '定位：' + (_feedbackPosition(item) || '—');" in js
    assert "position: _feedbackPosition(item)" in js
    assert "position: _feedbackPosition(it)" in js
    assert "_feedbackPositionLabel(item)" in js
    assert "item.status === 'deleted' ? '已取消'" in js
    assert "function _sharePosition(item)" in share
    assert "'定位：' + (_sharePosition(it) || '—')" in share
    assert "position: _sharePosition(it)" in share
    assert "start_line: it.start_line || it.startLine || 0" in share
    assert "end_line: it.end_line || it.endLine || 0" in share
    assert "scope: it.scope || 'document'" in share
    assert "task_id: it.task_id || ''" in share
    assert 'sel.get("position") or sel.get("location")' in store
    assert 'selection.get("position") or selection.get("location")' in share_routes


def test_share_history_and_panel_state_contracts():
    """Share history uses the token-scoped API; tooltip sends preserve panel state."""
    share = (ROOT / "dev/static/share-view.html").read_text(encoding="utf-8")
    routes = (ROOT / "dev/share_routes.py").read_text(encoding="utf-8")
    assert "'/share/' + TOKEN + '/feedback'" in share
    assert "await _shareLoadSubmitted();" in share
    assert "closeShareFeedback();" not in share[share.index("async function _shareSubmitPending"):share.index("// Selection tooltip logic")]
    assert "syncShareFeedbackButton();" in share[share.index("async function _shareSubmitPending"):share.index("// Selection tooltip logic")]
    assert "syncShareFeedbackButton" in share
    assert "aria-pressed=\"false\"" in share
    assert "_shareStatusLabel(it.status)" in share
    assert "time.textContent = String(it.updated || it.created || '').substring(5,16);" in share
    assert "创建 ' + String(it.created" not in share
    assert "item.get(\"share_token_id\") == token_id" in routes
    assert "_feedback_paths_match(safe_rel, item.get(\"file\", \"\"))" in routes


def test_feedback_card_times_show_only_last_updated_time():
    """Review, completed, and share feedback cards show updated time before created time."""
    js = (ROOT / "dev/static/js/preview.js").read_text(encoding="utf-8")
    share = (ROOT / "dev/static/share-view.html").read_text(encoding="utf-8")

    assert js.count("String(item.updated || item.created || '').substring(5, 16)") >= 3
    assert "function _feedbackStage(item)" not in js
    assert "time.textContent = String(it.updated || it.created || '').substring(5,16);" in share
    assert "创建 ' + String(it.created" not in share
