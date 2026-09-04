from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_JS = ROOT / "dev" / "static" / "js" / "preview.js"
PREVIEW_CSS = ROOT / "dev" / "static" / "css" / "preview.css"


def test_markdown_refresh_preserves_outline_state_and_bypasses_cached_assets():
    source = PREVIEW_JS.read_text(encoding="utf-8")

    assert "await loadContent({ preserveOutlineState: true, forceRefresh: true });" in source
    assert "var outlineWasOpen = !leftSidebar.classList.contains('hidden');" in source
    assert "if (outlineWasOpen) openLeftSidebar();" in source
    assert "else closeLeftSidebar();" in source
    assert "function buildTOC(div, preserveSidebarVisibility)" in source
    assert "if (!preserveSidebarVisibility && window.innerWidth >= 768)" in source
    assert "function buildPreviewUrl(path, refreshToken)" in source
    assert "function buildStaticAssetUrl(path, refreshToken)" in source
    assert "^\\/?dev\\/static\\/" in source
    assert "source.pathname = '/clawmate/'" in source
    assert "_clawmate_refresh" in source
    assert "{ cache: 'no-store' }" in source
    assert "refreshRenderedImageSources(mdDiv, refreshToken);" in source


def test_responsive_outline_state_tracks_actual_visibility_and_can_be_forced_open():
    source = PREVIEW_JS.read_text(encoding="utf-8")
    css = PREVIEW_CSS.read_text(encoding="utf-8")

    assert "function isLeftSidebarVisible()" in source
    assert "function syncOutlineToggleState()" in source
    assert "leftSidebar.classList.contains('responsive-hidden')" in source
    assert "outlineForcedOpen = true;" in source
    assert "window.innerWidth <= 768" in source
    assert "window.matchMedia('(max-width: 768px)')" in source
    assert ".preview-left.responsive-hidden { display: none; }" in css
    assert "body.preview-panel-open .preview-left { display: none; }" not in css
