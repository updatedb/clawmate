"""
Unit tests for validators.py — format validation (JSON, CSS, HTML).

Usage:
    cd /home/openclaw/webprojects/clawmate
    python -m pytest test/test_validators.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dev"))

from validators import validate_json, validate_css, validate_html


class TestValidateJson:
    def test_valid_json(self):
        ok, msg = validate_json('{"key": "value"}')
        assert ok is True
        assert msg == ""

    def test_valid_json_array(self):
        ok, msg = validate_json('[1, 2, 3]')
        assert ok is True

    def test_invalid_json_trailing_comma(self):
        ok, msg = validate_json('{"key": "value",}')
        assert ok is False
        assert "JSON" in msg

    def test_invalid_json_unquoted_key(self):
        ok, msg = validate_json('{key: "value"}')
        assert ok is False

    def test_empty_string(self):
        ok, msg = validate_json("")
        assert ok is False


class TestValidateCss:
    def test_valid_css(self):
        ok, msg = validate_css("body { color: red; }")
        assert ok is True

    def test_valid_css_multiple_rules(self):
        ok, msg = validate_css("""
            .header { font-size: 16px; }
            .footer { margin-top: 10px; }
        """)
        assert ok is True

    def test_unbalanced_braces_missing_close(self):
        ok, msg = validate_css("body { color: red;")
        assert ok is False
        assert "花括号" in msg

    def test_unbalanced_braces_extra_close(self):
        ok, msg = validate_css("body { color: red; }}")
        assert ok is False
        # tinycss2 reports parse error, brace balance check also catches this
        assert "语法" in msg or "花括号" in msg

    def test_empty_css(self):
        ok, msg = validate_css("")
        assert ok is True


class TestValidateHtml:
    def test_valid_html_fragment(self):
        ok, msg = validate_html("<div>hello</div>")
        assert ok is True

    def test_valid_html_with_attrs(self):
        ok, msg = validate_html('<a href="/link">click</a>')
        assert ok is True

    def test_self_closing_tags(self):
        ok, msg = validate_html('<br><img src="x.jpg"><hr>')
        assert ok is True

    def test_missing_close_tag(self):
        ok, msg = validate_html("<div>hello")
        assert ok is False
        assert "div" in msg or "标签" in msg

    def test_extra_close_tag(self):
        ok, msg = validate_html("<div>hello</div></span>")
        assert ok is False

    def test_nested_tags_balanced(self):
        ok, msg = validate_html("<div><p>text</p></div>")
        assert ok is True

    def test_empty_string(self):
        ok, msg = validate_html("")
        # Empty string should be valid (no mismatched tags)
        assert ok is True
