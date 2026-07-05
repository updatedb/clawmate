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
import re as _re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketState

from config import load as load_cfg
from service import find_project_marker
from session_logger import SessionLogger, SessionIndex, _SESSION_ALL_EXTS

router = APIRouter()
logger = logging.getLogger("clawmate.agent")

# --- Session manager ---

# Max output buffer per session (keep last ~200KB of terminal output for replay)
_MAX_BUFFER_ENTRIES = 200  # ~200 chunks ≈ ~800KB with typical 4KB reads
# Idle timeout: kill session after N seconds with no WebSocket attached
_IDLE_TIMEOUT_SECONDS = 600  # 10 minutes
# Max session lifetime (even with active connections)
_MAX_SESSION_LIFETIME = 24 * 3600  # 24 hours



# ── Terminal input cleanup ──


def _clean_terminal_input(raw: str) -> str:
    """Strip ANSI escape codes and process backspace from raw terminal input."""
    # OSC: ESC ] ... (ST = ESC \ or BEL)
    s = _re.sub(r'\x1b\][^\x1b\x07]*(?:\x1b\\|\x07)', '', raw)
    # CSI: ESC [ param* intermediate* byte
    s = _re.sub(r'\x1b\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]', '', s)
    # Remaining bare ESC + any char
    s = _re.sub(r'\x1b.', '', s)
    # Strip non-printable control chars (keep tab)
    s = ''.join(c for c in s if c >= ' ' or c in '\t')
    # Process backspace (DEL = \x7f; BS \b is already stripped above)
    buf = []
    for c in s:
        if c == '\x7f':
            if buf:
                buf.pop()
        else:
            buf.append(c)
    return ''.join(buf).strip()

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
    last_injected_file: str = ""   # path of the last file_context injected (avoid dupes on reconnect)
    logger: Optional[SessionLogger] = None  # session log writer (.chat.jsonl)
    cwd: str = ""                            # working directory (for transcript matching)
    log_dir: str = ""                        # .clawmate/sessions/ path (for transcript collection)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()
        if not self.last_active:
            self.last_active = time.time()


# session registry: key → _AgentSession
_sessions: dict[str, _AgentSession] = {}


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


def resolve_session_cwd(root: str, dir_: str = "") -> str:
    """确定 session 的工作目录。有 .clawmate marker → marker 所在目录，无 → root 目录。"""
    root_path = _resolve_root_dir(root)
    if not root_path:
        return os.path.expanduser("~")
    if dir_:
        project = find_project_marker(root_path, dir_)
        if project:
            return str(root_path / project)
    return str(root_path)


def _session_log_dir(key: str, cwd: str | None = None) -> Path | None:
    """Resolve .clawmate/sessions/ path from session key.

    key format: {backend}:{root}[:{project}]
    If cwd is provided, search upward for a project .clawmate/ marker.
    Root-only sessions are stored under the root's own .clawmate/sessions/.
    """
    parts = key.split(":")
    if len(parts) < 2:
        return None
    root_id = parts[1]
    root_path = _resolve_root_dir(root_id)
    if not root_path:
        return None
    if len(parts) >= 3 and parts[2]:
        project = parts[2]
    elif cwd:
        project = find_project_marker(root_path, cwd)
    else:
        project = None
    if not project:
        return root_path / ".clawmate" / "sessions"
    return root_path / project / ".clawmate" / "sessions"


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


async def _cleanup_dead_sessions():
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
            # Collect assistant turns from CLI transcript before closing
            if sess.logger and sess.log_dir:
                _collect_transcript(sess, Path(sess.log_dir))
            if sess.logger:
                await sess.logger.aclose("ended")
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
                # Collect assistant turns from CLI transcript before closing
                if sess.logger and sess.log_dir:
                    _collect_transcript(sess, Path(sess.log_dir))
                if sess.logger:
                    await sess.logger.aclose("killed")
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

        # ── Sync last_active for live sessions before TTL reap ──
        try:
            dir_updates: dict[str, dict[str, dict]] = defaultdict(dict)
            for key, sess in _sessions.items():
                if sess.log_dir and sess.logger:
                    dir_updates[sess.log_dir][sess.logger.session_id] = {
                        "last_active": sess.last_active,
                    }
            for log_dir, updates in dir_updates.items():
                idx = SessionIndex.for_dir(log_dir)
                await idx.update_batch(updates)
        except Exception as exc:
            logger.debug("last_active sync error: %s", exc)

        # ── TTL: 清理过期会话日志 ──
        try:
            cfg = load_cfg()
            ttl = getattr(cfg.agent, "session_log_ttl_days", 30)
            seen_roots = set()
            for key in list(_sessions.keys()):
                parts = key.split(":")
                if len(parts) >= 2:
                    seen_roots.add(parts[1])
            for rid in seen_roots:
                rp = _resolve_root_dir(rid)
                if rp and rp.is_dir():
                    # ── Root-level sessions (no project marker) ──
                    root_sess_dir = rp / ".clawmate" / "sessions"
                    if root_sess_dir.is_dir():
                        try:
                            idx = SessionIndex.for_dir(root_sess_dir)
                            removed = await idx.reap_async(
                                ttl, active_keys=set(_sessions.keys()),
                            )
                            if removed:
                                logger.info(
                                    "TTL reaper: removed %d expired sessions from %s",
                                    removed, root_sess_dir,
                                )
                        except Exception as exc:
                            logger.debug("TTL reap error for %s: %s", root_sess_dir, exc)
                    for proj_dir in rp.iterdir():
                        if not proj_dir.is_dir():
                            continue
                        sess_dir = proj_dir / ".clawmate" / "sessions"
                        if sess_dir.is_dir():
                            try:
                                idx = SessionIndex.for_dir(sess_dir)
                                removed = await idx.reap_async(
                                    ttl, active_keys=set(_sessions.keys()),
                                )
                                if removed:
                                    logger.info(
                                        "TTL reaper: removed %d expired sessions from %s",
                                        removed, sess_dir,
                                    )
                            except Exception as exc:
                                logger.debug("TTL reap error for %s: %s", sess_dir, exc)
        except Exception as exc:
            logger.warning("TTL reaper error: %s", exc)


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


def spawn_background_agent(
    message: str,
    cwd: str,
    backend: str = "claude",
    extra_env: dict[str, str] | None = None,
) -> bool:
    """Spawn a one-shot non-interactive agent process for feedback execution.

    Uses ``claude -p`` / ``codex -p`` (non-interactive mode).  The prompt
    is piped via stdin to avoid ARG_MAX limits.  Runs in a daemon thread;
    fire-and-forget — the process communicates results back via the
    batch-update HTTP API embedded in *message*.

    Returns True if the process started, False if the binary was not found.
    """
    import subprocess
    import threading

    try:
        if backend == "codex":
            binary = _find_codex_binary()
        else:
            binary = _find_claude_binary()
    except RuntimeError:
        logger.warning(
            "[bg-agent] %s binary not found, cannot spawn background process", backend
        )
        return False

    env = os.environ.copy()
    if backend == "claude":
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    if extra_env:
        env.update(extra_env)

    args = [binary, "-p"]
    if backend == "claude":
        args.append("--dangerously-skip-permissions")

    def _run():
        try:
            proc = subprocess.Popen(
                args,
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
            # Pipe prompt via stdin — no ARG_MAX limit
            try:
                proc.stdin.write(message.encode())
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            logger.info(
                "[bg-agent] spawned pid=%d backend=%s cwd=%s msg_len=%d",
                proc.pid, backend, cwd, len(message),
            )
        except Exception as e:
            logger.warning("[bg-agent] spawn failed: %s", e)

    threading.Thread(target=_run, daemon=True).start()
    return True


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
    env["COLUMNS"] = str(wsize.columns)
    env["LINES"] = str(wsize.lines)
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
    # Detect if codex is the same binary as claude (symlink / wrapper)
    try:
        claude_bin = _find_claude_binary()
        if os.path.samefile(binary, claude_bin):
            logger.warning("codex binary (%s) is the same file as claude (%s) — refusing to spawn", binary, claude_bin)
            return None
    except (RuntimeError, OSError):
        pass  # claude not found or paths on different filesystems — proceed
    return await _spawn_pt(cwd, cols, rows, binary, extra_env=extra_env)


async def _attach_session(sess: _AgentSession, ws: WebSocket, root: str = "",
                          cols: int = 0, rows: int = 0):
    """Bridge a WebSocket to an existing PTY session.

    If cols/rows are provided (>0), applies TIOCSWINSZ BEFORE replaying
    buffered output so that history aligns with the new client dimensions.
    """
    sess.ws_set.add(ws)
    sess.last_active = time.time()

    # Apply new dimensions BEFORE replaying buffer and sending output,
    # so everything the new client sees matches its current viewport.
    if cols > 0 and rows > 0:
        try:
            os.set_blocking(sess.master_fd, True)
            fcntl.ioctl(sess.master_fd, termios.TIOCSWINSZ,
                        struct.pack("HHHH", rows, cols, 0, 0))
            os.set_blocking(sess.master_fd, False)
        except Exception:
            pass

    # Replay buffered output so the new client sees history
    for chunk in list(sess.output_buffer):
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                await ws.send_text(chunk)
        except WebSocketDisconnect:
            break

    async def ws_to_pty():
        """Forward WebSocket → PTY (keyboard input)."""
        _input_buf = ""  # accumulate raw characters until newline
        _input_batch = []  # cleaned lines waiting to be flushed as one user turn
        _last_batch_ts = 0.0  # timestamp of the last line added to _input_batch
        try:
            while not sess.stop_event.is_set():
                # ── Flush input batch if idle for >1.5s ──
                if _input_batch and (time.time() - _last_batch_ts) > 1.5:
                    await sess.logger.record_user('\n'.join(_input_batch))
                    _input_batch = []
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
                                # TIOCSWINSZ → SIGWINCH.  All modern TUI programs
                                # (Claude Code, Codex, etc.) use ioctl(TIOCGWINSZ),
                                # not $COLUMNS/$LINES, so no env-var injection needed.
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
                            # Skip if key unchanged — same project, no reconnect needed
                            if new_key == sess.key:
                                continue
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
                        if msg.get("type") == "file_context":
                            # When the user opens the Agent panel while previewing a
                            # file, auto-inject a prompt asking the agent to read and
                            # analyze it, then output 3 actionable suggestions.
                            # Skip if we already injected for this exact file (e.g. on
                            # WebSocket reconnect — don't re-trigger the same prompt).
                            _path = msg.get("path", "")
                            if _path and sess.master_fd is not None and sess.last_injected_file != _path:
                                sess.last_injected_file = _path
                                # ── 从文件名设置 session title ──
                                if sess.logger and not sess.logger._title_set:
                                    _fname = os.path.basename(_path).rsplit('.', 1)[0] if '.' in os.path.basename(_path) else os.path.basename(_path)
                                    if _fname:
                                        await sess.logger._extract_and_set_title(f"分析: {_fname}")
                                # 带 ANSI 青色的提示，回显即显示，同时作为 Claude 的输入
                                _prompt = (
                                    f"\x1b[1;36m分析文件: {_path}\x1b[0m\r\n"
                                    f"\x1b[2m1. 摘要（≤100字）\x1b[0m\r\n"
                                    f"\x1b[2m2. 问题与待办（≤3条）\x1b[0m\r\n"
                                )
                                # 记录到 .chat.jsonl 中，避免 session 因缺失 user turn 被过滤
                                _clean_content = f"分析文件: {_path}\n1. 摘要（≤100字）\n2. 问题与待办（≤3条）"
                                if sess.logger:
                                    await sess.logger.record_user(_clean_content)
                                async def _inject_analysis():
                                    await asyncio.sleep(2.5)
                                    # 写入前校验 session 仍存活，避免向已回收的 FD 写入（FD 可能已被新 session 复用）
                                    if sess.key not in _sessions:
                                        return
                                    try:
                                        os.write(sess.master_fd, _prompt.encode())
                                    except (OSError, BlockingIOError):
                                        pass
                                asyncio.create_task(_inject_analysis())
                            continue
                except (json.JSONDecodeError, TypeError, AttributeError):
                    pass

                # Raw terminal input
                # Accumulate user input and record complete lines for chat log
                _input_buf += data
                if '\n' in _input_buf or '\r' in _input_buf:
                    parts = _input_buf.replace('\r\n', '\n').replace('\r', '\n').split('\n')
                    for part in parts[:-1]:
                        cleaned = _clean_terminal_input(part)
                        if cleaned and sess.logger:
                            now = time.time()
                            # Gap exceeded flush threshold → flush previous batch as one record
                            if _input_batch and (now - _last_batch_ts) > 1.5:
                                await sess.logger.record_user('\n'.join(_input_batch))
                                _input_batch = []
                            _input_batch.append(cleaned)
                            _last_batch_ts = now
                    _input_buf = parts[-1]  # keep incomplete fragment
                try:
                    os.write(sess.master_fd, data.encode())
                except (OSError, BlockingIOError):
                    pass
                sess.last_input_time = time.time()
                sess.last_active = time.time()
        except Exception:
            pass
        finally:
            if _input_batch and sess.logger:
                await sess.logger.record_user('\n'.join(_input_batch))

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

async def _connect_openclaw(oc_url: str, oc_token: str):
    """Connect and authenticate to the OpenClaw Gateway.

    Tries localhost first (Gateway auto-grants scopes to local clients),
    then the configured URL.  Each URL is tried for BOTH connection AND
    authentication; if auth fails we try the next URL instead of giving up.

    Returns (oc_ws, hello, req_id) on success, or (None, error_text, 0) on failure.
    """
    try_urls = []
    local_url = "ws://127.0.0.1:18789"
    if oc_url != local_url:
        try_urls.append(local_url)
    try_urls.append(oc_url)

    oc_ws = None
    req_id = 0
    last_auth_error = None

    for url in try_urls:
        if oc_ws is not None:
            try:
                await oc_ws.close()
            except Exception:
                pass
            oc_ws = None

        # Connect
        try:
            oc_ws = await asyncio.wait_for(
                websockets.connect(url, ping_interval=30, ping_timeout=60),
                timeout=5,
            )
        except Exception:
            continue

        # Handshake
        try:
            raw = await asyncio.wait_for(oc_ws.recv(), timeout=5)
            challenge = json.loads(raw)
            if challenge.get("event") != "connect.challenge":
                last_auth_error = "Unexpected OpenClaw handshake"
                continue
        except Exception as e:
            last_auth_error = f"Handshake failed: {e}"
            continue

        # Authenticate
        req_id += 1
        await oc_ws.send(json.dumps({
            "type": "req", "id": str(req_id), "method": "connect",
            "params": {
                "minProtocol": 4, "maxProtocol": 4,
                "client": {"id": "gateway-client", "version": "1.0.0", "platform": "linux", "mode": "backend"},
                "role": "operator",
                "scopes": ["operator.read", "operator.write", "operator.admin"],
                "auth": {"token": oc_token},
                "locale": "en-US",
                "userAgent": "clawmate-agent/1.0.0",
            },
        }))

        try:
            hello_raw = await asyncio.wait_for(oc_ws.recv(), timeout=5)
            hello = json.loads(hello_raw)
        except Exception as e:
            last_auth_error = f"Auth response failed: {e}"
            continue

        if hello.get("ok"):
            return (oc_ws, hello, req_id)

        err = hello.get("error", {}).get("message", "unknown")
        last_auth_error = err

    # All URLs failed
    error_text = (
        f"✕ OpenClaw 鉴权失败: {last_auth_error}\r\n"
        f"  已尝试 {', '.join(try_urls)}，均未通过鉴权。\r\n"
        f"  请确认 openclaw_token 有效，且 Gateway 已授予 operator.write 权限。"
    ) if oc_ws is not None else (
        f"✕ Cannot connect to OpenClaw gateway\r\n"
        f"  Tried: {', '.join(try_urls)}"
    )
    if oc_ws is not None:
        try:
            await oc_ws.close()
        except Exception:
            pass
    return (None, error_text, 0)


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

    oc_ws, hello_or_error, req_id = await _connect_openclaw(oc_url, oc_token)
    if oc_ws is None:
        await ws.send_text(json.dumps({
            "type": "error",
            "text": hello_or_error,
        }, ensure_ascii=False))
        return

    hello = hello_or_error

    line_buf = ""
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

        # Save device token if returned (pairing approved)
        new_device_token = hello.get("payload", {}).get("auth", {}).get("deviceToken", "")
        if new_device_token and new_device_token != agent_cfg.openclaw_device_token:
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
        history_req_id = await oc_send("chat.history", {
            "sessionKey": f"agent:{agent_id or 'default'}:main",
            "limit": 20,
        })
        # Drain gateway messages until we find the matching res for chat.history.
        # Other events (health, tick, etc.) are skipped.  Max ~10s total wait.
        await ws.send_text(json.dumps({"type": "info", "text": "Loading history..."}, ensure_ascii=False))
        try:
            for _ in range(40):
                raw = await asyncio.wait_for(oc_ws.recv(), timeout=0.5)
                evt = json.loads(raw)
                if evt.get("type") == "res" and evt.get("id") == str(history_req_id):
                    messages = evt.get("payload", {}).get("messages", [])
                    if messages:
                        for msg in messages[-10:]:
                            role = msg.get("role", "")
                            # content is [{type: "text", text: "..."}, ...]
                            content_blocks = msg.get("content", [])
                            if isinstance(content_blocks, list):
                                text = " ".join(
                                    c.get("text", "") for c in content_blocks
                                    if isinstance(c, dict) and c.get("type") == "text"
                                )
                            else:
                                text = str(content_blocks)
                            text = text.strip()
                            if not text:
                                continue
                            # Map roles to frontend message types
                            if role == "assistant":
                                msg_type = "assistant"
                            elif role == "toolResult":
                                # Show tool results as a compact system note
                                tool_name = msg.get("toolName", "")
                                label = f"[{tool_name}]" if tool_name else "[tool]"
                                text = f"{label} {text[:500]}"
                                msg_type = "assistant"
                            else:
                                msg_type = "user"
                            await ws.send_text(json.dumps({
                                "type": msg_type,
                                "text": text[:2000],
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
            backend: str = Query(""),
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
    await _cleanup_dead_sessions()

    cfg = load_cfg()
    agent_cfg = getattr(cfg, "agent", None)
    config_backend = getattr(agent_cfg, "backend", "claude") if agent_cfg else "claude"
    # Client-side backend override (from badge click passing ?backend=...)
    if backend and backend in ("claude", "codex", "openclaw"):
        pass  # use client-provided backend
    else:
        backend = config_backend

    cwd = resolve_session_cwd(root, dir)
    key = _session_key(root, dir, backend)

    # Send session key to frontend so it can display it
    await ws.send_text(json.dumps({
        "type": "session",
        "key": key,
    }, ensure_ascii=False))

    # Check for existing session
    sess = _sessions.get(key)

    if sess and not sess.stop_event.is_set() and sess.proc.returncode is None:
        # Existing session — apply new dimensions BEFORE sending any output.
        # Without this, the reconnected banner and buffered history would be
        # formatted for the OLD PTY dimensions, causing misalignment with the
        # agent panel's current viewport.
        if cols > 0 and rows > 0:
            try:
                os.set_blocking(sess.master_fd, True)
                fcntl.ioctl(sess.master_fd, termios.TIOCSWINSZ,
                            struct.pack("HHHH", rows, cols, 0, 0))
                os.set_blocking(sess.master_fd, False)
            except Exception:
                pass

        await ws.send_text(
            f"\x1b[1;32m⟳ 重新连接到已有会话\x1b[0m\r\n"
            f"\x1b[2m   backend: {backend}  cwd: {cwd}\x1b[0m\r\n"
            f"\x1b[2m   session: {key}\x1b[0m\r\n"
            f"\x1b[2m   会话已运行 {(time.time() - sess.created_at):.0f}s\x1b[0m\r\n"
            f"\x1b[2m   term: {cols}×{rows}\x1b[0m\r\n\r\n"
        )
        await _attach_session(sess, ws, root, cols, rows)
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
        sess.cwd = cwd
        _sessions[key] = sess

        # Initialize session logger (.chat.jsonl)
        try:
            sess_dir = _session_log_dir(key, cwd)
            if sess_dir:
                sess.log_dir = str(sess_dir)
                ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
                safe_key = key.replace(":", "_").replace("/", "_")
                session_id = f"{safe_key}_{ts}"
                sess.logger = SessionLogger(
                    session_id=session_id,
                    meta={
                        "session_id": session_id,
                        "key": key,
                        "backend": backend,
                        "cwd": cwd,
                        "root": root,
                        "started_at": time.time(),
                        "status": "active",
                        "title": backend,
                    },
                    log_dir=sess_dir,
                )
                await SessionIndex.for_dir(sess_dir).add_async({
                    "id": session_id,
                    "key": key,
                    "backend": backend,
                    "root": root,
                    "started_at": time.time(),
                    "last_active": time.time(),
                    "title": backend,
                    "status": "active",
                })
        except Exception as exc:
            logger.warning("failed to init session logger for key=%s: %s", key, exc)

        logger.info(
            "session created key=%s pid=%d cols=%d rows=%d (%d total sessions)",
            key, sess.proc.pid, cols or 0, rows or 0, len(_sessions),
        )
        await _attach_session(sess, ws, root, cols, rows)
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


# ── Transcript collection (from CLI's own on-disk .jsonl transcripts) ──


def _sanitized_fragment(path: str) -> str:
    """Convert a filesystem path to the sanitized form used by Claude Code's project dirs.
    e.g. /home/user/projects/my-app → home-user-projects-my-app
    """
    return path.lstrip("/").replace("/", "-")


def _find_claude_transcript(cwd: str, started_at: float) -> Path | None:
    """Locate Claude Code's transcript file by matching a timestamp line.

    Claude Code writes transcripts to:
      ~/.claude/projects/<sanitized-cwd>/<uuid>.jsonl

    The first few lines are metadata (no timestamp).  Scans forward in each
    candidate until it finds a JSON line with a parseable ``timestamp``,
    then returns the candidate whose timestamp is closest to ``started_at``.
    Falls back to mtime if no line with a timestamp can be found.
    """
    import datetime as _dt
    sanitized = _sanitized_fragment(cwd)
    transcript_dir = Path.home() / ".claude" / "projects" / f"-{sanitized}"
    if not transcript_dir.is_dir():
        return None
    candidates = sorted(transcript_dir.glob("*.jsonl"), key=os.path.getmtime, reverse=True)

    best_path: Path | None = None
    best_distance = float('inf')

    for c in candidates:
        try:
            with open(c) as f:
                found_ts = None
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = obj.get("timestamp", 0)
                    if ts and isinstance(ts, str):
                        ts = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                    if ts:
                        found_ts = float(ts)
                        break
        except Exception:
            continue

        if found_ts:
            distance = abs(found_ts - started_at)
            if distance < best_distance:
                best_distance = distance
                best_path = c
        else:
            # Fallback to mtime for candidates without any parseable timestamp
            mtime = os.path.getmtime(c)
            distance = abs(mtime - started_at)
            if distance < best_distance:
                best_distance = distance
                best_path = c

    return best_path if best_path else (candidates[0] if candidates else None)


def _find_codex_transcript(cwd: str, started_at: float) -> Path | None:
    """Locate Codex CLI's session transcript file by timestamp proximity.

    Codex writes transcripts to:
      ~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl

    The first line is ``session_meta`` with ``cwd`` and ``timestamp``.
    Candidates are filtered by cwd, then the one with timestamp closest
    to ``started_at`` is returned.
    """
    import datetime as _dt
    dt = _dt.datetime.fromtimestamp(started_at)
    session_dir = Path.home() / ".codex" / "sessions" / f"{dt.year:04d}" / f"{dt.month:02d}" / f"{dt.day:02d}"
    if not session_dir.is_dir():
        return None
    candidates = sorted(session_dir.glob("rollout-*.jsonl"), key=os.path.getmtime, reverse=True)

    best_path: Path | None = None
    best_distance = float('inf')

    for c in candidates:
        try:
            with open(c) as f:
                first = json.loads(f.readline())
            if first.get("type") != "session_meta":
                continue
            meta = first.get("payload", {})
            if meta.get("cwd") != cwd:
                continue
            # Match by session_meta timestamp
            ts = first.get("timestamp") if first.get("timestamp") is not None else meta.get("timestamp", 0)
            if isinstance(ts, str):
                ts = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
            distance = abs(float(ts) - started_at) if ts else abs(os.path.getmtime(c) - started_at)
            if distance < best_distance:
                best_distance = distance
                best_path = c
        except Exception:
            continue

    return best_path if best_path else (candidates[0] if candidates else None)


def _parse_claude_transcript(path: Path, started_at: float = 0) -> list[dict]:
    """Parse Claude Code transcript and extract assistant text replies,
    skipping tool- call blocks and thinking blocks.

    Claude Code transcript format:
      {"type":"user", "message":{"role":"user", "content":[...]}}
      {"type":"assistant", "message":{"role":"assistant", "content":[{"type":"text","text":"..."}, ...]}}
    """
    turns = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "assistant":
                    continue
                msg = obj.get("message", "")
                if isinstance(msg, str):
                    try:
                        msg = json.loads(msg)
                    except json.JSONDecodeError:
                        continue
                if not isinstance(msg, dict):
                    continue
                content_blocks = msg.get("content", [])
                texts = []
                for block in content_blocks:
                    if isinstance(block, dict) and block.get("type") == "text":
                        texts.append(block.get("text", ""))
                if texts:
                    ts = obj.get("timestamp", time.time())
                    if isinstance(ts, str):
                        try:
                            import datetime
                            ts = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                        except Exception:
                            ts = time.time()
                    elif not isinstance(ts, (int, float)):
                        ts = time.time()  # guard: null / list / dict → current time
                    turns.append({
                        "role": "assistant",
                        "ts": ts,
                        "content": "\n".join(texts),
                    })
    except FileNotFoundError:
        pass
    # Filter out turns that predate this session (cross-session contamination guard)
    if started_at:
        cutoff = started_at - 60  # 60s grace period
        turns = [t for t in turns if t.get("ts", 0) >= cutoff]
    return turns


def _parse_codex_transcript(path: Path, started_at: float = 0) -> list[dict]:
    """Parse Codex CLI transcript and extract assistant messages only.

    User messages are already recorded at the WebSocket boundary via
    ``SessionLogger.record_user()``, so we only collect assistant turns
    here to avoid duplication.

    Codex transcript format:
      {"type":"response_item","payload":{"role":"user","content":[{"type":"input_text","text":"..."}]}}
      {"type":"response_item","payload":{"role":"assistant","content":[{"type":"text","text":"..."}]}}
    """
    turns = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "response_item":
                    continue
                pl = obj.get("payload", {})
                if pl.get("role") != "assistant":
                    continue
                content_blocks = pl.get("content", []) or []
                texts = []
                for block in content_blocks:
                    if isinstance(block, dict):
                        txt = block.get("text", "")
                        if txt:
                            texts.append(txt)
                if texts:
                    ts_str = obj.get("timestamp", "")
                    ts = time.time()
                    if ts_str:
                        try:
                            import datetime
                            ts = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
                        except Exception:
                            pass
                    turns.append({
                        "role": "assistant",
                        "ts": ts,
                        "content": "\n".join(texts),
                    })
    except FileNotFoundError:
        pass
    # Filter out turns that predate this session (cross-session contamination guard)
    if started_at:
        cutoff = started_at - 60  # 60s grace period
        turns = [t for t in turns if t.get("ts", 0) >= cutoff]
    return turns


def _parse_transcript(cwd: str, backend: str, started_at: float) -> list[dict]:
    """Find and parse CLI transcript for a session.

    Returns a list of assistant-turn dicts (``{"role": "assistant", "ts": ..., "content": ...}``),
    or an empty list if the transcript cannot be found/parsed.
    """
    turns: list[dict] = []
    if backend == "claude":
        transcript_path = _find_claude_transcript(cwd, started_at)
        if transcript_path:
            turns = _parse_claude_transcript(transcript_path, started_at=started_at)
    elif backend == "codex":
        transcript_path = _find_codex_transcript(cwd, started_at)
        if transcript_path:
            turns = _parse_codex_transcript(transcript_path, started_at=started_at)
    return turns


def _collect_transcript(sess, log_dir: Path):
    """After a session ends, try to collect assistant turns from CLI transcript files.

    Called from session cleanup code. Best-effort — silently does nothing
    if transcript files cannot be found or parsed.
    """
    if not sess.logger:
        return
    cwd = getattr(sess, "cwd", None) or ""
    backend = (sess.key or "").split(":")[0] or "claude"
    started_at = getattr(sess, "created_at", 0)

    turns = _parse_transcript(cwd, backend, started_at)
    if turns:
        sess.logger.record_turns(turns)
        logger.info(
            "collected %d assistant turns from transcript (backend=%s cwd=%s)",
            len(turns), backend, cwd,
        )


# ── Session History APIs ──

def _roots_for_session_query(cfg, root: str):
    """Return config roots constrained by the optional root id."""
    if root:
        return [r for r in cfg.roots if r.id == root]
    return cfg.roots


def _projects_for_session_query(root_dir: Path, project: str = "", dir_: str = "") -> list[tuple[str, Path]]:
    """Resolve session project directories for history APIs.

    `dir_` is the current file-browser directory. When it sits inside a
    `.clawmate` project, use that project instead of listing every project
    under the root. With no project constraint, include the root's own
    `.clawmate/sessions` directory before project directories.
    """
    projects_to_check: list[tuple[str, Path]] = []

    project_name = project
    if not project_name and dir_:
        project_name = find_project_marker(root_dir, dir_) or ""

    if project_name:
        p = root_dir / project_name
        if p.is_dir():
            projects_to_check.append((project_name, p))
        return projects_to_check

    if (root_dir / ".clawmate" / "sessions").is_dir():
        projects_to_check.append(("", root_dir))

    for p in root_dir.iterdir():
        if p.is_dir() and (p / ".clawmate" / "sessions").is_dir():
            projects_to_check.append((p.name, p))
    return projects_to_check


def _load_chat_turns(chat_path: Path) -> list[dict]:
    """Load valid JSONL chat turns from a session log."""
    if not chat_path.is_file():
        return []
    turns: list[dict] = []
    try:
        with chat_path.open(encoding="utf-8") as cf:
            for chat_line in cf:
                if not chat_line.strip():
                    continue
                try:
                    turn = json.loads(chat_line)
                except json.JSONDecodeError:
                    continue
                if isinstance(turn, dict):
                    turns.append(turn)
    except OSError:
        return []
    return turns


def _chat_turn_ts(turn: dict) -> float:
    try:
        return float(turn.get("ts") or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalize_chat_turns(turns: list[dict]) -> list[dict]:
    """Return the same turn sequence used by the session detail view.

    Counting rules:
    - turns with blank content are ignored;
    - turns are sorted by timestamp, because assistant transcript collection can
      append older assistant messages after user input has already been logged;
    - consecutive user turns within 1 second are merged, matching terminal
      multi-line paste handling in the history detail UI.
    """
    display_turns: list[dict] = []
    non_empty_turns = [
        dict(t) for t in turns
        if str(t.get("content") or "").strip()
    ]
    non_empty_turns.sort(key=_chat_turn_ts)
    for turn in non_empty_turns:
        prev = display_turns[-1] if display_turns else None
        prev_ts = _chat_turn_ts(prev) if prev else 0.0
        turn_ts = _chat_turn_ts(turn)
        if (
            prev
            and prev.get("role") == "user"
            and turn.get("role") == "user"
            and prev_ts
            and turn_ts
            and abs(turn_ts - prev_ts) <= 1.0
        ):
            prev["content"] = f"{prev.get('content', '')}\n{turn.get('content', '')}"
        else:
            display_turns.append(turn)
    turn_index = 0
    for turn in display_turns:
        if turn.get("role") == "user":
            turn_index += 1
        if turn_index:
            turn["turn_index"] = turn_index
    return display_turns


def _chat_log_stats(chat_path: Path) -> dict:
    """Analyse a chat JSONL log and return stats dict.

    Returns:
        instruction_count: number of user instructions (条指令)
        turn_count: number of user turns (轮对话; same as instruction_count)
        total_turns: total entries across all roles
        first_ts: timestamp of the earliest entry (epoch seconds)
        last_ts:  timestamp of the latest entry (epoch seconds)
    """
    turns = _normalize_chat_turns(_load_chat_turns(chat_path))
    user_count = sum(1 for t in turns if t.get("role") == "user")
    timestamps = [t.get("ts") for t in turns if t.get("ts")]
    first_ts = min(timestamps) if timestamps else None
    last_ts = max(timestamps) if timestamps else None
    return {
        "instruction_count": user_count,
        "turn_count": user_count,
        "total_turns": len(turns),
        "first_ts": first_ts,
        "last_ts": last_ts,
    }


@router.get("/api/clawmate/agent/sessions")
async def agent_session_list(
    root: str = "",
    project: str = "",
    dir: str = "",
    backend: str = "",
    status: str = "",
    q: str = "",
    limit: int = 50,
    offset: int = 0,
):
    """List archived agent sessions, grouped by project."""
    await _cleanup_dead_sessions()
    results: list[dict] = []
    seen: set[str] = set()

    cfg = load_cfg()
    roots_to_check = _roots_for_session_query(cfg, root)

    for r in roots_to_check:
        root_dir = Path(r.dir)
        if not root_dir.is_dir():
            continue
        dirs_to_check = _projects_for_session_query(root_dir, project, dir)

        for proj_name, proj_dir in dirs_to_check:
            sess_dir = proj_dir / ".clawmate" / "sessions"
            if not sess_dir.is_dir():
                continue
            sessions = await SessionIndex.for_dir(sess_dir).load_async()
            # 预先收集当前活跃会话的 ID（不能用 key 判断，因为多个会话共享同一 key）
            active_ids: set[str] = set()
            if not status:
                for asess in _sessions.values():
                    if asess.logger:
                        active_ids.add(asess.logger.session_id)
            for s in sessions:
                # 过滤当前正在活跃运行的会话（id 在 active_ids 中），
                # 而非依赖 status 字段（历史会话可能一直遗留为 "active"）
                if not status and s.get("id", "") in active_ids:
                    continue
                if status and s.get("status", "") != status:
                    continue
                if backend and s.get("backend", "") != backend:
                    continue
                if q:
                    sid = s.get("id", "")
                    chat_path = sess_dir / f"{sid}.chat.jsonl"
                    if chat_path.is_file():
                        try:
                            with open(chat_path) as cf:
                                matched = False
                                for chat_line in cf:
                                    if q.lower() in chat_line.lower():
                                        matched = True
                                        break
                                if not matched:
                                    continue
                        except Exception:
                            continue
                    else:
                        continue
                sid = s.get("id", "")
                chat_path = sess_dir / f"{sid}.chat.jsonl"
                try:
                    stats = _chat_log_stats(chat_path)
                except (ValueError, OSError, TypeError) as _ex:
                    logger.debug("skipping corrupt session %s: %s", sid, _ex)
                    continue
                if stats["total_turns"] == 0:
                    continue
                if sid in seen:
                    continue
                seen.add(sid)

                results.append({
                    **s,
                    "root": r.id,
                    "project": proj_name,
                    "log_dir": str(sess_dir),
                    **stats,
                })

    results.sort(key=lambda x: x.get("started_at", 0), reverse=True)
    total = len(results)
    paged = results[offset:offset + limit]
    return JSONResponse({"total": total, "sessions": paged})


@router.get("/api/clawmate/agent/sessions/{session_id}/log")
async def agent_session_log(
    session_id: str,
    root: str = "",
    project: str = "",
    dir: str = "",
):
    """Read session chat log (.chat.jsonl). Returns structured conversation turns.

    If the log contains user turns but no assistant turns, this endpoint
    attempts an on-demand transcript collection from the CLI's own transcript
    files (``~/.claude/projects/`` for claude, ``~/.codex/sessions/`` for
    codex).  Collected turns are appended back to ``.chat.jsonl`` so
    subsequent views are fast.
    """
    # Pre-clean any in-memory dead sessions so their transcripts are flushed
    await _cleanup_dead_sessions()

    cfg = load_cfg()
    for r in _roots_for_session_query(cfg, root):
        root_dir = Path(r.dir)
        if not root_dir.is_dir():
            continue
        projects_to_check = _projects_for_session_query(root_dir, project, dir)

        for proj_name, proj_path in projects_to_check:
            sess_dir = proj_path / ".clawmate" / "sessions"
            chat_path = sess_dir / f"{session_id}.chat.jsonl"
            if not chat_path.is_file():
                continue

            meta = {}
            meta_path = sess_dir / f"{session_id}.meta.json"
            if meta_path.is_file():
                try:
                    meta = json.loads(meta_path.read_text("utf-8"))
                except Exception:
                    pass

            turns = _load_chat_turns(chat_path)

            # ── On-demand transcript collection ──────────────────────────
            # If .chat.jsonl has user turns but zero assistant turns, try to
            # pull assistant responses from the CLI's own transcript files.
            has_assistant = any(t.get("role") == "assistant" for t in turns)
            if turns and not has_assistant:
                cwd = meta.get("cwd", "")
                backend = meta.get("backend", "")
                raw_started = meta.get("started_at", 0)
                if cwd and backend and raw_started:
                    try:
                        started_at = float(raw_started)
                    except (TypeError, ValueError):
                        started_at = 0
                    if started_at:
                        collected = _parse_transcript(cwd, backend, started_at)
                        if collected:
                            # Append to .chat.jsonl so next view skips this step
                            try:
                                with open(chat_path, "a", encoding="utf-8") as f:
                                    for t in collected:
                                        f.write(json.dumps(t, ensure_ascii=False) + "\n")
                            except OSError:
                                pass
                            turns.extend(collected)
                            logger.info(
                                "on-demand collected %d assistant turns for session=%s backend=%s",
                                len(collected), session_id, backend,
                            )

            turns = _normalize_chat_turns(turns)
            instruction_count = sum(1 for t in turns if t.get("role") == "user")

            return JSONResponse({
                "session_id": session_id,
                "meta": meta,
                "turns": turns,
                "total_turns": len(turns),
                "instruction_count": instruction_count,
            })

    raise HTTPException(status_code=404, detail="Session not found")


@router.get("/api/clawmate/agent/sessions/{session_id}")
async def agent_session_detail(session_id: str, root: str = "", project: str = "", dir: str = ""):
    """Return session metadata + chat.jsonl turn count."""
    cfg = load_cfg()
    for r in _roots_for_session_query(cfg, root):
        root_dir = Path(r.dir)
        if not root_dir.is_dir():
            continue
        projects_to_check = _projects_for_session_query(root_dir, project, dir)

        for proj_name, proj_path in projects_to_check:
            sess_dir = proj_path / ".clawmate" / "sessions"
            meta_path = sess_dir / f"{session_id}.meta.json"
            chat_path = sess_dir / f"{session_id}.chat.jsonl"

            if not meta_path.is_file() and not chat_path.is_file():
                continue

            meta = {}
            if meta_path.is_file():
                try:
                    meta = json.loads(meta_path.read_text("utf-8"))
                except Exception:
                    pass

            stats = _chat_log_stats(chat_path)

            return JSONResponse({
                "session_id": session_id,
                "meta": meta,
                "root": r.id,
                "project": proj_name,
                **stats,
            })

    raise HTTPException(status_code=404, detail="Session not found")


@router.delete("/api/clawmate/agent/sessions/{session_id}")
async def agent_session_delete(session_id: str, root: str = "", project: str = "", dir: str = ""):
    """Delete a session log."""
    # Validate session_id format to prevent path traversal
    if not _re.match(r"^[A-Za-z0-9_.-]+$", session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id format")

    # Reject deletion of active sessions
    for sess in _sessions.values():
        if sess.logger and sess.logger.session_id == session_id:
            raise HTTPException(
                status_code=409,
                detail=f"Session {session_id} is currently active; kill it before deleting logs",
            )

    cfg = load_cfg()
    for r in _roots_for_session_query(cfg, root):
        root_dir = Path(r.dir)
        if not root_dir.is_dir():
            continue
        projects_to_check = _projects_for_session_query(root_dir, project, dir)

        for proj_name, proj_path in projects_to_check:
            sess_dir = proj_path / ".clawmate" / "sessions"
            meta_path = sess_dir / f"{session_id}.meta.json"
            if not meta_path.is_file():
                continue

            deleted_files = []
            for ext in _SESSION_ALL_EXTS:
                p = sess_dir / f"{session_id}{ext}"
                if p.exists():
                    p.unlink()
                    deleted_files.append(ext)
            await SessionIndex.for_dir(sess_dir).remove_async(session_id)
            return JSONResponse({
                "ok": True,
                "session_id": session_id,
                "deleted_files": deleted_files,
            })

    raise HTTPException(status_code=404, detail="Session not found")
