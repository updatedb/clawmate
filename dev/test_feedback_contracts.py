"""Deterministic contracts for browser-side feedback isolation and layout."""

from pathlib import Path


ROOT = Path(__file__).parent
SHARE = (ROOT / "static/share-view.html").read_text(encoding="utf-8")
PREVIEW = (ROOT / "static/js/preview.js").read_text(encoding="utf-8")
CSS = (ROOT / "static/css/preview.css").read_text(encoding="utf-8")
ROUTES = (ROOT / "share_routes.py").read_text(encoding="utf-8")


def test_share_pst_payload_keeps_position_and_line_contract():
    assert "function _shareSelectionLocation(text)" in SHARE
    assert "position: _sharePosition(it), start_line: it.start_line || it.startLine || 0" in SHARE
    assert "end_line: it.end_line || it.endLine || 0" in SHARE
    assert "return String(item.position || item.location || '').trim();" in SHARE


def test_share_pending_drafts_are_token_and_file_scoped_and_restored():
    assert "clawmate.share-pending.v1:' + TOKEN + ':' + (_shareFile || '')" in SHARE
    assert "function _sharePersistPending()" in SHARE
    assert "function _shareRestorePending()" in SHARE
    assert "_sharePersistPending();" in SHARE
    assert "_shareRestorePending();" in SHARE
    assert "sharePending = sharePending.filter(function(it){ return !pendingIds.has(it.id); });" in SHARE


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
