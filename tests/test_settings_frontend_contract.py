from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "dev" / "static"


def test_index_declares_two_settings_tabs():
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert 'id="btnSettings"' in html and 'id="settingsModal"' in html
    assert 'data-settings-tab="roots"' in html and 'data-settings-tab="users"' in html
    assert 'data-more="btnSettings"' in html


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
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    assert "openDirPicker" in script
    assert "/api/clawmate/settings/browse" not in script


def test_root_browse_starts_at_the_system_root():
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    assert "selectedDir: ''" in script
    assert "rootId: '.'" in script


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

    assert "#dirPickerModal" in css and "z-index: 10001" in css
    assert html.index('id="dirPickerModal"') < html.index('id="settingsModal"'), \
        "if the picker is ever moved after the settings modal this rule is no longer needed"


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
