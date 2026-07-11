from dev.session_history_service import SessionHistoryService
import pytest


def test_history_list_filters_and_uses_stable_cursor():
    service = SessionHistoryService([
        {"id": "new", "backend": "codex", "state": "ended", "started_at": 30, "title": "release notes"},
        {"id": "middle", "backend": "claude", "state": "running", "started_at": 20, "title": "draft"},
        {"id": "old", "backend": "codex", "state": "ended", "started_at": 10, "title": "release checklist"},
    ])

    first = service.list(limit=1, backend="codex", status="ended", keyword="release")
    second = service.list(limit=1, cursor=first["next_cursor"], backend="codex", status="ended", keyword="release")

    assert [row["id"] for row in first["sessions"]] == ["new"]
    assert [row["id"] for row in second["sessions"]] == ["old"]
    assert second["next_cursor"] is None


def test_history_rejects_malformed_cursor():
    with pytest.raises(ValueError, match="invalid session history cursor"):
        SessionHistoryService().list(cursor="not-a-cursor")
