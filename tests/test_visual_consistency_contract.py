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
    preview_css = (ROOT / "dev" / "static" / "css" / "preview.css").read_text(encoding="utf-8")

    assert ".preview-app > .topbar #btnProjectPanel," in preview_css
    assert ".preview-app > .topbar #themeToggle," in preview_css
    assert ".preview-app > .topbar #btnLogout { display: none; }" in preview_css
    assert ".preview-left.responsive-hidden { display: none !important; }" in preview_css
