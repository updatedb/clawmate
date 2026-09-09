# tests/test_command_palette_contract.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")

def test_center_title_wraps():
    style = _read("dev/static/css/style.css")
    i = style.index(".path-title-wrap {")
    assert "justify-content: center" in style[i:i + 220]

    preview = _read("dev/static/css/preview.css")
    j = preview.rindex(".preview-topbar-title-wrap {")
    assert "justify-content: center" in preview[j:j + 240]

def test_mru_helpers_in_app_js():
    src = _read("dev/static/js/app.js")
    assert "function recordProjectUse(rootId, name)" in src
    assert "function projectUseAt(rootId, name)" in src
    assert "clawmate.recentProjects" in src
