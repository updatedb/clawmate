"""
Unit tests for service.py — safe_path, file operations.

Usage:
    cd /home/openclaw/webprojects/clawmate
    python -m pytest test/test_service.py -v
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dev"))

from service import safe_path, guess_category, _normalize_rel_path
from config import set_config_path


# Module-scoped fixture — one tmp dir for all tests, avoids config TTL cache issues
@pytest.fixture(scope="module")
def _mock_config():
    """Mock config to use a temp directory (shared across module tests)."""
    tmp = tempfile.mkdtemp()
    cfg_path = Path(tmp) / "config.json"
    cfg_data = {
        "roots": [
            {"id": "testroot", "label": "Test Root", "dir": tmp, "agent_id": "main"}
        ],
        "defaultRootId": "testroot",
    }
    cfg_path.write_text(json.dumps(cfg_data, ensure_ascii=False))
    set_config_path(str(cfg_path))
    yield {"root_id": "testroot", "tmp": Path(tmp)}
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


class TestNormalizeRelPath:
    def test_empty_path(self):
        assert _normalize_rel_path("") == ""
        assert _normalize_rel_path("  ") == ""

    def test_simple_relative(self):
        assert _normalize_rel_path("file.txt") == "file.txt"
        assert _normalize_rel_path("dir/file.txt") == "dir/file.txt"

    def test_rejects_leading_slash_as_absolute(self):
        """Paths starting with / are treated as absolute → rejected."""
        with pytest.raises(ValueError, match="Absolute"):
            _normalize_rel_path("/file.txt")

    def test_rejects_backslash(self):
        with pytest.raises(ValueError, match="Backslash"):
            _normalize_rel_path("dir\\file.txt")

    def test_rejects_parent_traversal(self):
        with pytest.raises(ValueError, match="Invalid path segment"):
            _normalize_rel_path("../etc/passwd")
        with pytest.raises(ValueError, match="Invalid path segment"):
            _normalize_rel_path("dir/../../etc/passwd")

    def test_rejects_current_dir_dot(self):
        with pytest.raises(ValueError, match="Invalid path segment"):
            _normalize_rel_path("./file.txt")


class TestSafePath:
    def test_resolves_valid_path(self, _mock_config):
        test_file = _mock_config["tmp"] / "hello.txt"
        test_file.write_text("world")

        root_path, target, safe_rel = safe_path(_mock_config["root_id"], "hello.txt")
        assert target.exists()
        assert safe_rel == "hello.txt"
        assert target.name == "hello.txt"

    def test_resolves_nested_path(self, _mock_config):
        sub = _mock_config["tmp"] / "subdir"
        sub.mkdir(exist_ok=True)
        (sub / "nested.txt").write_text("data")

        root_path, target, safe_rel = safe_path(_mock_config["root_id"], "subdir/nested.txt")
        assert target.exists()
        assert safe_rel == "subdir/nested.txt"

    def test_rejects_traversal(self, _mock_config):
        with pytest.raises((PermissionError, ValueError)):
            safe_path(_mock_config["root_id"], "../etc/passwd")

    def test_unknown_root_raises(self, _mock_config):
        with pytest.raises((PermissionError, FileNotFoundError)):
            safe_path("nonexistent_root", "file.txt")

    def test_missing_root_id_raises(self, _mock_config):
        with pytest.raises(PermissionError):
            safe_path("", "file.txt")


class TestGuessCategory:
    @pytest.fixture
    def tmpdir(self):
        """Temp dir fixture (function scope — cheap to create)."""
        d = tempfile.mkdtemp()
        yield Path(d)
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    def test_text_file(self, tmpdir):
        path = tmpdir / "readme.md"
        path.write_text("# Hello")
        assert guess_category(path) == "text"

    def test_python_file(self, tmpdir):
        path = tmpdir / "script.py"
        path.write_text("print('hello')")
        assert guess_category(path) == "text"

    def test_json_file(self, tmpdir):
        path = tmpdir / "data.json"
        path.write_text('{"ok": true}')
        assert guess_category(path) == "text"

    def test_binary_file_sniffed(self, tmpdir):
        path = tmpdir / "binary.bin"
        path.write_bytes(b"\x00\x01\x02\x03")
        assert guess_category(path) == "other"

    def test_directory(self, tmpdir):
        sub = tmpdir / "adir"
        sub.mkdir()
        assert guess_category(sub) == "dir"

    def test_extensionless_text(self, tmpdir):
        path = tmpdir / "noext"
        path.write_text("plain text content here")
        assert guess_category(path) == "text"
