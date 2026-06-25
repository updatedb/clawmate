"""
Agent WebSocket routes — connects xterm.js to Claude Code (or OpenClaw).

Endpoint:  ws://.../api/clawmate/agent/terminal?root=<root_id>&dir=<rel_dir>
Backends:  claude (pty.spawn → claude CLI), openclaw (reserved)

Session persistence: Claude Code processes survive WebSocket disconnects.
Reconnecting within the idle timeout resumes the same session.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import pty
import signal
import struct
import termios
import time
import websockets
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from starlette.websockets import WebSocketState

from config import load as load_cfg
from service import find_project_marker

router = APIRouter()
logger = logging.getLogger("clawmate.agent")

# --- Session manager ---

# Max output buffer per session (keep last ~200KB of terminal output for replay)
_MAX_BUFFER_ENTRIES = 200  # ~200 chunks ≈ ~800KB with typical 4KB reads
# Idle timeout: kill session after N seconds with no WebSocket attached
_IDLE_TIMEOUT_SECONDS = 600  # 10 minutes
# Max session lifetime (even with active connections)
_MAX_SESSION_LIFETIME = 24 * 3600  # 24 hours


@dataclass
class _AgentSession:
    """A persistent Claude Code process that survives WebSocket reconnects."""
    key: str
    proc: object  # asyncio subprocess
    master_fd: int
    stop_event: asyncio.Event
    output_buffer: deque = field(default_factory=lambda: deque(maxlen=_MAX_BUFFER_ENTRIES))
    ws_set: set = field(default_factory=set)  # currently attached WebSocket(s)
    created_at: float = 0.0
    last_active: float = 0.0
    last_input_time: float = 0.0  # timestamp of last user keystroke (for output coordination)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()
        if not self.last_active:
            self.last_active = time.time()


# session registry: key → _AgentSession
_sessions: dict[str, _AgentSession] = {}
_session_lock = asyncio.Lock()


def _session_key(root: str, dir_: str = "", backend: str = "claude") -> str:
    """构造 session key。格式为 {backend}:{root}[:{project}] 以确保不同后端会话隔离。"""
    base = root
    if dir_:
        root_path = _resolve_root_dir(root)
        if root_path:
            project = find_project_marker(root_path, dir_)
            if project:
                base = f"{root}:{project}"
    return f"{backend}:{base}"


def _resolve_session_cwd(root: str, dir_: str = "") -> str:
    """确定 session 的工作目录。有 .clawmate marker → marker 所在目录，无 → root 目录。"""
    root_path = _resolve_root_dir(root)
    if not root_path:
        return os.path.expanduser("~")
    if dir_:
        project = find_project_marker(root_path, dir_)
        if project:
            return str(root_path / project)
    return str(root_path)


def get_agent_session(root: str, dir_: str = "", backend: str = ""):
    """Return active agent session for root+dir, or None.

    Uses .clawmate/ marker walking to determine session key.
    If backend is specified, only searches that backend.
    If not, searches all PTY backends (claude, codex).
    Only returns session if:
    - It exists and stop_event is not set
    - It has at least one active WebSocket (someone is viewing the terminal)
    - The agent process is still running
    """
    backends = [backend] if backend else ["claude", "codex"]
    for bk in backends:
        key = _session_key(root, dir_, bk)
        sess = _sessions.get(key)
        if not sess:
            continue
        if sess.stop_event.is_set():
            continue
        if not sess.ws_set:
            continue
        if sess.proc and hasattr(sess.proc, "returncode") and sess.proc.returncode is not None:
            continue
        return sess
    return None


def inject_to_session(sess, text: str):
    """Write text into a Claude Code PTY session (non-blocking)."""
    try:
        os.write(sess.master_fd, text.encode())
    except (OSError, BlockingIOError):
        pass


def _cleanup_dead_sessions():
    """Remove sessions whose processes have died."""
    dead = []
    for key, sess in _sessions.items():
        if sess.stop_event.is_set():
            dead.append(key)
        elif sess.proc and hasattr(sess.proc, 'returncode') and sess.proc.returncode is not None:
            dead.append(key)
    for key in dead:
        try:
            sess = _sessions.pop(key)
            try:
                os.close(sess.master_fd)
            except OSError:
                pass
        except KeyError:
            pass
    if dead:
        logger.debug("cleaned %d dead sessions, %d remain", len(dead), len(_sessions))


async def _idle_reaper():
    """Periodically kill sessions that have been idle with NO WebSocket attached.

    Never kills an active session. Only cleans up orphans after the
    idle timeout (10 min with no client) or max lifetime (24h with no client).
    """
    while True:
        await asyncio.sleep(60)  # check every minute
        now = time.time()
        dead = []
        for key, sess in list(_sessions.items()):
            # Skip sessions that still have active WebSockets — never kill them
            if sess.ws_set:
                continue
            # No WebSocket attached: kill if idle too long OR exceeded max lifetime
            if ((now - sess.last_active) > _IDLE_TIMEOUT_SECONDS or
                (now - sess.created_at) > _MAX_SESSION_LIFETIME):
                dead.append(key)
        for key in dead:
            sess = _sessions.pop(key, None)
            if sess:
                sess.stop_event.set()
                try:
                    os.killpg(os.getpgid(sess.proc.pid), signal.SIGTERM)
                    idle_sec = now - sess.last_active
                    lifetime_sec = now - sess.created_at
                    logger.info(
                        "reaper killed session key=%s pid=%d idle=%.0fs lifetime=%.0fs (%d sessions remain)",
                        key, sess.proc.pid, idle_sec, lifetime_sec, len(_sessions),
                    )
                except (ProcessLookupError, OSError):
                    logger.info(
                        "reaper cleaned dead session key=%s pid=%d (process already gone)",
                        key, sess.proc.pid,
                    )
                try:
                    os.close(sess.master_fd)
                except OSError:
                    pass


# Start reaper on module load
_reaper_task = None


def _ensure_reaper():
    global _reaper_task
    if _reaper_task is None or _reaper_task.done():
        try:
            loop = asyncio.get_running_loop()
            _reaper_task = loop.create_task(_idle_reaper())
        except RuntimeError:
            pass


# --- helpers ---

def _resolve_root_dir(root_id: str) -> Path | None:
    """Resolve a root_id to an absolute directory path."""
    if not root_id:
        return None
    try:
        cfg = load_cfg()
        return cfg.root_dir(root_id)
    except (ValueError, Exception):
        return None


def _find_binary(name: str, candidates: list[str]) -> str:
    """Find a CLI binary from a list of candidate paths, falling back to PATH."""
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    import shutil
    found = shutil.which(name)
    if found:
        return found
    raise RuntimeError(f"{name} CLI not found in PATH")

def _find_claude_binary() -> str:
    """Find the claude CLI binary."""
    return _find_binary("claude", [
        "/usr/local/bin/claude",
        "/usr/bin/claude",
        os.path.expanduser("~/.npm-global/bin/claude"),
        os.path.expanduser("~/.local/bin/claude"),
    ])

def _find_codex_binary() -> str:
    """Find the codex CLI binary."""
    return _find_binary("codex", [
        "/usr/local/bin/codex",
        "/usr/bin/codex",
        os.path.expanduser("~/.npm-global/bin/codex"),
        os.path.expanduser("~/.local/bin/codex"),
    ])


# --- PTY agent backends (Claude, Codex) ---

async def _spawn_pt(cwd: str, cols: int, rows: int, binary: str,
                     extra_args: list[str] | None = None,
                     extra_env: dict[str, str] | None = None) -> _AgentSession | None:
    """Spawn a new agent PTY process. Returns session or None on failure."""
    master_fd, slave_fd = pty.openpty()
    if cols > 0 and rows > 0:
        wsize = os.terminal_size((cols, rows))
    else:
        try:
            wsize = os.get_terminal_size()
        except OSError:
            wsize = os.terminal_size((80, 24))
    fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", wsize.lines, wsize.columns, 0, 0))
    os.set_blocking(master_fd, False)

    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    if extra_env:
        env.update(extra_env)

    args = [binary]
    if extra_args:
        args.extend(extra_args)

    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
        preexec_fn=os.setsid,
        close_fds=True,
    )
    os.close(slave_fd)

    return _AgentSession(
        key="",
        proc=proc,
        master_fd=master_fd,
        stop_event=asyncio.Event(),
    )

async def _spawn_claude(cwd: str, cols: int = 0, rows: int = 0,
                        extra_env: dict[str, str] | None = None) -> _AgentSession | None:
    """Spawn a new Claude Code PTY process."""
    try:
        binary = _find_claude_binary()
    except RuntimeError:
        return None
    base_env = {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
    if extra_env:
        base_env.update(extra_env)
    return await _spawn_pt(cwd, cols, rows, binary,
                           extra_args=["--dangerously-skip-permissions"],
                           extra_env=base_env)

async def _spawn_codex(cwd: str, cols: int = 0, rows: int = 0,
                       extra_env: dict[str, str] | None = None) -> _AgentSession | None:
    """Spawn a new Codex agent PTY process."""
    try:
        binary = _find_codex_binary()
    except RuntimeError:
        return None
    return await _spawn_pt(cwd, cols, rows, binary, extra_env=extra_env)


async def _attach_session(sess: _AgentSession, ws: WebSocket, root: str = ""):
    """Bridge a WebSocket to an existing PTY session."""
    sess.ws_set.add(ws)
    sess.last_active = time.time()

    # Replay buffered output so the new client sees history
    for chunk in list(sess.output_buffer):
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_text(chunk)
        except WebSocketDisconnect:
            break

    async def ws_to_pty():
        """Forward WebSocket → PTY (keyboard input)."""
        try:
            while not sess.stop_event.is_set():
                try:
                    data = await asyncio.wait_for(ws.receive_text(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                except WebSocketDisconnect:
                    break

                # Control messages — only {} objects with a "type" key
                try:
                    msg = json.loads(data)
                    if isinstance(msg, dict):
                        if msg.get("type") == "resize":
                            cols = msg.get("cols", 80)
                            rows = msg.get("rows", 24)
                            try:
                                os.set_blocking(sess.master_fd, True)
                                fcntl.ioctl(sess.master_fd, termios.TIOCSWINSZ,
                                            struct.pack("HHHH", rows, cols, 0, 0))
                                os.set_blocking(sess.master_fd, False)
                            except Exception:
                                pass
                            continue
                        if msg.get("type") == "chdir":
                            new_root = msg.get("root", root)
                            new_dir = msg.get("dir", "")
                            _bk = sess.key.split(":")[0] if sess.key and ":" in sess.key else "claude"
                            new_key = _session_key(new_root, new_dir, _bk)
                            for w in list(sess.ws_set):
                                try:
                                    if w.client_state == WebSocketState.CONNECTED:
                                        await w.send_text(json.dumps({
                                            "type": "session",
                                            "key": new_key,
                                        }, ensure_ascii=False))
                                except Exception:
                                    pass
                            continue
                except (json.JSONDecodeError, TypeError, AttributeError):
                    pass

                # Raw terminal input
                try:
                    os.write(sess.master_fd, data.encode())
                except (OSError, BlockingIOError):
                    pass
                sess.last_input_time = time.time()
                sess.last_active = time.time()
        except Exception:
            pass

    async def pty_to_ws():
        """Forward PTY output → WebSocket + buffer (60fps flush to prevent interleaving)."""
        out_buf = ""
        last_flush = time.monotonic()
        FLUSH_INTERVAL = 0.016  # ~60fps, groups tiny reads into smooth chunks
        try:
            while not sess.stop_event.is_set():
                try:
                    data = os.read(sess.master_fd, 4096)
                    if not data:
                        break  # PTY closed — Claude Code exited
                    text = data.decode("utf-8", errors="replace")
                    sess.output_buffer.append(text)
                    out_buf += text
                    now = time.monotonic()
                    # Brief yield after user input so echo arrives before output
                    if sess.last_input_time and (now - sess.last_input_time) < 0.05:
                        await asyncio.sleep(0.01)
                    if now - last_flush >= FLUSH_INTERVAL and out_buf:
                        batch = out_buf
                        out_buf = ""
                        last_flush = now
                        for w in list(sess.ws_set):
                            try:
                                if w.client_state == WebSocketState.CONNECTED:
                                    await w.send_text(batch)
                            except WebSocketDisconnect:
                                sess.ws_set.discard(w)
                            except Exception:
                                pass
                except BlockingIOError:
                    # Flush any pending output on idle
                    if out_buf:
                        batch = out_buf
                        out_buf = ""
                        last_flush = time.monotonic()
                        for w in list(sess.ws_set):
                            try:
                                if w.client_state == WebSocketState.CONNECTED:
                                    await w.send_text(batch)
                            except WebSocketDisconnect:
                                sess.ws_set.discard(w)
                            except Exception:
                                pass
                    await asyncio.sleep(0.01)
                except OSError:
                    break  # master_fd closed — session is shutting down
        except Exception:
            pass
        finally:
            # Final flush
            if out_buf:
                for w in list(sess.ws_set):
                    try:
                        if w.client_state == WebSocketState.CONNECTED:
                            await w.send_text(out_buf)
                    except Exception:
                        pass

    await asyncio.gather(ws_to_pty(), pty_to_ws())

    # WebSocket disconnected — detach but keep session alive
    sess.ws_set.discard(ws)
    sess.last_active = time.time()


# --- Markdown → ANSI terminal converter ---

# --- OpenClaw backend ---

async def _openclaw_backend(
    ws: WebSocket,
    cwd: str,
    cfg,
    root: str,
    agent_id: str,
):
    """Connect to OpenClaw gateway WebSocket and bridge to xterm.js."""
    agent_cfg = cfg.agent
    oc_url = agent_cfg.openclaw_ws_url
    oc_token = agent_cfg.openclaw_token

    if not oc_url:
        await ws.send_text(
            "\x1b[1;31m✕ OpenClaw WebSocket URL not configured\x1b[0m\r\n"
            "\x1b[2m  Set agent.openclaw_ws_url in config.json\x1b[0m\r\n"
        )
        return
    if not oc_token:
        await ws.send_text(
            "\x1b[1;31m✕ OpenClaw token not configured\x1b[0m\r\n"
            "\x1b[2m  Set agent.openclaw_token in config.json\x1b[0m\r\n"
        )
        return

    # Device identity for pairing
    # Configured URL first, local Gateway default as fallback
    try_urls = [oc_url] if oc_url else []
    fallback = "ws://127.0.0.1:18789"
    if fallback not in try_urls:
        try_urls.append(fallback)

    oc_ws = None
    req_id = 0
    line_buf = ""

    for url in try_urls:
        try:
            oc_ws = await asyncio.wait_for(
                websockets.connect(url, ping_interval=30, ping_timeout=60),
                timeout=5,
            )
            conn_url = url
            break
        except Exception:
            continue

    if oc_ws is None:
        await ws.send_text(
            f"\x1b[1;31m✕ Cannot connect to OpenClaw gateway\x1b[0m\r\n"
            f"\x1b[2m  Tried: {', '.join(try_urls)}\x1b[0m\r\n"
        )
        return

    async def oc_send(method, params=None):
        nonlocal req_id
        req_id += 1
        msg = {"type": "req", "id": str(req_id), "method": method}
        if params:
            msg["params"] = params
        raw = json.dumps(msg)
        await oc_ws.send(raw)
        return req_id

    try:
        # Step 1: receive challenge
        raw = await asyncio.wait_for(oc_ws.recv(), timeout=5)
        challenge = json.loads(raw)
        if challenge.get("event") != "connect.challenge":
            await ws.send_text(json.dumps({"type": "error", "text": "Unexpected OpenClaw handshake"}, ensure_ascii=False))
            return

        # Step 2: authenticate
        await oc_send("connect", {
            "minProtocol": 4, "maxProtocol": 4,
            "client": {"id": "gateway-client", "version": "1.0.0", "platform": "linux", "mode": "backend"},
            "role": "operator",
            "scopes": ["operator.read", "operator.write", "operator.admin"],
            "auth": {"token": oc_token},
            "locale": "en-US",
            "userAgent": "clawmate-agent/1.0.0",
        })

        hello_raw = await asyncio.wait_for(oc_ws.recv(), timeout=5)
        hello = json.loads(hello_raw)
        if not hello.get("ok"):
            err = hello.get("error", {}).get("message", "unknown")
            await ws.send_text(json.dumps({"type": "error", "text": f"OpenClaw auth failed: {err}"}, ensure_ascii=False))
            return

        # Save device token if returned (pairing approved)
        new_device_token = hello.get("payload", {}).get("auth", {}).get("deviceToken", "")
        if new_device_token and new_device_token != device_token:
            await ws.send_text(json.dumps({
                "type": "info",
                "text": f"Device paired! Token saved. Add to config.json: agent.openclaw_device_token"
            }, ensure_ascii=False))
            # Log for user to save
            import sys
            print(f"[clawmate] OpenClaw device paired. Add to config.json: \"openclaw_device_token\": \"{new_device_token}\"", file=sys.stderr)

        # Log granted scopes
        granted = hello.get("payload", {}).get("auth", {}).get("scopes", [])

        server_ver = hello.get("payload", {}).get("server", {}).get("version", "?")
        conn_id = hello.get("payload", {}).get("server", {}).get("connId", "?")
        await ws.send_text(json.dumps({
            "type": "info",
            "text": f"✓ 已连接 OpenClaw Gateway v{server_ver}\ncwd: {cwd}\n输入消息后按 Enter 发送",
            "serverVer": server_ver,
            "connId": conn_id,
            "sessionKey": f"agent:{agent_id or 'default'}:main",
            "cwd": cwd,
        }, ensure_ascii=False))

        # Step 3: load history (if any) — drain response before bridge
        await oc_send("chat.history", {
            "sessionKey": f"agent:{agent_id or 'default'}:main",
            "limit": 20,
        })
        # Drain chat.history response + any pending events
        await ws.send_text(json.dumps({"type": "info", "text": "Loading history..."}, ensure_ascii=False))
        try:
            for _ in range(20):
                raw = await asyncio.wait_for(oc_ws.recv(), timeout=0.5)
                evt = json.loads(raw)
                if evt.get("event") == "chat" and evt.get("payload", {}).get("state") == "history":
                    entries = evt.get("payload", {}).get("entries", [])
                    if entries:
                        for entry in entries[-5:]:
                            role = entry.get("role", "")
                            content = entry.get("message", {}).get("content", "")
                            if isinstance(content, list):
                                content = " ".join(
                                    c.get("text", "") for c in content
                                    if isinstance(c, dict) and c.get("type") == "text"
                                )
                            content = str(content)[:300]
                            if content.strip():
                                await ws.send_text(json.dumps({
                                    "type": "assistant" if role == "assistant" else "user",
                                    "text": content,
                                    "final": True,
                                }, ensure_ascii=False))
                    break
        except (asyncio.TimeoutError, Exception):
            pass

        # Step 4: bidirectional bridge — structured JSON for chat UI
        first_msg = True
        done = False

        async def send_json(obj):
            """Send structured JSON to frontend."""
            try:
                await ws.send_text(json.dumps(obj, ensure_ascii=False))
            except Exception:
                pass

        while not done:
            # --- Read line from xterm.js ---
            try:
                while True:
                    try:
                        data = await asyncio.wait_for(ws.receive_text(), timeout=0.5)
                        break
                    except asyncio.TimeoutError:
                        continue
            except WebSocketDisconnect:
                break

            # Skip control messages — only {} objects with a "type" key
            try:
                ctrl = json.loads(data)
                if isinstance(ctrl, dict):
                    if ctrl.get("type") == "resize":
                        continue
                    if ctrl.get("type") == "chdir":
                        new_root = ctrl.get("root", root)
                        new_dir = ctrl.get("dir", "")
                        new_key = _session_key(new_root, new_dir, "openclaw")
                        try:
                            await ws.send_text(json.dumps({
                                "type": "session",
                                "key": new_key,
                            }, ensure_ascii=False))
                        except Exception:
                            pass
                        continue
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass

            # Buffer characters into lines
            for ch in data:
                if ch == '\r' or ch == '\n':
                    line = line_buf.strip()
                    line_buf = ""
                    if line:
                        msg = line
                        if first_msg:
                            pass  # work dir shown in info banner
                            first_msg = False
                        await send_json({"type": "user", "text": line})
                        await oc_send("chat.send", {
                            "sessionKey": f"agent:{agent_id or 'default'}:main",
                            "message": msg,
                            "idempotencyKey": f"clawmate-{int(time.time()*1000)}",
                        })

                        # --- Wait for agent response ---
                        while True:
                            try:
                                raw = await asyncio.wait_for(oc_ws.recv(), timeout=45)
                            except asyncio.TimeoutError:
                                await send_json({"type": "error", "text": "Agent response timed out"})
                                break
                            except websockets.exceptions.ConnectionClosed:
                                done = True
                                break
                            except Exception:
                                done = True
                                break

                            try:
                                evt = json.loads(raw)
                            except json.JSONDecodeError:
                                continue

                            event = evt.get("event", "")
                            payload = evt.get("payload", {})
                            t = evt.get("type", "")

                            if t == "res" and not evt.get("ok"):
                                err = evt.get("error", {}).get("message", "?")
                                await send_json({"type": "error", "text": err})
                                break

                            if event == "chat":
                                state = payload.get("state", "")
                                if state == "delta":
                                    delta = payload.get("deltaText", "")
                                    if delta:
                                        await send_json({"type": "assistant", "text": delta, "final": False})
                                elif state == "final":
                                    await send_json({"type": "assistant", "text": "", "final": True})
                                continue

                            if event == "agent" and payload.get("stream") == "lifecycle":
                                phase = payload.get("data", {}).get("phase", "")
                                if phase == "end":
                                    reason = payload.get("data", {}).get("stopReason", "")
                                    await send_json({"type": "assistant", "text": "", "final": True, "stopReason": reason})
                                    for _ in range(5):
                                        try:
                                            await asyncio.wait_for(oc_ws.recv(), timeout=0.3)
                                        except (asyncio.TimeoutError, Exception):
                                            break
                                    break
                                continue
                elif ch == '\x7f':
                    if line_buf:
                        line_buf = line_buf[:-1]
                else:
                    line_buf += ch

    except Exception as e:
        await send_json({"type": "error", "text": f"OpenClaw backend error: {e}"})
    finally:
        if oc_ws:
            try:
                await oc_ws.close()
            except Exception:
                pass

# --- Main WebSocket endpoint ---

@router.websocket("/api/clawmate/agent/terminal")
async def agent_terminal(
    ws: WebSocket,
    root: str = Query(""),
    agentId: str = Query(""),
    dir: str = Query(""),
    cols: int = Query(0),
    rows: int = Query(0),
):
    """
    WebSocket endpoint for xterm.js Agent panel.

    Sessions persist across WebSocket disconnects:
    - First connect: spawn Claude Code
    - Disconnect/reconnect: reattach to same process
    - Idle 10min with no client: auto-kill

    Session key = {root}:{project} when .clawmate/ marker found,
    else just {root}. agentId is kept for OpenClaw backend only.
    """
    await ws.accept()
    _ensure_reaper()
    _cleanup_dead_sessions()

    cfg = load_cfg()
    agent_cfg = getattr(cfg, "agent", None)
    backend = getattr(agent_cfg, "backend", "claude") if agent_cfg else "claude"

    cwd = _resolve_session_cwd(root, dir)
    key = _session_key(root, dir, backend)

    # Send session key to frontend so it can display it
    await ws.send_text(json.dumps({
        "type": "session",
        "key": key,
    }, ensure_ascii=False))

    # Check for existing session
    sess = _sessions.get(key)

    if sess and not sess.stop_event.is_set():
        # Existing session — reattach
        await ws.send_text(
            f"\x1b[1;32m⟳ 重新连接到已有会话\x1b[0m\r\n"
            f"\x1b[2m   backend: {backend}  cwd: {cwd}\x1b[0m\r\n"
            f"\x1b[2m   session: {key}\x1b[0m\r\n"
            f"\x1b[2m   会话已运行 {(time.time() - sess.created_at):.0f}s\x1b[0m\r\n\r\n"
        )
        await _attach_session(sess, ws, root)
        return

    # No existing session — send banner
    if backend == "openclaw":
        await ws.send_text(json.dumps({
            "type": "info",
            "text": f"ClawMate Agent Terminal\nbackend: {backend}\ncwd: {cwd}",
            "backend": backend,
            "cwd": cwd,
        }, ensure_ascii=False))
    else:
        await ws.send_text(
            f"\x1b[1;36m╔══════════════════════════════════════╗\x1b[0m\r\n"
            f"\x1b[1;36m║     ClawMate Agent Terminal         ║\x1b[0m\r\n"
            f"\x1b[1;36m║     backend: {backend.ljust(24)}║\x1b[0m\r\n"
            f"\x1b[1;36m║     cwd:    {cwd[:24].ljust(24)}║\x1b[0m\r\n"
            f"\x1b[1;36m╚══════════════════════════════════════╝\x1b[0m\r\n\r\n"
        )

    if backend in ("claude", "codex"):
        # Enforce session limit to prevent process accumulation.
        # Only count active sessions (with attached WebSocket) -- idle sessions
        # without clients don't consume resources and will be reaped shortly.
        max_sessions = cfg.agent.max_sessions
        active_count = sum(1 for s in _sessions.values() if s.ws_set)
        if active_count >= max_sessions:
            logger.warning(
                "session limit reached: %d active sessions (max %d), rejecting new connection for key=%s",
                active_count, max_sessions, key,
            )
            await ws.send_text(
                "\x1b[1;31m✕ 会话数已达上限 (%d)，请关闭其他终端后重试\x1b[0m\r\n" % max_sessions
            )
            await ws.close()
            return
        if backend == "codex":
            sess = await _spawn_codex(cwd, cols=cols, rows=rows, extra_env=cfg.agent.env)
            if sess is None:
                await ws.send_text("\x1b[1;31m✕ Codex CLI not found\x1b[0m\r\n")
                return
        else:
            sess = await _spawn_claude(cwd, cols=cols, rows=rows, extra_env=cfg.agent.env)
            if sess is None:
                await ws.send_text("\x1b[1;31m✕ Claude CLI not found\x1b[0m\r\n")
                return
        sess.key = key
        _sessions[key] = sess
        logger.info(
            "session created key=%s pid=%d cols=%d rows=%d (%d total sessions)",
            key, sess.proc.pid, cols or 0, rows or 0, len(_sessions),
        )
        await _attach_session(sess, ws, root)
    elif backend == "openclaw":
        try:
            await _openclaw_backend(ws, cwd, cfg, root, agentId)
        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                await ws.send_text(f"\r\n\x1b[1;31m✕ OpenClaw backend error: {e}\x1b[0m\r\n")
            except Exception:
                pass
    else:
        await ws.send_text(f"\x1b[1;31m✕ Unknown agent backend: {backend}\x1b[0m\r\n")
