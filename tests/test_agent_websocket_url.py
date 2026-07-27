import sys
from pathlib import Path
from types import SimpleNamespace

from starlette.requests import Request

DEV = Path(__file__).resolve().parents[1] / "dev"
if str(DEV) not in sys.path:
    sys.path.insert(0, str(DEV))

import routes


def _request(host: str, scheme: str = "http") -> Request:
    return Request({
        "type": "http",
        "scheme": scheme,
        "server": (host, 5533),
        "headers": [(b"host", f"{host}:5533".encode())],
        "path": "/api/clawmate/config",
        "query_string": b"",
    })


def test_agent_websocket_uses_same_lan_origin_instead_of_public_tunnel(monkeypatch):
    monkeypatch.setattr(routes, "get_public_base_url", lambda request: "https://note.updatedb.online:18443")

    assert routes._agent_ws_url(_request("192.168.254.130")) == (
        "ws://192.168.254.130:5533/api/clawmate/agent/terminal"
    )


def test_agent_websocket_keeps_public_wss_origin(monkeypatch):
    monkeypatch.setattr(routes, "get_public_base_url", lambda request: "https://note.updatedb.online:18443")

    assert routes._agent_ws_url(_request("note.updatedb.online", "https")) == (
        "wss://note.updatedb.online:18443/api/clawmate/agent/terminal"
    )


def test_lan_http_login_cookie_is_not_marked_secure_by_public_base_url(monkeypatch):
    monkeypatch.setattr(
        routes,
        "config",
        lambda: SimpleNamespace(public_base_url="https://note.updatedb.online:18443"),
    )

    assert routes._request_is_https(_request("openclaw.lan")) is False
