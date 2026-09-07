import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))

import service  # noqa: E402
import store  # noqa: E402


class _Config:
    def __init__(self, root: Path):
        self.root = root
        self.feedback = type("Feedback", (), {"cleanup_done_after_days": 0})()

    def root_dir(self, root_id: str) -> Path:
        assert root_id == "root"
        return self.root


@pytest.fixture
def feedback_root(tmp_path, monkeypatch):
    for project in ("project", "other"):
        (tmp_path / project / ".clawmate").mkdir(parents=True)
    monkeypatch.setattr(service, "resolve_root", lambda root_id: tmp_path)
    monkeypatch.setattr(store, "load_config", lambda: _Config(tmp_path))
    return tmp_path


def _create(root, project, path, status="pending_review"):
    item = store.create_items("root", project, path, [{"text": path, "note": "remove me"}])[0]
    if status != "pending_review":
        store.update_item("root", project, item["id"], status)
    return item["id"]


def test_delete_file_releases_only_unexecuted_feedback_and_audits(feedback_root):
    target = feedback_root / "project" / "note.md"
    target.write_text("content", encoding="utf-8")
    pending = _create(feedback_root, "project", "project/note.md")
    executed = _create(feedback_root, "project", "note.md", "executed")
    other = _create(feedback_root, "other", "other/note.md")

    service.delete_file("root", "project/note.md")

    assert not target.exists()
    items, _ = store.list_items("root", "project")
    assert [item["id"] for item in items] == [executed]
    assert [item["id"] for item in store.list_items("root", "other")[0]] == [other]
    audit = (feedback_root / "project" / ".clawmate" / "feedback.audit.jsonl").read_text(encoding="utf-8")
    record = next(json.loads(line) for line in audit.splitlines() if '"file_deleted"' in line)
    assert set(record["item_ids"]) == {pending, executed}
    assert record["detail"]["file"] == "project/note.md"


def test_delete_directory_releases_each_nested_file_without_touching_other_paths(feedback_root):
    nested = feedback_root / "project" / "drafts"
    nested.mkdir()
    (nested / "one.md").write_text("one", encoding="utf-8")
    (nested / "two.md").write_text("two", encoding="utf-8")
    one = _create(feedback_root, "project", "project/drafts/one.md")
    two = _create(feedback_root, "project", "drafts/two.md")
    outside = _create(feedback_root, "project", "project/keep.md")

    service.delete_dir("root", "project/drafts")

    assert not nested.exists()
    assert [item["id"] for item in store.list_items("root", "project")[0]] == [outside]
    audit = (feedback_root / "project" / ".clawmate" / "feedback.audit.jsonl").read_text(encoding="utf-8")
    deleted = [json.loads(line) for line in audit.splitlines() if '"file_deleted"' in line]
    assert {item_id for record in deleted for item_id in record["item_ids"]} == {one, two}
