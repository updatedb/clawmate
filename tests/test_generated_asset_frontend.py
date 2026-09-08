from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_HTML = ROOT / "dev/static/preview.html"
PREVIEW_JS = ROOT / "dev/static/js/preview.js"
PANEL_JS = ROOT / "dev/static/js/image-assets-panel.js"
PREVIEW_CSS = ROOT / "dev/static/css/preview.css"


def test_image_asset_panel_is_lazy_registered_without_base64_transport():
    preview = PREVIEW_JS.read_text(encoding="utf-8")
    assert "loadImageAssetsPanel" in preview
    assert "image-assets-panel.js" in preview
    assert "data:image" not in preview


def test_image_asset_panel_has_explicit_grid_column_and_source_prompt():
    css = PREVIEW_CSS.read_text(encoding="utf-8")
    html = PREVIEW_HTML.read_text(encoding="utf-8")
    assert "#previewImageAssetsPanel { grid-column: 4;" in css
    assert 'id="previewImageAssetsPanel"' in html
    assert "panel-close-btn" in html
    assert "原图生成提示词" in html
