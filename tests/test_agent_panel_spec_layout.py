from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "dev" / "static" / "index.html"
PREVIEW_HTML = ROOT / "dev" / "static" / "preview.html"


def test_agent_panel_has_terminal_toolbar_and_status_contract():
    for path, prefix in ((INDEX_HTML, ""), (PREVIEW_HTML, "preview")):
        html = path.read_text(encoding="utf-8")
        assert f'id="{prefix}AgentToolbar"' in html
        assert f'id="{prefix}AgentStatus"' in html
        assert f'id="{prefix}AgentSearch"' in html
        assert f'id="{prefix}AgentReconnect"' in html
        assert f'id="{prefix}BtnAgentHistory"' in html if prefix else 'id="btnAgentHistory"' in html


def test_terminal_panel_width_uses_same_responsive_track_as_grid():
    css = (ROOT / "dev" / "frontend" / "terminal" / "terminal.css").read_text(
        encoding="utf-8"
    )
    assert "grid-template-columns" not in css
    assert "width: 100%;" in css


def test_openclaw_chat_bubbles_preserve_gateway_line_breaks():
    css = (ROOT / "dev" / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    assert "white-space: pre-wrap" in css


def test_agent_panel_exposes_context_resize_and_history_contract():
    for path, prefix in ((INDEX_HTML, ""), (PREVIEW_HTML, "preview")):
        html = path.read_text(encoding="utf-8")
        assert f'id="{prefix}AgentTitle"' in html if prefix else 'id="agentPanelTitle"' in html
        assert f'id="{prefix}BtnNewAgentSession"' in html if prefix else 'id="btnNewAgentSession"' in html
    assert 'id="agentResizeHandle"' in INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="previewResizeHandle"' in PREVIEW_HTML.read_text(encoding="utf-8")


def test_clear_screen_toolbar_action_matches_ctrl_l_semantics():
    for path in (INDEX_HTML, PREVIEW_HTML):
        html = path.read_text(encoding="utf-8")
        assert 'title="清屏"' in html
        assert 'aria-label="清屏"' in html
        assert '清空终端' not in html


def test_history_runtime_contract_includes_search_backend_and_pagination():
    source = (ROOT / "dev" / "frontend" / "terminal" / "agent-panel-adapter.ts").read_text(
        encoding="utf-8"
    )
    for token in ("agent-history-search-input", "agent-history-backend-input", "agent-history-prev", "agent-history-next", "offset"):
        assert token in source
    assert "agent-history-date-input" not in source
    assert '.search-clear { display: none;' in (ROOT / "dev" / "static" / "css" / "style.css").read_text(encoding="utf-8")


def test_agent_search_controls_use_compact_30px_layout_and_history_filters_only_supported_backends():
    css = (ROOT / "dev" / "static" / "css" / "style.css").read_text(encoding="utf-8")
    terminal_css = (ROOT / "dev" / "frontend" / "terminal" / "terminal.css").read_text(encoding="utf-8")
    source = (ROOT / "dev" / "frontend" / "terminal" / "agent-panel-adapter.ts").read_text(encoding="utf-8")

    assert "width: 84px; flex: 0 0 84px; height: 30px" in css
    assert "appearance: none; width: 84px; max-width: 84px; height: 30px" in css
    assert ".search-input {\n  width: 100%;\n  height: 30px;" in css
    assert 'value="openclaw">OpenClaw' not in source


def test_history_header_modes_respect_hidden_attribute():
    css = (ROOT / "dev" / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    assert ".agent-history-detail-header[hidden]" in css
    assert ".agent-history-list-header[hidden]" in css
    assert ".agent-history-date-axis[hidden]" in css
    assert ".agent-history-pagination[hidden]" in css
    assert "font-family: Arial, sans-serif; font-size: 12px" in css


def test_terminal_toolbar_actions_have_compact_icon_contract():
    css = (ROOT / "dev" / "frontend" / "terminal" / "terminal.css").read_text(
        encoding="utf-8"
    )
    assert "font: 500 11px/1 Arial, sans-serif" in css
    assert ".agent-toolbar-actions .agent-toolbar-btn svg" in css
    for path in (INDEX_HTML, PREVIEW_HTML):
        html = path.read_text(encoding="utf-8")
        start = html.index('class="agent-toolbar-actions"')
        end = html.index('</div>', start)
        assert '<svg' in html[start:end]
        assert '缩小' in html[start:end]
        assert '放大' in html[start:end]


def test_history_typography_matches_index_card_scale_and_refreshes_bundle_cache():
    css = (ROOT / "dev" / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    sw = (ROOT / "dev" / "static" / "sw.js").read_text(encoding="utf-8")
    assert ".agent-history-item-title { color: var(--text-primary); font-size: 12px;" in css
    assert ".agent-history-item-meta { display: block; margin-top: 3px; color: var(--text-muted); font-size: 10px;" in css
    assert "font: 500 12px/1 var(--font-ui); white-space: nowrap" in css
    assert "v20260712-search-ui-v18" in sw


def test_agent_panel_separates_terminal_and_web_typography():
    terminal_css = (ROOT / "dev" / "frontend" / "terminal" / "terminal.css").read_text(
        encoding="utf-8"
    )
    css = (ROOT / "dev" / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    assert ".agent-panel-v2 .xterm" in terminal_css
    assert "font-family: var(--font-mono" in terminal_css
    assert "font-family: var(--font-ui)" in css
    assert "grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr)" in css
    back_start = css.index(".agent-history-back {\n  flex:")
    assert "white-space: nowrap" in css[back_start:back_start + 500]
    assert "font-size: 12px; line-height: 1.5" in css


def test_xterm_overlay_scrollbar_matches_application_scrollbar_contract():
    css = (ROOT / "dev" / "frontend" / "terminal" / "terminal.css").read_text(
        encoding="utf-8"
    )
    assert ".xterm-scrollable-element > .scrollbar.vertical" in css
    assert "width: 6px !important" in css
    assert ".xterm-scrollable-element > .scrollbar.horizontal" in css
    assert "display: none !important" in css


def test_history_list_and_detail_header_labels_share_typography():
    css = (ROOT / "dev" / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    assert "font: 500 12px/1 var(--font-ui)" in css
    assert ".agent-history-title-icon" in css
    assert ".agent-history-back" in css


def test_history_list_and_detail_headers_share_close_button_contract():
    source = (ROOT / "dev" / "frontend" / "terminal" / "agent-panel-adapter.ts").read_text(
        encoding="utf-8"
    )
    css = (ROOT / "dev" / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    assert "agent-history-overlay-close agent-history-header-close" in source
    assert "agent-history-detail-close agent-history-header-close" in source
    assert ".agent-history-detail-close.agent-history-header-close" in css
    assert "agent-history-overlay-title agent-history-header-label" in source
    assert "agent-history-back agent-history-header-label" in source
    assert ".agent-history-header-icon" in css
    assert ".agent-history-overlay-header > .agent-history-detail-header[hidden]" in css
    assert ".agent-panel-header svg,\n.agent-history-overlay-header svg,\n.agent-toolbar svg { width: 14px; height: 14px; }" in css
    assert ".agent-history-date-axis,\n.agent-history-date-axis * { font-family: Arial, sans-serif; font-size: 11px; }" in css
