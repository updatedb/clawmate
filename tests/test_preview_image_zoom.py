from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_JS = ROOT / "dev" / "static" / "js" / "preview.js"


def test_image_preview_toolbar_exposes_ten_percent_zoom_controls():
    source = PREVIEW_JS.read_text(encoding="utf-8")

    assert "const IMAGE_ZOOM_STEP = 0.1;" in source
    assert 'id="imageZoomOut"' in source
    assert 'id="imageZoomLevel"' in source
    assert 'id="imageZoomIn"' in source
    assert "function setupImageZoomToolbar()" in source
    assert "dyn.querySelectorAll('.image-sort-btn').forEach" in source
    assert "btn.className = 'preview-bottom-btn image-sort-btn';" in source


def test_image_preview_toolbar_uses_compact_zoom_labels_and_toggle_edit_state():
    source = PREVIEW_JS.read_text(encoding="utf-8")

    assert 'id="imageZoomOut" title="缩小图片">−</button>' in source
    assert 'id="imageZoomIn" title="放大图片">+</button>' in source
    assert 'id="btnEditImage" title="编辑图片" aria-pressed="false">编辑</button>' in source
    assert "function toggleImageAssets()" in source
    assert "button.classList.toggle('active', isOpen);" in source
    assert "button.setAttribute('aria-pressed', String(isOpen));" in source


def test_image_preview_zoom_is_bounded_and_preserved_on_navigation():
    source = PREVIEW_JS.read_text(encoding="utf-8")

    assert "const IMAGE_ZOOM_MIN = 0.1;" in source
    assert "const IMAGE_ZOOM_MAX = 5;" in source
    assert "function resetImageZoom()" in source
    assert "imageZoomScale = 1;" in source
    navigation_body = source.split("function navigateToImage(newFilePath)", 1)[1].split(
        "// Reusable: fetch sibling images", 1
    )[0]
    assert "resetImageZoom();" not in navigation_body
    assert "imageZoomBaseWidth = 0;" in navigation_body
    assert "imageZoomBaseHeight = 0;" in navigation_body
    assert "img.onload = function()" in source
    assert "applyImageZoom();" in source.split("img.onload = function()", 1)[1].split("img.onerror", 1)[0]
    assert "img.style.transform = 'scale(' + imageZoomScale + ')';" in source
