from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TERMINAL_ADAPTER = ROOT / "dev" / "frontend" / "terminal" / "agent-panel-adapter.ts"


def test_pure_v2_adapter_owns_insert_and_has_no_legacy_agent_file():
    source = TERMINAL_ADAPTER.read_text(encoding="utf-8")

    assert "this.terminal?.input(text, true);" in source
    assert not (ROOT / "dev" / "static" / "js" / "agent.js").exists()
