import asyncio
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))

import fs_routes  # noqa: E402
import fs_watch as fs_watch_mod  # noqa: E402
from fs_watch import fs_watch_service  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


# ── fs_watch service: subscribe → filesystem event → SSE payload ────────────


@pytest.mark.asyncio
async def test_watch_emits_added_event_for_new_file(tmp_path):
    root_path = tmp_path
    watched = tmp_path / "sub"
    watched.mkdir()
    loop = asyncio.get_running_loop()
    queue = fs_watch_service.subscribe("test-root", "sub", root_path, watched, loop)
    try:
        target = watched / "hello.txt"

        def _create():
            time.sleep(0.1)
            target.write_text("hi", encoding="utf-8")

        threading.Thread(target=_create, daemon=True).start()
        payload = await asyncio.wait_for(queue.get(), timeout=6)
        assert "added" in payload
        assert "sub/hello.txt" in payload
    finally:
        fs_watch_service.unsubscribe("test-root", "sub", queue)


@pytest.mark.asyncio
async def test_watch_emits_modified_event_for_existing_file(tmp_path):
    root_path = tmp_path
    watched = tmp_path / "sub"
    watched.mkdir()
    existing = watched / "doc.txt"
    existing.write_text("v1", encoding="utf-8")
    loop = asyncio.get_running_loop()
    queue = fs_watch_service.subscribe("test-root", "sub", root_path, watched, loop)
    try:
        def _touch():
            time.sleep(0.1)
            existing.write_text("v2", encoding="utf-8")

        threading.Thread(target=_touch, daemon=True).start()
        payload = await asyncio.wait_for(queue.get(), timeout=6)
        assert "modified" in payload
        assert "sub/doc.txt" in payload
    finally:
        fs_watch_service.unsubscribe("test-root", "sub", queue)


@pytest.mark.asyncio
async def test_watch_emits_deleted_event(tmp_path):
    root_path = tmp_path
    watched = tmp_path / "sub"
    watched.mkdir()
    doomed = watched / "bye.txt"
    doomed.write_text("x", encoding="utf-8")
    loop = asyncio.get_running_loop()
    queue = fs_watch_service.subscribe("test-root", "sub", root_path, watched, loop)
    try:
        def _delete():
            time.sleep(0.1)
            doomed.unlink()

        threading.Thread(target=_delete, daemon=True).start()
        payload = await asyncio.wait_for(queue.get(), timeout=6)
        assert "deleted" in payload
        assert "sub/bye.txt" in payload
    finally:
        fs_watch_service.unsubscribe("test-root", "sub", queue)


@pytest.mark.asyncio
async def test_watch_coalesces_burst_into_refresh(tmp_path):
    """A burst of many distinct paths in one window coalesces into a refresh."""
    root_path = tmp_path
    watched = tmp_path / "sub"
    watched.mkdir()
    loop = asyncio.get_running_loop()
    queue = fs_watch_service.subscribe("test-root", "sub", root_path, watched, loop)
    try:
        n = fs_watch_mod._RESCAN_BURST_THRESHOLD + 5

        def _burst():
            time.sleep(0.1)
            for i in range(n):
                (watched / f"f{i}.txt").write_text("x", encoding="utf-8")

        threading.Thread(target=_burst, daemon=True).start()
        payload = await asyncio.wait_for(queue.get(), timeout=8)
        assert "refresh" in payload
    finally:
        fs_watch_service.unsubscribe("test-root", "sub", queue)


# ── route contract: GET /api/clawmate/fs/events ────────────────────────────


@pytest.fixture
def fs_client():
    app = FastAPI()
    app.include_router(fs_routes.router)
    return TestClient(app)


def test_fs_events_missing_root_returns_422(fs_client):
    response = fs_client.get("/api/clawmate/fs/events?dir=sub")
    assert response.status_code == 422


def test_fs_events_returns_503_when_watchdog_unavailable(fs_client, monkeypatch):
    monkeypatch.setattr(fs_routes, "_WATCHDOG_AVAILABLE", False)
    response = fs_client.get("/api/clawmate/fs/events?root=test&dir=sub")
    assert response.status_code == 503
