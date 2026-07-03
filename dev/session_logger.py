"""Session output persistence — records structured conversation turns to .chat.jsonl."""

from __future__ import annotations

import asyncio
import json
import time
import typing
from pathlib import Path
from typing import Optional


# ── Known log file extensions (for cleanup) ──

# New format (structured chat logs)
_SESSION_LOG_EXTS = [".meta.json", ".chat.jsonl"]
# Legacy format (raw PTY logs)
_SESSION_LEGACY_EXTS = [".ansi.log", ".text.log"]
# All known log extensions for cleanup
_SESSION_ALL_EXTS = _SESSION_LOG_EXTS + _SESSION_LEGACY_EXTS


# ── SessionLogger ──

class SessionLogger:
    """Per-session logger: appends structured conversation turns to .chat.jsonl.

    User input is recorded immediately at the WebSocket boundary.
    Assistant responses are captured after session end from the CLI's own
    transcript files (~/.claude/projects/*.jsonl or ~/.codex/sessions/*.jsonl).
    """

    def __init__(self, session_id: str, meta: dict, log_dir: str | Path):
        self.session_id = session_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._started_at = meta.get("started_at", time.time())
        self._chat_fd: Optional[typing.IO] = None

        # Write meta.json
        meta_path = self.log_dir / f"{session_id}.meta.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        # Open .chat.jsonl
        self._chat_fd = open(
            self.log_dir / f"{session_id}.chat.jsonl",
            "a", encoding="utf-8",
        )

    def record_user(self, content: str):
        """Record a user input turn (called from WebSocket boundary).

        Written immediately so even incomplete sessions are captured.
        """
        if not self._chat_fd:
            return
        turn = {
            "role": "user",
            "ts": time.time(),
            "content": content,
        }
        self._chat_fd.write(json.dumps(turn, ensure_ascii=False) + "\n")
        self._chat_fd.flush()

    def record_turns(self, turns: list[dict]):
        """Batch-write turns parsed from CLI transcript files (e.g. assistant replies)."""
        if not self._chat_fd:
            return
        for t in turns:
            self._chat_fd.write(json.dumps(t, ensure_ascii=False) + "\n")
        self._chat_fd.flush()

    def flush(self):
        """Force-flush file handle."""
        if self._chat_fd:
            self._chat_fd.flush()

    def close(self, status: str = "ended"):
        """Close .chat.jsonl handle and update meta.json.

        Sync version — index is updated with basic fields (status/ended_at).
        Prefer ``await logger.aclose(status)`` from async code for a full
        metadata sync (file sizes, line count, title).
        """
        self._close_chat()
        meta_path = self.log_dir / f"{self.session_id}.meta.json"
        try:
            with open(meta_path, "r") as f:
                meta = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            meta = {}
        meta["status"] = status
        meta["ended_at"] = time.time()
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        SessionIndex.update(self.log_dir, self.session_id, {
            "status": status,
            "ended_at": time.time(),
            "last_active": time.time(),
        })

    async def aclose(self, status: str = "ended"):
        """Async close — computes file stats and updates index atomically.

        Prefer this over the sync ``close()`` when in an async context
        so the index receives full metadata (title, ansi_size, text_size,
        line_count) under a per-directory lock.
        """
        self._close_chat()

        chat_path = self.log_dir / f"{self.session_id}.chat.jsonl"
        ansi_size = text_size = line_count = 0
        if chat_path.exists():
            ansi_size = chat_path.stat().st_size
            try:
                with open(chat_path, "r") as f:
                    for line in f:
                        line_count += 1
                        try:
                            turn = json.loads(line)
                            text_size += len(turn.get("content", ""))
                        except json.JSONDecodeError:
                            text_size += len(line)
            except OSError:
                pass

        meta_path = self.log_dir / f"{self.session_id}.meta.json"
        try:
            with open(meta_path, "r") as f:
                meta = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            meta = {}
        meta["status"] = status
        meta["ended_at"] = time.time()
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        idx = SessionIndex.for_dir(self.log_dir)
        await idx.update_async(self.session_id, {
            "status": status,
            "ended_at": time.time(),
            "last_active": time.time(),
            "title": meta.get("title", ""),
            "ansi_size": ansi_size,
            "text_size": text_size,
            "line_count": line_count,
        })

    def _close_chat(self):
        """Close the chat file handle (idempotent)."""
        if self._chat_fd:
            self._chat_fd.close()
            self._chat_fd = None

    @property
    def session_dir(self) -> Path:
        """Alias for ``self.log_dir``."""
        return self.log_dir

    def count_turns(self) -> int:
        """Count turns recorded so far (for display in session list)."""
        if not self._chat_fd:
            return 0
        try:
            with open(self.log_dir / f"{self.session_id}.chat.jsonl") as f:
                return sum(1 for _ in f)
        except FileNotFoundError:
            return 0


# ── SessionIndex ──

class SessionIndex:
    """Manage index.json in a session log directory.

    Instance-based with per-directory asyncio.Lock to prevent lost updates.
    Use ``SessionIndex.for_dir(log_dir)`` to get or create the instance for a path.
    """

    _instances: dict[str, "SessionIndex"] = {}

    @classmethod
    def for_dir(cls, log_dir: str | Path) -> "SessionIndex":
        """Get or create a SessionIndex bound to *log_dir* (resolved path)."""
        path = str(Path(log_dir).resolve())
        if path not in cls._instances:
            cls._instances[path] = cls(path)
        return cls._instances[path]

    # ------------------------------------------------------------------
    # Backward-compatible static helpers (used from sync code paths)
    # ------------------------------------------------------------------

    @staticmethod
    def load(log_dir: str | Path) -> list[dict]:
        """Synchronous read — prefer the async instance method when possible."""
        return SessionIndex._sync_load(Path(log_dir))

    @staticmethod
    def save(log_dir: str | Path, sessions: list[dict]):
        """Synchronous write — prefer the async instance method when possible."""
        SessionIndex._sync_save(Path(log_dir), sessions)

    @staticmethod
    def add(log_dir: str | Path, entry: dict):
        """Synchronous add — prefer the async instance method when possible."""
        sessions = SessionIndex._sync_load(Path(log_dir))
        for s in sessions:
            if s.get("id") == entry.get("id"):
                s.update(entry)
                SessionIndex._sync_save(Path(log_dir), sessions)
                return
        sessions.append(entry)
        SessionIndex._sync_save(Path(log_dir), sessions)

    @staticmethod
    def update(log_dir: str | Path, session_id: str, updates: dict):
        """Synchronous update — prefer the async instance method when possible."""
        sessions = SessionIndex._sync_load(Path(log_dir))
        for s in sessions:
            if s.get("id") == session_id:
                s.update(updates)
                break
        SessionIndex._sync_save(Path(log_dir), sessions)

    @staticmethod
    def remove(log_dir: str | Path, session_id: str):
        """Synchronous remove — prefer the async instance method when possible."""
        sessions = SessionIndex._sync_load(Path(log_dir))
        sessions = [s for s in sessions if s.get("id") != session_id]
        SessionIndex._sync_save(Path(log_dir), sessions)

    @staticmethod
    def reap(log_dir: str | Path, ttl_days: int) -> int:
        """Synchronous reap — prefer the async instance method when possible."""
        log_dir = Path(log_dir)
        idx = SessionIndex.for_dir(log_dir)
        sessions = SessionIndex._sync_load(log_dir)
        now = time.time()
        cutoff = now - ttl_days * 86400
        kept = []
        removed = 0
        for s in sessions:
            if s.get("status") == "active":
                kept.append(s)
                continue
            if s.get("last_active", 0) < cutoff:
                sid = s.get("id", "")
                if sid:
                    for ext in _SESSION_ALL_EXTS:
                        p = log_dir / f"{sid}{ext}"
                        if p.exists():
                            p.unlink()
                removed += 1
            else:
                kept.append(s)
        if removed:
            SessionIndex._sync_save(log_dir, kept)
        return removed

    @staticmethod
    def _index_path(log_dir: Path) -> Path:
        return log_dir / "index.json"

    @staticmethod
    def _sync_load(log_dir: Path) -> list[dict]:
        path = log_dir / "index.json"
        try:
            with open(path, "r") as f:
                data = json.load(f)
                return data.get("sessions", [])
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    @staticmethod
    def _sync_save(log_dir: Path, sessions: list[dict]):
        if not log_dir.is_dir():
            return  # log dir cleaned up — skip silently
        path = log_dir / "index.json"
        data = {"version": 1, "sessions": sessions}
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.rename(path)

    # ------------------------------------------------------------------
    # Instance-based async API (preferred)
    # ------------------------------------------------------------------

    def __init__(self, log_dir: str | Path):
        self._log_dir = Path(log_dir)
        self._lock = asyncio.Lock()

    async def load_async(self) -> list[dict]:
        async with self._lock:
            return self._sync_load(self._log_dir)

    async def add_async(self, entry: dict):
        async with self._lock:
            sessions = self._sync_load(self._log_dir)
            for s in sessions:
                if s.get("id") == entry.get("id"):
                    s.update(entry)
                    self._sync_save(self._log_dir, sessions)
                    return
            sessions.append(entry)
            self._sync_save(self._log_dir, sessions)

    async def update_async(self, session_id: str, updates: dict):
        async with self._lock:
            sessions = self._sync_load(self._log_dir)
            for s in sessions:
                if s.get("id") == session_id:
                    s.update(updates)
                    break
            self._sync_save(self._log_dir, sessions)

    async def update_batch(self, updates: dict[str, dict]):
        """Update multiple sessions in a single atomic load+save."""
        async with self._lock:
            sessions = self._sync_load(self._log_dir)
            for sid, fields in updates.items():
                for s in sessions:
                    if s.get("id") == sid:
                        s.update(fields)
                        break
            self._sync_save(self._log_dir, sessions)

    async def remove_async(self, session_id: str):
        async with self._lock:
            sessions = self._sync_load(self._log_dir)
            sessions = [s for s in sessions if s.get("id") != session_id]
            self._sync_save(self._log_dir, sessions)

    async def reap_async(self, ttl_days: int) -> int:
        """Remove sessions whose last_active is older than *ttl_days*.

        Active sessions (status == "active") are never reaped as a
        belt-and-suspenders measure.  Returns count removed.
        """
        async with self._lock:
            sessions = self._sync_load(self._log_dir)
            now = time.time()
            cutoff = now - ttl_days * 86400
            kept = []
            removed = 0
            for s in sessions:
                if s.get("status") == "active":
                    kept.append(s)
                    continue
                if s.get("last_active", 0) < cutoff:
                    sid = s.get("id", "")
                    if sid:
                        for ext in _SESSION_ALL_EXTS:
                            p = self._log_dir / f"{sid}{ext}"
                            if p.exists():
                                p.unlink()
                    removed += 1
                else:
                    kept.append(s)
            if removed:
                self._sync_save(self._log_dir, kept)
            return removed
