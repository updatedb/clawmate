"""Deterministic contracts for browser-side feedback isolation and layout."""

from pathlib import Path
import json
import subprocess

from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth
import feedback_api
import store


ROOT = Path(__file__).parent
SHARE = (ROOT / "static/share-view.html").read_text(encoding="utf-8")
PREVIEW = (ROOT / "static/js/preview.js").read_text(encoding="utf-8")
CSS = (ROOT / "static/css/preview.css").read_text(encoding="utf-8")
ROUTES = (ROOT / "share_routes.py").read_text(encoding="utf-8")


def _execution_payload(**overrides):
    payload = {
        "root": "root", "project": "project", "task_id": "task-1",
        "success": True, "summary": "done", "diff": "", "artifacts": [], "checks": [],
        "outcomes": [
            {"feedback_id": "FB-1", "status": "executed", "impact": "", "result": "done",
             "failure_reason": "", "failure_stage": ""},
            {"feedback_id": "FB-2", "status": "needs_attention", "impact": "", "result": "",
             "failure_reason": "needs review", "failure_stage": "apply"},
        ],
    }
    payload.update(overrides)
    return payload


def _callback_app(monkeypatch, tmp_path, *, token_allowed=False):
    feedback_path = tmp_path / "feedback.json"
    feedback_path.write_text(json.dumps({
        "root": "root", "project": "project", "last_id": 2,
        "items": [{"id": "FB-1", "status": "in_progress"}, {"id": "FB-2", "status": "in_progress"}],
        "tasks": [{"id": "task-1", "status": "in_progress", "item_ids": ["FB-1", "FB-2"]}],
    }), encoding="utf-8")
    monkeypatch.setattr(store, "_get_feedback_path", lambda root, project: feedback_path)
    monkeypatch.setattr(auth, "is_auth_enabled", lambda config=None: True)
    monkeypatch.setattr(auth, "verify_internal_token", lambda request: token_allowed and request.headers.get("X-Internal-Token") == "test-capability")
    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware, config={})
    app.include_router(feedback_api.router)
    return app


def test_review_loading_is_compact_and_does_not_change_document_loading_contract():
    assert ".review-loading {" in CSS
    assert "min-height: 72px;" in CSS
    assert "padding: 18px 12px;" in CSS
    assert ".review-loading::before" in CSS
    assert "@keyframes review-loading-spin" in CSS
    assert ".preview-loading {\n      text-align: center;\n      padding: 80px 20px;" in CSS
    assert ".fb-card-list > .fb-card { margin: 0; width: 100%; }" in CSS


def test_review_result_auth_boundary_allows_loopback_and_token_fallback(monkeypatch, tmp_path):
    # A non-loopback request cannot use the callback without the existing
    # internal capability; a local CLI callback needs no browser session.
    denied = TestClient(_callback_app(monkeypatch, tmp_path, token_allowed=False))
    assert denied.post("/api/clawmate/review/result", json=_execution_payload()).status_code == 401

    loopback = TestClient(_callback_app(monkeypatch, tmp_path, token_allowed=False), client=("127.0.0.1", 43210))
    assert loopback.post("/api/clawmate/review/result", json=_execution_payload()).status_code == 200

    fallback = TestClient(_callback_app(monkeypatch, tmp_path, token_allowed=True))
    assert fallback.post("/api/clawmate/review/result", json=_execution_payload(), headers={"X-Internal-Token": "test-capability"}).status_code == 200


def test_review_result_422_identifies_missing_extra_and_field_type_errors(monkeypatch, tmp_path):
    client = TestClient(_callback_app(monkeypatch, tmp_path), client=("127.0.0.1", 43210))
    payload = _execution_payload(outcomes=[
        {"feedback_id": "FB-1", "status": "executed", "impact": 7, "result": "", "failure_reason": "", "failure_stage": ""},
        {"feedback_id": "FB-X", "status": "bad", "impact": "", "result": "", "failure_reason": "", "failure_stage": ""},
    ])
    response = client.post("/api/clawmate/review/result", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "missing feedback_ids: FB-2" in detail
    assert "unexpected feedback_ids: FB-X" in detail
    assert "outcomes[0].impact: expected string" in detail
    assert "outcomes[1].status: expected executed, failed, or needs_attention" in detail


def test_share_pst_payload_keeps_canonical_position_contract():
    assert '<script src="./js/preview-common.js"></script>' in SHARE
    assert "function _shareSelectionLocation(text, range)" in SHARE
    assert "getFeedbackSelectionPosition({" in SHARE
    assert "getFeedbackPositionPlaceholder" in SHARE
    assert "position: _sharePosition(it)" in SHARE
    assert "start_line: it.start_line" not in SHARE
    assert "return String(item.position || item.location || '').trim();" in SHARE


def test_common_position_contract_has_deterministic_file_type_and_selection_formats():
    """Exercise the actual shared JS instead of only asserting source strings."""
    common = ROOT / "static/js/preview-common.js"
    script = """
const fs = require('fs'), vm = require('vm');
const ctx = { window: {}, document: { querySelector: () => null } };
vm.createContext(ctx); vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const p = ctx.window.getFeedbackSelectionPosition;
function eq(a, b) { if (a !== b) throw new Error(a + ' !== ' + b); }
let line = p({ext:'js', text:'two\\nthree', rawContent:'one\\ntwo\\nthree'});
eq(line.position, 'Line 2-3');
eq(ctx.window.getPosValue('pdf', 2, 3), 'Page 2-3');
eq(ctx.window.getPosValue('xlsx', 2, 3), 'Range A2');
eq(ctx.window.getFeedbackPositionPlaceholder('mp4'), 'Time {HH:MM:SS}');
eq(ctx.window.getFeedbackPositionPlaceholder('png'), 'Area [x,y]xR');
eq(ctx.window.formatFeedbackTime(3723), '01:02:03');
"""
    subprocess.run(["node", "-e", script, str(common)], check=True)


def test_share_nontext_anchor_and_history_keep_canonical_position_contract():
    assert "function _shareOpenManualAnchor(text, position)" in SHARE
    assert "'Page 1'" in SHARE
    assert "'Range A1'" in SHARE
    assert "'Time ' + formatFeedbackTime" in SHARE
    assert "'Area [' + Math.round" in SHARE
    # Toolbar add now creates a card directly; visual/manual anchoring remains
    # available through _shareOpenManualAnchor for image/media interaction.
    assert "_shareOpenManualAnchor('[' + _shareFile + ']', 'Area ['" in SHARE
    assert "_shareOpenManualAnchor('[' + _shareFile + ']', 'Time '" in SHARE
    assert "text: item.content || '', note: item.note || '', position: _sharePosition(item)" in SHARE


def test_share_pending_drafts_are_token_and_file_scoped_and_restored():
    assert "clawmate.share-pending.v1:' + TOKEN + ':' + (_shareFile || '')" in SHARE
    assert "function _sharePersistPending()" in SHARE
    assert "function _shareRestorePending()" in SHARE
    assert "_sharePersistPending();" in SHARE
    assert "_shareRestorePending();" in SHARE
    assert "sharePending = sharePending.filter(function(it){ return !pendingIds.has(it.id); });" in SHARE


def test_share_toolbar_add_creates_and_persists_editable_pending_drafts_for_all_file_types():
    """Toolbar add must not fall back to a selection-only hint or tooltip."""
    add_handler = SHARE.split("function _shareAddPendingDraft(text, location)", 1)[1].split("// 面板「提交评审」", 1)[0]
    assert "sharePending.push({" in add_handler
    assert "_sharePersistPending();" in add_handler
    assert "shareFbFilter = 'pending'; openShareFeedback(); _shareRender();" in add_handler
    assert "_shareAddPendingDraft(text, location);" in add_handler
    assert "请先在正文中选中内容" not in add_handler
    # Keep existing position formats, but create the card instead of opening a
    # separate manual-anchor tooltip from the toolbar.
    for position in ("Page 1", "Range A1", "Time ' + formatFeedbackTime", "Area [0,0]x0"):
        assert position in add_handler
    assert "_shareOpenManualAnchor(" not in add_handler


def test_review_pending_drafts_are_root_project_file_scoped_and_local_only():
    assert "clawmate.review-pending.v1:' + rootId" in PREVIEW
    assert "((filePath || '').split('/')[0] || '') + ':' + filePath" in PREVIEW
    assert "function _persistReviewPending()" in PREVIEW
    assert "function _restoreReviewPending()" in PREVIEW
    assert "_restoreReviewPending();" in PREVIEW
    # The local storage helper is intentionally independent from the POST body.
    assert "localStorage.setItem(_reviewPendingStorageKey(), JSON.stringify(pendingItems))" in PREVIEW


def test_share_history_returns_scoped_canonical_position_and_populated_legacy_location():
    assert 'item.get("share_token_id") == token_id' in ROUTES
    assert "_feedback_paths_match(safe_rel, item.get(\"file\", \"\"))" in ROUTES
    assert 'position = item.get("position") or item.get("location") or ""' in ROUTES
    assert 'if item.get("location"):' in ROUTES
    assert 'response_item["location"] = item["location"]' in ROUTES


def test_feedback_lists_share_scroll_and_card_inset_contract():
    assert ".fb-card-list {" in CSS
    assert "overflow-y: auto;" in CSS
    assert "min-height: 0;" in CSS
    assert ".fb-card-list > .fb-card { margin: 0; width: 100%; }" in CSS
    assert "var cardList = document.createElement('div');" in PREVIEW
    assert "cardList.className = 'fb-card-list';" in PREVIEW
    assert ".share-right .preview-right-body { padding: 0; min-height: 0; }" in SHARE

def test_editable_feedback_cards_have_one_shared_field_order_without_meta():
    """All editable cards share locator/original/feedback/tags/actions order."""
    preview = PREVIEW
    share = SHARE
    css = CSS

    pending = preview.split("function createReviewPendingCard", 1)[1].split("function renderFeedbackPanel", 1)[0]
    reviewing = preview.split("function buildReviewCard", 1)[1].split("// Wire the 3-row toolbar buttons", 1)[0]
    share_card = share.split("function _shareBuildCard(it)", 1)[1].split("// Selection tooltip logic", 1)[0]

    for source in (pending, reviewing, share_card):
        assert "fb-card-position-edit" in source
        assert source.count("fb-note-input") >= 2
        assert "aria-label', '定位（可编辑）'" in source
        assert "aria-label', '原文（可编辑）'" in source
        assert "aria-label', '反馈（可编辑）'" in source
        assert source.index("fb-card-position-edit") < source.index("fb-note-input")
        tags = "pst-tags" if "pst-tags" in source else "_buildActionTags"
        assert source.index("fb-note-input") < source.index(tags) < source.index("fb-card-actions")

    assert "_appendFeedbackMeta(card, item" not in pending
    assert "_appendFeedbackMeta(card, item" not in reviewing.split("} else {", 1)[0]
    assert "feedbackMeta.appendChild(posLabel)" not in share_card
    assert "header.appendChild(id); header.appendChild(time); header.appendChild(status);" in preview
    assert "head.appendChild(time);\n    head.appendChild(status);" in preview
    assert "head.appendChild(id); head.appendChild(meta); head.appendChild(status); head.appendChild(del);" in preview
    assert "head.appendChild(id); head.appendChild(time); head.appendChild(status); head.appendChild(del);" in share_card
    assert "if (isReadOnly)" in share_card

    assert ".fb-card-meta { display: flex;" in css
    assert ".fb-card-header .fb-btn-delete { flex: 0 0 auto;" in css
    assert ".fb-card-actions .preview-bottom-btn" in css
    assert "@media (max-width: 480px)" in css
