"""Session output persistence — records structured conversation turns to .chat.jsonl."""

from __future__ import annotations

import json
import time
import typing
from pathlib import Path
from typing import Optional


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
        """Close .chat.jsonl handle and update meta.json."""
        if self._chat_fd:
            self._chat_fd.close()
            self._chat_fd = None

        # Update meta.json
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

        # Update index
        SessionIndex.update(self.log_dir, self.session_id, {
            "status": status,
            "ended_at": time.time(),
            "last_active": time.time(),
        })

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
    """Manage index.json in a session log directory."""

    @staticmethod
    def _index_path(log_dir: Path) -> Path:
        return log_dir / "index.json"

    @staticmethod
    def load(log_dir: str | Path) -> list[dict]:
        path = SessionIndex._index_path(Path(log_dir))
        try:
            with open(path, "r") as f:
                data = json.load(f)
                return data.get("sessions", [])
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    @staticmethod
    def save(log_dir: str | Path, sessions: list[dict]):
        path = SessionIndex._index_path(Path(log_dir))
        data = {"version": 1, "sessions": sessions}
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.rename(path)

    @staticmethod
    def add(log_dir: str | Path, entry: dict):
        sessions = SessionIndex.load(log_dir)
        # Don't add duplicates
        for s in sessions:
            if s.get("id") == entry.get("id"):
                s.update(entry)
                SessionIndex.save(log_dir, sessions)
                return
        sessions.append(entry)
        SessionIndex.save(log_dir, sessions)

    @staticmethod
    def update(log_dir: str | Path, session_id: str, updates: dict):
        sessions = SessionIndex.load(log_dir)
        for s in sessions:
            if s.get("id") == session_id:
                s.update(updates)
                break
        SessionIndex.save(log_dir, sessions)

    @staticmethod
    def remove(log_dir: str | Path, session_id: str):
        sessions = SessionIndex.load(log_dir)
        sessions = [s for s in sessions if s.get("id") != session_id]
        SessionIndex.save(log_dir, sessions)

    @staticmethod
    def reap(log_dir: str | Path, ttl_days: int) -> int:
        """Remove sessions whose last_active is older than ttl_days. Returns count removed."""
        log_dir = Path(log_dir)
        sessions = SessionIndex.load(log_dir)
        now = time.time()
        cutoff = now - ttl_days * 86400
        kept = []
        removed = 0
        for s in sessions:
            if s.get("last_active", 0) < cutoff:
                sid = s.get("id", "")
                if sid:
                    for ext in [".meta.json", ".chat.jsonl"]:
                        p = log_dir / f"{sid}{ext}"
                        if p.exists():
                            p.unlink()
                removed += 1
            else:
                kept.append(s)
        if removed:
            SessionIndex.save(log_dir, kept)
        return removed
