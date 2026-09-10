from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_directory_panel_uses_a_root_to_current_path_stack():
    """The one-column panel exposes the active path, current children, and Up."""
    source = (ROOT / "dev" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    markup = (ROOT / "dev" / "static" / "index.html").read_text(encoding="utf-8")

    assert 'id="btnDirUp"' not in markup
    assert 'id="rootSwitchMenu"' in markup
    assert "async function loadSidebarPath(dir)" in source
    assert 'dir.split("/").filter(Boolean)' in source
    assert "sidebarPathEntries" in source
    assert "sidebar-current-children" in source
    assert "sidebar-path-item" in source
    assert "sidebarPathEntries = [{ name: rootLabel, relPath: \"\" }]" in source
    panel_loader = source.split("async function loadSidebarPath", 1)[1].split("function appendSidebarCurrentChildren", 1)[0]
    assert "sidebarCurrentChildren" in panel_loader
    assert "await Promise.all" not in panel_loader
    assert "appendSidebarCurrentChildren(children);" in source
    assert "await loadSidebarPath(state.dir);" in source


def test_directory_panel_root_selector_uses_the_standard_quiet_treatment():
    css = (ROOT / "dev" / "static" / "css" / "style.css").read_text(encoding="utf-8")
    rule = css.split(".root-switch-menu #rootSelect {", 1)[1].split("}", 1)[0]

    assert "font-weight: 600" in rule
    assert "border: 1px solid var(--border-color)" in rule
    assert "background: var(--bg-secondary)" in rule


def test_index_places_directory_toggle_before_command_palette_when_sidebar_is_closed():
    markup = (ROOT / "dev" / "static" / "index.html").read_text(encoding="utf-8")
    source = (ROOT / "dev" / "static" / "js" / "app.js").read_text(encoding="utf-8")

    assert markup.index('id="btnToggleSidebar"') < markup.index('id="btnCommandPalette"')
    assert "target.nextElementSibling === btn" in source
    assert "target.insertAdjacentElement('afterend', btn);" in source
    assert "var closeButton = document.getElementById('btnCloseSidebar');" in source


def test_root_path_node_has_a_separate_root_switch_control():
    source = (ROOT / "dev" / "static" / "js" / "app.js").read_text(encoding="utf-8")

    assert 'btnRootSwitch' in source
    assert 'rootSwitchMenu' in source
    assert 'entry.relPath === ""' in source


def test_root_switch_menu_is_anchored_to_the_root_row_without_reflowing_the_tree():
    source = (ROOT / "dev" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "dev" / "static" / "css" / "style.css").read_text(encoding="utf-8")

    assert "li.appendChild(els.rootSwitchMenu);" in source
    root_item_rule = css.split(".sidebar-root-path-item {", 1)[1].split("}", 1)[0]
    switch_menu_rule = css.split(".root-switch-menu {", 1)[1].split("}", 1)[0]
    assert "position: relative" in root_item_rule
    assert "position: absolute" in switch_menu_rule
    assert "top: 0" in switch_menu_rule
    assert "left: 0" in switch_menu_rule
    assert 'switchButton.innerHTML = typeof iconSVG === \'function\' ? iconSVG(\'arrow-left-right\', 14) : \'↔\';' in source


def test_directory_rows_and_root_switch_controls_use_a_30px_height():
    css = (ROOT / "dev" / "static" / "css" / "style.css").read_text(encoding="utf-8")

    assert "height: 30px" in css.split(".root-switch-menu #rootSelect {", 1)[1].split("}", 1)[0]
    assert "width: 30px; height: 30px" in css.split(".root-switch-btn {", 1)[1].split("}", 1)[0]
    directory_row_rule = css.split(".sidebar-path-link, .sidebar-child-item > button {", 1)[1].split("}", 1)[0]
    assert "height: 30px" in directory_row_rule


def test_root_switch_closes_when_clicking_outside_and_matches_root_row_background():
    source = (ROOT / "dev" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "dev" / "static" / "css" / "style.css").read_text(encoding="utf-8")

    assert "function hideRootSwitchMenu()" in source
    assert 'document.addEventListener("click", function (event)' in source
    assert "rootItem.contains(event.target)" in source
    assert "sidebar-root-current" in source
    assert ".sidebar-root-current .root-switch-btn { background: var(--accent-light);" in css
    assert ".sidebar-root-ancestor .root-switch-btn { background: var(--bg-tertiary);" in css


def test_root_current_children_stay_below_the_root_control_row():
    css = (ROOT / "dev" / "static" / "css" / "style.css").read_text(encoding="utf-8")

    root_item_rule = css.split(".sidebar-root-path-item {", 1)[1].split("}", 1)[0]
    assert "flex-wrap: wrap" in root_item_rule
    assert ".sidebar-root-path-item > .sidebar-current-children { flex-basis: 100%; }" in css
