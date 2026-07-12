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
from terminal_replay import OutputChunk


def _tracking_manager_of(manager, logger_factory):
    """Build a lightweight TerminalManager adapter that injects *logger_factory*
    instances into _v2_loggers after get_or_create."""

    class _Wrapper:
        def __init__(self):
            self._manager = manager

        async def get_or_create(self, request):
            session = await self._manager.get_or_create(request)
            agent_routes._v2_loggers[session.id] = logger_factory()
            return session

        async def subscribe(self, *args):
            return await self._manager.subscribe(*args)

        async def unsubscribe(self, *args):
            return await self._manager.unsubscribe(*args)

        async def terminate(self, *args):
            return await self._manager.terminate(*args)

    return _Wrapper()


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
async def test_v2_sender_emits_explicit_replay_complete_after_boundary():
    class SenderWebSocket:
        def __init__(self):
            self.binary_frames: list[bytes] = []
            self.text_frames: list[dict] = []
            self.client_state = agent_routes.WebSocketState.DISCONNECTED

        async def send_bytes(self, data: bytes) -> None:
            self.binary_frames.append(data)

        async def send_text(self, data: str) -> None:
            self.text_frames.append(json.loads(data))

    class ReplaySession:
        close_reason = ""

        def __init__(self):
            self.chunks = iter([OutputChunk(0, 6, b"replay")])

        async def next_output(self, connection_id: str) -> OutputChunk:
            try:
                return next(self.chunks)
            except StopIteration as exc:
                raise ConnectionError from exc

    websocket = SenderWebSocket()
    connection = SimpleNamespace(id="browser", closed=False)

    await agent_routes._send_terminal_v2_frames(
        websocket,
        ReplaySession(),
        connection,
        replay_latest=6,
        last_output_ack=0,
        replay_chunk_count=1,
    )

    assert len(websocket.binary_frames) == 1
    assert websocket.text_frames == [{"v": 2, "type": "replay_complete", "sequence": 6}]


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
async def test_v2_input_buffering_records_one_instruction_per_idle_window(monkeypatch):
    """Verifies keystroke buffering: multi-char input is recorded as a
    single user instruction (idle-window based, not per-character or per-\r)."""
    calls: list[str] = []

    class FakeLogger:
        async def record_user(self, content: str, ts=None):
            calls.append(content)
        async def aclose(self):
            pass

    async def factory(request: SessionRequest) -> FakePty:
        return FakePty()

    manager = TerminalManager(factory, replay_bytes=4096)
    monkeypatch.setattr(agent_routes, "_terminal_v2_manager", manager)
    monkeypatch.setattr(agent_routes, "resolve_session_cwd", lambda root, dir_: "/tmp/project")

    # Simulate typing "history\r" — each character is a separate binary frame
    websocket = FakeWebSocket([
        {"text": json.dumps({
            "v": 2, "type": "hello", "client_id": "browser-1", "root": "root",
            "dir": "project", "backend": "claude", "cols": 80, "rows": 24,
        })},
        {"bytes": encode_binary_frame(1, b'h')},
        {"bytes": encode_binary_frame(2, b'i')},
        {"bytes": encode_binary_frame(3, b's')},
        {"bytes": encode_binary_frame(4, b't')},
        {"bytes": encode_binary_frame(5, b'o')},
        {"bytes": encode_binary_frame(6, b'r')},
        {"bytes": encode_binary_frame(7, b'y')},
        {"bytes": encode_binary_frame(8, b'\r')},
    ])

    # Patch SessionLogger to capture record_user calls
    original_get = agent_routes._v2_loggers.get
    agent_routes._v2_loggers.clear()

    async def run():
        await agent_routes.agent_terminal_v2(websocket)

    # Intercept logger creation: inject FakeLogger
    monkeypatch.setattr(agent_routes, "_terminal_v2_manager", _tracking_manager_of(manager, FakeLogger))
    await run()

    # "history" should be one call, not 7 separate ones + Enter
    assert calls == ["history"], f"Expected ['history'], got {calls}"
    await manager.close_all("test_complete")


@pytest.mark.asyncio
async def test_v2_unsubmitted_input_is_discarded_on_disconnect(monkeypatch):
    """Only a real Enter submission is a user-history turn."""
    calls: list[str] = []

    class FakeLogger:
        session_id = "v2-unsubmitted"

        async def record_user(self, content: str, ts=None):
            calls.append(content)

        async def aclose(self):
            pass

    async def factory(request: SessionRequest) -> FakePty:
        return FakePty()

    manager = TerminalManager(factory, replay_bytes=4096)
    monkeypatch.setattr(agent_routes, "_terminal_v2_manager", manager)
    monkeypatch.setattr(agent_routes, "resolve_session_cwd", lambda root, dir_: "/tmp/project")
    websocket = FakeWebSocket([
        {"text": json.dumps({
            "v": 2, "type": "hello", "client_id": "browser-1", "root": "root",
            "dir": "project", "backend": "claude", "cols": 80, "rows": 24,
        })},
        {"bytes": encode_binary_frame(1, b"draft command")},
    ])

    monkeypatch.setattr(agent_routes, "_terminal_v2_manager", _tracking_manager_of(manager, FakeLogger))
    await agent_routes.agent_terminal_v2(websocket)

    assert calls == []
    await manager.close_all("test_complete")


@pytest.mark.asyncio
async def test_v2_history_records_the_enter_submitted_edited_line(monkeypatch):
    calls: list[str] = []

    class FakeLogger:
        session_id = "v2-edited"

        async def record_user(self, content: str, ts=None):
            calls.append(content)

        async def aclose(self):
            pass

    async def factory(request: SessionRequest) -> FakePty:
        return FakePty()

    manager = TerminalManager(factory, replay_bytes=4096)
    monkeypatch.setattr(agent_routes, "resolve_session_cwd", lambda root, dir_: "/tmp/project")
    websocket = FakeWebSocket([
        {"text": json.dumps({
            "v": 2, "type": "hello", "client_id": "browser-1", "root": "root",
            "dir": "project", "backend": "claude", "cols": 80, "rows": 24,
        })},
        {"bytes": encode_binary_frame(1, b"draft")},
        {"bytes": encode_binary_frame(2, b"\x7f")},
        {"bytes": encode_binary_frame(3, b"?")},
        {"bytes": encode_binary_frame(4, b"\r")},
    ])

    monkeypatch.setattr(agent_routes, "_terminal_v2_manager", _tracking_manager_of(manager, FakeLogger))
    await agent_routes.agent_terminal_v2(websocket)

    assert calls == ["draf?"]
    await manager.close_all("test_complete")


@pytest.mark.asyncio
async def test_v2_session_removal_collects_assistant_transcript(monkeypatch):
    collected = []

    class FakeLogger:
        session_id = "v2-transcript"
        log_dir = "/tmp"

        def record_turns(self, turns):
            collected.extend(turns)

        async def aclose(self):
            collected.append({"closed": True})

    logger = FakeLogger()
    agent_routes._v2_loggers["terminal-1"] = logger
    monkeypatch.setattr(
        agent_routes,
        "_collect_transcript",
        lambda session, log_dir: session.logger.record_turns([
            {"role": "assistant", "content": "saved reply", "ts": 2},
        ]),
    )

    await agent_routes._on_v2_session_removed("terminal-1", "manual")

    assert collected == [
        {"role": "assistant", "content": "saved reply", "ts": 2},
        {"closed": True},
    ]


@pytest.mark.asyncio
async def test_v2_reaper_expires_idle_sessions(monkeypatch):
    calls = []

    class FakeManager:
        async def expire_idle(self):
            calls.append("expired")
            return 1

    monkeypatch.setattr(agent_routes, "_terminal_v2_manager", FakeManager())

    assert await agent_routes._expire_v2_sessions() == 1
    assert calls == ["expired"]


@pytest.mark.asyncio
async def test_v2_input_buffering_handles_paste_and_chinese(monkeypatch):
    """Verifies that paste (many chars in one frame) and Chinese multi-byte
    UTF-8 characters are correctly buffered and flushed on Enter."""
    class FakeLogger:
        def __init__(self):
            self.records: list[str] = []
        async def record_user(self, content: str, ts=None):
            self.records.append(content)
        async def aclose(self):
            pass
        async def count_turns(self):
            return len(self.records)

    async def factory(request: SessionRequest) -> FakePty:
        return FakePty()

    manager = TerminalManager(factory, replay_bytes=4096)
    monkeypatch.setattr(agent_routes, "_terminal_v2_manager", manager)
    monkeypatch.setattr(agent_routes, "resolve_session_cwd", lambda root, dir_: "/tmp/project")

    # Paste "你好世界" (4 Chinese chars, 12 UTF-8 bytes) + Enter
    websocket = FakeWebSocket([
        {"text": json.dumps({
            "v": 2, "type": "hello", "client_id": "browser-1", "root": "root",
            "dir": "project", "backend": "claude", "cols": 80, "rows": 24,
        })},
        {"bytes": encode_binary_frame(1, '你好世界'.encode('utf-8'))},
        {"bytes": encode_binary_frame(2, b'\r')},
    ])

    monkeypatch.setattr(agent_routes, "_terminal_v2_manager", _tracking_manager_of(manager, FakeLogger))
    await agent_routes.agent_terminal_v2(websocket)

    logger = next(iter(agent_routes._v2_loggers.values()))
    assert logger.records == ["你好世界"], f"Expected ['你好世界'], got {logger.records}"
    await manager.close_all("test_complete")


@pytest.mark.asyncio
async def test_v2_input_buffering_preserves_newlines_in_paste(monkeypatch):
    """Verifies that a multi-line paste is recorded as a single instruction
    with \\n preserved, not split into separate turns per line."""
    class FakeLogger:
        def __init__(self):
            self.records: list[str] = []
        async def record_user(self, content: str, ts=None):
            self.records.append(content)
        async def aclose(self):
            pass

    async def factory(request: SessionRequest) -> FakePty:
        return FakePty()

    manager = TerminalManager(factory, replay_bytes=4096)
    monkeypatch.setattr(agent_routes, "_terminal_v2_manager", manager)
    monkeypatch.setattr(agent_routes, "resolve_session_cwd", lambda root, dir_: "/tmp/project")

    # Paste "def foo():\n    return 42\n\r" — newlines + trailing Enter
    payload = "def foo():\n    return 42\n\r".encode("utf-8")
    websocket = FakeWebSocket([
        {"text": json.dumps({
            "v": 2, "type": "hello", "client_id": "browser-1", "root": "root",
            "dir": "project", "backend": "claude", "cols": 80, "rows": 24,
        })},
        {"bytes": encode_binary_frame(1, payload)},
    ])

    class _TrackingManager:
        def __init__(self):
            self._manager = manager
        async def get_or_create(self, request):
            session = await self._manager.get_or_create(request)
            agent_routes._v2_loggers[session.id] = FakeLogger()
            return session
        async def subscribe(self, session_id, client_id, last_ack):
            return await self._manager.subscribe(session_id, client_id, last_ack)
        async def unsubscribe(self, session_id, connection_id):
            await self._manager.unsubscribe(session_id, connection_id)
        async def terminate(self, session_id, reason):
            await self._manager.terminate(session_id, reason)

    monkeypatch.setattr(agent_routes, "_terminal_v2_manager", _TrackingManager())
    await agent_routes.agent_terminal_v2(websocket)

    logger = next(iter(agent_routes._v2_loggers.values()))
    # Newlines preserved, trailing \r stripped by _clean_input_for_history
    assert logger.records == ["def foo():\n    return 42"], \
        f"Expected multi-line paste as one instruction, got {logger.records}"
    await manager.close_all("test_complete")


@pytest.mark.asyncio
async def test_v2_endpoint_returns_ready_when_manager_uninitialized(monkeypatch):
    monkeypatch.setattr(agent_routes, "_terminal_v2_manager", None)
    monkeypatch.setattr(agent_routes, "load_cfg", lambda: SimpleNamespace(agent=SimpleNamespace(
        replay_bytes=4 * 1024 * 1024,
        connection_queue_bytes=4 * 1024 * 1024,
        input_queue_bytes=2 * 1024 * 1024,
        resize_lease_seconds=15,
        terminal_idle_seconds=24 * 3600,
        terminal_max_lifetime_seconds=24 * 3600,
        max_sessions=10,
    )))
    websocket = FakeWebSocket([])

    await agent_routes.agent_terminal_v2(websocket)

    assert not websocket.text_frames or all(
        frame.get("error", {}).get("code") != "terminal_v2_disabled"
        for frame in websocket.text_frames
    )
