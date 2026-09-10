"""The panels are gone for an administrator on both pages, and the more-menu
mirror follows without being told separately -- topbar.js's _syncItems() reads
the target button's `hidden`, so hiding the button IS the whole mechanism.
"""

from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "dev" / "static"
ENTRIES = ("btnToggleAgent", "btnProjectPanel", "btnToggleFeedback")


def test_the_shared_gate_is_a_single_fetch():
    topbar = (STATIC / "js" / "topbar.js").read_text(encoding="utf-8")
    assert "ClawMateAdmin" in topbar
    assert "/api/clawmate/auth/status" in topbar
    # One request per page load, not one per caller.
    assert topbar.count("/api/clawmate/auth/status") == 1


def test_the_three_entries_are_the_ones_hidden():
    """Hiding the topbar button is the whole mechanism: _syncItems() derives
    each more-menu mirror from its target's `hidden`, so the mobile menu needs
    no separate code. The attribute is used rather than an inline display
    because #btnProjectPanel has its display rewritten on every navigation."""
    topbar = (STATIC / "js" / "topbar.js").read_text(encoding="utf-8")
    for entry in ENTRIES:
        assert entry in topbar, entry
    assert "el.hidden = true" in topbar


def test_both_pages_apply_the_boundary():
    for page in ("app.js", "preview.js"):
        source = (STATIC / "js" / page).read_text(encoding="utf-8")
        assert "ClawMateAdmin" in source, page
