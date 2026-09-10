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


def test_settings_script_uses_identity_and_settings_endpoints():
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    assert "/api/clawmate/auth/me" in script
    assert "/api/clawmate/settings/users" in script
