from pathlib import Path


def test_preview_uses_shared_panel_and_single_file_watch_contract():
    root = Path(__file__).resolve().parents[1]
    common = (root / "dev/static/js/preview-common.js").read_text(encoding="utf-8")
    panel = (root / "dev/static/js/project-panel.js").read_text(encoding="utf-8")
    assert "project-panel.js" in common
    assert "ClawMateProjectPanel" in panel
    assert "/overview" in panel
    assert "/api/clawmate/fs/events?root=" in panel
    assert "&file=" in panel
    assert "has-update" in panel
    assert "stopImmediatePropagation" in panel
