"""
Format validators for ClawMate save endpoint.

Validates JSON, CSS, and HTML content before writing to disk.
Prevents syntax errors from corrupting config files.
"""

from __future__ import annotations

import json
import re

import tinycss2
import html5lib
from html5lib.html5parser import ParseError


def validate_json(content: str) -> tuple[bool, str]:
    """Validate JSON syntax. Returns (ok, error_description)."""
    try:
        json.loads(content)
        return True, ""
    except json.JSONDecodeError as e:
        lines = content.split("\n")
        lineno = e.lineno
        colno = e.colno
        context_before = ""
        context_after = ""
        if 1 <= lineno <= len(lines):
            line = lines[lineno - 1]
            context_before = line[max(0, colno - 30):colno]
            context_after = line[colno:colno + 30]
        return False, (
            f"JSON 语法错误 (第 {lineno} 行, 第 {colno} 列): {e.msg}\n"
            f"  上下文: ...{context_before}>>>HERE<<<{context_after}..."
        )


def validate_css(content: str) -> tuple[bool, str]:
    """Validate CSS syntax using tinycss2 + brace balance. Returns (ok, error_description)."""
    try:
        rules = tinycss2.parse_stylesheet(
            content, skip_whitespace=True, skip_comments=True
        )
        errors = [r for r in rules if r.type == "error"]
        if errors:
            err_lines = []
            for e in errors[:3]:
                line = getattr(e, "source_line", "?") or "?"
                col = getattr(e, "source_column", "?") or "?"
                msg = getattr(e, "message", str(e))
                err_lines.append(f"  第 {line} 行, 第 {col} 列: {msg}")
            return False, "CSS 语法错误:\n" + "\n".join(err_lines)
        # Fallback: brace balance check (tinycss2 may not catch unclosed braces)
        return _check_brace_balance(content, "{", "}", "CSS")
    except Exception as e:
        return False, f"CSS 解析异常: {str(e)}"


def validate_html(content: str) -> tuple[bool, str]:
    """Validate HTML syntax. Tries strict html5lib first, falls back to tag balance check.
    Returns (ok, error_description).
    """
    # Phase 1: strict html5lib parsing
    try:
        parser = html5lib.HTMLParser(strict=True)
        parser.parse(content)
        return True, ""
    except ParseError as e:
        # html5lib strict is too strict for real-world HTML fragments
        # (e.g. no DOCTYPE triggers "Expected DOCTYPE")
        # Fall through to balance check instead of rejecting
        pass
    except Exception:
        pass

    # Phase 2: tag balance check (fallback)
    return _check_html_balance(content)


def _check_brace_balance(content: str, open_b: str, close_b: str, label: str = "") -> tuple[bool, str]:
    """Check that open/close braces are balanced. Returns (ok, error_description)."""
    opens = content.count(open_b)
    closes = content.count(close_b)
    if opens != closes:
        prefix = f"{label} " if label else ""
        if opens > closes:
            return False, f"{prefix}花括号不平衡: {opens} 个 '{open_b}' vs {closes} 个 '{close_b}' — 可能缺少 {opens - closes} 个 '{close_b}'"
        else:
            return False, f"{prefix}花括号不平衡: {opens} 个 '{open_b}' vs {closes} 个 '{close_b}' — 可能多出 {closes - opens} 个 '{close_b}'"
    return True, ""


def _check_html_balance(content: str) -> tuple[bool, str]:
    """Fallback: count open/close tags to detect missing closing tags."""
    # Self-closing / void elements (HTML5)
    void_elements = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
    # Count <tagname...> open tags
    open_tags = re.findall(r"<(\w+)[\s>/]", content)
    # Count </tagname> close tags
    close_tags = re.findall(r"</(\w+)>", content)

    # Build frequency counts
    from collections import Counter
    open_freq = Counter(tag.lower() for tag in open_tags if tag.lower() not in void_elements)
    close_freq = Counter(tag.lower() for tag in close_tags if tag.lower() not in void_elements)

    # Find mismatches
    mismatches = []
    all_tag_names = set(open_freq.keys()) | set(close_freq.keys())
    for tag in sorted(all_tag_names):
        delta = open_freq[tag] - close_freq[tag]
        if delta > 0:
            mismatches.append(f"缺少 {delta} 个 </{tag}> 闭合标签")
        elif delta < 0:
            mismatches.append(f"多出 {abs(delta)} 个 </{tag}> 闭合标签")

    if mismatches:
        return False, "HTML 标签不平衡:\n" + "\n".join(f"  - {m}" for m in mismatches)
    return True, ""


# File extension → validator mapping
VALIDATORS = {
    ".json": validate_json,
    ".css": validate_css,
    ".html": validate_html,
    ".htm": validate_html,
}
