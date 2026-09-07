"""Browser release-gate entry point for the terminal-v2 gray release.

Run this suite only against a started ClawMate instance with
``CLAWMATE_E2E_URL`` set. The default unit suite excludes the ``e2e`` marker.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.e2e


def test_terminal_v2_bundle_is_available_to_browser_runtime():
    pytest.importorskip("playwright.sync_api")
    base_url = os.environ.get("CLAWMATE_E2E_URL")
    if not base_url:
        pytest.skip("set CLAWMATE_E2E_URL to run browser terminal-v2 gates")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"{base_url.rstrip('/')}/clawmate/", wait_until="networkidle")
            assert page.locator('script[src="./dist/terminal.js"]').count() == 1
            assert page.locator('link[href="./dist/terminal.css"]').count() == 1
        finally:
            browser.close()
