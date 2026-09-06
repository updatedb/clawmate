"""Unit tests for project_routes overview/recommendation aggregation."""

from __future__ import annotations

import json
import sys
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
    assert ".project-panel { display: flex; flex-direction: column; overflow: hidden; position: fixed;" in css
    assert "_setProjectPanelOpen(!_isProjectPanelOpen())" in js
    assert "待评审 (" in js
    assert "/clawlist/complete" in js
    assert "/tasks/" in js
