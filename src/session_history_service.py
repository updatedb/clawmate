from __future__ import annotations

import base64
import json
from typing import Iterable


class SessionHistoryService:
    """Pure, cursor-based session history query layer.

    Storage and route adapters can refresh ``records`` before querying; the
    pagination token contains the immutable sort key rather than page index.
    """

    def __init__(self, records: Iterable[dict] = ()):
        self.records = [dict(record) for record in records]

    def list(
        self,
        *,
        limit: int = 15,
        cursor: str | None = None,
        backend: str = "",
        status: str = "",
        keyword: str = "",
    ) -> dict:
        rows = sorted(self.records, key=lambda row: (float(row.get("started_at") or 0), str(row.get("id") or "")), reverse=True)
        keyword = keyword.casefold().strip()
        rows = [
            row for row in rows
            if (not backend or row.get("backend") == backend)
            and (not status or row.get("state", row.get("status", "ended")) == status)
            and (not keyword or keyword in str(row.get("title", "")).casefold())
        ]
        if cursor:
            cursor_key = self._decode_cursor(cursor)
            rows = [row for row in rows if self._sort_key(row) < cursor_key]
        page = rows[:max(1, min(int(limit), 100))]
        next_cursor = self._encode_cursor(self._sort_key(page[-1])) if len(rows) > len(page) else None
        return {"sessions": page, "next_cursor": next_cursor, "total": len(rows)}

    @staticmethod
    def _sort_key(row: dict) -> tuple[float, str]:
        return float(row.get("started_at") or 0), str(row.get("id") or "")

    @staticmethod
    def _encode_cursor(key: tuple[float, str]) -> str:
        return base64.urlsafe_b64encode(json.dumps(key, separators=(",", ":")).encode()).decode()

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[float, str]:
        try:
            value = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            return float(value[0]), str(value[1])
        except (ValueError, TypeError, IndexError, UnicodeDecodeError) as exc:
            raise ValueError("invalid session history cursor") from exc
