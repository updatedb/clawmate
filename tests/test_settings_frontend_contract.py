from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "dev" / "static"


def _strip_js_comments(source: str) -> str:
    """Drop // line comments and /* */ blocks so an assertion cannot be
    satisfied by explanatory prose that happens to quote the code.

    Only whole-line // comments are dropped: `//` inside a string literal
    (a URL, say) must stay, or the strip would truncate real code.
    """
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", without_blocks)


def _handler_body(source: str, anchor: str) -> str:
    """Return the callback body registered by the addEventListener call that
    follows `anchor`, bounded by brace matching.

    Bounding is the point: `openDirPicker` is called from a dozen places in this
    7000-line file, so only a call *inside* this handler proves the settings
    browse button is wired to the picker. The brace count is naive about braces
    inside string literals, which is acceptable here because the handler holds
    no literal `{` or `}`.
    """
    start = source.index(anchor)
    start = source.index("addEventListener", start)
    open_brace = source.index("{", start)
    depth = 0
    for index in range(open_brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[open_brace:index + 1]
    raise AssertionError(f"unbalanced braces in the handler after {anchor!r}")


def test_index_declares_two_settings_tabs():
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert 'id="btnSettings"' in html and 'id="settingsModal"' in html
    assert 'data-settings-tab="roots"' in html and 'data-settings-tab="users"' in html


def test_settings_entry_is_a_desktop_topbar_control_and_a_mobile_menu_mirror():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    menu_start = html.index('<div class="more-menu"')
    menu_end = html.index('</div>', menu_start)
    menu = html[menu_start:menu_end]

    assert '<button id="btnSettings" class="topbar-btn"' in html
    assert 'data-more="btnSettings"' in menu


def test_root_tab_declares_registry_controls():
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert 'id="settingsRootList"' in html
    assert 'id="settingsRootDir"' in html
    assert 'id="settingsRootBrowse"' in html
    assert 'id="settingsRootAgent"' in html


def test_user_tab_uses_registry_checkboxes_not_a_path_multiselect():
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert 'id="settingsUserRoots"' in html
    assert '<select id="settingsRootDirs"' not in html


def test_user_edit_reuses_the_registry_checkbox_form():
    script = _strip_js_comments((STATIC / "js" / "app.js").read_text(encoding="utf-8"))
    edit_handler = _handler_body(script, "text.textContent = user.username")

    assert "editingUserId = user.id" in edit_handler
    assert "settingsUserRoots" in edit_handler
    assert "window.prompt('授权 Rootdir id" not in edit_handler


def test_frontend_sends_root_ids_not_the_removed_root_dirs_key():
    """The API now rejects root_dirs, so a stale payload would 422 silently."""
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    assert "root_ids" in script
    assert "root_dirs" not in script


def test_settings_script_calls_registry_and_grant_endpoints():
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    assert "/api/clawmate/settings/roots" in script
    assert "/api/clawmate/settings/users" in script
    assert "/api/clawmate/auth/status" in script
    assert "root_ids" in script


def test_root_browse_reuses_the_shared_directory_picker():
    """A bare `"openDirPicker" in script` would prove nothing: the identifier
    occurs a dozen times across the file. The call has to be inside the
    settings browse handler."""
    script = _strip_js_comments((STATIC / "js" / "app.js").read_text(encoding="utf-8"))

    assert "openDirPicker(" in _handler_body(script, "settingsRootBrowse"), \
        "the settings browse button must call the shared directory picker"
    assert "/api/clawmate/settings/browse" not in script


def test_root_browse_starts_at_the_system_root():
    script = _strip_js_comments((STATIC / "js" / "app.js").read_text(encoding="utf-8"))
    handler = _handler_body(script, "settingsRootBrowse")

    # In code, not in the explanatory comment above the call: without the empty
    # string the picker seeds itself from the preview panel's current directory.
    assert "selectedDir: ''" in handler
    assert "rootId: '.'" in handler


def test_settings_script_reports_failed_admin_requests():
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    assert "设置请求失败" in script
    assert "当前账号不是管理员" in script
    assert "if (!response.ok)" in script


def test_app_falls_back_from_an_unavailable_root_url_to_an_authorized_root():
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    assert "已切换到可访问根目录" in script


def test_settings_identity_probe_does_not_redirect_local_auth_bypass_to_login():
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    assert "await fetch('/api/clawmate/auth/status')" in script


def test_dir_picker_paints_above_the_settings_modal():
    """Both are .modal-overlay siblings; DOM order puts the settings modal last."""
    css = (STATIC / "css" / "style.css").read_text(encoding="utf-8")
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    # The selector must be bound to its value: `z-index: 10001` also appears in
    # the mermaid and bpmn overlays, so a file-wide substring check stays green
    # while the picker itself regresses to 9999 and the settings modal swallows
    # its clicks.
    assert re.search(r"#dirPickerModal\s*\{[^}]*z-index:\s*10001", css), \
        "the picker must outrank .modal-overlay's 10000"
    assert html.index('id="dirPickerModal"') < html.index('id="settingsModal"'), \
        "if the picker is ever moved after the settings modal this rule is no longer needed"


def test_the_hidden_attribute_actually_gates_topbar_and_more_menu_controls():
    """`.topbar-btn`/`.more-item` set `display: flex`, which outranks the UA
    `[hidden] { display: none }` -- so before this rule the admin-only settings
    gear stayed visible *and clickable* for an ordinary user on both the topbar
    and the mobile "more" menu, and it opened a modal whose every request 403s.

    The selector is bound to its value: a file-wide `"display: none" in css`
    would be satisfied a hundred times over, so the check reads the one rule
    whose selector is `[hidden]`. Comments are stripped first, or the
    explanatory comment above the rule would satisfy it on its own.
    """
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "css" / "style.css").read_text(encoding="utf-8"),
                 flags=re.S)

    assert re.search(r"\.topbar-btn\[hidden\][^{]*\{[^}]*display:\s*none", css), \
        "the topbar gear must obey its own hidden attribute"
    assert re.search(r"\.more-item\[hidden\][^{]*\{[^}]*display:\s*none", css), \
        "the mobile more-menu entry must obey its own hidden attribute"


def _balanced_body(source: str, anchor: str) -> str:
    """Return the brace-balanced block that follows `anchor`.

    `_js_function` below cannot be used for these: `_syncItems` is nested inside
    an IIFE, so it never closes at column 0. Bounding matters -- `hidden` occurs
    all over topbar.js, so only an occurrence inside this one function proves
    the mirror consults it.
    """
    start = source.index(anchor)
    open_brace = source.index("{", start)
    depth = 0
    for index in range(open_brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[open_brace:index + 1]
    raise AssertionError(f"unbalanced braces after {anchor!r}")


def test_more_menu_mirrors_a_target_gated_by_the_hidden_attribute():
    """The more-menu entry must track the same signal as the button it mirrors.

    Mirroring only the inline `display:none` missed the settings gear, which is
    gated with the `hidden` attribute -- so an ordinary user got 系统设置 in the
    mobile menu. Reading `target.hidden` alone is not enough either: the entry's
    own `hidden` default has to be cleared for an admin, or the CSS rule above
    hides the entry from the one account that should see it.
    """
    script = _strip_js_comments((STATIC / "js" / "topbar.js").read_text(encoding="utf-8"))

    body = _balanced_body(script, "function _syncItems()")
    assert "target.hidden" in body, "the mirror must consult the target's hidden attribute"
    assert "item.hidden = off" in body, "the entry's own hidden default must follow the target"


def test_settings_entry_is_gated_on_the_admin_flag():
    """The gate the CSS rule above makes effective has to still be set."""
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    body = _js_function(script, "async function initSettings()")
    assert "btn.hidden = !me.is_admin" in body


def test_dir_picker_exposes_a_hidden_directory_toggle():
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert 'id="dirPickerShowHidden"' in html


def _js_function(source, signature):
    """Return one top-level JS function's text: its signature up to the next
    line that is exactly '}' (top-level functions in app.js close at column 0).
    """
    start = source.index(signature)
    end = source.index("\n}\n", start)
    return source[start:end]


def test_dir_picker_filters_hidden_entries_behind_the_toggle():
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    assert "DIR_PICKER_TOGGLE_PREFIXES" in script
    # A leftover old-named constant would mean a second, toggle-blind filter.
    assert "DIR_PICKER_SKIP_PREFIXES" not in script

    body = _js_function(script, "function _filterDirsForPicker")
    # The prefix skip must stay *inside* the show-hidden guard; an unguarded
    # loop would filter hidden dirs even with the checkbox ticked.
    assert "dirPickerShowHidden" in body
    assert "if (!showHidden)" in body
    assert body.index("if (!showHidden)") < body.index("DIR_PICKER_TOGGLE_PREFIXES")


def test_dir_picker_accepts_an_options_argument_without_breaking_old_callers():
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    assert "async function openDirPicker(title, options)" in script
    body = _js_function(script, "async function openDirPicker(title, options)")
    # Options must stay optional: the three legacy callers below pass a title
    # only, so requiring a second argument would break them at runtime.
    assert "options || {}" in body
    assert "opts.rootId" in body
    assert "opts.onSelect" in body

    assert "openDirPicker(`选择目标目录 — 移动 ${paths.length} 个文件`);" in script
    assert "openDirPicker('选择目标目录 — ' + entry.name);" in script
    assert "openDirPicker('解压 \"' + entry.name + '\" 到...');" in script


def test_dir_picker_reloads_the_tree_when_the_toggle_changes():
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    body = _js_function(script, "function initDirPicker")
    assert "dirPickerShowHidden" in body
    assert "addEventListener('change'" in body
    # Dropping the cache and re-rendering alone leaves an empty tree (the root
    # row has no expand arrow); the reload must go back through openDirPicker.
    assert "openDirPicker(" in body


def test_dir_picker_restores_the_previous_root_on_close():
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    body = _js_function(script, "function closeDirPicker")
    # The stash must be applied to the live root and then cleared, or closing
    # the picker leaves the file browser on the caller-supplied root.
    assert "dirPickerRootIdBeforeOpen" in body
    assert "state.rootId = dirPickerRootIdBeforeOpen" in body
    assert "dirPickerRootIdBeforeOpen = null" in body

    open_body = _js_function(script, "async function openDirPicker(title, options)")
    # Stash only once, so a reload while the picker is open (toggle change)
    # cannot overwrite the stash with the already-overridden root.
    assert "dirPickerRootIdBeforeOpen === null" in open_body
    assert "state.rootId = opts.rootId" in open_body


# ── Settings panel redesign ────────────────────────────────────────────

def _settings_css() -> str:
    return (STATIC / "css" / "style.css").read_text(encoding="utf-8")


def _settings_css_without_comments() -> str:
    return re.sub(r"/\*.*?\*/", "", _settings_css(), flags=re.S)


def test_the_form_input_rule_does_not_reach_checkboxes():
    """`.settings-form input { width: 100% }` matches by element name, so it
    also hit the grant checkboxes: measured 308x30 each, with their labels
    pushed to a second line (54.5px rows). A control's size rule must not be
    applied across control types."""
    css = _settings_css()
    assert '.settings-form input:not([type="checkbox"])' in css
    # The bare form of the rule must be gone, not merely shadowed.
    assert ".settings-form input {" not in css


def test_the_grant_checkboxes_are_reset_to_natural_size():
    css = _settings_css()
    assert "#settingsUserRoots" in css
    block = css[css.index("#settingsUserRoots"):]
    block = block[:block.index("}")]
    assert "grid-template-columns" in block          # two-column grid
    assert "accent-color: var(--accent)" in block    # matches style.css:958
    # A reset for the leaked width/min-height lives on the input itself.
    assert "#settingsUserRoots input" in css


def test_autofill_follows_the_theme():
    """Chrome paints autofilled inputs with its own light fill, which wins over
    --bg-primary: in dark mode one field rendered light next to a dark one."""
    css = _settings_css()
    assert "-webkit-autofill" in css
    assert "0 0 0 1000px var(--bg-primary) inset" in css


def test_the_two_tabs_share_one_row_rule():
    """`.settings-user` had a border-bottom and `.settings-root` did not, so
    the two tabs of one modal looked like different screens."""
    css = _settings_css()
    assert ".settings-row" in css
    assert ".settings-root" not in css
    assert ".settings-user" not in css


def test_settings_controls_gated_by_hidden_are_really_hidden():
    """`.btn` and `.settings-row` both set a display value, which outranks the
    UA `[hidden] { display: none }` -- the same trap the topbar gear hit (see
    the comment above .topbar-btn[hidden]). Without this rule the "+ 新建" and
    "取消编辑" controls stay visible in every view, and the paired
    .settings-danger-confirm rule keeps the in-place delete confirmation from
    showing both of its steps at once."""
    css = _settings_css_without_comments()

    assert re.search(r"\.settings-modal-box \.btn\[hidden\][^{]*\{[^}]*display:\s*none", css), \
        "settings buttons must obey their own hidden attribute"
    assert re.search(r"\.settings-danger-confirm\[hidden\][^{]*\{[^}]*display:\s*none", css), \
        "the armed delete step must hide the other one"


def test_settings_row_buttons_use_the_btn_family():
    """The row actions were createElement('button') with no className, and the
    stylesheet has no bare `button` rule -- only `.btn`. So they rendered as
    browser defaults next to `.btn .btn-primary` form buttons in the same
    modal, and 删除 (irreversible) looked identical to 编辑."""
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert "edit.className = 'btn btn-secondary'" in script
    assert "remove.className = 'btn btn-secondary danger'" in script


def test_the_settings_button_font_size_fallback_is_gone():
    """`.settings-root button { font-size: 12px }` was the only styling on those
    unstyled buttons; it papered over the class gap instead of closing it."""
    assert ".settings-root button" not in _settings_css()
