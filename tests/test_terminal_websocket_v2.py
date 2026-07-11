import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "dev"
if str(DEV) not in sys.path:
    sys.path.insert(0, str(DEV))

import agent_routes
from terminal_manager import SessionRequest, TerminalManager
from terminal_protocol import encode_binary_frame


class FakePty:
    def __init__(self):
        self.written = b""

    async def read(self, size: int) -> bytes:
        await asyncio.Future()
        return b""

    async def write_all(self, data: bytes) -> None:
        self.written += data

    async def resize(self, cols: int, rows: int) -> None:
        return None

    async def terminate(self) -> None:
        return None


class FakeWebSocket:
    def __init__(self, messages: list[dict]):
        self.messages = iter(messages)
        self.text_frames: list[dict] = []
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive(self) -> dict:
        try:
            return next(self.messages)
        except StopIteration as exc:
            raise WebSocketDisconnect() from exc

    async def send_text(self, data: str) -> None:
        self.text_frames.append(json.loads(data))


@pytest.mark.asyncio
async def test_v2_hello_returns_ready_and_disconnect_unsubscribes(monkeypatch):
    async def factory(request: SessionRequest) -> FakePty:
        return FakePty()

    manager = TerminalManager(factory, replay_bytes=4096)
    monkeypatch.setattr(agent_routes, "_terminal_v2_manager", manager)
    monkeypatch.setattr(agent_routes, "resolve_session_cwd", lambda root, dir_: "/tmp/project")
    websocket = FakeWebSocket([
        {"text": json.dumps({
            "v": 2,
            "type": "hello",
            "id": "hello-1",
            "client_id": "browser-1",
            "root": "root",
            "dir": "project",
            "backend": "codex",
            "cols": 80,
            "rows": 24,
        })},
    ])

    await agent_routes.agent_terminal_v2(websocket)

    assert websocket.accepted is True
    assert websocket.text_frames[0]["type"] == "ready"
    assert websocket.text_frames[0]["session_id"]
    assert manager.diagnostics()["connection_count"] == 0
    await manager.close_all("test_complete")


@pytest.mark.asyncio
async def test_v2_binary_input_is_not_parsed_as_a_control_frame(monkeypatch):
    ptys: list[FakePty] = []

    async def factory(request: SessionRequest) -> FakePty:
        pty = FakePty()
        ptys.append(pty)
        return pty

    manager = TerminalManager(factory, replay_bytes=4096)
    monkeypatch.setattr(agent_routes, "_terminal_v2_manager", manager)
    monkeypatch.setattr(agent_routes, "resolve_session_cwd", lambda root, dir_: "/tmp/project")
    websocket = FakeWebSocket([
        {"text": json.dumps({
            "v": 2, "type": "hello", "client_id": "browser-1", "root": "root",
            "dir": "project", "backend": "claude", "cols": 80, "rows": 24,
        })},
        {"bytes": encode_binary_frame(7, b'{"type":"terminate"}')},
    ])

    await agent_routes.agent_terminal_v2(websocket)

    assert ptys[0].written == b'{"type":"terminate"}'
    assert any(frame["type"] == "input_ack" for frame in websocket.text_frames)
    await manager.close_all("test_complete")


@pytest.mark.asyncio
async def test_v2_endpoint_rejects_connections_until_the_feature_flag_is_enabled(monkeypatch):
    monkeypatch.setattr(agent_routes, "_terminal_v2_manager", None)
    monkeypatch.setattr(agent_routes, "load_cfg", lambda: SimpleNamespace(agent=SimpleNamespace(terminal_v2=False)))
    websocket = FakeWebSocket([])

    await agent_routes.agent_terminal_v2(websocket)

    assert websocket.text_frames[0]["error"]["code"] == "terminal_v2_disabled"
