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


def test_markdown_bpmn_fence_uses_the_bpmn_renderer():
    preview = PREVIEW_JS.read_text(encoding="utf-8")

    assert "if (language === 'bpmn')" in preview
    assert 'class="bpmn-diagram"' in preview
    assert "bpmnStore[id] = raw;" in preview
    assert "window.BpmnPreview.renderEmbedded" in preview


def test_bpmn_module_supports_preview_edit_and_export():
    source = BPMN_JS.read_text(encoding="utf-8")

    assert "window.BpmnPreview =" in source
    assert "function renderFile" in source
    assert "function renderEmbedded" in source
    assert "function openEditor" in source
    assert "fetch('/api/clawmate/save'" in source
    assert "saveSVG" in source
    assert "image/png" in source
    assert "editable: true" in source
    assert "var ViewerConstructor = null;" in source
    assert "var ModelerConstructor = null;" in source
    assert "new ViewerConstructor" in source
    assert "new ModelerConstructor" in source


def test_bpmn_dialog_errors_restore_page_scroll():
    source = BPMN_JS.read_text(encoding="utf-8")

    assert "function closeFailedOverlay(overlay, instance)" in source
    assert "document.body.style.overflow = '';" in source


def test_preview_loads_bpmn_module_from_local_assets_only():
    html = PREVIEW_HTML.read_text(encoding="utf-8")

    assert './js/bpmn-preview.js' in html
    assert "unpkg.com/bpmn-js" not in html
