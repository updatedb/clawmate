import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))

import store  # noqa: E402


class _Config:
    def __init__(self, root: Path):
        self.root = root
        self.feedback = type("Feedback", (), {"cleanup_done_after_days": 0})()

    def root_dir(self, root_id: str) -> Path:
        if root_id != "root":
            raise ValueError("unknown root")
        return self.root


@pytest.fixture
def review_project(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / ".clawmate").mkdir()
    document = project / "note.md"
    document.write_text("before\nselected text\nafter\n", encoding="utf-8")
    monkeypatch.setattr(store, "load_config", lambda: _Config(tmp_path))
    return document


def test_review_requires_approval_and_confirmed_plan(review_project):
    created = store.create_items("root", "project", "project/note.md", [{
        "text": "selected text", "note": "make clearer", "action": "modify",
        "start_line": 2, "end_line": 2,
    }])
    item_id = created[0]["id"]
    assert created[0]["status"] == "pending_review"
    with pytest.raises(ValueError, match="not approved"):
        store.create_execution_plan("root", "project", [item_id])

    store.review_items("root", "project", [item_id], "approved")
    plan = store.create_execution_plan("root", "project", [item_id])
    assert plan["status"] == "planned"
    assert plan["operations"][0]["file"] == "project/note.md"
    confirmed = store.confirm_execution_plan("root", "project", plan["id"])
    assert confirmed["status"] == "confirmed"
    started = store.mark_execution_started("root", "project", plan["id"])
    assert started["status"] == "in_progress"


def test_stale_anchor_blocks_plan_and_is_audited(review_project):
    created = store.create_items("root", "project", "project/note.md", [{"text": "selected text", "note": "x"}])
    item_id = created[0]["id"]
    store.review_items("root", "project", [item_id], "approved")
    review_project.write_text("before\nreplaced\nafter\n", encoding="utf-8")
    with pytest.raises(ValueError, match="anchor stale"):
        store.create_execution_plan("root", "project", [item_id])
    path = review_project.parent / ".clawmate" / "feedback.json"
    assert "anchor_invalid" in path.read_text(encoding="utf-8")


def test_list_items_matches_equivalent_relative_paths(review_project):
    store.create_items("root", "project", "project/note.md", [{"text": "selected text", "note": "x"}])

    # A share link can store a root-relative path while preview carries a
    # project-prefixed path (or vice versa).
    assert len(store.list_items("root", "project", file="project/note.md")[0]) == 1
    assert len(store.list_items("root", "project", file="note.md")[0]) == 1
