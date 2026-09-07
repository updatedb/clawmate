"""Deterministic coverage for safe local recommendation discovery."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dev"))

import project_routes
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


def test_discover_replaces_legacy_discover_records_and_is_idempotent(tmp_path: Path):
    project = tmp_path / "polluted-meeting"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    (project / "AGENTS.md").write_text("## Meeting-update trigger\n更新会议进展\n", encoding="utf-8")
    (project / "WORKFLOW.md").write_text("- [ ] 更新会议信息\n", encoding="utf-8")
    (scripts / "meeting_pipeline.py").write_text("# fixture", encoding="utf-8")
    (project / ".clawmate").mkdir()
    (project / ".clawmate" / "project.json").write_text(
        json.dumps({"recommended_tasks": [
            {"id": "learned-agents-md-12", "label": "维护者：路姐", "source": "discover"},
            {"id": "learned-workflow-md-4", "label": "关联文件：会议记录", "source": "discover"},
            {"id": "manual-review", "label": "手工推荐", "source": "manual", "running": True},
        ]}),
        encoding="utf-8",
    )

    first = discover_project_tasks(project)["recommended_tasks"]
    second = discover_project_tasks(project)["recommended_tasks"]

    assert first == second
    assert first[0] == {"id": "manual-review", "label": "手工推荐", "source": "manual", "running": True}
    discovered = [task for task in first if task.get("source") == "discover"]
    assert {task["id"] for task in discovered} == {"meet-update-progress", "meet-update-info"}
    assert all(not task["id"].startswith("learned-") for task in discovered)
    assert all(task["execution"] == "script" for task in discovered)
    assert all(task["command"] == "python scripts/meeting_pipeline.py --json" for task in discovered)


def test_discover_semantically_extracts_tasks_and_ignores_document_prose(tmp_path: Path):
    project = tmp_path / "3gpp"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    (project / "AGENTS.md").write_text(
        "# 3GPP 项目说明\n"
        "维护者：路姐\n"
        "关联文件：[会议记录](notes.md)\n"
        "本文档是项目协作说明，不是待办。\n"
        "## Meeting-update trigger\n"
        "维护项目文档：仅记录已确认事实\n"
        "普通段落：会议状态由人工确认。\n",
        encoding="utf-8",
    )
    (project / "WORKFLOW.md").write_text(
        "# 工作流说明\n"
        "## 一、当前状态仪表盘\n"
        "- [ ] A1 增量资料整理：确认输入后归档\n"
        "- [ ] MAASTRICHT-POST follow-up\n"
        "- 说明：本段仅供阅读\n",
        encoding="utf-8",
    )
    (scripts / "meeting_pipeline.py").write_text("# fixture", encoding="utf-8")

    tasks = [task for task in discover_project_tasks(project)["recommended_tasks"] if task.get("source") == "discover"]
    by_id = {task["id"]: task for task in tasks}
    assert by_id["meet-update-info"]["label"] == "更新会议信息"
    assert by_id["meet-update-info"]["execution"] == "script"
    assert by_id["meet-update-info"]["command"] == "python scripts/meeting_pipeline.py --json"
    assert by_id["maastricht-post"]["label"] == "处理 Maastricht 会后事项"
    assert by_id["maastricht-post"]["execution"] == "script"
    assert by_id["maintain-docs"]["label"] == "维护项目文档"
    assert by_id["maintain-docs"]["execution"] == "needs_agent"
    assert any(task["label"] == "处理 A1 增量资料整理" for task in tasks)
    assert all(len(task["label"]) <= 40 for task in tasks)
    joined = " ".join(task["label"] for task in tasks)
    assert "维护者" not in joined and "关联文件" not in joined and "本文档是" not in joined
    assert all(not task["id"].startswith("learned-") for task in tasks)


def test_discovery_sources_and_keywords_can_be_overridden(tmp_path: Path):
    project = tmp_path / "configured"
    project.mkdir()
    (project / "CUSTOM.md").write_text("- 执行发布检查\n", encoding="utf-8")
    (project / "README.md").write_text("- [ ] 更新状态报告\n", encoding="utf-8")
    (project / ".clawmate").mkdir()
    (project / ".clawmate" / "project.json").write_text(
        json.dumps({"task_discovery": {"sources": ["CUSTOM.md"], "keywords": ["发布"]}}), encoding="utf-8"
    )
    result = discover_project_tasks(project)
    tasks = [task for task in result["recommended_tasks"] if task.get("source") == "discover"]
    assert result["markdown_sources"] == ["CUSTOM.md"]
    assert [task["label"] for task in tasks] == ["执行发布检查"]
    assert tasks[0]["execution"] == "needs_agent"


def test_llm_discovery_validates_and_replaces_own_snapshot(tmp_path: Path, monkeypatch):
    project = tmp_path / "3gpp"
    (project / "scripts").mkdir(parents=True)
    (project / "scripts" / "meeting_pipeline.py").write_text("# fixture", encoding="utf-8")
    (project / "AGENTS.md").write_text("3gpp meeting workflow", encoding="utf-8")
    (project / "WORKFLOW.md").write_text("更新会议资料", encoding="utf-8")
    (project / ".clawmate").mkdir()
    (project / ".clawmate" / "project.json").write_text(json.dumps({
        "type": "meeting", "task_discovery": {"engine": "llm"},
        "recommended_tasks": [{"id": "manual", "label": "手工任务", "source": "manual"}, {"id": "old", "label": "旧发现", "source": "discover"}],
    }), encoding="utf-8")
    monkeypatch.setattr(project_routes, "_llm_extract", lambda *args: [
        {"label": "更新会议信息", "kind": "update", "priority": "high", "reason": "会议资料变化", "script": "meeting_pipeline.py"},
        {"label": "分析会议文档", "kind": "analyze", "priority": "normal", "reason": "整理议题"},
        {"label": "收集会议结论", "kind": "collect", "priority": "normal", "reason": "行动项"},
    ])
    tasks = discover_project_tasks(project)["recommended_tasks"]
    assert tasks[0]["id"] == "manual"
    learned = [item for item in tasks if item.get("source") == "discover-llm"]
    assert [item["label"] for item in learned] == ["更新会议信息", "分析会议文档", "收集会议结论"]
    assert learned[0]["command"] == "python scripts/meeting_pipeline.py --json"
    assert all(item["kind"] in {"update", "analyze", "collect", "followup"} for item in learned)
    assert all(item["id"] != "old" for item in tasks)


def test_llm_invalid_command_or_response_falls_back_to_rules(tmp_path: Path, monkeypatch):
    project = tmp_path / "meeting"
    project.mkdir()
    (project / "WORKFLOW.md").write_text("- [ ] 更新会议信息\n", encoding="utf-8")
    (project / ".clawmate").mkdir()
    (project / ".clawmate" / "project.json").write_text(json.dumps({"task_discovery": {"engine": "llm"}}), encoding="utf-8")
    monkeypatch.setattr(project_routes, "_llm_extract", lambda *args: [
        {"label": "更新会议信息", "kind": "update", "priority": "high", "command": "rm -rf /", "script": "../../evil.py"}
    ])
    tasks = discover_project_tasks(project)["recommended_tasks"]
    assert any(item["source"] == "discover" for item in tasks)
    assert all(item.get("command") != "rm -rf /" for item in tasks)


def test_llm_timeout_falls_back_without_error(tmp_path: Path, monkeypatch):
    project = tmp_path / "timeout"
    project.mkdir()
    (project / "WORKFLOW.md").write_text("- [ ] 更新状态报告\n", encoding="utf-8")
    (project / ".clawmate").mkdir()
    (project / ".clawmate" / "project.json").write_text(json.dumps({"task_discovery": {"engine": "llm"}}), encoding="utf-8")
    def timeout(*_args):
        raise TimeoutError("mock timeout")
    monkeypatch.setattr(project_routes, "_llm_extract", timeout)
    tasks = discover_project_tasks(project)["recommended_tasks"]
    assert any(item["source"] == "discover" for item in tasks)


def test_large_document_change_is_detected(tmp_path: Path):
    project = tmp_path / "changed"
    project.mkdir()
    (project / "AGENTS.md").write_text("更新状态", encoding="utf-8")
    (project / ".clawmate").mkdir()
    (project / ".clawmate" / "project.json").write_text(json.dumps({"task_discovery": {"change_threshold": 10}}), encoding="utf-8")
    discover_project_tasks(project)
    cfg = project_routes._read_project_json(project)
    assert not project_routes._should_auto_discover(project, cfg)
    (project / "AGENTS.md").write_text("更新状态" + "新增内容" * 10, encoding="utf-8")
    assert project_routes._should_auto_discover(project, cfg)
