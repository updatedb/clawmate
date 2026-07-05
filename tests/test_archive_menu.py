from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "dev" / "static" / "js" / "app.js"


def test_index_archive_card_menu_exposes_extract_action():
    app_js = APP_JS.read_text(encoding="utf-8")

    assert "entry.category === \"archive\"" in app_js
    assert "解压到..." in app_js
    assert "/api/clawmate/extract" in app_js
