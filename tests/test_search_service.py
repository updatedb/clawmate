import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))

import search_service  # noqa: E402


def test_search_media_recursively_searches_from_nested_directory(tmp_path, monkeypatch):
    root = tmp_path / "root"
    nested = root / "project" / "docs"
    nested.mkdir(parents=True)
    (nested / "deep-match.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        search_service,
        "safe_path",
        lambda root_id, rel_dir: (root, root / rel_dir, rel_dir),
    )

    result = search_service.search_media("match", "root", "project", max_depth=8)

    assert [entry["path"] for entry in result["results"]] == [
        "project/docs/deep-match.md"
    ]


def test_search_content_runs_ripgrep_from_nested_directory_without_marker(
    tmp_path, monkeypatch
):
    root = tmp_path / "root"
    nested = root / "project" / "docs"
    nested.mkdir(parents=True)
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return subprocess.CompletedProcess(command, 1, "", "")

    monkeypatch.setattr(
        search_service, "safe_path", lambda *_: (root, nested, "project/docs")
    )
    monkeypatch.setattr(search_service, "_rg_available", lambda: True)
    monkeypatch.setattr(search_service, "_RG_PATH", "rg")
    monkeypatch.setattr(subprocess, "run", fake_run)

    search_service.search_content("needle", "root", "project/docs")

    assert seen["command"][-1:] == [str(nested)]


def test_search_content_uses_ancestor_project_cache_once(tmp_path, monkeypatch):
    root = tmp_path / "root"
    project = root / "project"
    nested = project / "docs"
    nested.mkdir(parents=True)
    (project / ".clawmate").mkdir()
    source = nested / "guide.pdf"
    source.write_bytes(b"pdf")
    cache_roots = []

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", "")

    monkeypatch.setattr(
        search_service, "safe_path", lambda *_: (root, nested, "project/docs")
    )
    monkeypatch.setattr(search_service, "_rg_available", lambda: True)
    monkeypatch.setattr(search_service, "_RG_PATH", "rg")
    monkeypatch.setattr(search_service, "_extract_by_type", lambda _: "needle")
    monkeypatch.setattr(subprocess, "run", fake_run)
    original_extract = search_service.extract_text
    monkeypatch.setattr(
        search_service,
        "extract_text",
        lambda file_path, project_dir: cache_roots.append(project_dir)
        or original_extract(file_path, project_dir),
    )

    search_service.search_content("needle", "root", "project/docs")

    assert cache_roots == [project]
    assert list((project / ".clawmate" / "cache" / "text").glob("*.txt"))
    assert not (nested / ".clawmate").exists()
