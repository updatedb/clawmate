from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OutputChunk:
    start: int
    end: int
    data: bytes


@dataclass(frozen=True, slots=True)
class ReplayResult:
    gap: bool
    earliest_sequence: int
    latest_sequence: int
    chunks: tuple[OutputChunk, ...]


class ReplayRing:
    def __init__(self, max_bytes: int):
        self.max_bytes = max(0, int(max_bytes))
        self._chunks: deque[OutputChunk] = deque()
        self.earliest_sequence = 0
        self.latest_sequence = 0
        self.retained_bytes = 0

    def append(self, data: bytes) -> None:
        payload = bytes(data or b"")
        if not payload:
            return
        chunk = OutputChunk(self.latest_sequence, self.latest_sequence + len(payload), payload)
        self._chunks.append(chunk)
        self.latest_sequence = chunk.end
        self.retained_bytes += len(payload)
        self._trim()

    def after(self, sequence: int) -> ReplayResult:
        sequence = max(0, int(sequence))
        gap = sequence < self.earliest_sequence
        start_at = self.earliest_sequence if gap else sequence
        chunks: list[OutputChunk] = []
        for chunk in self._chunks:
            if chunk.end <= start_at:
                continue
            if chunk.start < start_at:
                offset = start_at - chunk.start
                data = chunk.data[offset:]
                chunks.append(OutputChunk(start_at, chunk.end, data))
            else:
                chunks.append(chunk)
        return ReplayResult(
            gap=gap,
            earliest_sequence=self.earliest_sequence,
            latest_sequence=self.latest_sequence,
            chunks=tuple(chunks),
        )

    def _trim(self) -> None:
        if self.max_bytes <= 0:
            while self._chunks:
                self._chunks.popleft()
            self.earliest_sequence = self.latest_sequence
            self.retained_bytes = 0
            return

        while self.retained_bytes > self.max_bytes and self._chunks:
            first = self._chunks[0]
            over = self.retained_bytes - self.max_bytes
            if over >= len(first.data):
                self._chunks.popleft()
                self.retained_bytes -= len(first.data)
                self.earliest_sequence = first.end
                continue

            sliced = first.data[over:]
            self._chunks[0] = OutputChunk(first.start + over, first.end, sliced)
            self.retained_bytes -= over
            self.earliest_sequence = self._chunks[0].start
            break
