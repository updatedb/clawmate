from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIEWER = ROOT / "dev" / "static" / "pdfjs" / "viewer.html"
PREVIEW_JS = ROOT / "dev" / "static" / "js" / "preview.js"


def test_pdf_viewer_builds_selectable_text_layer_for_each_page():
    source = VIEWER.read_text(encoding="utf-8")

    assert "page.getTextContent()" in source
    assert "textLayer.className = 'textLayer'" in source
    assert "pageDiv.appendChild(textLayer)" in source
    assert "pdfjsLib.renderTextLayer" in source
    assert "textContentSource: textContent" in source
    assert "cMapUrl: '/clawmate/pdfjs/cmaps/'" in source
    assert "cMapPacked: true" in source
    assert "standardFontDataUrl: '/clawmate/pdfjs/standard_fonts/'" in source
    assert "window.devicePixelRatio" in source
    assert "Math.max(window.devicePixelRatio || 1, 2)" in source
    assert "renderScale" in source
    assert "renderViewport" in source
    assert "canvas.style.width" in source
    assert "position: absolute" in source


def test_pdf_viewer_accepts_navigation_and_zoom_messages_before_rendering():
    source = VIEWER.read_text(encoding="utf-8")

    assert "function scrollToPage(pageNum)" in source
    assert "window.addEventListener('message'" in source
    assert source.index("window.addEventListener('message'") < source.index("pdfjsLib.getDocument(")
    assert "type === 'zoom-pdf'" in source
    assert "type: 'pdf-scale-change'" in source


def test_pdf_preview_populates_bottom_toolbar_with_zoom_controls():
    source = PREVIEW_JS.read_text(encoding="utf-8")

    assert "pdfZoomOut" in source
    assert "pdfZoomIn" in source
    assert "zoom-pdf" in source
