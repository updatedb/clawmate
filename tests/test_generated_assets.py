import json
from pathlib import Path

import pytest

from generated_assets import GeneratedAssetService
import generated_asset_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient


PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0dIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / ".clawmate").mkdir(parents=True)
    return project


def test_create_task_uses_source_directory_candidates_and_project_metadata(tmp_path: Path):
    project = _project(tmp_path)
    source = project / "art" / "source.png"
    source.parent.mkdir()
    source.write_bytes(PNG_1X1)

    task = GeneratedAssetService(project).create_task(
        source_path=source,
        prompt="turn the cabin display blue",
        purpose="PRD",
        topic="cabin-ui",
        width=1024,
        height=1024,
        candidate_count=2,
        backend="codex",
        operator="admin",
    )

    assert task.candidate_dir == source.parent / "candidates" / task.id
    assert task.metadata_dir == project / ".clawmate" / "generated-tasks" / task.id
    payload = json.loads((task.metadata_dir / "request.json").read_text(encoding="utf-8"))
    assert payload["candidate_count"] == 2
    assert payload["source_path"] == "art/source.png"


def test_create_task_rejects_more_than_four_candidates(tmp_path: Path):
    with pytest.raises(ValueError, match="candidate_count"):
        GeneratedAssetService(_project(tmp_path)).create_task(
            source_path=None,
            prompt="new cover",
            purpose="cover",
            topic="cover",
            width=1024,
            height=1024,
            candidate_count=5,
            backend="codex",
            operator="admin",
        )


def test_result_rejects_candidate_outside_server_created_directory(tmp_path: Path):
    service = GeneratedAssetService(_project(tmp_path))
    task = service.create_task(
        source_path=None, prompt="new cover", purpose="cover", topic="cover",
        width=1024, height=1024, candidate_count=1, backend="codex", operator="admin",
    )
    (task.metadata_dir / "result.json").write_text(
        json.dumps({"candidates": [{"id": "bad", "file": "../../secret.png", "summary": "bad"}]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="candidate"):
        service.read_result(task.id)


def test_adopt_candidate_copies_asset_and_records_prompt(tmp_path: Path):
    project = _project(tmp_path)
    service = GeneratedAssetService(project)
    task = service.create_task(
        source_path=None, prompt="make it blue", purpose="cover", topic="cabin-ui",
        width=1024, height=1024, candidate_count=1, backend="codex", operator="admin",
    )
    (task.candidate_dir / "one.png").write_bytes(PNG_1X1)
    (task.metadata_dir / "result.json").write_text(
        json.dumps({"candidates": [{"id": "one", "file": "one.png", "summary": "blue cover"}]}),
        encoding="utf-8",
    )

    adopted = service.adopt_candidate(task.id, "one")

    manifest = json.loads((adopted.path.parent / "manifest.json").read_text(encoding="utf-8"))
    assert adopted.path.is_file()
    assert manifest["assets"][-1]["generation_prompt"] == "make it blue"
    assert service.source_prompt(adopted.path) == "make it blue"


def test_create_route_uses_configured_agent_backend(tmp_path: Path, monkeypatch):
    project = _project(tmp_path)
    source = project / "art" / "source.png"
    source.parent.mkdir()
    source.write_bytes(PNG_1X1)
    launched = {}

    class Executor:
        def launch(self, **kwargs):
            launched.update(kwargs)
            return type("Receipt", (), {"status": "running", "payload": lambda self: {"status": "running"}})()

    monkeypatch.setattr(generated_asset_routes, "safe_path", lambda root, path: (tmp_path, project, "project"))
    monkeypatch.setattr(generated_asset_routes, "load_cfg", lambda: type("Cfg", (), {"agent": type("Agent", (), {"backend": "codex"})()})())
    monkeypatch.setattr(generated_asset_routes, "TaskExecutor", lambda cfg: Executor())
    app = FastAPI()
    app.include_router(generated_asset_routes.router)
    response = TestClient(app).post("/api/clawmate/generated-assets/demo/project/tasks", json={
        "source_path": "art/source.png", "prompt": "annotate the safety zone", "purpose": "review",
        "topic": "safety", "width": 1024, "height": 1024, "candidate_count": 2,
    })
    assert response.status_code == 201
    assert launched["backend"] == "codex"
    assert "result.json" in launched["message"]
