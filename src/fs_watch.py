"""Directory filesystem watch service (SSE-backed).

Backs ``GET /api/clawmate/fs/events``. Watches the *direct* children of a
directory — non-recursive, matching ``list_dir``'s view — via
``watchdog.Observer``. Subscriptions are reference-counted per
``(root, dir)``: the observer only runs while at least one client is
connected, and is stopped when the last client disconnects. Rapid events are
debounced so a burst collapses into a single change notification per path.

Events carry a ``kind`` of ``added`` / ``modified`` / ``deleted``; the
frontend uses those to tag session-scoped changes (added/modified only) and
to decide whether a row needs to disappear (deleted).

watchdog is an optional dependency: if it is not installed ``_WATCHDOG_AVAILABLE``
is ``False``, the service still resolves but never emits events, so the SSE
endpoint can return a clean 503 instead of crashing the process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from pathlib import Path
from typing import Dict, Optional, Set

logger = logging.getLogger("clawmate.fs_watch")

try:  # pragma: no cover - watchdog optional
    from watchdog.observers import Observer
    from watchdog.events import (
        DirCreatedEvent,
        DirDeletedEvent,
        DirModifiedEvent,
        DirMovedEvent,
        FileCreatedEvent,
        FileDeletedEvent,
        FileModifiedEvent,
        FileMovedEvent,
        FileSystemEventHandler,
    )
    _WATCHDOG_AVAILABLE = True
except Exception:  # pragma: no cover - watchdog optional
    _WATCHDOG_AVAILABLE = False
    Observer = None  # type: ignore[assignment]
    FileSystemEventHandler = object  # type: ignore[assignment]


# Debounce window: events that arrive within this window are coalesced into a
# single notification per path, so editor "save" bursts / touch tests stay calm.
DEBOUNCE_SECONDS = 0.4

# When one debounce window observes this many *distinct* changed paths, we treat
# it as a burst that may have overflowed the kernel inotify queue. watchdog
# silently drops IN_Q_OVERFLOW (wd == -1) events, so instead of trusting the
# incremental list we emit a single "refresh" event that makes the client do one
# full re-list of the directory. This is event-driven — no periodic polling.
_RESCAN_BURST_THRESHOLD = 50

# Higher priority wins when a path is seen with several kinds in one window.
# new file (added) is the most useful signal; a delete that is superseded by a
# re-create should still surface as "added".
_KIND_PRIORITY = {"added": 3, "modified": 2, "deleted": 1}

# Kind labels the frontend understands.
_ADDED = "added"
_MODIFIED = "modified"
_DELETED = "deleted"


def _normalize_kind(event) -> Optional[str]:
    """Map a watchdog event to one of added / modified / deleted."""
    if isinstance(event, (FileCreatedEvent, DirCreatedEvent)):
        return _ADDED
    if isinstance(event, (FileModifiedEvent, DirModifiedEvent)):
        return _MODIFIED
    if isinstance(event, (FileDeletedEvent, DirDeletedEvent)):
        return _DELETED
    return None


class _Handler(FileSystemEventHandler):
    """Bridge watchdog callbacks (dispatcher thread) into a _WatchEntry."""

    def __init__(self, entry: "_WatchEntry") -> None:
        super().__init__()
        self._entry = entry

    def on_any_event(self, event) -> None:
        self._entry._on_event(event)


class _WatchEntry:
    """Watch state for a single (root, dir) the user has open."""

    def __init__(
        self,
        root_id: str,
        dir_rel: str,
        root_path: Path,
        dir_abs: Path,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.root_id = root_id
        self.dir_rel = dir_rel
        self.root_path = root_path
        self.dir_abs = dir_abs
        self.loop = loop
        self.queues: Set[asyncio.Queue] = set()
        self._observer: Optional[Observer] = None
        self._started = False
        self._buffer: Dict[str, str] = {}  # rel_path -> kind
        # A moved event arrives after its destination has been installed, so
        # ``Path(dest).exists()`` alone cannot distinguish a rename-overwrite
        # from a rename to a new name. Keep the direct children known before
        # each event instead.
        self._direct_children: Optional[Set[str]] = self._snapshot_direct_children()
        self._flush_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    # ── lifecycle (called from the event-loop thread) ────────────────────
    def start(self) -> None:
        if not _WATCHDOG_AVAILABLE:
            logger.warning("watchdog not available; fs watch disabled for %s/%s", self.root_id, self.dir_rel)
            return
        if self._started:
            return
        observer = Observer()
        observer.schedule(_Handler(self), str(self.dir_abs), recursive=False)
        observer.daemon = True
        observer.start()
        self._observer = observer
        self._started = True
        logger.info("fs watch started for %s/%s (%s)", self.root_id, self.dir_rel, self.dir_abs)

    def stop(self) -> None:
        if not self._started:
            return
        self._cancel_flush_timer()
        observer = self._observer
        self._observer = None
        self._started = False
        self._buffer.clear()
        if observer is not None:
            # stop() is thread-safe and non-blocking; join in a daemon thread so we
            # never block the event loop with a 2s join.
            observer.stop()
            t = threading.Thread(target=_safe_join, args=(observer,), daemon=True)
            t.start()
        logger.info("fs watch stopped for %s/%s", self.root_id, self.dir_rel)

    # ── event handler (dispatcher thread) ────────────────────────────────
    def _on_event(self, event) -> None:
        if not _WATCHDOG_AVAILABLE:
            return
        changed = False
        with self._lock:
            if isinstance(event, (FileMovedEvent, DirMovedEvent)):
                # A move out of the watched dir is a delete. For a destination
                # inside it, a pre-existing direct child means an editor-style
                # rename-overwrite and is therefore a modification, not an add.
                src = getattr(event, "src_path", None)
                dest = getattr(event, "dest_path", None)
                src_is_child = bool(src and self._is_direct_child(src))
                dest_is_child = bool(dest and self._is_direct_child(dest))
                if src_is_child and dest_is_child and self._same_path(src, dest):
                    # Some backends report an in-place replacement as a move
                    # with equal paths. It must not become deleted + added.
                    rel = self._rel(dest)
                    self._buffer_set(rel, _MODIFIED)
                    self._remember_direct_child(rel)
                    changed = True
                else:
                    if src_is_child:
                        src_rel = self._rel(src)
                        # Atomic-save temporary files are often created in the
                        # watched directory immediately before this move. They
                        # were not present in the pre-event snapshot, so their
                        # disappearance is an implementation detail rather
                        # than a user-visible deletion.
                        if not dest_is_child or self._was_direct_child(src_rel):
                            self._buffer_set(src_rel, _DELETED)
                            changed = True
                        self._forget_direct_child(src_rel)
                    if dest_is_child:
                        dest_rel = self._rel(dest)
                        # If the pre-event snapshot is unavailable, prefer
                        # modified: editor atomic saves commonly overwrite an
                        # existing target, and calling that an add is misleading.
                        kind = _MODIFIED if self._was_direct_child(dest_rel) else _ADDED
                        self._buffer_set(dest_rel, kind)
                        self._remember_direct_child(dest_rel)
                        changed = True
            else:
                kind = _normalize_kind(event)
                if kind:
                    path = getattr(event, "src_path", None) or getattr(event, "path", None)
                    if path and self._is_direct_child(path):
                        rel = self._rel(path)
                        self._buffer_set(rel, kind)
                        if kind == _DELETED:
                            self._forget_direct_child(rel)
                        else:
                            self._remember_direct_child(rel)
                        changed = True
            if changed:
                self._arm_flush()

    def _is_direct_child(self, path: str) -> bool:
        """True when path is a direct child of the watched directory."""
        try:
            return Path(path).resolve().parent == self.dir_abs
        except OSError:
            return False

    def _rel(self, path: str) -> str:
        """Path relative to the root, using forward slashes (matches list_dir)."""
        try:
            rel = os.path.relpath(path, self.root_path)
        except ValueError:
            return Path(path).name
        return rel.replace(os.sep, "/")

    def _snapshot_direct_children(self) -> Optional[Set[str]]:
        """Return the initial direct-child set, or None when it cannot be read."""
        try:
            return {self._rel(str(path)) for path in self.dir_abs.iterdir()}
        except OSError:
            logger.debug("cannot snapshot watched directory %s", self.dir_abs, exc_info=True)
            return None

    def _was_direct_child(self, rel_path: str) -> bool:
        """Whether the destination existed before this event; unknown -> modified."""
        return self._direct_children is None or rel_path in self._direct_children

    def _remember_direct_child(self, rel_path: str) -> None:
        if self._direct_children is not None:
            self._direct_children.add(rel_path)

    def _forget_direct_child(self, rel_path: str) -> None:
        if self._direct_children is not None:
            self._direct_children.discard(rel_path)

    @staticmethod
    def _same_path(src: str, dest: str) -> bool:
        return os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dest))

    def _buffer_set(self, rel_path: str, kind: str) -> None:
        existing = self._buffer.get(rel_path)
        if existing is None or _KIND_PRIORITY.get(kind, 0) > _KIND_PRIORITY.get(existing, 0):
            self._buffer[rel_path] = kind

    def _arm_flush(self) -> None:
        if self._flush_timer is not None:
            self._flush_timer.cancel()
        timer = threading.Timer(DEBOUNCE_SECONDS, self._flush)
        timer.daemon = True
        self._flush_timer = timer
        timer.start()

    def _cancel_flush_timer(self) -> None:
        if self._flush_timer is not None:
            self._flush_timer.cancel()
            self._flush_timer = None

    def _flush(self) -> None:
        with self._lock:
            self._flush_timer = None
            buffer = self._buffer
            self._buffer = {}
        if not buffer:
            return
        # Burst / possible inotify queue overflow → one full rescan (refresh).
        # Keeps the frontend honest without polluting it with dozens of events.
        if len(buffer) >= _RESCAN_BURST_THRESHOLD:
            self._broadcast({"type": "refresh"})
            return
        for rel_path, kind in buffer.items():
            self._broadcast({"type": "change", "path": rel_path, "kind": kind})

    def _broadcast(self, event: dict) -> None:
        payload = "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        # asyncio.Queue is not thread-safe; hop onto the event loop before
        # enqueuing from the watchdog dispatcher thread.
        for queue in list(self.queues):
            try:
                self.loop.call_soon_threadsafe(queue.put_nowait, payload)
            except RuntimeError:
                # Event loop already closed (e.g. Ctrl-C shutdown) — drop the
                # event rather than crashing the dispatcher thread.
                pass


def _safe_join(observer: Observer, timeout: float = 2) -> None:
    try:
        observer.join(timeout)
    except Exception:  # pragma: no cover - defensive
        logger.debug("observer join failed", exc_info=True)


class FsWatchService:
    """Reference-counted registry of active directory watches."""

    def __init__(self) -> None:
        self._entries: Dict[str, _WatchEntry] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(root_id: str, dir_rel: str) -> str:
        return f"{root_id}|{dir_rel}"

    def subscribe(
        self,
        root_id: str,
        dir_rel: str,
        root_path: Path,
        dir_abs: Path,
        loop: asyncio.AbstractEventLoop,
    ) -> asyncio.Queue:
        """Register a new client queue and start the observer if needed."""
        key = self._key(root_id, dir_rel)
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = _WatchEntry(root_id, dir_rel, root_path, dir_abs, loop)
                self._entries[key] = entry
            entry.queues.add(queue)
        # Start outside the lock (idempotent); only threads on the event-loop
        # call subscribe, so this stays single-threaded per entry.
        entry.start()
        return queue

    def unsubscribe(self, root_id: str, dir_rel: str, queue: asyncio.Queue) -> None:
        """Drop a client queue and stop the observer when none remain."""
        key = self._key(root_id, dir_rel)
        remove_entry = False
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            entry.queues.discard(queue)
            if not entry.queues:
                remove_entry = True
                self._entries.pop(key, None)
        if remove_entry:
            entry.stop()


# Module-level singleton shared by the routes layer.
fs_watch_service = FsWatchService()
