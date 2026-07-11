import asyncio

import pytest

from dev.terminal_session import TerminalSession


class FakePty:
    def __init__(self):
        self.reads = 0
        self.written = b""
        self.resizes: list[tuple[int, int]] = []
        self.terminated = False
        self._output: asyncio.Queue[bytes] = asyncio.Queue()

    async def read(self, size: int) -> bytes:
        self.reads += 1
        return await self._output.get()

    async def write_all(self, data: bytes) -> None:
        self.written += data

    async def resize(self, cols: int, rows: int) -> None:
        self.resizes.append((cols, rows))

    async def terminate(self) -> None:
        self.terminated = True

    async def emit(self, data: bytes) -> None:
        await self._output.put(data)


@pytest.mark.asyncio
async def test_reconnect_does_not_create_another_reader_or_writer():
    pty = FakePty()
    session = TerminalSession("s1", pty, replay_bytes=4096)
    await session.start()

    for index in range(30):
        connection = await session.subscribe(f"c{index}")
        await session.unsubscribe(connection.id)

    assert session.reader_start_count == 1
    assert session.writer_start_count == 1
    await session.close("test_complete")


@pytest.mark.asyncio
async def test_binary_input_is_serialized_and_acknowledged():
    pty = FakePty()
    session = TerminalSession("s1", pty, replay_bytes=4096)
    await session.start()
    await session.subscribe("c1")

    await session.enqueue_input("c1", 1, b'{"type":"terminate"}')
    await session.wait_input_ack("c1", 1)

    assert pty.written == b'{"type":"terminate"}'
    await session.close("test_complete")


@pytest.mark.asyncio
async def test_slow_subscriber_skips_chunks_instead_of_closing():
    pty = FakePty()
    session = TerminalSession("s1", pty, replay_bytes=4096, connection_queue_bytes=4)
    await session.start()
    connection = await session.subscribe("slow")

    await pty.emit(b"abc")
    await pty.emit(b"def")
    await asyncio.sleep(0)

    # Connection stays alive — the second chunk is silently dropped instead
    # of hard‑closing the WebSocket and triggering a reconnect cycle.
    assert connection.closed is False
    assert connection.id in session.connections
    # The first chunk made it into the queue; the second was skipped.
    assert connection.queued_bytes == 3
    # Replay always captures everything regardless of per‑connection drops.
    assert session.replay.latest_sequence == 6
    await session.close("test_complete")


@pytest.mark.asyncio
async def test_resize_requires_active_focus_lease():
    pty = FakePty()
    session = TerminalSession("s1", pty, replay_bytes=4096, resize_lease_seconds=15)
    await session.start()
    await session.subscribe("owner")
    await session.subscribe("other")

    await session.focus("owner")
    assert await session.resize("other", 100, 30) is False
    assert await session.resize("owner", 100, 30) is True
    assert pty.resizes == [(100, 30)]

    await session.unsubscribe("owner")
    assert await session.resize("other", 120, 40) is True
    assert pty.resizes[-1] == (120, 40)
    await session.close("test_complete")


@pytest.mark.asyncio
async def test_input_lock_rejects_other_connections():
    pty = FakePty()
    session = TerminalSession("s1", pty, replay_bytes=4096)
    await session.start()
    await session.subscribe("owner")
    await session.subscribe("other")

    await session.set_input_lock("owner")
    with pytest.raises(PermissionError):
        await session.enqueue_input("other", 1, b"blocked")

    await session.enqueue_input("owner", 1, b"allowed")
    await session.wait_input_ack("owner", 1)
    assert pty.written == b"allowed"
    await session.close("test_complete")


@pytest.mark.asyncio
async def test_close_is_idempotent_and_terminates_pty_once():
    pty = FakePty()
    session = TerminalSession("s1", pty, replay_bytes=4096)
    await session.start()

    await session.close("test_complete")
    await session.close("test_complete")

    assert pty.terminated is True
    assert session.closed is True
