from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "dev" / "static" / "index.html"
PREVIEW_HTML = ROOT / "dev" / "static" / "preview.html"


def test_agent_panel_has_terminal_toolbar_and_status_contract():
    for path, prefix in ((INDEX_HTML, ""), (PREVIEW_HTML, "preview")):
        html = path.read_text(encoding="utf-8")
        assert f'id="{prefix}AgentToolbar"' in html
        assert f'id="{prefix}AgentStatus"' in html
        assert f'id="{prefix}AgentSearch"' in html
        assert f'id="{prefix}AgentReconnect"' in html


def test_terminal_panel_width_uses_same_responsive_track_as_grid():
    css = (ROOT / "dev" / "frontend" / "terminal" / "terminal.css").read_text(
        encoding="utf-8"
    )
    assert "grid-template-columns" not in css
    assert "width: clamp(420px, 46vw, 820px);" in css
