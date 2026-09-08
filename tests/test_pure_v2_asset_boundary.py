from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pages_load_only_the_xterm6_bundle_for_agent_runtime():
    index_html = (ROOT / "dev" / "static" / "index.html").read_text(encoding="utf-8")
    preview_html = (ROOT / "dev" / "static" / "preview.html").read_text(encoding="utf-8")
    preview_js = (ROOT / "dev" / "static" / "js" / "preview.js").read_text(encoding="utf-8")

    assert "./dist/terminal.js" in index_html
    # The preview loads the same v2 bundle only after its Agent panel opens.
    assert "await loadScript('./dist/terminal.js')" in preview_js
    assert "./dist/terminal.js" not in preview_html
    assert "./js/agent.js" not in index_html
    assert "./js/agent.js" not in preview_html


def test_runtime_bundle_has_no_legacy_agent_reference():
    source = (ROOT / "dev" / "frontend" / "terminal" / "index.ts").read_text(encoding="utf-8")
    assert "legacyAgent" not in source
    assert "switchBackend" not in source
