"""
Static file cache-busting middleware.

Two mechanisms work together:

1.  HTML rewriting — when serving an HTML file, the middleware scans the
    response body for <script src="..."> and <link href="..."> tags that
    reference local static files (under /clawmate/js/, /clawmate/css/,
    /clawmate/asset/, or /clawmate/dist/).  Each URL gets a ?v=<mtime> query string appended
    automatically, where <mtime> is the file's modification time.  When a
    file changes on disk, its mtime changes → the URL changes → browsers
    fetch the new version immediately.  Zero maintenance.

2.  Cache-Control headers — JS/CSS/asset responses with a ?v= query string
    get "public, max-age=31536000, immutable" (1 year).  Since the URL is
    content-addressed via mtime, this is safe: the URL changes whenever
    the file content changes.

    HTML files get "no-cache" so browsers always fetch the latest page
    (which then references the latest JS/CSS URLs).

    sw.js gets "no-cache" so browsers check for Service Worker updates.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from starlette.types import ASGIApp, Scope, Receive, Send
from starlette.datastructures import MutableHeaders


# ── Mtime cache ───────────────────────────────────────────────────────
# Cache file mtimes for 2 seconds to avoid excessive stat() calls during
# a single page load that references many files.  Short enough that a
# file change + page reload picks up the new mtime.
_mtime_cache: dict[str, tuple[float, int]] = {}  # path -> (cached_at, mtime)
_MTIME_CACHE_TTL = 2.0  # seconds


def _get_mtime(abs_path: str) -> int:
    """Return file mtime as int, with a short-lived cache."""
    now = time.time()
    entry = _mtime_cache.get(abs_path)
    if entry and now - entry[0] < _MTIME_CACHE_TTL:
        return entry[1]
    try:
        mtime = int(Path(abs_path).stat().st_mtime)
    except (OSError, ValueError):
        mtime = 0
    _mtime_cache[abs_path] = (now, mtime)
    return mtime


# HTML tag patterns — match src="..." or href="..." that point to local
# static files (not CDN, not data: URIs, not absolute URLs).
_STATIC_DIRS = ("js/", "css/", "asset/", "dist/", "vendor/", "pdfjs/")
_RE_SCRIPT_SRC = re.compile(
    r'(<script\b[^>]*?\ssrc=")(\.\.?/)(js/[^"]+)(")',
    re.IGNORECASE,
)
_RE_LINK_HREF = re.compile(
    r'(<link\b[^>]*?\s(?:href)=")(\.\.?/)(css/[^"]+\.css)(")',
    re.IGNORECASE,
)
# Broader pattern for any local reference under ./ that we can mtime-stamp
_RE_ANY_SRC = re.compile(
    r'((?:src|href)=")(\.\.?/)((?:js|css|asset|dist|vendor|pdfjs)/[^"]+)(")',
    re.IGNORECASE,
)


class StaticCacheMiddleware:
    """Auto-mtime cache busting + Cache-Control headers for static files.

    Must be added as middleware AFTER the StaticFiles mount so it can
    intercept responses from it.
    """

    def __init__(self, app: ASGIApp, static_dir: str = "") -> None:
        self.app = app
        self._static_dir = Path(static_dir) if static_dir else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        if not path.startswith("/clawmate/"):
            await self.app(scope, receive, send)
            return

        # Clean path (no query string)
        clean_path = path.rsplit("?", 1)[0]

        # ── sw.js: always no-cache ─────────────────────────────────
        if clean_path == "/clawmate/sw.js":
            await self._with_cache_control(scope, receive, send, "no-cache")
            return

        # ── HTML files: rewrite static URLs with mtime versions ────
        if clean_path == "/clawmate/" or clean_path.endswith(".html"):
            await self._rewrite_html(scope, receive, send)
            return

        # ── JS/CSS/assets: long cache if versioned, else no-cache ──
        cc = _cache_control_for_static(clean_path, path)
        await self._with_cache_control(scope, receive, send, cc)

    # ── helpers ──────────────────────────────────────────────────────

    async def _with_cache_control(self, scope, receive, send, cc: str) -> None:
        async def _send(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=message.get("headers", []))
                if "cache-control" not in headers:
                    headers["Cache-Control"] = cc
            await send(message)

        await self.app(scope, receive, _send)

    async def _rewrite_html(self, scope, receive, send) -> None:
        """Buffer HTML response, rewrite static URLs with mtime versions."""
        # Determine static directory
        static_dir = self._static_dir
        if static_dir is None:
            # Try to find it from the main module's STATIC_DIR
            import sys
            main = sys.modules.get("__main__")
            if main and hasattr(main, "STATIC_DIR"):
                static_dir = main.STATIC_DIR
                self._static_dir = static_dir
            else:
                # Fallback: relative to this file
                static_dir = Path(__file__).resolve().parent / "static"
                self._static_dir = static_dir

        response_started = False
        start_message: dict | None = None
        body_chunks: list[bytes] = []
        content_type = ""

        async def _capture(message: dict) -> None:
            nonlocal response_started, start_message, content_type
            if message["type"] == "http.response.start":
                response_started = True
                start_message = message
                headers = MutableHeaders(raw=message.get("headers", []))
                content_type = headers.get("content-type", "")
            elif message["type"] == "http.response.body":
                body_chunks.append(message.get("body", b""))
                # Don't forward yet — we need the full body

        await self.app(scope, receive, _capture)

        if not response_started or start_message is None:
            # No response? Forward whatever we have
            await send({"type": "http.response.start", "status": 500,
                        "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"Internal error"})
            return

        # Only rewrite HTML responses
        body = b"".join(body_chunks)
        if "text/html" in content_type and body:
            body = self._inject_mtime_versions(body, static_dir)

        # Update Content-Length
        headers = MutableHeaders(raw=start_message.get("headers", []))
        headers["Cache-Control"] = "no-cache"
        headers["Content-Length"] = str(len(body))

        await send({
            "type": "http.response.start",
            "status": start_message["status"],
            "headers": list(headers.raw),
        })
        await send({
            "type": "http.response.body",
            "body": body,
            "more_body": False,
        })

    def _inject_mtime_versions(self, body: bytes, static_dir: Path) -> bytes:
        """Scan HTML for local static references and append ?v=<mtime>."""
        text = body.decode("utf-8", errors="replace")

        def _replacer(m: re.Match) -> str:
            prefix = m.group(1)   # src=" or href="
            relative = m.group(2)  # ./ or ../
            file_path = m.group(3)  # js/app.js or css/style.css
            suffix = m.group(4)    # "
            # Skip if already has ?v=
            full_match = m.group(0)
            if "?v=" in full_match:
                return full_match
            # Resolve to absolute path
            abs_path = static_dir / file_path
            mtime = _get_mtime(str(abs_path))
            if mtime:
                return f'{prefix}{relative}{file_path}?v={mtime}{suffix}'
            return full_match

        text = _RE_ANY_SRC.sub(_replacer, text)
        return text.encode("utf-8")


# ── Cache-Control per static file type ───────────────────────────────

def _cache_control_for_static(clean_path: str, original_path: str) -> str:
    """Return Cache-Control header for a non-HTML static file request.

    If the request URL already has a ?v= query string (mtime-based cache
    buster), use a long immutable cache. Otherwise, use no-cache so the
    browser revalidates.
    """
    # If the request has a version query string, it's content-addressed → long cache
    if "?v=" in original_path:
        ext = _ext(clean_path)
        if ext in (".js", ".mjs", ".css"):
            return "public, max-age=31536000, immutable"
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
                    ".woff", ".woff2", ".ttf", ".otf", ".eot",
                    ".mp4", ".webm", ".mp3", ".ogg", ".pdf"):
            return "public, max-age=31536000, immutable"
        return "public, max-age=86400"

    # No version → short cache, must revalidate
    ext = _ext(clean_path)
    if ext in (".js", ".mjs", ".css"):
        return "public, max-age=300, must-revalidate"  # 5 min, safe fallback
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
                ".woff", ".woff2", ".ttf", ".otf", ".eot"):
        return "public, max-age=86400"
    return "no-cache"


def _ext(path: str) -> str:
    filename = path.rsplit("/", 1)[-1]
    if "." in filename:
        return "." + filename.rsplit(".", 1)[-1].lower()
    return ""
