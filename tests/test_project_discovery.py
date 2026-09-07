"""Deterministic coverage for safe local recommendation discovery."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dev"))

from project_routes import discover_project_tasks


def test_discover_reads_named_docs_and_maps_only_project_scripts(tmp_path: Path):
    project = tmp_path / "meeting"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    (project / "AGENTS.md").write_text("## Meeting-update trigger\n更新会议信息\n", encoding="utf-8")
    (project / "WORKFLOW.md").write_text("- [ ] 更新会议进展\n", encoding="utf-8")
    (scripts / "meeting_pipeline.py").write_text("# fixture", encoding="utf-8")
    result = discover_project_tasks(project)
    mapped = [task for task in result["recommended_tasks"] if "会议" in task["label"]]
    assert mapped and all(task["origin_file"] in {"AGENTS.md", "WORKFLOW.md"} for task in mapped)
    assert any(task["command"] == "python scripts/meeting_pipeline.py --json" for task in mapped)
    saved = json.loads((project / ".clawmate" / "project.json").read_text(encoding="utf-8"))
    assert saved["markdown_sources"] == ["AGENTS.md", "WORKFLOW.md"]


def test_discover_never_invents_command_and_preserves_manual_task(tmp_path: Path):
    project = tmp_path / "plain"
    project.mkdir()
    (project / "README.md").write_text("- [ ] 更新状态报告\n", encoding="utf-8")
    (project / ".clawmate").mkdir()
    (project / ".clawmate" / "project.json").write_text(json.dumps({"recommended_tasks": [{"id": "manual", "label": "手工任务", "running": True}]}), encoding="utf-8")
    result = discover_project_tasks(project)
    assert result["recommended_tasks"][0]["id"] == "manual"
    learned = next(task for task in result["recommended_tasks"] if task.get("source") == "discover")
    assert learned["execution"] == "needs_agent"
    assert learned["command"] is None and learned["script_path"] is None
