"""The panels are gone for an administrator on both pages, and the more-menu
mirror follows without being told separately -- topbar.js's _syncItems() reads
the target button's `hidden`, so hiding the button IS the whole mechanism.

These read the source text, so every assertion here is bounded to the code that
has to carry the property. Otherwise the gate is not guarded at all: the entry
ids are quoted in the comment above the array that is supposed to hide them, and
`_applyAdminContentPanelBoundary()` appears in its own definition -- so a
file-wide substring search stays green with the entries deleted or the call site
neutered. Comments are stripped (they are prose about the code, not the code)
and the reads are brace/bracket-bounded.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "dev" / "static"
ENTRIES = ("btnToggleAgent", "btnProjectPanel", "btnToggleFeedback")
# The containers the entries close through. index and preview name theirs
# differently (agentPanel vs previewAgentPanel) and preview has no project
# container at all; hideContentPanelEntries() skips the ids that are absent.
PANELS = ("agentPanel", "previewAgentPanel", "projectPanel", "rightSidebar")

BOUNDARY_FN = "_applyAdminContentPanelBoundary"


def _strip_js_comments(source: str) -> str:
    """Drop // line comments and /* */ blocks so an assertion cannot be
    satisfied by explanatory prose that happens to quote the code.

    Only whole-line // comments are dropped: `//` inside a string literal
    (a URL, say) must stay, or the strip would truncate real code.
    """
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", without_blocks)


def _bracketed(source: str, anchor: str, open_ch: str, close_ch: str) -> str:
    """Return the bracket-balanced block that follows `anchor`.

    Bounding is the point: `btnProjectPanel` and `btnToggleFeedback` are both
    named in the comment above the entries array, so only an occurrence inside
    the array proves the entry is really configured. The count is naive about
    brackets inside string literals, which is fine here because these literals
    hold plain identifiers.
    """
    start = source.index(anchor)
    open_at = source.index(open_ch, start)
    depth = 0
    for index in range(open_at, len(source)):
        char = source[index]
        if char == open_ch:
            depth += 1
        elif char == close_ch:
            depth -= 1
            if depth == 0:
                return source[open_at:index + 1]
    raise AssertionError(f"unbalanced {open_ch}{close_ch} after {anchor!r}")


def test_the_shared_gate_is_a_single_fetch():
    script = _strip_js_comments((STATIC / "js" / "topbar.js").read_text(encoding="utf-8"))

    assert "window.ClawMateAdmin" in script
    # Exactly one fetch site in this file, which is what makes the probe one
    # request per caller: the promise is cached, so a second caller re-uses it.
    # This is not a claim about the whole page -- app.js's initSettings() also
    # probes the same endpoint for the settings gear.
    assert script.count("/api/clawmate/auth/status") == 1


def test_the_three_entries_are_the_ones_hidden():
    """Hiding the topbar button is the whole mechanism: _syncItems() derives
    each more-menu mirror from its target's `hidden`, so the mobile menu needs
    no separate code. The attribute is used rather than an inline display
    because #btnProjectPanel has its display rewritten on every navigation.

    Comments are stripped and the reads are bounded to the entries array and to
    hideContentPanelEntries() itself: the ids are quoted in the comment above
    the array, so an unbounded search would stay green with two of the three
    entries deleted -- the boundary would hide one entry and report success.
    """
    script = _strip_js_comments((STATIC / "js" / "topbar.js").read_text(encoding="utf-8"))

    entries = _bracketed(script, "CONTENT_PANEL_ENTRIES =", "[", "]")
    for entry in ENTRIES:
        assert f"'{entry}'" in entries, entry
    for panel in PANELS:
        assert f"'{panel}'" in entries, panel

    body = _bracketed(script, "function hideContentPanelEntries()", "{", "}")
    assert "CONTENT_PANEL_ENTRIES" in body, "the loop must walk the entries array"
    # Variable names are free; the properties are not. The id has to come off
    # the entry (not be hardcoded) and the gate has to be the `hidden` attribute.
    assert re.search(r"getElementById\(\s*\w+\.toggle\s*\)", body), \
        "each entry is looked up by its own toggle id"
    assert re.search(r"\.hidden\s*=\s*true", body), \
        "the gate has to be the hidden attribute, not an inline display"


def test_both_pages_apply_the_boundary():
    """Both pages have to *invoke* the boundary, not merely mention it.

    `"ClawMateAdmin" in source` is satisfied by the shared API object and by the
    function's own definition, so `_applyAdminContentPanelBoundary;` (a bare
    identifier where the call belongs) leaves the boundary dead and the check
    green. Require a real call, and require the definition it resolves to.
    """
    for page in ("app.js", "preview.js"):
        script = _strip_js_comments((STATIC / "js" / page).read_text(encoding="utf-8"))

        assert "window.ClawMateAdmin" in script, page
        assert re.search(rf"(?m)^\s*function {BOUNDARY_FN}\(\)", script), \
            f"{page} must define {BOUNDARY_FN}()"
        # Not the definition: that one is preceded by `function `.
        calls = re.findall(rf"(?<!function ){BOUNDARY_FN}\(\)", script)
        assert calls, f"{page} must invoke {BOUNDARY_FN}(), not merely define it"


def test_the_project_panel_does_not_auto_open_for_an_admin():
    """_updateProjectPanelBtn() opens the panel on a project's first visit in a
    login session. With the entry hidden for an administrator, that would open a
    panel nobody can close -- so the auto-open has to be a conjunction of the
    first visit and the admin gate.

    Three things keep this from going green on prose or on a neighbour:

    - `_strip_js_comments()` runs first, because the expression is spelled out in
      the comment above the call.
    - The read is anchored to the start of its own line. The helper drops
      whole-line `//` comments only (its docstring says so), so without the
      anchor the expression planted in a trailing comment would satisfy the
      assertion while the call itself lost its guard.
    - The read is bounded to _updateProjectPanelBtn(), so a guarded call anywhere
      else in the file cannot stand in for the one that auto-opens the panel.

    Whitespace is free; the tokens and their order are not.
    """
    script = _strip_js_comments((STATIC / "js" / "app.js").read_text(encoding="utf-8"))
    body = _bracketed(script, "function _updateProjectPanelBtn()", "{", "}")

    assert re.search(
        r"(?m)^\s*_setProjectPanelOpen\(\s*firstVisit\s*&&\s*!_adminDeniesContentPanels\s*\)",
        body,
    ), "the auto-open must stay gated on !_adminDeniesContentPanels as well as firstVisit"
