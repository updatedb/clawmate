from __future__ import annotations

import io
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import routes  # noqa: E402


def _client_for_image(tmp_path: Path, monkeypatch) -> TestClient:
    source = tmp_path / "large.png"
    Image.new("RGB", (1600, 900), color="navy").save(source)
    monkeypatch.setattr(routes, "safe_path", lambda root, path: (tmp_path, source, "large.png"))
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def test_thumbnail_route_returns_a_bounded_webp_derivative(tmp_path: Path, monkeypatch):
    """Would fail if the gallery receives the original image instead of a thumbnail."""
    client = _client_for_image(tmp_path, monkeypatch)

    response = client.get("/api/clawmate/thumbnail", params={"root": "media", "path": "large.png", "size": 160})

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    with Image.open(io.BytesIO(response.content)) as thumbnail:
        assert thumbnail.size == (160, 90)


def test_thumbnail_route_uses_revalidatable_cache_headers(tmp_path: Path, monkeypatch):
    """Would fail if thumbnail reloads are forced to bypass browser caches."""
    client = _client_for_image(tmp_path, monkeypatch)

    response = client.get("/api/clawmate/thumbnail", params={"root": "media", "path": "large.png"})

    assert response.status_code == 200
    assert "no-store" not in response.headers["cache-control"]
    assert "etag" in response.headers


def test_image_preview_uses_revalidatable_cache_headers(tmp_path: Path, monkeypatch):
    """Would fail if every original-image revisit is still forced to redownload."""
    client = _client_for_image(tmp_path, monkeypatch)

    response = client.get("/api/clawmate/preview", params={"root": "media", "path": "large.png"})

    assert response.status_code == 200
    assert "no-store" not in response.headers["cache-control"]
    assert "etag" in response.headers
