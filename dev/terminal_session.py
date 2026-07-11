from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from collections.abc import Awaitable, Callable
from typing import Protocol

try:  # FastAPI imports modules from dev/, while tests import dev.* packages.
    from terminal_protocol import ProtocolError, validate_dimensions
    from terminal_replay import OutputChunk, ReplayRing
except ModuleNotFoundError:  # pragma: no cover - exercised by the test import path
    from dev.terminal_protocol import ProtocolError, validate_dimensions
    from dev.terminal_replay import OutputChunk, ReplayRing


class PtyAdapter(Protocol):
    async def read(self, size: int) -> bytes: ...

    async def write_all(self, data: bytes) -> None: ...

    async def resize(self, cols: int, rows: int) -> None: ...

    async def terminate(self) -> None: ...


@dataclass(slots=True)
class TerminalConnection:
    id: str
    output_queue: asyncio.Queue[OutputChunk | None]
    queued_bytes: int = 0
    last_output_ack: int = 0
    input_locked_out: bool = False
    closed: bool = False


@dataclass(slots=True)
class _InputFrame:
    connection_id: str
    sequence: int
    data: bytes


class TerminalSession:
    """Own one PTY reader/writer pair and bounded connection subscriptions."""

    def __init__(
        self,
        session_id: str,
        pty: PtyAdapter,
        *,
        replay_bytes: int,
        connection_queue_bytes: int = 4 * 1024 * 1024,
        input_queue_bytes: int = 2 * 1024 * 1024,
        resize_lease_seconds: int = 15,
        on_process_exited: Callable[[str], Awaitable[None]] | None = None,
    ):
        self.id = session_id
        self.pty = pty
        self.replay = ReplayRing(replay_bytes)
        self.connection_queue_bytes = connection_queue_bytes
        self.input_queue_bytes = input_queue_bytes
        self.resize_lease_seconds = resize_lease_seconds
        self.connections: dict[str, TerminalConnection] = {}
        self.reader_start_count = 0
        self.writer_start_count = 0
        self.closed = False
        self.close_reason = ""
        self._started = False
        self._reader_task: asyncio.Task[None] | None = None
        self._writer_task: asyncio.Task[None] | None = None
        self._input_queue: asyncio.Queue[_InputFrame] = asyncio.Queue()
        self._queued_input_bytes = 0
        self._input_acks: dict[tuple[str, int], asyncio.Future[None]] = {}
        self._input_lock_owner: str | None = None
        self._resize_owner: str | None = None
        self._resize_lease_expires_at = 0.0
        self._terminated = False
        self._on_process_exited = on_process_exited

    async def start(self) -> None:
        if self.closed:
            raise RuntimeError("terminal session is closed")
        if self._started:
            return
        self._started = True
        self.reader_start_count += 1
        self.writer_start_count += 1
        self._reader_task = asyncio.create_task(self._read_loop())
        self._writer_task = asyncio.create_task(self._write_loop())

    async def subscribe(self, connection_id: str, last_output_ack: int = 0) -> TerminalConnection:
        if self.closed:
            raise RuntimeError("terminal session is closed")
        await self.start()
        await self.unsubscribe(connection_id)
        connection = TerminalConnection(
            id=connection_id,
            output_queue=asyncio.Queue(),
            last_output_ack=max(0, last_output_ack),
        )
        self.connections[connection_id] = connection
        for chunk in self.replay.after(connection.last_output_ack).chunks:
            self._offer_output(connection, chunk)
            if connection.closed:
                break
        return connection

    async def unsubscribe(self, connection_id: str) -> None:
        connection = self.connections.pop(connection_id, None)
        if connection:
            connection.closed = True
        if self._resize_owner == connection_id:
            self._resize_owner = None
            self._resize_lease_expires_at = 0.0
        if self._input_lock_owner == connection_id:
            self._input_lock_owner = None

    async def next_output(self, connection_id: str) -> OutputChunk:
        connection = self.connections[connection_id]
        chunk = await connection.output_queue.get()
        if chunk is None:
            raise ConnectionError("terminal session closed")
        connection.queued_bytes -= len(chunk.data)
        return chunk

    def acknowledge_output(self, connection_id: str, sequence: int) -> None:
        connection = self.connections.get(connection_id)
        if connection:
            connection.last_output_ack = max(connection.last_output_ack, sequence)

    async def enqueue_input(self, connection_id: str, sequence: int, data: bytes) -> None:
        connection = self.connections.get(connection_id)
        if not connection or connection.closed:
            raise ConnectionError("terminal connection is not active")
        if self._input_lock_owner and self._input_lock_owner != connection_id:
            raise PermissionError("terminal input is locked by another connection")
        payload = bytes(data)
        if not payload:
            return
        if len(payload) > self.input_queue_bytes or self._queued_input_bytes + len(payload) > self.input_queue_bytes:
            raise ProtocolError("input_queue_full", "Terminal input queue is full")
        key = (connection_id, sequence)
        if key in self._input_acks:
            raise ProtocolError("duplicate_input", "Input sequence is already pending")
        future = asyncio.get_running_loop().create_future()
        self._input_acks[key] = future
        self._queued_input_bytes += len(payload)
        self._input_queue.put_nowait(_InputFrame(connection_id, sequence, payload))
        self._renew_resize_lease(connection_id)

    async def wait_input_ack(self, connection_id: str, sequence: int) -> None:
        key = (connection_id, sequence)
        future = self._input_acks.get(key)
        if future is None:
            return
        try:
            await future
        finally:
            self._input_acks.pop(key, None)

    async def focus(self, connection_id: str) -> None:
        if connection_id not in self.connections:
            raise ConnectionError("terminal connection is not active")
        self._renew_resize_lease(connection_id)

    async def resize(self, connection_id: str, cols: object, rows: object) -> bool:
        validate_dimensions(cols, rows)
        if connection_id not in self.connections:
            raise ConnectionError("terminal connection is not active")
        now = time.monotonic()
        if self._resize_owner and self._resize_lease_expires_at > now and self._resize_owner != connection_id:
            return False
        await self.pty.resize(cols, rows)
        self._renew_resize_lease(connection_id, now)
        return True

    async def set_input_lock(self, owner_connection_id: str | None) -> None:
        if owner_connection_id is not None and owner_connection_id not in self.connections:
            raise ConnectionError("terminal connection is not active")
        self._input_lock_owner = owner_connection_id
        for connection in self.connections.values():
            connection.input_locked_out = bool(owner_connection_id and connection.id != owner_connection_id)

    async def close(self, reason: str) -> None:
        if self.closed:
            return
        self.closed = True
        self.close_reason = reason
        for connection in self.connections.values():
            connection.closed = True
            connection.output_queue.put_nowait(None)
        self.connections.clear()
        for future in self._input_acks.values():
            if not future.done():
                future.set_exception(ConnectionError("terminal session closed"))
        tasks = [task for task in (self._reader_task, self._writer_task) if task]
        current_task = asyncio.current_task()
        for task in tasks:
            if task is not current_task:
                task.cancel()
        await asyncio.gather(*(task for task in tasks if task is not current_task), return_exceptions=True)
        if not self._terminated:
            self._terminated = True
            await self.pty.terminate()

    async def _read_loop(self) -> None:
        try:
            while not self.closed:
                data = await self.pty.read(64 * 1024)
                if not data:
                    await self._notify_process_exited()
                    return
                self.replay.append(data)
                chunk = OutputChunk(self.replay.latest_sequence - len(data), self.replay.latest_sequence, data)
                for connection in list(self.connections.values()):
                    self._offer_output(connection, chunk)
        except asyncio.CancelledError:
            raise
        except OSError:
            if not self.closed:
                await self._notify_process_exited()

    async def _notify_process_exited(self) -> None:
        if not self.closed and self._on_process_exited:
            await self._on_process_exited(self.id)

    async def _write_loop(self) -> None:
        try:
            while not self.closed:
                frame = await self._input_queue.get()
                self._queued_input_bytes -= len(frame.data)
                future = self._input_acks.get((frame.connection_id, frame.sequence))
                try:
                    await self.pty.write_all(frame.data)
                    if future and not future.done():
                        future.set_result(None)
                except Exception as exc:
                    if future and not future.done():
                        future.set_exception(exc)
        except asyncio.CancelledError:
            raise

    def _offer_output(self, connection: TerminalConnection, chunk: OutputChunk) -> None:
        if connection.closed:
            return
        if connection.queued_bytes + len(chunk.data) > self.connection_queue_bytes:
            # Connection send queue is full (WS sender can't keep up with PTY
            # output rate).  Instead of hard‑closing the WebSocket — which loses
            # input capability and triggers a disruptive reconnect cycle — skip
            # the chunk for this connection.  The sender will continue draining
            # older chunks, and once it catches up new output will be delivered
            # normally.  Skipped content is available from the replay buffer on
            # reconnect, and the terminal's own scrollback captures the PTY
            # output via the ReadLoop → terminal data path.
            return
        connection.output_queue.put_nowait(chunk)
        connection.queued_bytes += len(chunk.data)

    def _renew_resize_lease(self, connection_id: str, now: float | None = None) -> None:
        self._resize_owner = connection_id
        self._resize_lease_expires_at = (time.monotonic() if now is None else now) + self.resize_lease_seconds
