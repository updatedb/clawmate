"""
Unit tests for store.py — FeedbackStore 核心 CRUD + 并发安全。

Usage:
    cd /home/openclaw/webprojects/clawmate
    python -m pytest test/test_store.py -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dev"))

from store import (
    _read_feedback,
    list_items,
    create_items,
    update_item,
    batch_update_items,
    project_abbr,
)
from config import set_config_path, clear_config_cache


# Module-scoped fixture avoids config TTL cache issues across tests
@pytest.fixture(scope="module")
def _mock_config():
    """Mock config to use a temp directory (shared across module tests)."""
    tmp = tempfile.mkdtemp()
    cfg_path = Path(tmp) / "config.json"
    cfg_data = {
        "roots": [
            {"id": "testroot", "label": "Test", "dir": tmp, "agent_id": "main"}
        ],
        "defaultRootId": "testroot",
    }
    cfg_path.write_text(json.dumps(cfg_data, ensure_ascii=False))
    clear_config_cache()  # 清除旧缓存
    set_config_path(str(cfg_path))

    # Create the test project dir with .clawmate/ marker
    proj_dir = Path(tmp) / "testproj"
    proj_dir.mkdir(exist_ok=True)
    (proj_dir / ".clawmate").mkdir(exist_ok=True)

    yield {"root_id": "testroot", "project": "testproj", "tmp": tmp, "proj_dir": proj_dir}

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


class TestReadFeedback:
    def test_missing_file_returns_empty(self, _mock_config):
        path = Path(_mock_config["tmp"]) / "nonexistent.json"
        result = _read_feedback(path)
        assert result.get("items") == []
        assert isinstance(result.get("tasks"), list)
        assert isinstance(result.get("audit"), list)

    def test_reads_valid_json(self, _mock_config):
        path = Path(_mock_config["tmp"]) / "test.json"
        path.write_text(json.dumps({"items": [{"id": "FD-TP-0001", "status": "pending"}]}))
        result = _read_feedback(path)
        assert len(result["items"]) == 1
        assert result["items"][0]["id"] == "FD-TP-0001"

    def test_corrupt_json_returns_empty(self, _mock_config):
        path = Path(_mock_config["tmp"]) / "corrupt.json"
        path.write_text("this is not valid {json")
        result = _read_feedback(path)
        assert result.get("items") == []
        assert isinstance(result.get("tasks"), list)
        assert isinstance(result.get("audit"), list)


class TestProjectAbbr:
    def test_empty_project(self):
        assert project_abbr("") == "RT"

    def test_hyphenated_project(self):
        abbr = project_abbr("hello-world")
        assert abbr == "HW"

    def test_underscore_project(self):
        abbr = project_abbr("test_project")
        assert abbr == "TP"

    def test_single_word(self):
        abbr = project_abbr("example")
        assert len(abbr) == 2
        assert abbr.isalpha()


class TestCreateItems:
    def test_creates_single_item(self, _mock_config):
        items = create_items(
            _mock_config["root_id"],
            _mock_config["project"],
            "docs/readme.md",
            [{"text": "hello world", "note": "fix this"}],
        )
        assert len(items) == 1
        assert items[0]["status"] == "pending_review"
        assert items[0]["file"] == "docs/readme.md"
        assert items[0]["content"] == "hello world"
        assert items[0]["note"] == "fix this"
        assert items[0]["id"].startswith("FD-")

    def test_skips_duplicate(self, _mock_config):
        sel = [{"text": "duplicate text", "note": "fix"}]
        first = create_items(_mock_config["root_id"], _mock_config["project"], "a.md", sel)
        second = create_items(_mock_config["root_id"], _mock_config["project"], "a.md", sel)
        assert len(first) == 1
        assert len(second) == 0  # Deduped

    def test_creates_multiple_selections(self, _mock_config):
        sels = [
            {"text": "first", "note": "note1"},
            {"text": "second", "note": "note2"},
        ]
        items = create_items(_mock_config["root_id"], _mock_config["project"], "b.md", sels)
        assert len(items) == 2

    def test_empty_text_allowed(self, _mock_config):
        """Empty content should still create an item (per v1.33 change)."""
        items = create_items(
            _mock_config["root_id"], _mock_config["project"],
            "c.md", [{"text": "", "note": "empty ok"}],
        )
        assert len(items) == 1


class TestListItems:
    def test_lists_all_items(self, _mock_config):
        create_items(_mock_config["root_id"], _mock_config["project"], "x.md",
                     [{"text": "t1"}, {"text": "t2"}])
        items, pending = list_items(_mock_config["root_id"], _mock_config["project"])
        assert len(items) >= 2
        assert pending >= 2

    def test_filter_by_status(self, _mock_config):
        items, pending = list_items(
            _mock_config["root_id"], _mock_config["project"], status="done"
        )
        assert all(i["status"] == "done" for i in items)

    def test_filter_by_file(self, _mock_config):
        create_items(_mock_config["root_id"], _mock_config["project"], "specific.md",
                     [{"text": "unique"}])
        items, _ = list_items(_mock_config["root_id"], _mock_config["project"], file="specific")
        assert all("specific" in i["file"] for i in items)

    def test_filter_by_since_today(self, _mock_config):
        items, _ = list_items(_mock_config["root_id"], _mock_config["project"], since="today")
        assert isinstance(items, list)


class TestUpdateItem:
    def test_updates_status(self, _mock_config):
        created = create_items(_mock_config["root_id"], _mock_config["project"], "u.md",
                               [{"text": "to update"}])
        item_id = created[0]["id"]
        updated = update_item(_mock_config["root_id"], _mock_config["project"],
                              item_id, "executed", result="fixed")
        assert updated["status"] == "executed"
        assert updated["result"] == "fixed"

    def test_raises_file_not_found_for_missing_feedback(self, _mock_config):
        """Non-existent project with no feedback.json raises FileNotFoundError."""
        with pytest.raises((FileNotFoundError, LookupError)):
            update_item(_mock_config["root_id"], "nonexistent_proj",
                        "FD-XX-9999", "done")

    def test_raises_value_error_for_invalid_status(self, _mock_config):
        created = create_items(_mock_config["root_id"], _mock_config["project"], "v.md",
                               [{"text": "x"}])
        with pytest.raises(ValueError):
            update_item(_mock_config["root_id"], _mock_config["project"],
                        created[0]["id"], "not_a_real_status")


class TestBatchUpdateItems:
    def test_batch_updates_multiple(self, _mock_config):
        created = create_items(_mock_config["root_id"], _mock_config["project"], "batch.md",
                               [{"text": "a"}, {"text": "b"}])
        ids = [c["id"] for c in created]
        result = batch_update_items(
            _mock_config["root_id"], _mock_config["project"],
            [{"id": ids[0], "status": "done"}, {"id": ids[1], "status": "failed", "result": "err"}],
        )
        assert len(result) == 2

    def test_skips_unknown_ids(self, _mock_config):
        result = batch_update_items(
            _mock_config["root_id"], _mock_config["project"],
            [{"id": "FD-XX-0000", "status": "done"}],
        )
        assert len(result) == 0


class TestConcurrentWriteSafety:
    def test_concurrent_creates_no_data_loss(self, _mock_config):
        """并发创建反馈条目时不应丢失数据。"""
        errors = []
        results = []

        def _create_batch(batch_id: int):
            try:
                sels = [{"text": f"concurrent-{batch_id}-{i}", "note": f"batch{batch_id}"}
                        for i in range(10)]
                r = create_items(_mock_config["root_id"], _mock_config["project"],
                                 f"concurrent.md", sels)
                results.extend(r)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_create_batch, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent writes: {errors}"
        assert len(results) == 50, f"Expected 50 items, got {len(results)}"

        # Verify persistence: all items should be readable
        items, _ = list_items(_mock_config["root_id"], _mock_config["project"])
        concurrent_items = [i for i in items if i["file"] == "concurrent.md"]
        assert len(concurrent_items) == 50
