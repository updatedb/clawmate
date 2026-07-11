import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "dev"
if str(DEV) not in sys.path:
    sys.path.insert(0, str(DEV))

from dev.terminal_manager import SessionRequest, TerminalManager
import agent_routes


class FakePty:
    async def read(self, size: int) -> bytes:
        await asyncio.Future()
        return b""

    async def write_all(self, data: bytes) -> None:
        return None

    async def resize(self, cols: int, rows: int) -> None:
        return None

    async def terminate(self) -> None:
        return None


@pytest.mark.asyncio
async def test_diagnostics_exposes_operational_counts_without_terminal_content():
    async def factory(request: SessionRequest) -> FakePty:
        return FakePty()

    manager = TerminalManager(factory, replay_bytes=4096)
    session = await manager.get_or_create(SessionRequest("codex", "root", "project", "/secret/cwd"))
    await manager.subscribe(session.id, "connection")
    data = manager.diagnostics()

    assert data["session_count"] == 1
    assert data["connection_count"] == 1
    assert "cwd" not in data
    assert "output" not in data
    assert "input" not in data
    await manager.close_all("test_complete")


@pytest.mark.asyncio
async def test_diagnostics_route_returns_only_manager_metadata(monkeypatch):
    async def factory(request: SessionRequest) -> FakePty:
        return FakePty()

    manager = TerminalManager(factory, replay_bytes=4096)
    monkeypatch.setattr(agent_routes, "_terminal_v2_manager", manager)

    response = await agent_routes.agent_terminal_diagnostics()

    assert b'"session_count":0' in response.body
    assert b"cwd" not in response.body
