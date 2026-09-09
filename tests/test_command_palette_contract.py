# tests/test_command_palette_contract.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")

def test_title_wraps_vertical_center_not_horizontal():
    style = _read("dev/static/css/style.css")
    i = style.index(".path-title-wrap {")
    assert "align-items: center" in style[i:i + 220]
    assert "justify-content: center" not in style[i:i + 220]

    preview = _read("dev/static/css/preview.css")
    j = preview.rindex(".preview-topbar-title-wrap {")
    assert "align-items: center" in preview[j:j + 240]
    assert "justify-content: center" not in preview[j:j + 240]

def test_mru_helpers_in_app_js():
    src = _read("dev/static/js/app.js")
    assert "function recordProjectUse(rootId, name)" in src
    assert "function projectUseAt(rootId, name)" in src
    assert "clawmate.recentProjects" in src

def test_palette_search_chips_and_cards():
    html = _read("dev/static/index.html")
    css = _read("dev/static/css/command-palette.css")
    assert "cp-chips" in html
    assert "data-cp-search" in html
    assert "文件搜索" in html
    assert "内容搜索" in html
    assert ".cp-chips" in css
    assert ".cp-chip" in css
    assert ".cp-card" in css
    assert "grid-template-columns: repeat(auto-fill" in css
