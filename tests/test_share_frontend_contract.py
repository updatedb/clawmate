from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_share_entry_points_offer_supported_expiry_days():
    app_js = (ROOT / "dev/static/js/app.js").read_text(encoding="utf-8")
    preview_js = (ROOT / "dev/static/js/preview.js").read_text(encoding="utf-8")

    for source in (app_js, preview_js):
        assert "expires_days" in source
        for days in (1, 3, 7, 30):
            assert str(days) in source


def test_share_success_messages_do_not_claim_fixed_24_hour_expiry():
    app_js = (ROOT / "dev/static/js/app.js").read_text(encoding="utf-8")
    assert "24小时有效" not in app_js
    assert "expires_days" in app_js
