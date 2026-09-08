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


def test_changed_content_and_position_are_passed_to_executor_without_blocking_task(review_project):
    created = store.create_items("root", "project", "project/note.md", [{"text": "selected text", "note": "x"}])
    item_id = created[0]["id"]
    store.review_items("root", "project", [item_id], "approved")
    review_project.write_text("before\nreplaced\nafter\n", encoding="utf-8")
    task = store.create_execution_task("root", "project", [item_id])
    assert task["status"] == "in_progress"
    assert task["operations"][0]["content"] == "selected text"
    assert task["operations"][0]["content_hash"].startswith("sha256:")
    audit_path = review_project.parent / ".clawmate" / "feedback.audit.jsonl"
    assert "execution_task_created" in audit_path.read_text(encoding="utf-8")


def test_atomic_task_locks_items_and_persists_per_feedback_outcomes(review_project):
    created = store.create_items("root", "project", "project/note.md", [
        {"text": "selected text", "note": "first"},
        {"text": "before", "note": "second"},
    ])
    ids = [item["id"] for item in created]
    store.review_items("root", "project", ids, "approved")
    task = store.create_execution_task("root", "project", ids)
    with pytest.raises(ValueError, match="reserved"):
        store.create_execution_task("root", "project", [ids[0]])
    store.record_execution_result("root", "project", task["id"], success=False, summary="task summary",
        outcomes=[
            {"feedback_id": ids[0], "status": "executed", "impact": "line 2", "result": "updated"},
            {"feedback_id": ids[1], "status": "needs_attention", "failure_reason": "conflict", "failure_stage": "merge"},
        ])
    items, _ = store.list_items("root", "project")
    by_id = {item["id"]: item for item in items}
    assert by_id[ids[0]]["result"] == "updated"
    assert by_id[ids[1]]["status"] == "needs_attention"
    assert by_id[ids[1]]["failure_stage"] == "merge"


def test_list_items_matches_equivalent_relative_paths(review_project):
    store.create_items("root", "project", "project/note.md", [{"text": "selected text", "note": "x"}])

    # A share link can store a root-relative path while preview carries a
    # project-prefixed path (or vice versa).
    assert len(store.list_items("root", "project", file="project/note.md")[0]) == 1
    assert len(store.list_items("root", "project", file="note.md")[0]) == 1


def test_create_items_normalizes_legacy_location_to_position(review_project):
    created = store.create_items("root", "project", "project/note.md", [{
        "text": "selected text", "note": "keep locator", "location": "Line 2",
    }])

    assert created[0]["position"] == "Line 2"

    stored = review_project.parent / ".clawmate" / "feedback.json"
    data = store._read_feedback(stored)
    data["items"].append({"id": "FD-legacy", "file": "project/note.md", "location": "Line 3"})
    stored.write_text(__import__("json").dumps(data), encoding="utf-8")
    listed, _ = store.list_items("root", "project")
    assert next(item for item in listed if item["id"] == "FD-legacy")["position"] == "Line 3"


def test_canonical_write_migrates_legacy_audit_and_keeps_full_content(review_project):
    marker = review_project.parent / ".clawmate"
    legacy = {
        "last_id": 2,
        "items": [],
        "tasks": [{"id": "RV-legacy", "operations": []}],
        "audit": [{"id": "AU-old", "event": "legacy", "at": "2026-01-01 00:00:00", "item_ids": []}],
    }
    (marker / "feedback.json").write_text(__import__("json").dumps(legacy), encoding="utf-8")
    content = "x" * 1200
    created = store.create_items("root", "project", "project/note.md", [{
        "text": content, "note": "keep everything", "position": "Line 2-2",
        "start_line": 2, "context_before": "must not persist",
    }])
    saved = __import__("json").loads((marker / "feedback.json").read_text(encoding="utf-8"))
    item = created[0]
    assert item["content"] == content
    assert item["content_hash"].startswith("sha256:")
    assert "audit" not in saved
    assert saved["tasks"] == legacy["tasks"]
    assert not {"anchor", "start_line", "end_line", "file_version", "context_before", "context_after"} & set(saved["items"][0])
    records = [__import__("json").loads(line) for line in (marker / "feedback.audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {record["id"] for record in records} >= {"AU-old"}
    assert any(record["event"] == "feedback_created" for record in records)


def test_bad_audit_line_does_not_block_status_or_task_audit(review_project):
    created = store.create_items("root", "project", "project/note.md", [{"text": "selected text", "note": "x"}])
    audit_path = review_project.parent / ".clawmate" / "feedback.audit.jsonl"
    with audit_path.open("a", encoding="utf-8") as f:
        f.write("not-json\n")
    store.update_item("root", "project", created[0]["id"], "approved")
    assert '"event":"status_approved"' in audit_path.read_text(encoding="utf-8")


def test_wake_review_task_runs_agent_wake_off_thread(review_project, monkeypatch):
    """wake_review_task must not hold the /review/execute HTTP response open on the
    synchronous gateway POST.  It validates the task, then spawns the agent wake on
    a background thread so the items (already reserved as in_progress) re-render
    immediately."""
    import threading
    import task_runner

    created = store.create_items("root", "project", "project/note.md", [{"text": "selected text", "note": "x"}])
    item_id = created[0]["id"]
    store.review_items("root", "project", [item_id], "approved")
    task = store.create_execution_task("root", "project", [item_id])
    assert task["status"] == "in_progress"

    state = {"called": threading.Event(), "thread_id": None}

    def fake_wake(root_id, **kwargs):
        state["thread_id"] = threading.current_thread().ident
        state["called"].set()

    monkeypatch.setattr(task_runner, "_wake_agent_for_root", fake_wake)
    caller_thread = threading.current_thread().ident
    task_runner.wake_review_task("root", "project", task["id"])

    # The wake runs on a different thread (never synchronously in the caller),
    # and it does eventually invoke the underlying agent wake.
    assert state["thread_id"] != caller_thread
    assert state["called"].wait(timeout=3)


def test_wake_review_task_requires_in_progress(review_project):
    import task_runner

    created = store.create_items("root", "project", "project/note.md", [{"text": "selected text", "note": "x"}])
    item_id = created[0]["id"]
    store.review_items("root", "project", [item_id], "approved")
    plan = store.create_execution_plan("root", "project", [item_id])
    store.confirm_execution_plan("root", "project", plan["id"])
    # A confirmed (but not yet reserved in_progress) task must be rejected; only
    # an in_progress reservation may wake an agent.
    with pytest.raises(ValueError, match="not executing"):
        task_runner.wake_review_task("root", "project", plan["id"])
