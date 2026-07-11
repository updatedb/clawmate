from __future__ import annotations

import asyncio
import fcntl
import os
import struct
import termios
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

try:
    from terminal_session import PtyAdapter, TerminalConnection, TerminalSession
except ModuleNotFoundError:  # pragma: no cover - exercised by the test import path
    from dev.terminal_session import PtyAdapter, TerminalConnection, TerminalSession


@dataclass(frozen=True, slots=True)
class SessionRequest:
    backend: str
    root: str
    project: str
    cwd: str

    @property
    def key(self) -> str:
        scope = self.root if not self.project else f"{self.root}:{self.project}"
        return f"{self.backend}:{scope}"


PtyFactory = Callable[[SessionRequest], Awaitable[PtyAdapter]]


class PosixPtyAdapter:
    """Async wrapper around the master side of a non-blocking POSIX PTY."""

    def __init__(self, master_fd: int, process: object):
        self.master_fd = master_fd
        self.process = process
        self._closed = False
        os.set_blocking(master_fd, False)

    async def read(self, size: int) -> bytes:
        while True:
            try:
                return os.read(self.master_fd, size)
            except BlockingIOError:
                await self._wait_for_fd(readable=True)

    async def write_all(self, data: bytes) -> None:
        view = memoryview(data)
        while view:
            try:
                written = os.write(self.master_fd, view)
                view = view[written:]
            except BlockingIOError:
                await self._wait_for_fd(readable=False)

    async def resize(self, cols: int, rows: int) -> None:
        was_blocking = os.get_blocking(self.master_fd)
        try:
            os.set_blocking(self.master_fd, True)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        finally:
            os.set_blocking(self.master_fd, was_blocking)

    async def terminate(self) -> None:
        if self._closed:
            return
        self._closed = True
        if getattr(self.process, "returncode", None) is None:
            self.process.terminate()
        try:
            os.close(self.master_fd)
        except OSError:
            pass

    async def _wait_for_fd(self, *, readable: bool) -> None:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()

        def ready() -> None:
            if not future.done():
                future.set_result(None)

        if readable:
            loop.add_reader(self.master_fd, ready)
        else:
            loop.add_writer(self.master_fd, ready)
        try:
            await future
        finally:
            if readable:
                loop.remove_reader(self.master_fd)
            else:
                loop.remove_writer(self.master_fd)


class TerminalManager:
    """Registry for persistent v2 terminal sessions and their idle lifetime."""

    def __init__(
        self,
        pty_factory: PtyFactory,
        *,
        replay_bytes: int,
        connection_queue_bytes: int = 4 * 1024 * 1024,
        input_queue_bytes: int = 2 * 1024 * 1024,
        resize_lease_seconds: int = 15,
        idle_seconds: int = 600,
        max_sessions: int = 10,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._pty_factory = pty_factory
        self._replay_bytes = replay_bytes
        self._connection_queue_bytes = connection_queue_bytes
        self._input_queue_bytes = input_queue_bytes
        self._resize_lease_seconds = resize_lease_seconds
        self._idle_seconds = idle_seconds
        self._max_sessions = max_sessions
        self._clock = clock
        self._sessions: dict[str, TerminalSession] = {}
        self._keys: dict[str, str] = {}
        self._idle_since: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._next_id = 0

    async def get_or_create(self, request: SessionRequest) -> TerminalSession:
        async with self._lock:
            session_id = self._keys.get(request.key)
            session = self._sessions.get(session_id or "")
            if session and not session.closed:
                return session
            return await self._create_locked(request)

    async def create_fresh(self, request: SessionRequest) -> TerminalSession:
        async with self._lock:
            previous_id = self._keys.get(request.key)
            if previous_id:
                await self._remove_locked(previous_id, "replaced")
            return await self._create_locked(request)

    async def subscribe(self, session_id: str, connection_id: str, last_output_ack: int = 0) -> TerminalConnection:
        session = self._require(session_id)
        connection = await session.subscribe(connection_id, last_output_ack)
        self._idle_since.pop(session_id, None)
        return connection

    async def unsubscribe(self, session_id: str, connection_id: str) -> None:
        session = self._require(session_id)
        await session.unsubscribe(connection_id)
        if not session.connections:
            self._idle_since[session_id] = self._clock()

    async def terminate(self, session_id: str, reason: str) -> None:
        async with self._lock:
            await self._remove_locked(session_id, reason)

    async def expire_idle(self) -> int:
        async with self._lock:
            now = self._clock()
            expired = [
                session_id
                for session_id, idle_since in self._idle_since.items()
                if now - idle_since >= self._idle_seconds
            ]
            for session_id in expired:
                await self._remove_locked(session_id, "idle_expired")
            return len(expired)

    async def close_all(self, reason: str) -> None:
        async with self._lock:
            for session_id in list(self._sessions):
                await self._remove_locked(session_id, reason)

    def diagnostics(self) -> dict[str, int]:
        sessions = list(self._sessions.values())
        return {
            "session_count": len(sessions),
            "connection_count": sum(len(session.connections) for session in sessions),
            "reader_task_count": sum(session.reader_start_count for session in sessions),
            "writer_task_count": sum(session.writer_start_count for session in sessions),
            "idle_session_count": len(self._idle_since),
        }

    async def _create_locked(self, request: SessionRequest) -> TerminalSession:
        if len(self._sessions) >= self._max_sessions:
            raise RuntimeError("terminal session limit reached")
        pty = await self._pty_factory(request)
        self._next_id += 1
        session = TerminalSession(
            f"terminal-{self._next_id}",
            pty,
            replay_bytes=self._replay_bytes,
            connection_queue_bytes=self._connection_queue_bytes,
            input_queue_bytes=self._input_queue_bytes,
            resize_lease_seconds=self._resize_lease_seconds,
        )
        await session.start()
        self._sessions[session.id] = session
        self._keys[request.key] = session.id
        return session

    async def _remove_locked(self, session_id: str, reason: str) -> None:
        session = self._sessions.pop(session_id, None)
        if not session:
            return
        self._idle_since.pop(session_id, None)
        for key, mapped_id in list(self._keys.items()):
            if mapped_id == session_id:
                del self._keys[key]
        await session.close(reason)

    def _require(self, session_id: str) -> TerminalSession:
        session = self._sessions.get(session_id)
        if not session or session.closed:
            raise KeyError(f"unknown terminal session: {session_id}")
        return session
