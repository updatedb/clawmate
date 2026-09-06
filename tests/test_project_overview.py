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
