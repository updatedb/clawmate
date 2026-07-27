import asyncio
from dataclasses import dataclass
import os
import pty
import signal
import tty

import pytest

from dev.terminal_manager import PosixPtyAdapter, SessionRequest, TerminalManager


class FakePty:
    def __init__(self):
        self.terminated = False
        self._output: asyncio.Queue[bytes] = asyncio.Queue()

    async def read(self, size: int) -> bytes:
        return await self._output.get()

    async def write_all(self, data: bytes) -> None:
        return None

    async def resize(self, cols: int, rows: int) -> None:
        return None

    async def terminate(self) -> None:
        self.terminated = True


@dataclass
class Factory:
    created: list[FakePty]

    async def __call__(self, request: SessionRequest) -> FakePty:
        pty = FakePty()
        self.created.append(pty)
        return pty


def request(backend: str = "claude") -> SessionRequest:
    return SessionRequest(backend=backend, root="root", project="project", cwd="/tmp/project")


@pytest.mark.asyncio
async def test_reuses_live_session_for_same_backend_and_scope():
    factory = Factory([])
    manager = TerminalManager(factory, replay_bytes=4096)

    first = await manager.get_or_create(request())
    second = await manager.get_or_create(request())

    assert first is second
    assert len(factory.created) == 1
    await manager.close_all("test_complete")


@pytest.mark.asyncio
async def test_backends_have_separate_sessions():
    factory = Factory([])
    manager = TerminalManager(factory, replay_bytes=4096)

    claude = await manager.get_or_create(request("claude"))
    codex = await manager.get_or_create(request("codex"))

    assert claude.id != codex.id
    assert len(factory.created) == 2
    await manager.close_all("test_complete")


@pytest.mark.asyncio
async def test_idle_session_restores_before_expiry_and_expires_after_deadline():
    factory = Factory([])
    now = [100.0]
    manager = TerminalManager(factory, replay_bytes=4096, idle_seconds=10, clock=lambda: now[0])
    session = await manager.get_or_create(request())
    connection = await manager.subscribe(session.id, "c1")
    await manager.unsubscribe(session.id, connection.id)

    now[0] = 109.0
    assert await manager.expire_idle() == 0
    assert await manager.get_or_create(request()) is session

    now[0] = 120.0
    assert await manager.expire_idle() == 1
    assert session.closed is True
    assert manager.diagnostics()["session_count"] == 0


@pytest.mark.asyncio
async def test_terminate_removes_the_session_and_closes_its_tasks():
    factory = Factory([])
    manager = TerminalManager(factory, replay_bytes=4096)
    session = await manager.get_or_create(request())

    await manager.terminate(session.id, "manual")

    assert session.closed is True
    assert factory.created[0].terminated is True
    assert manager.diagnostics()["session_count"] == 0


@pytest.mark.asyncio
async def test_terminate_does_not_block_a_replacement_on_history_cleanup():
    factory = Factory([])
    cleanup_started = asyncio.Event()
    unblock_cleanup = asyncio.Event()

    async def on_session_removed(session_id: str, reason: str) -> None:
        cleanup_started.set()
        await unblock_cleanup.wait()

    manager = TerminalManager(
        factory,
        replay_bytes=4096,
        on_session_removed=on_session_removed,
    )
    first = await manager.get_or_create(request())

    await asyncio.wait_for(manager.terminate(first.id, "replaced"), timeout=0.1)
    replacement = await asyncio.wait_for(manager.get_or_create(request()), timeout=0.1)

    assert replacement.id != first.id
    await asyncio.wait_for(cleanup_started.wait(), timeout=0.1)
    unblock_cleanup.set()
    await manager.close_all("test_complete")


@pytest.mark.asyncio
async def test_process_eof_removes_session_and_runs_archive_callback():
    factory = Factory([])
    removed: list[tuple[str, str]] = []
    removed_event = asyncio.Event()

    async def on_session_removed(session_id: str, reason: str) -> None:
        removed.append((session_id, reason))
        removed_event.set()

    manager = TerminalManager(
        factory,
        replay_bytes=4096,
        on_session_removed=on_session_removed,
    )
    session = await manager.get_or_create(request())

    await factory.created[0]._output.put(b"")
    await asyncio.wait_for(removed_event.wait(), timeout=1)

    assert session.closed is True
    assert removed == [(session.id, "process_exited")]
    assert manager.diagnostics()["session_count"] == 0


@pytest.mark.asyncio
async def test_posix_pty_adapter_transfers_bytes_and_terminates_process():
    class Process:
        returncode = None

        def __init__(self):
            self.terminated = False

        def terminate(self):
            self.terminated = True

    master_fd, slave_fd = pty.openpty()
    tty.setraw(slave_fd)
    process = Process()
    adapter = PosixPtyAdapter(master_fd, process)
    try:
        os.write(slave_fd, b"output")
        assert await adapter.read(64) == b"output"

        await adapter.write_all(b"input")
        assert os.read(slave_fd, 64) == b"input"

        await adapter.terminate()
        assert process.terminated is True
        with pytest.raises(OSError):
            os.fstat(master_fd)
    finally:
        os.close(slave_fd)


@pytest.mark.asyncio
async def test_posix_pty_adapter_terminates_the_whole_cli_process_group(monkeypatch):
    class Process:
        pid = 4242
        returncode = None

        def terminate(self):
            raise AssertionError("a CLI process group must be terminated, not only its leader")

    signals: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(os, "killpg", lambda pid, sig: signals.append((pid, sig)))

    master_fd, slave_fd = pty.openpty()
    adapter = PosixPtyAdapter(master_fd, Process())
    try:
        await adapter.terminate()
        assert signals == [(4242, signal.SIGTERM)]
    finally:
        os.close(slave_fd)
        try:
            os.close(master_fd)
        except OSError:
            pass
