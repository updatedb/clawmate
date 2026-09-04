from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_JS = ROOT / "dev" / "static" / "js" / "preview.js"
PREVIEW_COMMON_JS = ROOT / "dev" / "static" / "js" / "preview-common.js"
BPMN_JS = ROOT / "dev" / "static" / "js" / "bpmn-preview.js"
PREVIEW_HTML = ROOT / "dev" / "static" / "preview.html"


def test_bpmn_is_a_previewable_standalone_format():
    common = PREVIEW_COMMON_JS.read_text(encoding="utf-8")
    preview = PREVIEW_JS.read_text(encoding="utf-8")

    assert "'bpmn'" in common
    assert "const isBpmnMode = ext === 'bpmn';" in preview
    assert "window.BpmnPreview.renderFile" in preview
    assert "setupBpmnFileEditButtons" in preview
    assert "window.BpmnPreview.openInlineEditor" in preview
    assert "window.BpmnPreview.exportPng" in preview


def test_markdown_bpmn_fence_uses_the_bpmn_renderer():
    preview = PREVIEW_JS.read_text(encoding="utf-8")

    assert "if (language === 'bpmn')" in preview
    assert 'class="bpmn-diagram"' in preview
    assert "bpmnStore[id] = raw;" in preview
    assert "window.BpmnPreview.renderEmbedded" in preview
    assert "updateMarkdownBpmnSource" in preview
    assert "openBpmnExpandDialog" in BPMN_JS.read_text(encoding="utf-8")
    assert "bpmn-modal-canvas" in BPMN_JS.read_text(encoding="utf-8")
    assert "editable: true" not in preview
    assert "onSaveXml" in BPMN_JS.read_text(encoding="utf-8")


def test_markdown_can_embed_and_save_a_relative_bpmn_file():
    preview = PREVIEW_JS.read_text(encoding="utf-8")

    assert "language === 'bpmn-file'" in preview
    assert "function resolveBpmnFilePath" in preview
    assert "function loadReferencedBpmnFile" in preview
    assert "function saveReferencedBpmnFile" in preview
    assert "path: bpmnPath" in preview
    assert "bpmnStore[id] = { fileRef: raw.trim() };" in preview


def test_bpmn_module_supports_preview_edit_and_export():
    source = BPMN_JS.read_text(encoding="utf-8")

    assert "window.BpmnPreview =" in source
    assert "function renderFile" in source
    assert "function renderEmbedded" in source
    assert "function openEditor" in source
    assert "function openInlineEditor" in source
    assert "fetch('/api/clawmate/save'" in source
    assert "saveSVG" in source
    assert "image/png" in source
    assert "openInlineEditor" in source
    assert "var ViewerConstructor = null;" in source
    assert "var ModelerConstructor = null;" in source
    assert "new ViewerConstructor" in source
    assert "new ModelerConstructor" in source
    assert "fitViewer(modeler);" in source


def test_bpmn_exposes_png_export_without_svg_export_controls():
    source = BPMN_JS.read_text(encoding="utf-8")

    assert 'data-bpmn-action="png"' in source
    assert 'data-bpmn-action="svg"' not in source
    assert 'title="导出 SVG"' not in source
    assert "options.pngExport !== false" in source
    assert 'data-bpmn-action="fullscreen"' not in source
    assert "function openViewerDialog" not in source
    assert "exportPng(instance, options.pngFileName || 'bpmn-diagram');" in source
    assert "function applyCurrentThemeToSvg" in source
    assert "applyCurrentThemeToSvg(result.svg)" in source
    assert 'data-bpmn-export-background="true"' in source


def test_bpmn_matches_mermaid_resize_and_zoom_affordances():
    source = BPMN_JS.read_text(encoding="utf-8")
    styles = (ROOT / "dev" / "static" / "css" / "style.css").read_text(encoding="utf-8")

    assert "function setupBpmnResizeHandle" in source
    assert 'data-bpmn-action="zoom-out"' in source
    assert 'data-bpmn-action="zoom-in"' in source
    assert "bpmn-resize-handle" in source
    assert ".bpmn-canvas .bjs-container" in styles


def test_bpmn_file_view_fills_and_centers_without_hover_outline():
    source = BPMN_JS.read_text(encoding="utf-8")
    styles = (ROOT / "dev" / "static" / "css" / "style.css").read_text(encoding="utf-8")

    assert "function fitViewer" in source
    assert "function centerViewerViewport" in source
    assert "requestAnimationFrame(function()" in source
    assert ".bpmn-file-view .djs-element.hover .djs-outline" in styles
    assert ".bpmn-file-view {\n  flex: 1;\n  height: auto;" in styles


def test_bpmn_removes_svg_focus_ring_and_has_dark_theme_contrast():
    styles = (ROOT / "dev" / "static" / "css" / "style.css").read_text(encoding="utf-8")

    assert ".bpmn-canvas .djs-container svg:focus" in styles
    assert "outline: none;" in styles
    assert '[data-theme="dark"] .bpmn-canvas .djs-container' in styles
    assert '[data-theme="dark"] .bpmn-canvas .djs-connection .djs-visual' in styles
    assert '[data-theme="dark"] .bpmn-canvas .djs-connection .djs-visual > path' in styles
    assert '[data-theme="dark"] .bpmn-canvas .djs-connection marker path' in styles
    assert '[data-theme="dark"] .bpmn-inline-editor .djs-palette' in styles
    assert '[data-theme="dark"] .bpmn-inline-editor .djs-palette .entry' in styles
    assert ".bpmn-inline-editor .djs-container svg:focus" in styles
    assert '[data-theme="dark"] .bpmn-inline-editor .djs-connection .djs-visual > path' in styles
    assert '[data-theme="dark"] .bpmn-inline-editor .djs-label' in styles
    assert '[data-theme="dark"] .bpmn-inline-editor .djs-search-icon path' in styles
    assert ".bpmn-modal-canvas .djs-container" in styles
    assert '[data-theme="dark"] .bpmn-modal-canvas .djs-container' in styles
    assert ".bpmn-modal-canvas .djs-container > svg" in styles
    assert "height: 100% !important;" in styles


def test_bpmn_modal_uses_icon_only_edit_save_toggle():
    source = BPMN_JS.read_text(encoding="utf-8")

    assert 'data-bpmn-expand="edit" aria-label="编辑 BPMN"' in source
    assert 'data-bpmn-expand="save" aria-label="保存 BPMN"' in source
    assert 'data-bpmn-expand="cancel"' not in source
    assert 'data-bpmn-expand="edit">编辑 BPMN</button>' not in source
    assert 'data-bpmn-expand="save">保存</button>' not in source


def test_expanded_diagrams_include_titles():
    preview = PREVIEW_JS.read_text(encoding="utf-8")

    assert "mermaid-expand-title" in preview


def test_bpmn_dialog_errors_restore_page_scroll():
    source = BPMN_JS.read_text(encoding="utf-8")

    assert "function closeFailedOverlay(overlay, instance)" in source
    assert "document.body.style.overflow = '';" in source


def test_preview_loads_bpmn_module_from_local_assets_only():
    html = PREVIEW_HTML.read_text(encoding="utf-8")

    assert './js/bpmn-preview.js' in html
    assert "unpkg.com/bpmn-js" not in html


def test_preview_cache_busts_bpmn_modal_assets():
    html = PREVIEW_HTML.read_text(encoding="utf-8")

    assert './css/style.css?v=20260727-bpmn-modal-theme' in html
    assert './js/bpmn-preview.js?v=20260727-bpmn-file' in html
