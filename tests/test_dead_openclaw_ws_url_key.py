"""`agent.openclaw_ws_url` was a dead config key and must stay removed.

`/api/clawmate/config` exposes an `agent.openclaw_ws_url` value, but that value
is computed per request by ``routes._openclaw_ws_url()`` from the request host
and ``public_base_url``.  It never came from this config key, so the key had no
consumer anywhere: not in ``dev/``, not in the shipped example, and no test
depended on it.  Configuring it changed nothing at runtime, which made it a trap
-- editing it looked like a fix while the live value came from elsewhere.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "src"
if str(DEV) not in sys.path:
    sys.path.insert(0, str(DEV))


def test_agent_config_has_no_openclaw_ws_url_field():
    from config import AgentConfig

    assert not hasattr(AgentConfig(), "openclaw_ws_url")


def test_parse_config_ignores_a_stale_openclaw_ws_url_key():
    # Upgrading hosts may still carry the key in their own config.json. Parsing
    # must tolerate it instead of crashing on an unexpected field.
    from config import _parse_config

    cfg = _parse_config({"agent": {"openclaw_ws_url": "wss://stale.example:18443"}})

    assert not hasattr(cfg.agent, "openclaw_ws_url")


def test_example_config_does_not_advertise_the_dead_key():
    example = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))

    assert "openclaw_ws_url" not in example["agent"]


def test_live_config_does_not_carry_the_dead_key():
    live = ROOT / "config.json"
    if not live.exists():
        pytest.skip("no live config.json in this checkout")

    assert "openclaw_ws_url" not in json.loads(live.read_text(encoding="utf-8"))["agent"]


def test_config_endpoint_still_serves_the_computed_openclaw_ws_url(monkeypatch):
    """Removing the config key must NOT remove the API key of the same name.

    The frontend reads ``cfg.agent.openclaw_ws_url`` from the /config response,
    so the computed value has to keep being emitted.
    """
    import routes
    from starlette.requests import Request

    monkeypatch.setattr(routes, "get_public_base_url", lambda request: "https://note.updatedb.online:18443")
    request = Request({
        "type": "http",
        "scheme": "http",
        "server": ("127.0.0.1", 5533),
        "headers": [(b"host", b"127.0.0.1:5533")],
        "path": "/api/clawmate/config",
        "query_string": b"",
    })

    assert routes._openclaw_ws_url(request) == "ws://127.0.0.1:5533/api/clawmate/agent/openclaw"
