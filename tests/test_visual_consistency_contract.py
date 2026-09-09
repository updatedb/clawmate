from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_mobile_shells_default_to_content_before_navigation_panels():
    app_js = (ROOT / "dev" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    preview_js = (ROOT / "dev" / "static" / "js" / "preview.js").read_text(encoding="utf-8")

    assert "function _syncMobileSidebarVisibility()" in app_js
    assert "window.addEventListener('resize', _syncMobileSidebarVisibility);" in app_js
    assert "window.addEventListener('resize', syncResponsiveOutlineVisibility);" in preview_js
    assert "syncResponsiveOutlineVisibility();" in preview_js


def test_edge_surfaces_consume_shared_tokens_and_recoverable_share_copy():
    login_css = (ROOT / "dev" / "static" / "css" / "login.css").read_text(encoding="utf-8")
    onlyoffice_html = (ROOT / "dev" / "static" / "onlyoffice.html").read_text(encoding="utf-8")
    share_html = (ROOT / "dev" / "static" / "share-view.html").read_text(encoding="utf-8")

    assert "@import url('./tokens.css');" in login_css
    assert '<link rel="stylesheet" href="./css/tokens.css" />' in onlyoffice_html
    assert "请向发送者索取新的分享链接" in share_html


def test_mobile_preview_prioritizes_document_context_over_secondary_tools():
    # Secondary tools (project / theme / logout) fold into the shared mobile more-menu.
    # The fold rules live in the shared stylesheet, scoped by :has(#btnMoreMenu) so the
    # share page (no such button) is unaffected; preview keeps its document-first behavior.
    style_css = (ROOT / "dev" / "static" / "css" / "style.css").read_text(encoding="utf-8")
    preview_css = (ROOT / "dev" / "static" / "css" / "preview.css").read_text(encoding="utf-8")

    assert ".content-col > .topbar:has(#btnMoreMenu) #btnProjectPanel," in style_css
    assert ".content-col > .topbar:has(#btnMoreMenu) #themeToggle," in style_css
    assert ".content-col > .topbar:has(#btnMoreMenu) #btnLogout," in style_css
    assert ".preview-left.responsive-hidden { display: none !important; }" in preview_css


def test_index_and_preview_left_panels_reclaim_content_width_when_slide_out_starts():
    """Guard the close ordering: the grid reflow must begin with the slide-out."""
    app_js = (ROOT / "dev" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    preview_js = (ROOT / "dev" / "static" / "js" / "preview.js").read_text(encoding="utf-8")

    index_close = app_js[app_js.index("const btnCloseSidebar"):app_js.index("// Single width-aware grid updater")]
    preview_close = preview_js[preview_js.index("function closeLeftSidebar() {"):preview_js.index("function openRightSidebar() {")]

    assert index_close.index("updateIndexGrid();") < index_close.index("setTimeout(function ()")
    assert preview_close.index("updateGridColumns();") < preview_close.index("_leftCloseTimer = setTimeout")
