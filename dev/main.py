"""
ClawMate v0.1 — Standalone ClawMate service.
Independent FastAPI server, Docker-deployable.

Usage:
    python main.py                          # uses defaults from config.json
    CLAWMATE_PORT=8080 python main.py       # override port
    CLAWMATE_CONFIG=/path/to/config.json python main.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# ── config resolution ──────────────────────────────────────────────
CONFIG_PATH = Path(
    os.environ.get("CLAWMATE_CONFIG") or (Path(__file__).parent / "config.json")
)
STATIC_DIR = Path(__file__).parent / "static"

try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    print(f"[clawmate] WARNING: config.json not found or invalid at {CONFIG_PATH}, using defaults", file=sys.stderr)
    config = {
        "roots": [
            {
                "id": "media",
                "label": "媒体",
                "dir": str((Path.home() / ".openclaw" / "media").resolve()),
            }
        ],
        "defaultRootId": "media",
        "onlyoffice": {"api_js_url": "https://file.updatedb.online:18443/web-apps/apps/api/documents/api.js"},
    }

# env overrides (highest priority)
_onlyoffice_cfg = config.get("onlyoffice", {}) or {}
ONLYOFFICE_API_JS_URL = os.environ.get(
    "CLAWMATE_ONLYOFFICE_URL",
    _onlyoffice_cfg.get("api_js_url", "https://file.updatedb.online:18443/web-apps/apps/api/documents/api.js"),
)
ONLYOFFICE_JWT_SECRET = os.environ.get(
    "CLAWMATE_ONLYOFFICE_JWT_SECRET",
    _onlyoffice_cfg.get("jwt_secret", ""),
)
PUBLIC_BASE_URL = os.environ.get(
    "CLAWMATE_PUBLIC_BASE_URL",
    config.get("public_base_url", ""),
)

# inject env vars for routes.py / service.py
os.environ.setdefault("CLAWMATE_ONLYOFFICE_JWT_SECRET", ONLYOFFICE_JWT_SECRET)
os.environ.setdefault("CLAWMATE_PUBLIC_BASE_URL", PUBLIC_BASE_URL)
os.environ.setdefault("CLAWMATE_CONFIG", str(CONFIG_PATH))

# ── FastAPI app ────────────────────────────────────────────────────
app = FastAPI(
    title="ClawMate",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# import routes AFTER env vars are set (they read env at import time)
from routes import router as clawmate_router  # noqa: E402

app.include_router(clawmate_router)

# mount static files under /clawmate/
if STATIC_DIR.exists() and STATIC_DIR.is_dir():
    app.mount("/clawmate", StaticFiles(directory=str(STATIC_DIR), html=True), name="clawmate_static")


# redirect root to /clawmate/
@app.get("/")
async def root_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/clawmate/")


# ── health check ───────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "clawmate", "version": "0.1.0"}


# ── entrypoint ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("CLAWMATE_PORT", config.get("port", 5533)))
    max_upload = int(os.environ.get("CLAWMATE_MAX_UPLOAD_MB", config.get("max_upload_mb", 100)))
    print(f"[clawmate] Starting on http://0.0.0.0:{port}")
    print(f"[clawmate] Web UI at /clawmate/")
    print(f"[clawmate] Config: {CONFIG_PATH}")
    print(f"[clawmate] ONLYOFFICE API JS: {ONLYOFFICE_API_JS_URL}")
    print(f"[clawmate] Max upload: {max_upload}MB")
    
    # Increase multipart upload size limit (default 1MB)
    from starlette.formparsers import MultiPartParser
    MultiPartParser.spool_max_size = max_upload * 1024 * 1024
    
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
