from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pages_load_only_the_xterm6_bundle_for_agent_runtime():
    for name in ("index.html", "preview.html"):
        html = (ROOT / "dev" / "static" / name).read_text(encoding="utf-8")
        assert "./dist/terminal.js" in html
        assert "./js/agent.js" not in html


def test_runtime_bundle_has_no_legacy_agent_reference():
    source = (ROOT / "dev" / "frontend" / "terminal" / "index.ts").read_text(encoding="utf-8")
    assert "legacyAgent" not in source
    assert "switchBackend" not in source
