"""Every actionable button in a mobile page's topbar belongs in More.

The topbar is the authoritative list. If CSS is updated separately, it can
leave a visible action outside More (or hide one with no menu mirror), so the
contract validates the HTML actions, their mirrors, and the fold rule together.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "dev" / "static"

_FOLD_SELECTOR = re.compile(r"#btnMoreMenu\)\s*#([\w-]+)")


def _folded_topbar_ids(css: str) -> set[str]:
    """Ids the mobile fold rules hide.

    Both halves matter: the selector ties the id to the mobile topbar, and the
    declaration is what hides it. Reading them flatly (selector text is
    everything since the previous `}`) is enough here because the fold lives in
    one selector group ending in a single `{ display: none; }` -- and it keeps
    `#btnMoreMenu` out, since its own rule declares `display: flex` separately.
    """
    folded: set[str] = set()
    cursor = 0
    while True:
        brace = css.find("{", cursor)
        if brace == -1:
            return folded
        close = css.find("}", brace)
        selector, declaration = css[cursor:brace], css[brace:close]
        if "display: none" in declaration and "#btnMoreMenu)" in selector:
            folded.update(_FOLD_SELECTOR.findall(selector))
        cursor = close + 1


def _more_menu_mirrors(html: str) -> set[str]:
    """`data-more` targets of the page's more-menu items."""
    start = html.index('class="more-menu"')
    end = html.index("</div>", start)
    return set(re.findall(r'data-more="([^"]+)"', html[start:end]))


def _topbar_action_ids(html: str) -> set[str]:
    start = html.index('class="topbar-actions"')
    end = html.index("</div>", start)
    actions = set(re.findall(r'id="([^"]+)"', html[start:end]))
    actions.remove("btnMoreMenu")
    return actions


def _assert_topbar_actions_are_mirrored_and_folded(page: str) -> set[str]:
    html = (STATIC / page).read_text(encoding="utf-8")
    folded = _folded_topbar_ids((STATIC / "css" / "style.css").read_text(encoding="utf-8"))
    actions = _topbar_action_ids(html)
    mirrors = _more_menu_mirrors(html)
    assert actions == mirrors, f"{page} topbar actions and More items diverged"
    assert actions <= folded, f"{page} leaves {sorted(actions - folded)} outside More on mobile"
    return actions


def test_index_mirrors_every_topbar_action():
    assert _assert_topbar_actions_are_mirrored_and_folded("index.html") == {
        "btnProjectPanel", "btnSettings", "themeToggle", "btnLogout", "btnToggleAgent"}


def test_preview_mirrors_every_topbar_action():
    assert _assert_topbar_actions_are_mirrored_and_folded("preview.html") == {
        "btnProjectPanel", "btnToggleFeedback", "themeToggle", "btnLogout", "btnToggleAgent"}


def test_fold_rules_are_discovered_not_assumed():
    """Guard on the parser: if the fold selector is rewritten, this test fails
    loudly instead of silently checking an empty set."""
    css = (STATIC / "css" / "style.css").read_text(encoding="utf-8")

    assert _folded_topbar_ids(css) == {
        "btnProjectPanel", "btnSettings", "btnToggleFeedback", "themeToggle", "btnLogout", "btnToggleAgent"}


def test_preview_more_menu_dispatches_the_agent_and_feedback_toggles():
    """The mirror is only useful if it targets the button the page wires up."""
    html = (STATIC / "preview.html").read_text(encoding="utf-8")
    preview_js = (STATIC / "js" / "preview.js").read_text(encoding="utf-8")
    topbar_js = (STATIC / "js" / "topbar.js").read_text(encoding="utf-8")

    assert 'data-more="btnToggleAgent"' in html
    assert 'id="btnToggleAgent"' in html
    assert "btnToggleAgent.addEventListener('click'" in preview_js
    assert 'data-more="btnToggleFeedback"' in html
    assert 'id="btnToggleFeedback"' in html
    assert "btnToggleFeedback').addEventListener('click'" in preview_js
    # Generic dispatch: a mirror is just the target id, so no per-item wiring.
    assert "document.getElementById(id)" in topbar_js and ".click()" in topbar_js
