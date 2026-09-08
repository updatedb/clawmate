"""Unit tests for project_routes overview/recommendation aggregation."""

from __future__ import annotations

import json
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dev"))

from project_routes import (
    _count_clawlist_todo,
    _count_review,
    _recommendations_for,
    _read_project_json,
)


def _mk_project(tmp_path: Path, **kw) -> Path:
    p = tmp_path / "proj"
    (p / ".clawmate").mkdir(parents=True)
    if kw.get("clawlist"):
        (p / "CLAWLIST.md").write_text(kw["clawlist"], encoding="utf-8")
    if kw.get("feedback"):
        (p / ".clawmate" / "feedback.json").write_text(
            json.dumps(kw["feedback"], ensure_ascii=False), encoding="utf-8")
    if kw.get("project_json") is not None:
        (p / ".clawmate" / "project.json").write_text(
            json.dumps(kw["project_json"], ensure_ascii=False), encoding="utf-8")
    if kw.get("changelog"):
        (p / "CHANGELOG.md").write_text("# Changelog", encoding="utf-8")
    if kw.get("meeting_dir"):
        (p / "meeting").mkdir()
    return p


def test_clawlist_todo_counts_unchecked(tmp_path):
    p = _mk_project(tmp_path, clawlist="# LIST\n- [x] done\n- [ ] todo A\n- [ ] todo B\n")
    total, items = _count_clawlist_todo(p)
    assert total == 2
    assert "todo A" in items and "todo B" in items


def test_clawlist_todo_missing(tmp_path):
    p = _mk_project(tmp_path)
    assert _count_clawlist_todo(p) == (0, [])


def test_review_counts_by_status(tmp_path):
    fb = {"items": [
        {"id": "1", "status": "pending_review"},
        {"id": "2", "status": "approved"},
        {"id": "3", "status": "executed"},
        {"id": "4", "status": "pending"},
        {"id": "5", "status": "done"},
    ]}
    p = _mk_project(tmp_path, feedback=fb)
    c = _count_review(p)
    assert c["pending_review"] == 2  # pending_review + legacy pending
    assert c["approved"] == 1
    assert c["executed"] == 2  # executed + legacy done


def test_project_json_type_and_custom_recommendations(tmp_path):
    p = _mk_project(tmp_path, project_json={"type": "product", "recommendations": [
        {"label": "自定义: 更新发布", "kind": "release"},
    ]})
    cfg = _read_project_json(p)
    assert cfg["type"] == "product"
    recs = _recommendations_for(p)
    labels = [r["label"] for r in recs]
    assert "自定义: 更新发布" in labels  # custom takes precedence
    assert "更新 CHANGELOG" in labels    # product archetype rule


def test_meeting_archetype_recommends_meeting_actions(tmp_path):
    p = _mk_project(tmp_path, meeting_dir=True, project_json={"type": "meeting"})
    recs = _recommendations_for(p)
    labels = [r["label"] for r in recs]
    assert any("会议" in lab for lab in labels)


def test_commit_metadata_is_compatible_and_bounded(tmp_path):
    from project_routes import update_project_after_commit
    p = _mk_project(tmp_path, clawlist="- [ ] 跟进需求\n", project_json={"type": "meeting", "legacy": True})
    result = update_project_after_commit(p, "更新会议纪要", "notes.md")
    saved = _read_project_json(p)
    assert 30 <= len(result["status_summary"]) <= 50
    assert saved["legacy"] is True
    assert saved["status_summary"] == result["status_summary"]
    assert len(saved["recommended_tasks"]) <= 5
    assert {item["id"] for item in saved["recommended_tasks"]} >= {"commit_version", "maintain_project_docs", "update_meeting_info"}


def test_clawlist_completion_requires_one_exact_unchecked_match(tmp_path):
    from project_routes import _mark_clawlist_task_done
    p = _mk_project(tmp_path, clawlist="- [ ] 唯一任务\n- [ ] 重复任务\n- [ ] 重复任务\n")
    assert _mark_clawlist_task_done(p, "唯一任务") is True
    assert "- [x] 唯一任务" in (p / "CLAWLIST.md").read_text(encoding="utf-8")
    with pytest.raises(LookupError):
        _mark_clawlist_task_done(p, "重复任务")


def test_main_project_panel_is_switchable_and_auto_opens_once_per_session_project():

    root = Path(__file__).resolve().parents[1]
    html = (root / "dev" / "static" / "index.html").read_text(encoding="utf-8")
    js = (root / "dev" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    css = (root / "dev" / "static" / "css" / "style.css").read_text(encoding="utf-8")
    assert 'id="projectPanel" class="project-panel hidden"' in html
    assert '<aside id="projectPanel"' in html
    assert 'id="btnCloseProjectPanel"' in html
    assert "project-panel-overlay" not in js
    assert "clawmate.projectPanel.seen:" in js
    assert "sessionStorage.getItem(key)" in js
    assert "if (_projectPanelContext === key) return;" in js
    assert "_setProjectPanelOpen(firstVisit);" in js
    assert 'if (_isProjectPanelOpen()) _setProjectPanelOpen(false);' in js
    assert "#projectPanel { grid-column: 3; min-width: 0; }" in css
    assert "_setProjectPanelOpen(!_isProjectPanelOpen())" in js
    assert "现在要处理" in js
    assert "正在执行" in js
    assert "CLAWLIST" in js
    assert 'data-project-review>待评审 (' not in js
    assert "project_tasks" in js
    assert "data-project-action" in js
    assert "/clawlist/complete" in js
    assert "/tasks/" in js
    assert "/runs/" in js
    assert "_scheduleProjectRunPolling" in js
    assert "_openProjectFeedback" in js
    assert "#previewFilterBar button" in js

def test_panel_actions_have_explicit_sources_and_hide_zero_counts(tmp_path):
    from project_routes import _clawlist_tasks, _project_panel_actions
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    p = _mk_project(tmp_path, clawlist="- [x] 已完成需求\n- [ ] 待办需求\n", feedback={"items": [
        {"status": "pending_review"}, {"status": "approved"},
    ]}, project_json={"project_panel": {"maintenance_required": True, "meetings": [{
        "starts_at": (now + timedelta(days=3)).isoformat(), "ends_at": (now - timedelta(days=2)).isoformat(),
    }]}})
    actions = _project_panel_actions(p, _count_review(p), _read_project_json(p), now=now)
    assert {action["id"] for action in actions} >= {"review_feedback", "implement_feedback", "maintain_project_docs", "update_meeting_agenda", "update_meeting_conclusion"}
    assert all(action["source"] for action in actions)
    assert _clawlist_tasks(p) == [{"task": "已完成需求", "completed": True}, {"task": "待办需求", "completed": False}]
    assert _project_panel_actions(p, {"pending_review": 0, "approved": 0}, {}, now=now) == []


def test_project_runs_api_is_bounded_and_excludes_prompt(tmp_path, monkeypatch):
    import project_routes
    p = _mk_project(tmp_path)
    monkeypatch.setattr(project_routes, "_project_target", lambda root, project: p)
    import task_executor
    monkeypatch.setattr(task_executor, "refresh_project_runs", lambda target: [{
        "task_run_id": "r1", "status": "running", "backend_actual": "codex",
        "task": {"id": "docs", "label": "维护文档"}, "prompt": "must never leak",
    }] * 12)
    response = asyncio.run(project_routes.project_task_runs("root", "project"))
    body = json.loads(response.body)
    assert len(body["recent"]) == 10
    assert body["active"][0]["task_run_id"] == "r1"
    assert "prompt" not in json.dumps(body)


def test_project_panel_frontend_uses_run_contract_without_full_poll_redraw():
    root = Path(__file__).resolve().parents[1]
    js = (root / "dev" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    css = (root / "dev" / "static" / "css" / "style.css").read_text(encoding="utf-8")

    assert "data-project-runs" in js
    assert "renderProjectRuns()" in js
    assert "nextRunsSignature !== _projectRunsSignature" in js
    assert "rawStatus === 'waiting_input' ? 'needs_attention'" in js
    assert "后端 " in js and "启动 " in js and "已用 " in js
    assert "data-project-retry" in js
    assert "data-project-task" in js
    assert "data-project-cancel" not in js
    assert ".project-run-needs_attention" in css
