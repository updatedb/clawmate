"""Session output persistence — writes PTY output to .ansi.log and .text.log."""

from __future__ import annotations

import json
import re
import time
import typing
from pathlib import Path
from typing import Optional


# ── ANSI strip ──

_ANSI_STRIP_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?(\x1b\\|\x07)|\x1b[\\\]_PX^]")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return _ANSI_STRIP_RE.sub("", text)


# ── SessionLogger ──

class SessionLogger:
    """Per-session logger: appends to .ansi.log (raw) and .text.log (plain text with timestamps)."""

    def __init__(self, session_id: str, meta: dict, log_dir: str | Path):
        self.session_id = session_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._started_at = meta.get("started_at", time.time())
        self._ansi_fd: Optional[typing.IO] = None  # noqa: UP045
        self._text_fd: Optional[typing.IO] = None  # noqa: UP045
        self._line_buf = ""

        # Write meta.json
        meta_path = self.log_dir / f"{session_id}.meta.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        # Open file handles
        self._ansi_fd = open(self.log_dir / f"{session_id}.ansi.log", "w", encoding="utf-8", buffering=1)
        self._text_fd = open(self.log_dir / f"{session_id}.text.log", "w", encoding="utf-8", buffering=1)

    def write(self, data: str):
        """Append raw PTY data to .ansi.log; strip ANSI and write lines with timestamps to .text.log."""
        if not data:
            return
        # 1) Write raw ANSI
        if self._ansi_fd:
            self._ansi_fd.write(data)

        # 2) Strip ANSI and accumulate lines for .text.log
        if self._text_fd:
            plain = strip_ansi(data)
            self._line_buf += plain
            while "\n" in self._line_buf:
                idx = self._line_buf.index("\n")
                line = self._line_buf[:idx]
                self._line_buf = self._line_buf[idx + 1:]
                elapsed = int(time.time() - self._started_at)
                mm, ss = divmod(elapsed, 60)
                self._text_fd.write(f"[+{mm:02d}:{ss:02d}] {line}\n")

    def flush(self):
        """Force-flush both file handles."""
        if self._ansi_fd:
            self._ansi_fd.flush()
        if self._text_fd:
            self._text_fd.flush()

    def close(self, status: str = "ended"):
        """Flush, close files, update meta.json."""
        if self._line_buf and self._text_fd:
            elapsed = int(time.time() - self._started_at)
            mm, ss = divmod(elapsed, 60)
            self._text_fd.write(f"[+{mm:02d}:{ss:02d}] {self._line_buf}\n")
            self._line_buf = ""

        if self._ansi_fd:
            self._ansi_fd.close()
            self._ansi_fd = None
        if self._text_fd:
            self._text_fd.close()
            self._text_fd = None

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

    def get_title(self) -> str:
        """Read first non-empty line from .text.log as session title."""
        text_path = self.log_dir / f"{self.session_id}.text.log"
        try:
            with open(text_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    # Strip timestamp prefix
                    content = re.sub(r"^\[\+\d+:\d{2}\]\s*", "", line)
                    if content:
                        return content[:60]
        except FileNotFoundError:
            pass
        return self.session_id


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
                    for ext in [".meta.json", ".ansi.log", ".text.log"]:
                        p = log_dir / f"{sid}{ext}"
                        if p.exists():
                            p.unlink()
                removed += 1
            else:
                kept.append(s)
        if removed:
            SessionIndex.save(log_dir, kept)
        return removed
