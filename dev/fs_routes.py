"""SSE endpoint for filesystem change events.

Backs ``GET /api/clawmate/fs/events``. The frontend opens a single
EventSource per directory it is viewing; the server streams a ``change``
event whenever a *direct* child of that directory is added, modified, or
deleted. Authentication is enforced by the shared ``AuthMiddleware`` (session
cookie), exactly like the rest of the API — EventSource sends the cookie
automatically for same-origin requests.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from fs_watch import _WATCHDOG_AVAILABLE, fs_watch_service
from service import safe_path

router = APIRouter()
logger = logging.getLogger("clawmate.fs_routes")

# Disable intermediary proxy buffering so events stream immediately instead of
# being held until the response completes.
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

# Heartbeat interval: keeps the connection alive past proxy/uvicorn keep-alive
# timeouts and lets the frontend detect a hard disconnect.
_HEARTBEAT_SECONDS = 15


@router.get("/api/clawmate/fs/events")
async def clawmate_fs_events(
    request: Request,
    root: str = Query(""),
    dir: str = Query(""),
):
    """Stream directory change events as a Server-Sent Event stream.

    The stream is long-lived and is closed automatically when the client
    disconnects (the generator is cancelled, which triggers unsubscribe).
    """
    if not root:
        raise HTTPException(status_code=422, detail="Missing root")
    if not _WATCHDOG_AVAILABLE:
        raise HTTPException(status_code=503, detail="fs watch unavailable (watchdog is not installed)")

    try:
        root_path, target, safe_rel = safe_path(root, dir)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Directory not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    loop = asyncio.get_running_loop()
    queue = fs_watch_service.subscribe(root, safe_rel, root_path, target, loop)
    logger.info("fs events subscribed root=%s dir=%s (dir_abs=%s)", root, safe_rel, target)

    async def event_stream():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    # Heartbeat comment; keeps the TCP connection warm.
                    yield ": keepalive\n\n"
                    continue
                yield payload
        except asyncio.CancelledError:
            raise
        finally:
            fs_watch_service.unsubscribe(root, safe_rel, queue)
            logger.info("fs events unsubscribed root=%s dir=%s", root, safe_rel)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
