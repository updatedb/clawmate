"""Dead config keys `search.ai_summary` and `agent.terminal_v2` stay removed.

Both keys looked meaningful and were configured as if live, but neither had a
consumer:

* `search.ai_summary` -- `SearchConfig` only declares `content`, and
  `_parse_search_config()` only reads `raw["content"]`.  A prior AI summary
  feature was already removed; `search_routes` still explicitly drops a
  `summary` key from its response.  The config block was four parameters of
  pure illusion.
* `agent.terminal_v2` -- never parsed.  Protocol v2 registers unconditionally
  at ``agent_routes.py`` ``@router.websocket("/api/clawmate/agent/terminal/v2")``;
  the `terminal_v2` identifiers there are internal manager symbols, unrelated
  to any config field.  The switch could not turn anything off.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "src"
if str(DEV) not in sys.path:
    sys.path.insert(0, str(DEV))


def test_search_config_has_no_ai_summary_field():
    from config import SearchConfig

    assert not hasattr(SearchConfig(), "ai_summary")


def test_parse_config_ignores_stale_dead_keys():
    # Upgrading hosts may still carry these keys in their own config.json;
    # parsing tolerates unknown fields instead of crashing on them.
    from config import _parse_config

    cfg = _parse_config({
        "search": {"ai_summary": {"enabled": True, "timeout_seconds": 45}},
        "agent": {"terminal_v2": True},
    })

    assert not hasattr(cfg.search, "ai_summary")
    assert not hasattr(cfg.agent, "terminal_v2")


def test_example_config_does_not_advertise_the_dead_keys():
    example = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))

    assert "terminal_v2" not in example["agent"]
    assert "ai_summary" not in example.get("search", {})


def test_live_config_does_not_carry_the_dead_keys():
    live = ROOT / "config.json"
    if not live.exists():
        pytest.skip("no live config.json in this checkout")

    raw = json.loads(live.read_text(encoding="utf-8"))
    assert "terminal_v2" not in raw.get("agent", {})
    assert "ai_summary" not in raw.get("search", {})


def test_terminal_v2_websocket_is_registered_unconditionally():
    """The v2 endpoint is always live; no config gate ever existed."""
    import agent_routes

    paths = [route.path for route in agent_routes.router.routes]

    assert "/api/clawmate/agent/terminal/v2" in paths
