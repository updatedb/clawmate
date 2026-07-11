from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_backend_select_routes_through_public_agent_facade():
    terminal_index = (ROOT / "dev" / "frontend" / "terminal" / "index.ts").read_text(encoding="utf-8")
    adapter = (ROOT / "dev" / "frontend" / "terminal" / "agent-panel-adapter.ts").read_text(encoding="utf-8")

    assert "setBackend(backend" in terminal_index
    assert "agent.setBackend" in terminal_index
    assert "select.onchange = () => this.setBackend" in adapter
