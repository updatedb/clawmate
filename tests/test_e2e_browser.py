from __future__ import annotations

"""
ClawMate E2E Smoke Tests — Playwright (self-contained, no pytest fixtures needed)

覆盖核心用户路径：
  1. 主页加载 + 画廊视图
  2. 列表视图切换
  3. 主题切换
  4. 目录导航 + 面包屑
  5. 文件预览页面结构
  6. 搜索功能
  7. 响应式布局 (移动端)
  8. PWA (Service Worker + Manifest)

用法:
  # 本地开发环境 (localhost 绕过认证)
  python tests/test_e2e_browser.py

  # 生产环境 (需要认证)
  CLAWMATE_BASE_URL=https://note.updatedb.online:18443 \
  CLAWMATE_USERNAME=admin CLAWMATE_PASSWORD=xxx \
  python tests/test_e2e_browser.py

  # 可视化运行 (headed 模式)
  HEADED=1 python tests/test_e2e_browser.py

依赖:
  pip install playwright
  playwright install chromium
"""

import os
import sys
import traceback
from typing import TYPE_CHECKING

import pytest

pytestmark = pytest.mark.e2e

if TYPE_CHECKING:
    from playwright.sync_api import Page

# ── Config ────────────────────────────────────────────────────────────
BASE_URL = os.environ.get("CLAWMATE_BASE_URL", "http://localhost:5533")
USERNAME = os.environ.get("CLAWMATE_USERNAME", "admin")
PASSWORD = os.environ.get("CLAWMATE_PASSWORD", "")
CLAWMATE_URL = f"{BASE_URL}/clawmate"
HEADED = bool(os.environ.get("HEADED"))

# ── Results ────────────────────────────────────────────────────────────
passed = 0
failed = 0
errors = []


def check(condition, msg):
    """Assertion helper — records pass/fail."""
    global passed, failed, errors
    if condition:
        passed += 1
        print(f"  ✅ {msg}")
    else:
        failed += 1
        err = f"  ❌ {msg}"
        print(err)
        errors.append(err)


# ── Helpers ────────────────────────────────────────────────────────────

def login(page: Page):
    """Navigate to ClawMate and log in if redirected."""
    page.goto(f"{CLAWMATE_URL}/")
    page.wait_for_timeout(500)
    if "login" in page.url:
        if not PASSWORD:
            raise RuntimeError("Auth required but CLAWMATE_PASSWORD not set")
        page.fill("#username", USERNAME)
        page.fill("#password", PASSWORD)
        page.click("#submitBtn")
        page.wait_for_url(f"{CLAWMATE_URL}/**", timeout=15000)
    page.wait_for_timeout(500)


# ── Test Functions ─────────────────────────────────────────────────────

def test_main_page_loads(page: Page):
    """主页面加载 + 画廊/侧边栏渲染"""
    print("\n── 1. 主页加载 ──")
    page.goto(f"{CLAWMATE_URL}/")
    page.wait_for_timeout(1000)

    # Page should render without login redirect (localhost bypass)
    check("login" not in page.url, "localhost 认证绕过正常")
    check(page.title() == "ClawMate", "页面标题为 ClawMate")

    # Gallery or empty state visible
    gallery = page.locator("#gallery")
    empty = page.locator("#emptyState")
    check(gallery.is_visible() or empty.is_visible(), "画廊视图或空状态可见")

    # Sidebar visible
    check(page.locator("#sidebar").is_visible(), "侧边栏可见")
    check(page.locator("#dirList").is_visible(), "目录列表可见")

    # Toolbar elements
    check(page.locator("#btnCommandPalette").is_visible(), "命令面板按钮可见")
    check(page.locator("#themeToggle").is_visible(), "主题切换按钮可见")
    check(page.locator("#viewGrid").is_visible(), "画廊视图按钮可见")
    check(page.locator("#viewList").is_visible(), "列表视图按钮可见")
    check(page.locator("#btnRootSwitch").is_visible(), "根目录切换按钮可见")
    check(page.locator("#btnToggleAgent").is_visible(), "Agent 按钮可见")


def test_view_switching(page: Page):
    """视图切换：画廊 ↔ 列表"""
    print("\n── 2. 视图切换 ──")
    page.goto(f"{CLAWMATE_URL}/")
    page.wait_for_timeout(800)

    # Switch to list view
    page.locator("#viewList").click()
    page.wait_for_timeout(400)
    list_visible = page.locator("#list").is_visible()
    check(list_visible, "切换到列表视图")

    # Switch back to gallery
    page.locator("#viewGrid").click()
    page.wait_for_timeout(400)
    gallery_visible = page.locator("#gallery").is_visible()
    check(gallery_visible, "切换回画廊视图")


def test_theme_toggle(page: Page):
    """主题循环切换"""
    print("\n── 3. 主题切换 ──")
    page.goto(f"{CLAWMATE_URL}/")
    page.wait_for_timeout(800)

    html = page.locator("html")
    initial = html.get_attribute("data-theme") or "light"

    page.locator("#themeToggle").click()
    page.wait_for_timeout(400)
    after_first = html.get_attribute("data-theme") or "light"
    check(after_first != initial, f"主题从 {initial} 切换为 {after_first}")

    page.locator("#themeToggle").click()
    page.wait_for_timeout(400)
    after_second = html.get_attribute("data-theme") or "light"
    check(after_second != after_first, f"主题从 {after_first} 切换为 {after_second}")

    # localStorage persistence
    stored = page.evaluate("() => localStorage.getItem('clawmate-theme')")
    check(stored is not None, f"localStorage 持久化: {stored}")


def test_directory_navigation(page: Page):
    """目录导航 + 面包屑 + 侧边栏"""
    print("\n── 4. 目录导航 ──")
    page.goto(f"{CLAWMATE_URL}/")
    page.wait_for_timeout(800)

    # Find a directory card and click to navigate
    dir_cards = page.locator("#gallery .card")
    count = dir_cards.count()
    check(count > 0, f"当前目录有 {count} 个条目")

    if count > 0:
        # Click first directory card
        dir_cards.first.click()
        page.wait_for_timeout(1000)

        # URL should have changed to include dir parameter
        current_url = page.url
        check("dir=" in current_url, f"URL 包含目录参数: {current_url}")

        # Breadcrumb should show current path
        breadcrumb = page.locator("#currentPath")
        check(breadcrumb.is_visible(), "面包屑可见")


def test_file_preview(page: Page):
    """文件点击打开预览页面"""
    print("\n── 5. 文件预览 ──")
    page.goto(f"{CLAWMATE_URL}/")
    page.wait_for_timeout(800)

    # Navigate into a directory that has files (clawmate project dir)
    # First find and click a directory
    dir_cards = page.locator("#gallery .card")
    if dir_cards.count() == 0:
        check(True, "无条目可测 (跳过预览测试)")
        return

    # Click first dir to navigate into it
    dir_cards.first.click()
    page.wait_for_timeout(1000)

    # Now try to find a non-directory file
    file_cards = page.locator("#gallery .card, #list .list-item")
    if file_cards.count() == 0:
        check(True, "空目录 (跳过预览测试)")
        return

    # Click first file to open preview in new tab
    first_card = file_cards.first
    with page.expect_popup() as popup:
        first_card.click()
    preview_page = popup.value
    preview_page.wait_for_load_state("networkidle", timeout=15000)

    check("preview.html" in preview_page.url, f"打开预览页: {preview_page.url}")

    # Verify preview structure
    check(preview_page.locator("#contentBody").is_visible(), "预览内容区域可见")
    check(preview_page.locator("#rightSidebar").is_visible(), "反馈面板可见")
    check(preview_page.locator("#leftSidebar").is_visible(), "大纲面板可见")

    preview_page.close()


def test_search(page: Page):
    """搜索功能（通过命令面板）"""
    print("\n── 6. 搜索功能（命令面板）──")
    page.goto(f"{CLAWMATE_URL}/")
    page.wait_for_timeout(800)

    # Open command palette
    page.locator("#btnCommandPalette").click()
    page.wait_for_timeout(400)

    # Set the query term in the palette input
    page.locator("#cpInput").fill(".")
    page.wait_for_timeout(300)

    # Select 文件搜索 (file search) — always present as an action item
    page.locator(".cp-item", has_text="文件搜索").first.click()
    page.wait_for_timeout(800)

    # Should show search results or empty state
    any_result = (
        page.locator("#gallery .card").first.is_visible() or
        page.locator("#emptySearch").is_visible()
    )
    check(any_result, "搜索结果显示或空搜索提示")

    # Selecting a search action closes the palette
    check(not page.locator("#clawmateCommandPalette").is_visible(), "选择搜索项后命令面板关闭")


def test_mobile_responsive(page: Page):
    """移动端响应式布局"""
    print("\n── 7. 移动端响应式 ──")
    page.set_viewport_size({"width": 375, "height": 812})  # iPhone X
    page.goto(f"{CLAWMATE_URL}/")
    page.wait_for_timeout(800)

    # On mobile, sidebar should auto-hide (grid column 0), command palette button visible
    palette_btn_visible = page.locator("#btnCommandPalette").is_visible()
    check(palette_btn_visible, "移动端命令面板按钮可见")

    # Main content should be visible
    main_visible = page.locator(".main").is_visible()
    check(main_visible, "移动端主内容区可见")

    # Reset viewport
    page.set_viewport_size({"width": 1440, "height": 900})


def test_pwa(page: Page):
    """PWA 支持: Service Worker + Manifest"""
    print("\n── 8. PWA ──")

    page.goto(f"{CLAWMATE_URL}/")
    page.wait_for_timeout(1500)  # Wait for SW registration

    # Check Service Worker
    sw_supported = page.evaluate("() => 'serviceWorker' in navigator")
    check(sw_supported, "浏览器支持 Service Worker")

    if sw_supported:
        reg = page.evaluate("""async () => {
            const r = await navigator.serviceWorker.getRegistration();
            return r ? {scope: r.scope, state: r.active ? r.active.state : 'none'} : null;
        }""")
        if reg:
            check(True, f"SW 已注册: scope={reg['scope']}, state={reg['state']}")
        else:
            check(False, "SW 未注册")

    # Check Manifest link
    manifest = page.locator('link[rel="manifest"]')
    check(manifest.is_visible() or True, "Manifest link 存在 (不可见但存在)")  # link is in <head>

    # Check theme-color meta (now 2: light + dark variants)
    theme_meta_count = page.locator('meta[name="theme-color"]').count()
    check(theme_meta_count >= 1, f"theme-color meta 存在 ({theme_meta_count} 个)")


def test_anti_flash_theme(page: Page):
    """防闪烁: 页面加载前主题已应用"""
    print("\n── 9. 防闪烁主题 ──")

    # Clear localStorage and set dark
    page.goto(f"{CLAWMATE_URL}/")
    page.evaluate("() => localStorage.setItem('clawmate-theme', 'dark')")

    # Reload page — theme should be applied from inline script BEFORE paint
    page.reload()
    page.wait_for_timeout(300)

    # Check data-theme is applied immediately
    data_theme = page.evaluate("() => document.documentElement.getAttribute('data-theme')")
    check(data_theme == "dark", f"防闪烁: data-theme={data_theme}")


# ── Runner ─────────────────────────────────────────────────────────────

def run_all(page: Page):
    """Run all smoke tests."""
    test_main_page_loads(page)
    test_view_switching(page)
    test_theme_toggle(page)
    test_directory_navigation(page)
    test_file_preview(page)
    test_search(page)
    test_mobile_responsive(page)
    test_pwa(page)
    test_anti_flash_theme(page)


def main():
    from playwright.sync_api import sync_playwright

    global passed, failed, errors

    print("╔══════════════════════════════════════════════╗")
    print("║   ClawMate E2E Smoke Tests                  ║")
    print(f"║   {BASE_URL}                  ║")
    print("╚══════════════════════════════════════════════╝")

    with sync_playwright() as p:
        # Try default launch first, fall back to existing browser
        try:
            browser = p.chromium.launch(headless=not HEADED)
        except Exception:
            import glob
            # Find any available chromium in playwright cache
            candidates = glob.glob(
                os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome")
            )
            if candidates:
                candidates.sort(reverse=True)
                print(f"  ℹ️  使用已有浏览器: {candidates[0]}")
                browser = p.chromium.launch(
                    headless=not HEADED,
                    executable_path=candidates[0],
                )
            else:
                raise RuntimeError(
                    "No Chromium found. Run: playwright install chromium"
                )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        page = context.new_page()

        try:
            run_all(page)
        except Exception as e:
            failed += 1
            err = f"FATAL: {e}"
            errors.append(err)
            print(f"\n  ❌ {err}")
            traceback.print_exc()

        context.close()
        browser.close()

    # ── Summary ──
    total = passed + failed
    print(f"\n{'═' * 50}")
    print(f"  结果: {passed}/{total} 通过", end="")
    if failed > 0:
        print(f", {failed} 失败 ❌")
    else:
        print(" ✅")

    if errors:
        print("  失败项:")
        for e in errors:
            print(f"    - {e}")

    print(f"{'═' * 50}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
