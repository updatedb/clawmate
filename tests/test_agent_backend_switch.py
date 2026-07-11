from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_backend_select_routes_through_public_agent_facade():
    agent_js = (ROOT / "dev" / "static" / "js" / "agent.js").read_text(encoding="utf-8")
    terminal_index = (ROOT / "dev" / "frontend" / "terminal" / "index.ts").read_text(encoding="utf-8")

    assert "window.Agent.setBackend(bm)" in agent_js
    assert "setBackend(backend" in terminal_index
    assert "v2Agent.setBackend" in terminal_index
