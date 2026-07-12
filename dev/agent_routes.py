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
import re as _re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketState

from config import load as load_cfg
from service import find_project_marker
from session_logger import SessionLogger, SessionIndex, _SESSION_LOG_EXTS
from session_history_service import SessionHistoryService
from terminal_manager import PosixPtyAdapter, SessionRequest, TerminalManager
from terminal_protocol import (
    PROTOCOL_VERSION,
    ProtocolError,
    decode_binary_frame,
    encode_binary_frame,
    parse_control,
    validate_dimensions,
)

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

# Pre-compiled ANSI escape patterns shared by all cleaners
_RE_OSC = _re.compile(r'\x1b\][^\x1b\x07]*(?:\x1b\\|\x07)')
_RE_CSI = _re.compile(r'\x1b\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]')
_RE_BARE_ESC = _re.compile(r'\x1b.')


def _strip_ansi_escapes(raw: str) -> str:
    """Remove OSC, CSI, and bare-ESC sequences from raw terminal input."""
    s = _RE_OSC.sub('', raw)
    s = _RE_CSI.sub('', s)
    s = _RE_BARE_ESC.sub('', s)
    return s


def _clean_terminal_input(raw: str) -> str:
    """Strip ANSI escape codes and process backspace from raw terminal input."""
    s = _strip_ansi_escapes(raw)
    # Strip non-printable control chars (keep tab)
    s = ''.join(c for c in s if c >= ' ' or c in '\t')
    # Process backspace (DEL = \x7f; BS \b is already stripped above)
    return _apply_backspace(s).strip()


def _apply_backspace(s: str) -> str:
    """Apply backspace (DEL = \\x7f) by dropping the preceding character."""
    buf = []
    for c in s:
        if c == '\x7f':
            if buf:
                buf.pop()
        else:
            buf.append(c)
    return ''.join(buf)


def _clean_input_for_history(raw: str) -> str:
    """Clean terminal input for session history display.

    Like _clean_terminal_input but preserves \\n so multi-line paste
    and inline line breaks appear naturally in the history log.
    """
    s = _strip_ansi_escapes(raw)
    # Normalise \r\n → \n; drop standalone \r
    s = s.replace('\r\n', '\n').replace('\r', '')
    # Keep printable, tab, and newline
    s = ''.join(c for c in s if c >= ' ' or c in '\t' or c == '\n')
    # Process backspace (DEL = \x7f)
    return _apply_backspace(s).strip()


def _append_v2_history_input(buffer: str, raw: str) -> tuple[str, bool]:
    """Apply a raw xterm input frame to a pending history line.

    The returned boolean is true only when the frame contains an actual
    terminal submission (the final CR/LF).  Editing controls update the
    pending line but never create a history turn by themselves.
    """
    text = _strip_ansi_escapes(raw).replace('\r\n', '\n')
    submitted = False
    for index, char in enumerate(text):
        is_final_char = index == len(text) - 1
        if char in '\r\n':
            if is_final_char:
                submitted = True
            else:
                buffer += '\n'
        elif char in ('\x7f', '\b'):
            buffer = buffer[:-1]
        elif char in ('\x03', '\x15'):
            buffer = ''
        elif char >= ' ' or char == '\t':
            buffer += char
    return buffer, submitted


def _extract_openclaw_text(value) -> str:
    """Extract assistant text from the gateway's delta/final payload variants."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ''.join(_extract_openclaw_text(item) for item in value)
    if not isinstance(value, dict):
        return ''
    for key in ('deltaText', 'text'):
        if isinstance(value.get(key), str):
            return value[key]
    if 'content' in value:
        return _extract_openclaw_text(value['content'])
    if 'message' in value:
        return _extract_openclaw_text(value['message'])
    return ''


def _openclaw_session_key(agent_id: str, root: str, dir_: str, session_id: str = "") -> str:
    """Give each ClawMate backend/root/project scope its own gateway session."""
    scope = _session_key(root, dir_, "openclaw").replace(":", "-").replace("/", "-")
    suffix = f":{session_id}" if session_id else ""
    return f"agent:{agent_id or 'default'}:clawmate:{scope}{suffix}"

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
    known_files: set[str] = field(default_factory=set)  # file refs already introduced in this session
    logger: Optional[SessionLogger] = None  # session log writer (.chat.jsonl)
    cwd: str = ""                            # working directory (for transcript matching)
    log_dir: str = ""                        # .clawmate/sessions/ path (for transcript collection)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()
        if not self.last_active:
            self.last_active = time.time()


_terminal_v2_manager: TerminalManager | None = None
_v2_loggers: dict[str, SessionLogger] = {}  # session.id → SessionLogger
_v2_input_buffers: dict[str, str] = {}     # session.id → accumulated display text
_v2_session_contexts: dict[str, tuple[str, str, float]] = {}


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


def _history_session_key(session: dict, root: str, project: str) -> str:
    """Return the persisted session key for history rows, deriving older entries if needed."""
    stored = str(session.get("key") or "").strip()
    if stored:
        return stored
    backend = str(session.get("backend") or "").strip() or "claude"
    base = root
    if project:
        base = f"{root}:{project}"
    return f"{backend}:{base}"


def _active_history_session_ids() -> set[str]:
    """Return archived-log IDs that still belong to live backend sessions."""
    return {
        logger_obj.session_id
        for logger_obj in _v2_loggers.values()
        if getattr(logger_obj, "session_id", "")
    }


def _build_file_context_prompt(path: str) -> tuple[str, str]:
    """Build the PTY prompt and log text for a preview file reference."""
    path = (path or "").strip()
    if not path:
        return "", ""

    if not path.startswith("@"):
        path = f"@{path}"

    prompt = path + "\n"
    clean = path
    return prompt, clean


def _normalize_known_file_path(path: str) -> str:
    value = str(path or "").strip()
    if not value:
        return ""
    if value.startswith("@"):
        value = value[1:].strip()
    return value


def _extract_known_file_path(text: str) -> str:
    line = _clean_terminal_input(str(text or "")).strip()
    if not line.startswith("@"):
        return ""
    return _normalize_known_file_path(line)


def _write_hidden_pty(sess, text: str):
    """Write to PTY with local echo temporarily disabled."""
    if not text or sess.master_fd is None:
        return
    try:
        attrs = termios.tcgetattr(sess.master_fd)
    except Exception:
        attrs = None
    try:
        if attrs is not None:
            noecho = list(attrs)
            noecho[3] &= ~termios.ECHO
            termios.tcsetattr(sess.master_fd, termios.TCSANOW, noecho)
        os.write(sess.master_fd, text.encode())
    except (OSError, BlockingIOError):
        pass
    finally:
        if attrs is not None:
            try:
                termios.tcsetattr(sess.master_fd, termios.TCSANOW, attrs)
            except Exception:
                pass


async def _expire_v2_sessions() -> int:
    """Run the v2 manager's idle/lifetime expiry sweep, if initialized."""
    manager = _terminal_v2_manager
    if manager is None:
        return 0
    return await manager.expire_idle()


async def _idle_reaper():
    """Periodically kill idle v2 sessions and expire old session logs.

    v2 sessions are managed by TerminalManager.expire_idle().  TTL checks
    scan all configured root directories for old session logs.

    On first run after restart, also recovers orphaned sessions (no ended_at)
    by scanning all roots and collecting assistant transcripts from CLI files.
    """
    # One-shot recovery for sessions orphaned by restart
    await _recover_orphaned_sessions()

    while True:
        await asyncio.sleep(60)  # check every minute
        try:
            await _expire_v2_sessions()
        except Exception as exc:
            logger.warning("v2 terminal expiry failed: %s", exc)

        # ── TTL: 清理过期会话日志 ──
        try:
            cfg = load_cfg()
            ttl = getattr(cfg.agent, "session_log_ttl_days", 30)
            for root_cfg in cfg.roots:
                rp = _resolve_root_dir(root_cfg.id)
                if rp and rp.is_dir():
                    root_sess_dir = rp / ".clawmate" / "sessions"
                    if root_sess_dir.is_dir():
                        try:
                            idx = SessionIndex.for_dir(root_sess_dir)
                            removed = await idx.reap_async(ttl)
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
                                removed = await idx.reap_async(ttl)
                                if removed:
                                    logger.info(
                                        "TTL reaper: removed %d expired sessions from %s",
                                        removed, sess_dir,
                                    )
                            except Exception as exc:
                                logger.debug("TTL reap error for %s: %s", sess_dir, exc)
        except Exception as exc:
            logger.warning("TTL reaper error: %s", exc)


# ── Restart recovery: collect transcripts for orphaned sessions ──

_recovered = False


async def _recover_orphaned_sessions():
    """One-shot recovery after restart: close orphaned sessions (no ended_at).

    Scans all known root directories for sessions in index.json that
    lack an ``ended_at`` timestamp (orphaned by restart).  For each:

    1. Attempts transcript collection from CLI files (best-effort).
    2. Computes ``ended_at`` from the latest turn timestamp in
       ``.chat.jsonl`` (assistant → user → current time).
    3. Updates the index with ``ended_at`` and file stats.

    The ``_recovered`` flag ensures this runs at most once per process
    lifetime, even if called from multiple entry points.
    """
    global _recovered
    if _recovered:
        return
    _recovered = True

    logger.info("recovery: scanning for orphaned sessions (no ended_at)...")

    try:
        cfg = load_cfg()
    except Exception:
        logger.warning("recovery: cannot load config, skipping")
        return

    recovered_count = 0

    for root_cfg in cfg.roots:
        root_dir = Path(root_cfg.dir)
        if not root_dir.is_dir():
            continue

        # Collect session directories (root-level + project-level)
        dirs_to_check: list[Path] = []
        root_sess = root_dir / ".clawmate" / "sessions"
        if root_sess.is_dir():
            dirs_to_check.append(root_sess)
        for proj in root_dir.iterdir():
            if proj.is_dir():
                proj_sess = proj / ".clawmate" / "sessions"
                if proj_sess.is_dir():
                    dirs_to_check.append(proj_sess)

        for sess_dir in dirs_to_check:
            idx = SessionIndex.for_dir(sess_dir)
            sessions = await idx.load_async()
            for entry in sessions:
                if entry.get("ended_at"):
                    continue  # already has end time, skip

                session_id = entry.get("id", "")
                if not session_id:
                    continue

                chat_path = sess_dir / f"{session_id}.chat.jsonl"

                # ── Estimate ended_at from existing turns ──────────────
                # Before collecting transcript, check .chat.jsonl for any
                # existing turns so we can use the latest timestamp as an
                # upper bound.  Sessions with no existing turns have no
                # known end time → pass 0 (no bound, but grace-limited).
                existing_last_ts: float | None = None
                if chat_path.exists():
                    try:
                        with open(chat_path, encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    turn = json.loads(line)
                                except json.JSONDecodeError:
                                    continue
                                ts = turn.get("ts")
                                if isinstance(ts, (int, float)):
                                    if existing_last_ts is None or ts > existing_last_ts:
                                        existing_last_ts = ts
                    except OSError:
                        pass

                # ── Transcript collection (best-effort) ────────────────
                cwd = _session_cwd_from_log_dir(sess_dir, session_id)
                backend = entry.get("backend", "")
                raw_started = entry.get("started_at", 0)
                try:
                    started_at = float(raw_started)
                except (TypeError, ValueError):
                    started_at = 0

                if cwd and backend and started_at:
                    collected = _parse_transcript(cwd, backend, started_at,
                                                  ended_at=existing_last_ts or 0)
                    if collected:
                        try:
                            with open(chat_path, "a", encoding="utf-8") as f:
                                for t in collected:
                                    f.write(json.dumps(t, ensure_ascii=False) + "\n")
                        except OSError:
                            pass
                        logger.info(
                            "recovery: collected %d assistant turns for session=%s (%s)",
                            len(collected), session_id, Path(cwd).name if cwd else sess_dir.parent.parent.name,
                        )

                # ── Compute ended_at from actual turn timestamps ───────
                # Priority: last assistant turn → last user turn → now.
                # Re-read after appending collected turns.
                last_ts: float | None = None
                if chat_path.exists():
                    try:
                        with open(chat_path, encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    turn = json.loads(line)
                                except json.JSONDecodeError:
                                    continue
                                ts = turn.get("ts")
                                if isinstance(ts, (int, float)):
                                    if last_ts is None or ts > last_ts:
                                        last_ts = ts
                    except OSError:
                        pass

                ended_at = last_ts if last_ts is not None else time.time()

                # ── Compute file stats (mirrors aclose logic) ──────────
                ansi_size = text_size = line_count = 0
                if chat_path.exists():
                    ansi_size = chat_path.stat().st_size
                    try:
                        with open(chat_path, encoding="utf-8") as f:
                            for line in f:
                                line_count += 1
                                try:
                                    turn = json.loads(line)
                                    text_size += len(turn.get("content", ""))
                                except json.JSONDecodeError:
                                    text_size += len(line)
                    except OSError:
                        pass

                await idx.update_async(session_id, {
                    "ended_at": ended_at,
                    "last_active": ended_at,
                    "ansi_size": ansi_size,
                    "text_size": text_size,
                    "line_count": line_count,
                })
                recovered_count += 1

    if recovered_count:
        logger.info("recovery: closed %d orphaned sessions", recovered_count)


# ── Schedule recovery on startup ─────────────────────────────────────
# We cannot schedule an async task at import time because the event loop
# is not yet running (uvicorn starts it *after* module imports complete).
# Instead, use a daemon thread to poll for the running loop and schedule
# the recovery as a background asyncio task once it becomes available.
# This ensures recovery runs automatically after every restart, even
# without any WebSocket connection or history API request.

import threading as _threading


def _schedule_initial_recovery():
    """Poll for the running event loop and schedule recovery once."""
    import asyncio
    import time

    for _ in range(100):  # up to ~10 seconds
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(_recover_orphaned_sessions())
                return
        except RuntimeError:
            pass
        time.sleep(0.1)


_recovery_thread = _threading.Thread(
    target=_schedule_initial_recovery,
    daemon=True,
    name="recovery-bootstrap",
)
_recovery_thread.start()


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

    Uses ``claude -p <message>`` / ``codex -p <message>`` (non-interactive).
    Runs in a daemon thread; fire-and-forget — the process communicates
    results back via the batch-update HTTP API embedded in *message*.

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

    if backend == "claude":
        # --dangerously-skip-permissions 必须在 -p 之前，否则会被 -p 当作 prompt 参数吞掉
        args = [binary, "--dangerously-skip-permissions", "-p", message]
    else:
        args = [binary, "-p", message]

    def _run():
        try:
            proc = subprocess.Popen(
                args,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
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


# --- Main WebSocket endpoint ---


async def _v2_pty_factory(request: SessionRequest) -> PosixPtyAdapter:
    cfg = load_cfg()
    if request.backend == "codex":
        legacy_session = await _spawn_codex(request.cwd, extra_env=cfg.agent.env)
    elif request.backend == "claude":
        legacy_session = await _spawn_claude(request.cwd, extra_env=cfg.agent.env)
    else:
        raise RuntimeError("terminal v2 supports only PTY backends")
    if legacy_session is None:
        raise RuntimeError(f"{request.backend} CLI not found")
    return PosixPtyAdapter(legacy_session.master_fd, legacy_session.proc)


def _get_terminal_v2_manager() -> TerminalManager:
    global _terminal_v2_manager
    if _terminal_v2_manager is None:
        cfg = load_cfg().agent
        _terminal_v2_manager = TerminalManager(
            _v2_pty_factory,
            replay_bytes=cfg.replay_bytes,
            connection_queue_bytes=cfg.connection_queue_bytes,
            input_queue_bytes=cfg.input_queue_bytes,
            resize_lease_seconds=cfg.resize_lease_seconds,
            idle_seconds=cfg.terminal_idle_seconds,
            max_lifetime_seconds=cfg.terminal_max_lifetime_seconds,
            max_sessions=cfg.max_sessions,
            on_session_removed=_on_v2_session_removed,
        )
    return _terminal_v2_manager


async def _flush_input_buffer_lines(logger, buf: str):
    """Flush buffered input as one user instruction.

    Pasted content (with internal ``\\n``) is preserved as a single turn.
    Empty or whitespace-only buffers are silently skipped.
    """
    if not logger or not buf:
        return
    line = buf.strip()
    if line:
        try:
            await logger.record_user(line)
        except Exception:
            pass


async def _on_v2_session_removed(session_id: str, reason: str) -> None:
    """Close and clean up SessionLogger when a v2 terminal session is removed."""
    # Unsubmitted terminal text is intentionally discarded: only an Enter
    # submission represents a user instruction in history.
    _v2_input_buffers.pop(session_id, None)
    key, cwd, started_at = _v2_session_contexts.pop(session_id, ("", "", 0.0))
    logger = _v2_loggers.pop(session_id, None)
    if logger:
        try:
            log_dir = Path(getattr(logger, "log_dir", ""))
            _collect_transcript(
                SimpleNamespace(
                    logger=logger,
                    key=key,
                    cwd=cwd,
                    created_at=started_at,
                ),
                log_dir,
            )
            await logger.aclose()
        except Exception as exc:
            logger_module = logging.getLogger("clawmate.agent")
            logger_module.warning("v2 session logger aclose failed for %s: %s", session_id, exc)


async def _send_terminal_v2_frames(
    ws: WebSocket,
    session,
    connection,
    *,
    replay_latest: int = 0,
    last_output_ack: int = 0,
    replay_chunk_count: int = 0,
) -> None:
    replay_pending = replay_latest > last_output_ack
    try:
        if replay_pending and replay_chunk_count == 0:
            await ws.send_text(json.dumps({
                "v": PROTOCOL_VERSION,
                "type": "replay_complete",
                "sequence": replay_latest,
            }))
            replay_pending = False
        while not connection.closed:
            chunk = await session.next_output(connection.id)
            await ws.send_bytes(encode_binary_frame(chunk.start, chunk.data))
            if replay_pending and chunk.end >= replay_latest:
                await ws.send_text(json.dumps({
                    "v": PROTOCOL_VERSION,
                    "type": "replay_complete",
                    "sequence": replay_latest,
                }))
                replay_pending = False
    except ConnectionError:
        pass
    finally:
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.close(code=1000, reason=session.close_reason or "terminated")


@router.get("/api/clawmate/agent/diagnostics")
async def agent_terminal_diagnostics():
    """Return authenticated operational terminal metadata without user content."""
    manager = _terminal_v2_manager
    if manager is None:
        return JSONResponse({
            "session_count": 0,
            "connection_count": 0,
            "reader_task_count": 0,
            "writer_task_count": 0,
            "idle_session_count": 0,
        })
    return JSONResponse(manager.diagnostics())


@router.websocket("/api/clawmate/agent/terminal/v2")
async def agent_terminal_v2(ws: WebSocket):
    """Protocol-v2 PTY endpoint with separate control and binary data frames."""
    await ws.accept()
    _ensure_reaper()
    # xterm 6 is now the only browser terminal implementation.  Keep the
    # config field for deployment compatibility, but never fall back to the
    # removed legacy browser protocol.
    manager = _get_terminal_v2_manager()
    connection = None
    session = None
    sender_task = None
    try:
        first = await ws.receive()
        if not first.get("text"):
            raise ProtocolError("expected_hello", "The first terminal v2 frame must be hello", True)
        hello = parse_control(first["text"])
        if hello.get("type") != "hello":
            raise ProtocolError("expected_hello", "The first terminal v2 frame must be hello", True)
        cols, rows = validate_dimensions(hello.get("cols"), hello.get("rows"))
        client_id = str(hello.get("client_id") or "").strip()
        backend = str(hello.get("backend") or "claude")
        if not client_id or backend not in {"claude", "codex"}:
            raise ProtocolError("invalid_hello", "Hello must include a client ID and PTY backend", True)
        _hello_root = str(hello.get("root") or "")
        _hello_dir = str(hello.get("dir") or "")
        _root_path = _resolve_root_dir(_hello_root)
        _project = find_project_marker(_root_path, _hello_dir) if _root_path and _hello_dir else ""
        request = SessionRequest(
            backend=backend,
            root=_hello_root,
            project=_project,
            cwd=resolve_session_cwd(_hello_root, _hello_dir),
        )
        session = await manager.get_or_create(request)
        # ── Initialize v2 session logger (.chat.jsonl) ─────────────
        if session.id not in _v2_loggers:
            try:
                key = _session_key(str(hello.get("root") or ""), str(hello.get("dir") or ""), backend)
                sess_dir = _session_log_dir(key, request.cwd)
                if sess_dir:
                    ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
                    safe_key = key.replace(":", "_").replace("/", "_")
                    log_session_id = f"{safe_key}_{ts}"
                    meta = {
                        "session_id": log_session_id,
                        "key": key,
                        "backend": backend,
                        "cwd": request.cwd,
                        "root": str(hello.get("root") or ""),
                        "started_at": time.time(),
                        "title": backend,
                    }
                    v2_logger = SessionLogger(
                        session_id=log_session_id,
                        meta=meta,
                        log_dir=sess_dir,
                    )
                    await SessionIndex.for_dir(sess_dir).add_async({
                        "id": log_session_id,
                        "key": key,
                        "backend": backend,
                        "cwd": request.cwd,
                        "root": str(hello.get("root") or ""),
                        "started_at": time.time(),
                        "last_active": time.time(),
                        "title": backend,
                    })
                    _v2_loggers[session.id] = v2_logger
                    _v2_session_contexts[session.id] = (key, request.cwd, meta["started_at"])
            except Exception as exc:
                logger.warning("failed to init v2 session logger for session=%s: %s", session.id, exc)
        # ─────────────────────────────────────────────────────────────
        last_output_ack = int(hello.get("last_output_ack") or 0)
        connection = await manager.subscribe(session.id, client_id, last_output_ack)
        await session.resize(client_id, cols, rows)
        await ws.send_text(json.dumps({
            "v": PROTOCOL_VERSION,
            "type": "ready",
            "id": hello.get("id", ""),
            "session_id": session.id,
            "connection_count": len(session.connections),
            "replay": {
                "earliest_sequence": connection.replay_earliest,
                "latest_sequence": connection.replay_latest,
            },
        }))
        sender_task = asyncio.create_task(_send_terminal_v2_frames(
            ws,
            session,
            connection,
            replay_latest=connection.replay_latest,
            last_output_ack=last_output_ack,
            replay_chunk_count=connection.replay_chunk_count,
        ))
        while True:
            message = await ws.receive()
            if message.get("bytes") is not None:
                sequence, payload = decode_binary_frame(message["bytes"])
                await session.enqueue_input(connection.id, sequence, payload)
                # Record only actual terminal submissions.  xterm sends
                # ordinary typing one key at a time, so idle/disconnect must
                # never turn an unfinished command into history.
                v2_logger = _v2_loggers.get(session.id)
                if v2_logger:
                    try:
                        buf = _v2_input_buffers.get(session.id, "")
                        buf, submitted = _append_v2_history_input(
                            buf,
                            payload.decode("utf-8", errors="replace"),
                        )
                        if submitted:
                            await _flush_input_buffer_lines(v2_logger, buf)
                            _v2_input_buffers.pop(session.id, None)
                        elif buf:
                            _v2_input_buffers[session.id] = buf
                    except Exception:
                        pass
                await session.wait_input_ack(connection.id, sequence)
                await ws.send_text(json.dumps({"v": PROTOCOL_VERSION, "type": "input_ack", "sequence": sequence}))
                continue
            if message.get("text") is None:
                raise WebSocketDisconnect()
            control = parse_control(message["text"])
            kind = control["type"]
            if kind == "focus":
                await session.focus(connection.id)
            elif kind == "resize":
                accepted = await session.resize(connection.id, control.get("cols"), control.get("rows"))
                await ws.send_text(json.dumps({"v": PROTOCOL_VERSION, "type": "resize_ack", "accepted": accepted}))
            elif kind == "output_ack":
                session.acknowledge_output(connection.id, int(control.get("sequence") or 0))
            elif kind == "lock_input":
                await session.set_input_lock(connection.id if control.get("locked") else None)
            elif kind == "terminate":
                reason = str(control.get("reason") or "manual")
                await manager.terminate(session.id, reason)
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.close(code=1000, reason=reason)
                return
            elif kind == "heartbeat":
                await ws.send_text(json.dumps({"v": PROTOCOL_VERSION, "type": "heartbeat_ack"}))
    except ProtocolError as exc:
        await ws.send_text(json.dumps(exc.as_message()))
    except WebSocketDisconnect:
        pass
    except RuntimeError as exc:
        error = ProtocolError("terminal_unavailable", str(exc), True)
        await ws.send_text(json.dumps(error.as_message()))
        try:
            await ws.close(code=1011, reason="terminal_unavailable")
        except Exception:
            pass
    finally:
        if sender_task:
            sender_task.cancel()
            await asyncio.gather(sender_task, return_exceptions=True)
        if session:
            _v2_input_buffers.pop(session.id, None)
        if connection and session:
            try:
                await manager.unsubscribe(session.id, connection.id)
            except KeyError:
                # A CLI exit or explicit terminate removes the session before
                # this websocket's cleanup runs.
                pass

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
    Candidates are constrained to the current session cwd/project, then the
    one with timestamp closest to ``started_at`` is returned.
    """
    import datetime as _dt
    dt = _dt.datetime.fromtimestamp(started_at)
    session_dir = Path.home() / ".codex" / "sessions" / f"{dt.year:04d}" / f"{dt.month:02d}" / f"{dt.day:02d}"
    if not session_dir.is_dir():
        return None
    candidates = sorted(session_dir.glob("rollout-*.jsonl"), key=os.path.getmtime, reverse=True)

    best_path: Path | None = None
    best_distance = float('inf')
    try:
        expected_cwd = Path(cwd).expanduser().resolve()
    except OSError:
        expected_cwd = Path(cwd).expanduser().absolute()

    for c in candidates:
        try:
            with open(c) as f:
                first = json.loads(f.readline())
            if first.get("type") != "session_meta":
                continue
            meta = first.get("payload", {})
            transcript_cwd = meta.get("cwd")
            if not transcript_cwd:
                continue
            try:
                transcript_path = Path(str(transcript_cwd)).expanduser().resolve()
            except OSError:
                transcript_path = Path(str(transcript_cwd)).expanduser().absolute()
            if transcript_path != expected_cwd and expected_cwd not in transcript_path.parents:
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

    return best_path


def _parse_claude_transcript(path: Path, started_at: float = 0, ended_at: float = 0) -> list[dict]:
    """Parse Claude Code transcript and extract assistant text replies,
    skipping tool- call blocks and thinking blocks.

    Claude Code transcript format:
      {"type":"user", "message":{"role":"user", "content":[...]}}
      {"type":"assistant", "message":{"role":"assistant", "content":[{"type":"text","text":"..."}, ...]}}

    Only turns whose timestamp falls within the session's time window
    ``[started_at - 60s, ended_at + 60s]`` are returned.  This prevents
    assistant replies from one session leaking into another session's log.
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
    # Filter turns to this session's time window (cross-session contamination guard)
    if started_at or ended_at:
        lower = (started_at - 60) if started_at else 0
        upper = (ended_at + 60) if ended_at else float('inf')
        turns = [t for t in turns if lower <= t.get("ts", 0) <= upper]
    return turns


def _parse_codex_transcript(path: Path, started_at: float = 0, ended_at: float = 0) -> list[dict]:
    """Parse Codex CLI transcript and extract assistant messages only.

    User messages are already recorded at the WebSocket boundary via
    ``SessionLogger.record_user()``, so we only collect assistant turns
    here to avoid duplication.

    Codex transcript format:
      {"type":"response_item","payload":{"role":"user","content":[{"type":"input_text","text":"..."}]}}
      {"type":"response_item","payload":{"role":"assistant","content":[{"type":"text","text":"..."}]}}

    Only turns whose timestamp falls within the session's time window
    ``[started_at - 60s, ended_at + 60s]`` are returned.
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
    # Filter turns to this session's time window (cross-session contamination guard)
    if started_at or ended_at:
        lower = (started_at - 60) if started_at else 0
        upper = (ended_at + 60) if ended_at else float('inf')
        turns = [t for t in turns if lower <= t.get("ts", 0) <= upper]
    return turns


def _parse_transcript(cwd: str, backend: str, started_at: float, ended_at: float = 0) -> list[dict]:
    """Find and parse CLI transcript for a session.

    Only returns assistant turns whose timestamp falls within the session's
    time window ``[started_at - 60s, ended_at + 60s]``.

    Returns a list of assistant-turn dicts (``{"role": "assistant", "ts": ..., "content": ...}``),
    or an empty list if the transcript cannot be found/parsed.
    """
    turns: list[dict] = []
    if backend == "claude":
        transcript_path = _find_claude_transcript(cwd, started_at)
        if transcript_path:
            turns = _parse_claude_transcript(transcript_path, started_at=started_at, ended_at=ended_at)
    elif backend == "codex":
        transcript_path = _find_codex_transcript(cwd, started_at)
        if transcript_path:
            turns = _parse_codex_transcript(transcript_path, started_at=started_at, ended_at=ended_at)
    return turns


def _collect_transcript(sess, log_dir: Path):
    """After a session ends, try to collect assistant turns from CLI transcript files.

    Called from session cleanup code. Best-effort — silently does nothing
    if transcript files cannot be found or parsed.

    ``ended_at`` is set to the current time (the moment the session is being
    cleaned up), providing an upper bound to avoid collecting assistant turns
    from future sessions that share the same PTY process.
    """
    if not sess.logger:
        return
    session_id = getattr(sess.logger, "session_id", "") or ""
    cwd = getattr(sess, "cwd", None) or _session_cwd_from_log_dir(log_dir, session_id)
    if cwd and not getattr(sess, "cwd", None):
        sess.cwd = cwd
    backend = (sess.key or "").split(":")[0] or "claude"
    started_at = getattr(sess, "created_at", 0)
    ended_at = time.time()

    turns = _parse_transcript(cwd, backend, started_at, ended_at)
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


def _session_cwd_from_log_dir(log_dir: str | Path, session_id: str = "") -> str:
    """Recover a session cwd from its log directory, preferring index.json metadata."""
    sess_dir = Path(log_dir)
    if session_id:
        try:
            for entry in SessionIndex.load(sess_dir):
                if entry.get("id") != session_id:
                    continue
                stored_cwd = str(entry.get("cwd") or "").strip()
                if stored_cwd:
                    return stored_cwd
                break
        except Exception:
            pass

    try:
        return str(sess_dir.resolve().parent.parent)
    except OSError:
        return str(sess_dir.absolute().parent.parent)


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
        turn_count: number of user turns (轮对话)
        instruction_count: total entries across all roles (条指令)
        total_turns: total entries across all roles
        first_ts: timestamp of the earliest entry (epoch seconds)
        last_ts:  timestamp of the latest entry (epoch seconds)
    """
    turns = _normalize_chat_turns(_load_chat_turns(chat_path))
    user_count = sum(1 for t in turns if t.get("role") == "user")
    total = len(turns)
    timestamps = [t.get("ts") for t in turns if t.get("ts")]
    first_ts = min(timestamps) if timestamps else None
    last_ts = max(timestamps) if timestamps else None
    return {
        "turn_count": user_count,
        "instruction_count": total,
        "total_turns": total,
        "first_ts": first_ts,
        "last_ts": last_ts,
    }


@router.get("/api/clawmate/agent/sessions")
async def agent_session_list(
    root: str = "",
    project: str = "",
    dir: str = "",
    backend: str = "",
    q: str = "",
    date: str = "",
    limit: int = 15,
    offset: int = 0,
    cursor: str = "",
):
    """List archived agent sessions, grouped by project."""
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
            active_ids = _active_history_session_ids()
            for s in sessions:
                # 过滤当前正在活跃运行的会话（id 在 active_ids 中）
                if s.get("id", "") in active_ids:
                    continue
                if backend and s.get("backend", "") != backend:
                    continue

                # ── date filter ────────────────────────────────────────
                if date:
                    session_end = s.get("ended_at") or s.get("started_at")
                    if session_end:
                        try:
                            dt = datetime.fromtimestamp(float(session_end))
                            if dt.strftime("%Y-%m-%d") != date:
                                continue
                        except (TypeError, ValueError):
                            continue
                    else:
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
                    "sessionKey": _history_session_key(s, r.id, proj_name),
                    "log_dir": str(sess_dir),
                    **stats,
                })

    results.sort(key=lambda x: x.get("ended_at") or x.get("started_at", 0), reverse=True)
    if cursor:
        page = SessionHistoryService(results).list(
            limit=limit,
            cursor=cursor,
            backend=backend,
            keyword=q,
        )
        return JSONResponse(page)
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

            turns = _load_chat_turns(chat_path)
            session_cwd = _session_cwd_from_log_dir(sess_dir, session_id)
            meta = {"cwd": session_cwd} if session_cwd else {}

            # ── On-demand transcript collection ──────────────────────────
            # If .chat.jsonl has user turns but zero assistant turns, try to
            # pull assistant responses from the CLI's own transcript files.
            # Note: this is a secondary path — the primary recovery runs on
            # startup via _recover_orphaned_sessions().  This endpoint handles
            # sessions that were still live when recovery ran (no transcript
            # available yet) or that were created after recovery.
            has_assistant = any(t.get("role") == "assistant" for t in turns)
            if turns and not has_assistant:
                # Derive cwd from stored session cwd (prefer over proj_path for
                # sessions started from nested subdirectories)
                cwd = session_cwd if session_cwd else str(proj_path) if proj_path and proj_path.is_dir() else ""
                backend = ""
                raw_started = 0
                try:
                    idx = SessionIndex.for_dir(sess_dir)
                    for entry in await idx.load_async():
                        if entry.get("id") == session_id:
                            backend = entry.get("backend", "")
                            raw_started = entry.get("started_at", 0)
                            break
                except Exception:
                    pass

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


@router.get("/api/clawmate/agent/sessions/dates")
async def agent_session_dates(
    root: str = "",
    dir: str = "",
):
    """Return available session dates sorted newest-first.

    Collects dates from the ``ended_at`` field of all archived sessions
    (falling back to ``started_at`` for older logs)
    (excluding currently active ones).  The return value is a flat list of
    ``"YYYY-MM-DD"`` strings that the client populates its date-axis with.
    """
    date_set: set[str] = set()

    cfg = load_cfg()
    roots_to_check = _roots_for_session_query(cfg, root)
    active_ids = _active_history_session_ids()

    for r in roots_to_check:
        root_dir = Path(r.dir)
        if not root_dir.is_dir():
            continue
        dirs_to_check = _projects_for_session_query(root_dir, "", dir)

        for proj_name, proj_dir in dirs_to_check:
            sess_dir = proj_dir / ".clawmate" / "sessions"
            if not sess_dir.is_dir():
                continue
            sessions = await SessionIndex.for_dir(sess_dir).load_async()

            for s in sessions:
                if s.get("id", "") in active_ids:
                    continue
                session_end = s.get("ended_at") or s.get("started_at")
                if session_end:
                    try:
                        dt = datetime.fromtimestamp(float(session_end))
                        date_set.add(dt.strftime("%Y-%m-%d"))
                    except (TypeError, ValueError):
                        continue

    dates = sorted(date_set, reverse=True)
    return JSONResponse({"dates": dates})


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
            chat_path = sess_dir / f"{session_id}.chat.jsonl"

            if not chat_path.is_file():
                continue

            meta = {"cwd": _session_cwd_from_log_dir(sess_dir, session_id)}

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

    # Reject deletion of active legacy and v2 sessions.
    if session_id in _active_history_session_ids():
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
            chat_path = sess_dir / f"{session_id}.chat.jsonl"
            if not chat_path.is_file() and not (sess_dir / "index.json").is_file():
                continue

            deleted_files = []
            for ext in _SESSION_LOG_EXTS:
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
