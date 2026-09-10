from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "dev" / "static"


def test_index_declares_grouped_settings_modal():
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert 'id="btnSettings"' in html
    assert 'id="settingsModal"' in html
    assert 'data-settings-section="users"' in html
    assert 'data-settings-section="rootdirs"' in html
    assert 'data-more="btnSettings"' in html
    assert 'data-settings-action="edit"' in html
    assert 'data-settings-action="delete"' in html


def test_settings_script_uses_identity_and_settings_endpoints():
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    assert "/api/clawmate/auth/status" in script
    assert "/api/clawmate/settings/users" in script
    assert "method:'PATCH'" in script
    assert "method:'DELETE'" in script


def test_settings_script_reports_failed_admin_requests_without_iterating_error_payload():
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
