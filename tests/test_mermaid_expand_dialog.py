from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLE_CSS = ROOT / "dev" / "static" / "css" / "style.css"


def test_mermaid_expand_dialog_uses_near_full_viewport_with_compact_body_padding():
    source = STYLE_CSS.read_text(encoding="utf-8")
    dialog = source.split(".mermaid-expand-dialog {", 1)[1].split(
        "}\n.mermaid-expand-overlay.active", 1
    )[0]
    body = source.split(".mermaid-expand-body {", 1)[1].split(
        "}\n\n.mermaid-expand-body svg", 1
    )[0]

    assert "width: calc(100vw - 16px);" in dialog
    assert "height: calc(100vh - 16px);" in dialog
    assert "padding: 8px;" in body
