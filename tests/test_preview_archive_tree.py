"""The preview archive view must render a tree, not a staircase.

Measured on a 62-entry .tar.gz (49 files / 13 dirs) before the fix: rows at the
same depth landed on different x, and depth 3 rendered *left* of depth 2 --

    depth 0: 52
    depth 1: 585
    depth 2: 910 / 933 / 918 / 712 / 782 / 751
    depth 3: 898 / 913 / 890 / 906

Indentation carried no meaning, the left half of the pane was empty, and the
root's own label sat vertically centred at y=743 inside a 1247px-tall row.

The JS computes the indent correctly (`row.style.paddingLeft = (depth * 20 + 12)`
in preview.js), so this is purely a CSS defect: `.archive-entry` is a nowrap
flex row, `.archive-name { flex: 1 }` grows to absorb the row's free space, and
the subtree container is a *sibling* in that same row rather than an element
below it. Each nesting level therefore opens a new column to the right, and how
far right depends on how much free space that particular branch absorbed.

`.archive-children { }` was an empty rule -- the tell that the subtree container
was meant to be styled and never was.
"""

from __future__ import annotations

import re
from pathlib import Path

CSS = Path(__file__).resolve().parents[1] / "dev" / "static" / "css" / "preview.css"
PREVIEW_JS = CSS.parents[1] / "js" / "preview.js"


def _uncommented(source: str) -> str:
    """Drop /* ... */ so a comment cannot satisfy a declaration check."""
    return re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)


def _rule_body(css: str, selector: str) -> str:
    """Return the declaration block for `selector`, comments stripped.

    Anchored to a rule that starts the line and is followed by `{`, so
    `.archive-entry-something` cannot stand in for `.archive-entry`.
    """
    cleaned = _uncommented(css)
    match = re.search(rf"(?m)^\s*{re.escape(selector)}\s*\{{([^}}]*)\}}", cleaned)
    assert match, f"no rule found for {selector}"
    return match.group(1)


def test_the_subtree_container_breaks_onto_its_own_line():
    """Without this the subtree container is laid out beside the name."""
    body = _rule_body(CSS.read_text(encoding="utf-8"), ".archive-children")
    assert "flex-basis: 100%" in body, (
        ".archive-children must take a full flex line of its own, or every "
        "nesting level opens a new column to the right instead of a new row")


def test_the_entry_row_allows_that_break():
    """`flex-basis: 100%` needs a wrapping row to have any effect."""
    body = _rule_body(CSS.read_text(encoding="utf-8"), ".archive-entry")
    assert "flex-wrap: wrap" in body, (
        ".archive-entry is a nowrap flex row; the subtree container can only "
        "reach its own line when the row is allowed to wrap")


def test_the_indent_is_still_computed_from_depth():
    """The fix is CSS-side only -- the JS indent must not be 'fixed' away.

    It was already correct: padding-left = depth * 20 + 12, with a matching
    guide line per level at d * 20 + 10.
    """
    source = PREVIEW_JS.read_text(encoding="utf-8")
    assert "paddingLeft = (depth * 20 + 12)" in source
    assert "guide.style.left = (d * 20 + 10)" in source


def test_a_directory_name_uses_the_same_toggle_handler_as_its_disclosure_icon():
    """A directory should not require the user to target its small arrow."""
    source = PREVIEW_JS.read_text(encoding="utf-8")
    assert "function toggleDirectory()" in source
    assert "icon.addEventListener('click', toggleDirectory)" in source
    assert "nameSpan.addEventListener('click', toggleDirectory)" in source
    assert "nameSpan.setAttribute('aria-expanded', 'false')" in source
    assert "event.key === 'Enter' || event.key === ' '" in source


def test_archive_metadata_columns_remain_right_aligned():
    """Deeply nested names must not pull size and date columns away from the right edge."""
    css = CSS.read_text(encoding="utf-8")
    assert "text-align: right" in _rule_body(css, ".archive-size")
    assert "text-align: right" in _rule_body(css, ".archive-mtime")
