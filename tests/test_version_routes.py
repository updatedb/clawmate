import sys
import subprocess
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))

import version_routes  # noqa: E402


def test_build_commit_message_for_new_file():
    assert version_routes._build_commit_message(Path("notes.md"), None) == "新增文档：notes.md"


def test_build_commit_message_for_modified_file():
    assert (
        version_routes._build_commit_message(Path("notes.md"), "12\t3\tnotes.md\n")
        == "更新文档：notes.md（新增 12 行，删除 3 行）"
    )


def test_version_modal_has_auto_commit_control():
    html = (ROOT / "dev" / "static" / "preview.html").read_text(encoding="utf-8")
    script = (ROOT / "dev" / "static" / "js" / "preview.js").read_text(encoding="utf-8")

    assert 'id="versionModalCommit"' in html
    assert "commitVersionFromModal" in script


def test_commit_route_generates_summary_and_leaves_other_changes_untouched(tmp_path, monkeypatch):
    target = tmp_path / "notes.md"
    other = tmp_path / "other.md"
    target.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "notes.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True)
    target.write_text("before\nafter\n", encoding="utf-8")
    other.write_text("unrelated\n", encoding="utf-8")

    monkeypatch.setattr(version_routes, "safe_path", lambda root, path: (tmp_path, target, "notes.md"))
    app = FastAPI()
    app.include_router(version_routes.router)
    response = TestClient(app).post(
        "/api/clawmate/version/commit",
        json={"root": "root-a", "path": "notes.md", "message": "ignored client subject"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    subject = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=tmp_path, check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert subject == "更新文档：notes.md（新增 1 行，删除 0 行）"
    status = subprocess.run(["git", "status", "--porcelain"], cwd=tmp_path, check=True, capture_output=True, text=True)
    assert status.stdout == "?? other.md\n"
