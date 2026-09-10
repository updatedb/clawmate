"""Every topbar action the mobile CSS folds away must be reachable from the
page's more-menu.

The fold is CSS-only: `.content-col > .topbar:has(#btnMoreMenu) #<id>` sets
`display: none` at <=768px. The button itself stays in the DOM and keeps its
handler, so nothing breaks loudly -- the action simply becomes untappable on a
phone. That is how the preview page lost its Agent 终端 button: the menu
mirrored three of the four folded actions, and the missing one had no other way
to be triggered.
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


def _assert_folded_actions_are_mirrored(page: str) -> set[str]:
    html = (STATIC / page).read_text(encoding="utf-8")
    folded = _folded_topbar_ids((STATIC / "css" / "style.css").read_text(encoding="utf-8"))
    # A page only inherits the rules for ids it actually declares: #btnSettings
    # is an index-only entry, so the preview page neither folds nor mirrors it.
    present = {root_id for root_id in folded if f'id="{root_id}"' in html}
    missing = sorted(present - _more_menu_mirrors(html))
    assert not missing, (
        f"{page} hides {missing} at <=768px with no more-menu entry, so those "
        f"actions cannot be triggered from a phone")
    return present


def test_index_mirrors_every_folded_topbar_action():
    assert _assert_folded_actions_are_mirrored("index.html") == {
        "btnProjectPanel", "btnSettings", "themeToggle", "btnLogout", "btnToggleAgent"}


def test_preview_mirrors_every_folded_topbar_action():
    present = _assert_folded_actions_are_mirrored("preview.html")
    # The preview topbar has no settings entry: asserting the set keeps the
    # test honest if a rule is added without a matching mirror.
    assert present == {"btnProjectPanel", "themeToggle", "btnLogout", "btnToggleAgent"}


def test_fold_rules_are_discovered_not_assumed():
    """Guard on the parser: if the fold selector is rewritten, this test fails
    loudly instead of silently checking an empty set."""
    css = (STATIC / "css" / "style.css").read_text(encoding="utf-8")

    assert _folded_topbar_ids(css) == {
        "btnProjectPanel", "btnSettings", "themeToggle", "btnLogout", "btnToggleAgent"}


def test_preview_more_menu_dispatches_the_agent_toggle():
    """The mirror is only useful if it targets the button the page wires up."""
    html = (STATIC / "preview.html").read_text(encoding="utf-8")
    preview_js = (STATIC / "js" / "preview.js").read_text(encoding="utf-8")
    topbar_js = (STATIC / "js" / "topbar.js").read_text(encoding="utf-8")

    assert 'data-more="btnToggleAgent"' in html
    assert 'id="btnToggleAgent"' in html
    assert "btnToggleAgent.addEventListener('click'" in preview_js
    # Generic dispatch: a mirror is just the target id, so no per-item wiring.
    assert "document.getElementById(id)" in topbar_js and ".click()" in topbar_js
