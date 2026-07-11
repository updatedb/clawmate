import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_CSS = ROOT / "dev" / "static" / "css" / "preview.css"


def test_mobile_agent_panel_is_bounded_not_fullscreen():
    css = PREVIEW_CSS.read_text(encoding="utf-8")

    match = re.search(
        r"/\* Mobile: agent panel as fixed overlay \*/(?P<body>.*?)(?=\.preview-agent-panel \.agent-chat-input \{ font-size: 16px; \})",
        css,
        flags=re.S,
    )
    assert match, "mobile agent panel rule block not found"

    block = match.group("body")
    assert "position: fixed;" in block
    assert "width: 100vw !important;" in block
