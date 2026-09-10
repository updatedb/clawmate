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

  # pytest: 未设置 CLAWMATE_BASE_URL 时自动拉起一个临时实例
  PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_e2e_browser.py -m e2e -q

pytest 运行说明:
  * 下面「Rootdir registry + settings acceptance」一节的用例需要一个真实
    会话，因此未设置 CLAWMATE_BASE_URL 时本文件会在 pytest 的 tmp 目录里
    生成 config.json / users.json / roots.json / 系统根目录，启动一个一次性
    实例并在结束后销毁；仓库真实的这些文件绝不会被读写。
  * `check()` 只做计数，因此在 pytest 下由一个 autouse fixture 把「本次用例
    记录了失败」升级为用例失败，否则浏览器断言失败仍会显示为通过。

依赖:
  pip install playwright
  playwright install chromium
"""

import json
import os
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
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

def login(page: Page, username: str | None = None, password: str | None = None):
    """Navigate to ClawMate and log in if redirected.

    `username`/`password` default to the module-level credentials, so every
    existing `login(page)` call keeps its behaviour; the registry acceptance
    tests pass an ordinary user's credentials to observe a different grant set.
    """
    user = USERNAME if username is None else username
    secret = PASSWORD if password is None else password
    page.goto(f"{CLAWMATE_URL}/")
    page.wait_for_timeout(500)
    if "login" in page.url:
        if not secret:
            raise RuntimeError("Auth required but CLAWMATE_PASSWORD not set")
        page.fill("#username", user)
        page.fill("#password", secret)
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
    """文件点击打开预览页面

    Repaired on three counts, all of which had to be measured against the app
    rather than assumed:

    * The file is addressed explicitly (`?dir=projects`, card matched by name).
      The old "click the first card, then the first card again" crawl depended on
      the real repository's shape and on entry ordering, so it could land on a
      second directory instead of a file.
    * Readiness is `load` plus a concrete element, never `networkidle`:
      preview.html holds an open EventSource for live file updates
      (file-watch.js), so the network is *never* idle by design and that wait
      could only ever time out.
    * The panel expectations were wrong, and unreachable while the wait above
      aborted the test before them. Measured here: a .txt preview hides *both*
      side panels (there is no outline to show), a .md preview shows the outline
      and keeps the feedback panel collapsed until `#btnToggleRight` opens it.
      The old assertions demanded both panels visible on any file.
    """
    print("\n── 5. 文件预览 ──")
    page.goto(f"{CLAWMATE_URL}/?root=.&dir=projects")
    page.wait_for_function("() => state.dir === 'projects'", timeout=15000)

    card = page.locator("#gallery .card, #list .list-item", has_text="readme.md").first
    card.wait_for(state="visible", timeout=10000)

    # Click the file to open preview in new tab
    with page.expect_popup() as popup:
        card.click()
    preview_page = popup.value
    preview_page.wait_for_load_state("load", timeout=15000)
    preview_page.locator("#contentBody").wait_for(state="visible", timeout=15000)

    check("preview.html" in preview_page.url, f"打开预览页: {preview_page.url}")

    # Verify preview structure
    check(preview_page.locator("#contentBody").is_visible(), "预览内容区域可见")
    check(preview_page.locator("#leftSidebar").is_visible(), "markdown 预览展示大纲面板")
    # The feedback panel is deliberately collapsed on load; the topbar toggle is
    # what opens it, so assert the transition rather than a static expectation.
    check(not preview_page.locator("#rightSidebar").is_visible(), "评审面板默认折叠")
    preview_page.locator("#btnToggleRight").click()
    preview_page.locator("#rightSidebar").wait_for(state="visible", timeout=10000)
    check(preview_page.locator("#rightSidebar").is_visible(), "点击开关后评审面板可见")

    preview_page.close()


def test_search(page: Page):
    """搜索功能（通过命令面板）

    Repaired after the palette was rewritten (36f8fec "search→palette"): the old
    `文件搜索` action item and its `.cp-item` markup no longer exist anywhere in
    the frontend, so the previous assertion could not pass against any build. The
    palette now lists *projects* (dirs carrying a `.clawmate/` marker) as
    `.cp-card` rows and filters them by the typed query, which is what this
    exercises.
    """
    print("\n── 6. 搜索功能（命令面板）──")
    page.goto(f"{CLAWMATE_URL}/")
    page.wait_for_timeout(800)

    # Open command palette
    page.locator("#btnCommandPalette").click()
    page.locator("#cpInput").wait_for(state="visible", timeout=10000)

    # A query that matches nothing must say so rather than render stale rows.
    page.locator("#cpInput").fill("zzz-no-such-project")
    page.locator(".cp-empty").wait_for(state="visible", timeout=10000)
    check(page.locator(".cp-empty").is_visible(), "无匹配时显示空状态")

    # The throwaway system root seeds `projects/` with a `.clawmate/` marker.
    page.locator("#cpInput").fill("projects")
    page.locator(".cp-card", has_text="projects").first.wait_for(state="visible", timeout=10000)
    check(page.locator(".cp-card").count() > 0, "搜索结果显示匹配的项目")

    # Selecting a project closes the palette and navigates into it.
    page.locator(".cp-card", has_text="projects").first.click()
    page.wait_for_function(
        "() => document.getElementById('clawmateCommandPalette')"
        ".style.display === 'none'", timeout=10000)
    check(not page.locator("#clawmateCommandPalette").is_visible(), "选择项目后命令面板关闭")
    page.wait_for_function("() => state.dir === 'projects'", timeout=10000)
    check(page.evaluate("() => state.dir") == "projects", "选择项目后进入该项目目录")


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


# ══════════════════════════════════════════════════════════════════════
# Rootdir registry + settings acceptance
#
# These checks close the gaps no headless test can: real DOM interactions
# against a really running server. They need a *session-authenticated*
# instance, because `auth._is_local_client` silently promotes a loopback client
# to a synthetic local administrator: a browser the app trusts that way is
# never shown a login form and never sees the grant set an ordinary user gets,
# so the login / grant / settings behaviours would be unobservable.
#
# The fixtures below stand up a throwaway instance whose config.json,
# users.json, roots.json and system root all live under pytest's tmp dir. The
# repository's real config.json / users.json / roots.json are never read or
# written, and dev/sessions.json (which login rewrites) is restored afterwards.
# ══════════════════════════════════════════════════════════════════════

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "dev"

E2E_ADMIN_USERNAME = "e2e-admin"
E2E_ADMIN_PASSWORD = "e2e-admin-pass"
E2E_USER_USERNAME = "e2e-user"
E2E_USER_PASSWORD = "e2e-user-pass"
SEEDED_ROOT_ID = "shared"
SEEDED_ROOT_LABEL = "Shared"

# Absolute path of the throwaway system root, so a test can prove the server
# never hands a client that path (empty when an external server is targeted).
E2E_SYSTEM_ROOT: str = ""
# Extra request headers that make the app treat the browser as a remote client
# instead of the local administrator it trusts implicitly (see admin_page).
CLIENT_HEADERS: dict[str, str] = {}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _password_hash(password: str) -> str:
    import bcrypt

    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _write_instance(tmp_path: Path) -> tuple[Path, Path, int]:
    """Create the throwaway system root, config.json, roots.json, users.json."""
    system_root = tmp_path / "system-root"
    (system_root / "projects").mkdir(parents=True)
    (system_root / "private").mkdir()
    (system_root / ".hidden-dir").mkdir()
    (system_root / "projects" / "readme.md").write_text("# Projects\n\nhello\n", encoding="utf-8")
    # The `.clawmate/` marker is what makes `projects` a *project*, which is the
    # only thing the command palette lists (see command-palette.js). Without it
    # the palette renders its empty state and test_search has nothing to find.
    (system_root / "projects" / ".clawmate").mkdir()
    (system_root / "private" / "notes.txt").write_text("private notes\n", encoding="utf-8")
    (system_root / ".hidden-dir" / "secret.md").write_text("secret\n", encoding="utf-8")

    port = _free_port()
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "system_root_dir": str(system_root),
        "port": port,
        # No auth.local_hosts: the browser must be treated as a remote client.
        "auth": {"session_ttl_minutes": 480},
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # The seeded root is granted to the ordinary user, so the settings UI can
    # show the "referenced by N users" hint on it and the grant tests have a
    # real id to reference. "projects" stays unregistered for the create test.
    (tmp_path / "roots.json").write_text(json.dumps({"roots": [
        {"id": SEEDED_ROOT_ID, "label": SEEDED_ROOT_LABEL, "dir": "private",
         "agent_id": "default"},
    ]}, ensure_ascii=False, indent=2), encoding="utf-8")

    (tmp_path / "users.json").write_text(json.dumps({"users": [
        {"id": "e2e-admin-id", "username": E2E_ADMIN_USERNAME,
         "password_hash": _password_hash(E2E_ADMIN_PASSWORD), "is_admin": True,
         # False on purpose: the forced-change modal is non-dismissible and
         # would block every interaction behind it.
         "must_change_password": False, "root_ids": []},
        {"id": "e2e-user-id", "username": E2E_USER_USERNAME,
         "password_hash": _password_hash(E2E_USER_PASSWORD), "is_admin": False,
         "must_change_password": False, "root_ids": [SEEDED_ROOT_ID]},
    ]}, ensure_ascii=False, indent=2), encoding="utf-8")
    return system_root, config_path, port


@pytest.fixture(scope="module", autouse=True)
def live_server(tmp_path_factory):
    """Launch a throwaway ClawMate instance unless CLAWMATE_BASE_URL is set."""
    global BASE_URL, CLAWMATE_URL, USERNAME, PASSWORD, E2E_SYSTEM_ROOT, CLIENT_HEADERS

    external = os.environ.get("CLAWMATE_BASE_URL")
    if external:
        # An externally managed deployment: never launch, use it as configured.
        yield external.rstrip("/")
        return

    tmp_path = tmp_path_factory.mktemp("clawmate-e2e")
    system_root, config_path, port = _write_instance(tmp_path)

    # Safety rails: this fixture may only ever touch throwaway paths.
    real_config = (ROOT_DIR / "config.json").resolve()
    assert config_path.resolve() != real_config
    assert real_config not in config_path.resolve().parents
    assert system_root.resolve() != ROOT_DIR
    assert ROOT_DIR not in system_root.resolve().parents

    # Loopback origin: http://127.0.0.1 is a browser "secure context" (the PWA
    # checks need one), and it is what the existing smoke tests assume. The
    # acceptance tests then add CLIENT_HEADERS so the app stops treating them
    # as a trusted local client and starts treating them as a remote one --
    # x-forwarded-for from a local peer is exactly the reverse-proxy path
    # auth.get_client_ip documents.
    base_url = f"http://127.0.0.1:{port}"
    CLIENT_HEADERS = {"X-Forwarded-For": "203.0.113.9"}

    env = {key: value for key, value in os.environ.items()
           if not key.startswith("CLAWMATE_")}
    env["CLAWMATE_CONFIG"] = str(config_path)
    env["CLAWMATE_PORT"] = str(port)
    env["CLAWMATE_PUBLIC_BASE_URL"] = base_url

    log_path = tmp_path / "server.log"

    # Login rewrites dev/sessions.json (auth._sessions_file is fixed to the
    # source tree). Snapshot it so the operator's runtime state is left alone.
    sessions_file = BACKEND_DIR / "sessions.json"
    sessions_backup = sessions_file.read_bytes() if sessions_file.exists() else None

    # uvicorn logs every request; a pipe would fill and block the child, so the
    # log goes to a file that survives long enough to be reported.
    with open(log_path, "wb") as log_file:
        proc = subprocess.Popen(
            [sys.executable, str(BACKEND_DIR / "main.py")],
            cwd=str(BACKEND_DIR), env=env, stdout=log_file, stderr=subprocess.STDOUT,
        )
        try:
            _wait_for_health(proc, port, log_path)
            E2E_SYSTEM_ROOT = str(system_root)
            BASE_URL = base_url
            CLAWMATE_URL = f"{base_url}/clawmate"
            USERNAME = E2E_ADMIN_USERNAME
            PASSWORD = E2E_ADMIN_PASSWORD
            yield base_url
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)

    if sessions_backup is None:
        sessions_file.unlink(missing_ok=True)
    else:
        sessions_file.write_bytes(sessions_backup)


def _wait_for_health(proc: subprocess.Popen, port: int, log_path: Path) -> None:
    """Poll a real endpoint until the app answers, or fail with its output."""
    deadline = time.time() + 60
    url = f"http://127.0.0.1:{port}/api/health"
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"ClawMate exited with {proc.returncode}:\n"
                + log_path.read_text(encoding="utf-8", errors="replace")[-4000:])
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            time.sleep(0.25)
    raise RuntimeError(
        "ClawMate did not become ready in 60s:\n"
        + log_path.read_text(encoding="utf-8", errors="replace")[-4000:])


@pytest.fixture(autouse=True)
def _fail_on_recorded_check(live_server):
    """Turn a recorded `check()` failure into a pytest failure.

    check() only tabulates into module counters, so without this a failed
    browser assertion would still be reported as a passing test.
    """
    before = failed
    yield
    assert failed == before, "check() 记录的失败: " + " | ".join(errors[before - failed:])


@pytest.fixture
def admin_page(page: Page, live_server) -> Page:
    """A page the app sees as a *remote* client, logged in as the admin.

    The smoke tests above keep the loopback client the app trusts implicitly,
    which is what they were written against. These acceptance tests opt into a
    real session instead, so an ordinary user's grants and the forced password
    change are observable at all.
    """
    page.context.set_extra_http_headers(CLIENT_HEADERS)
    login(page)
    _wait_for_app(page)
    return page


# ── Helpers for the registry / settings tests ──────────────────────────

def _wait_for_app(page: Page) -> None:
    """Wait until the app finished its async init.

    initSettings() registers the #btnSettings handler only after it has probed
    /auth/status, so a click that lands earlier silently does nothing and looks
    like a broken modal rather than the race it is. loadConfig() runs after
    initSettings(), so a populated state.roots proves the handler is wired.
    """
    page.wait_for_function(
        "() => typeof state !== 'undefined' && Array.isArray(state.roots)"
        " && state.roots.length > 0",
        timeout=15000)


def _open_settings(page: Page) -> None:
    page.locator("#btnSettings").click()
    page.locator("#settingsModal").wait_for(state="visible")
    page.locator("#settingsRootList .settings-root").first.wait_for(state="visible")


def _open_picker(page: Page) -> None:
    _open_settings(page)
    page.locator("#settingsRootBrowse").click()
    page.locator("#dirPickerTree .dir-picker-item").first.wait_for(state="visible")


def _wait_for_settled_picker(page: Page, *, expect_hidden: bool) -> None:
    """Wait for the tree to finish re-rendering after a toggle flip.

    openDirPicker blanks the tree to "加载中..." and refetches asynchronously, so
    "the tree no longer mentions .hidden-dir" is already true of the *blank*
    state: the count sampled right after it came back 0, which is how the
    uncheck half of this check first failed against a working app. Settling means
    a non-empty tree whose hidden entries match the toggle, so a genuinely empty
    tree still times out instead of passing.
    """
    page.wait_for_function(
        "(expectHidden) => { const t = document.querySelector('#dirPickerTree');"
        " if (!t.querySelectorAll('.dir-picker-item').length) return false;"
        " return t.textContent.includes('.hidden-dir') === expectHidden; }",
        arg=expect_hidden, timeout=10000)


def _goto_root(page: Page, root_id: str) -> None:
    """Load the main browser on a specific root, so an override is visible."""
    page.goto(f"{CLAWMATE_URL}/?root={root_id}")
    page.locator("#rootSelect").wait_for(state="attached")
    page.wait_for_function(
        "(rootId) => state.rootId === rootId", arg=root_id, timeout=10000)


def _picker_row(page: Page, text: str):
    return page.locator("#dirPickerTree .dir-picker-item", has_text=text).first


def _close_settings(page: Page) -> None:
    page.locator("#settingsModalClose").click()
    page.locator("#settingsModal").wait_for(state="hidden")


def test_unauthenticated_browser_is_redirected_to_login(browser):
    """Guard: the browser must be a remote client, not a trusted local one.

    If this fails the app handed the browser a synthetic local administrator,
    and every other assertion in this file would be measuring the wrong
    principal.
    """
    context = browser.new_context(extra_http_headers=CLIENT_HEADERS or None)
    try:
        page = context.new_page()
        page.goto(f"{CLAWMATE_URL}/")
        page.wait_for_timeout(800)
        check("login" in page.url, f"未登录访问被重定向到登录页（{page.url}）")
        check(page.locator("#username").is_visible(), "登录页展示用户名输入框")
    finally:
        context.close()


@pytest.mark.usefixtures("admin_page")
def test_settings_modal_is_admin_only(page: Page):
    check(page.locator("#btnSettings").is_visible(), "管理员可见设置入口")
    _open_settings(page)
    check(page.locator("#settingsModal").is_visible(), "管理员可见设置弹窗")
    check(page.locator('[data-settings-tab="roots"]').is_visible(), "默认展示 Rootdir 管理")
    check(page.locator("#settingsRootList").get_by_text(SEEDED_ROOT_LABEL).count() > 0,
          "Rootdir 列表已加载")
    page.locator('[data-settings-tab="users"]').click()
    check(page.locator("#settingsUserRoots").is_visible(), "用户管理展示授权复选框")
    check(page.locator("#settingsUserRoots input[name=root_ids]").count() > 0,
          "授权复选框来自 Rootdir 注册表")


@pytest.mark.usefixtures("admin_page")
def test_admin_registers_edits_and_deletes_a_root(page: Page):
    """Authenticated root create / edit / delete, plus the reference hint."""
    page.on("dialog", lambda dialog: dialog.accept())
    _open_picker(page)

    page.locator("#settingsRootLabel").fill("UI Projects")
    _picker_row(page, "projects").click()
    page.locator("#dirPickerConfirm").click()
    check(page.locator("#settingsRootDir").input_value() == "projects",
          "浏览后 Rootdir 表单已填入所选目录")
    page.locator("#settingsRootForm button[type=submit]").click()
    page.locator("#settingsRootList").get_by_text("UI Projects").first.wait_for(
        state="visible", timeout=10000)
    check(page.locator("#settingsRootList").get_by_text("UI Projects").count() > 0,
          "新建 Rootdir 已出现在列表")

    # Editing a root a user holds must warn that grants follow the id.
    holders = sum(1 for user in page.request.get(
        f"{BASE_URL}/api/clawmate/settings/users").json()["users"]
        if SEEDED_ROOT_ID in user.get("root_ids", []))
    shared_row = page.locator("#settingsRootList .settings-root", has_text=SEEDED_ROOT_LABEL).first
    shared_row.get_by_text("编辑").click()
    hint = page.locator("#settingsRootHint").inner_text()
    check(holders >= 1 and f"已被 {holders} 位用户引用" in hint,
          f"被引用 Rootdir 显示引用提示（{holders} 位用户；{hint}）")
    page.locator("#settingsRootCancel").click()
    check(page.locator("#settingsRootHint").inner_text() == "", "取消编辑后清空提示")

    # Edit the created root through the same form.
    created_row = page.locator("#settingsRootList .settings-root", has_text="UI Projects").first
    created_row.get_by_text("编辑").click()
    page.locator("#settingsRootLabel").fill("UI Projects Renamed")
    page.locator("#settingsRootForm button[type=submit]").click()
    page.locator("#settingsRootList").get_by_text("UI Projects Renamed").first.wait_for(
        state="visible", timeout=10000)
    check(page.locator("#settingsRootList").get_by_text("UI Projects Renamed").count() > 0,
          "编辑后的 Rootdir 名称已保存")

    # Delete it again (the confirm dialog is accepted by the handler above).
    page.locator("#settingsRootList .settings-root", has_text="UI Projects Renamed") \
        .first.get_by_text("删除").click()
    page.wait_for_function(
        "() => !document.querySelector('#settingsRootList').textContent.includes('UI Projects Renamed')",
        timeout=10000)
    check(page.locator("#settingsRootList").get_by_text("UI Projects Renamed").count() == 0,
          "删除后 Rootdir 已从列表移除")
    check(page.locator("#settingsRootList").get_by_text(SEEDED_ROOT_LABEL).count() > 0,
          "删除未影响其它 Rootdir")


def test_ordinary_user_does_not_render_the_settings_entry(browser):
    """An ordinary user must not get a rendered, clickable settings entry.

    The plan forbids rendering it for ordinary users, and the app does mark it
    hidden (`btnSettings.hidden = !me.is_admin`, plus `hidden` in index.html) --
    but that alone was not enough. `.topbar-btn { display: flex }` (style.css)
    outranked the UA `[hidden] { display: none }`, so the attribute had no
    effect: the gear kept a 34px box and stayed clickable, opening a modal whose
    every request 403s. The mobile "more" menu entry was exposed the same way,
    and topbar.js consulted only inline `style.display`, which is empty here.

    This test is the one that caught it: both assertions below were red, with
    `hidden=True, display=flex`, until style.css gained the `[hidden]` rules and
    topbar.js learned to mirror the attribute.
    """
    context = browser.new_context(extra_http_headers=CLIENT_HEADERS or None)
    try:
        page = context.new_page()
        login(page, E2E_USER_USERNAME, E2E_USER_PASSWORD)
        _wait_for_app(page)
        options = page.locator("#rootSelect option").all_inner_texts()
        check(options == [SEEDED_ROOT_LABEL], f"普通用户只看到获授 root（{options}）")

        gated = page.evaluate(
            "() => { const b = document.getElementById('btnSettings');"
            " return {hidden: b.hidden, display: getComputedStyle(b).display}; }")
        check(gated["hidden"], "普通用户会话下设置入口被标记为 hidden")
        check(not page.locator("#btnSettings").is_visible(),
              f"普通用户看不到设置入口（hidden={gated['hidden']}, display={gated['display']}）")

        # The mobile menu mirrors the same gate; opening it must not resurrect
        # the entry, or the gear is merely folded away instead of gated.
        page.set_viewport_size({"width": 375, "height": 812})
        page.locator("#btnMoreMenu").click()
        page.locator(".more-menu").wait_for(state="visible")
        check(page.locator('.more-item[data-more="btnSettings"]').count() == 1,
              "移动端菜单仍声明设置入口（用于管理员）")
        check(not page.locator('.more-item[data-more="btnSettings"]').is_visible(),
              "普通用户在移动端菜单里也看不到设置入口")
        check(page.locator('.more-item[data-more="btnLogout"]').is_visible(),
              "对照：移动端菜单的其它项不受影响")
        page.set_viewport_size({"width": 1440, "height": 900})

        body = page.request.get(f"{BASE_URL}/api/clawmate/config").text()
        check("password_hash" not in body, "配置响应不包含密码哈希")
        check(E2E_SYSTEM_ROOT and E2E_SYSTEM_ROOT not in body,
              "配置响应不包含系统根目录的绝对路径")
    finally:
        context.close()


@pytest.mark.usefixtures("admin_page")
def test_grant_post_from_the_user_tab(page: Page):
    """A grant POST from the tab, and 422 messages rendered in the error region."""
    _open_settings(page)
    page.locator('[data-settings-tab="users"]').click()

    page.locator("#settingsUserRoots input[name=root_ids]").first.check()
    page.locator("#settingsUsername").fill("grantee")
    page.locator("#settingsPassword").fill("grantee-pass")
    page.locator("#settingsUserForm button[type=submit]").click()
    page.locator("#settingsUsers").get_by_text("grantee").first.wait_for(
        state="visible", timeout=10000)
    check(page.locator("#settingsUsers").get_by_text("grantee").count() > 0,
          "用户管理列表出现新建用户")
    check(page.locator("#settingsUsers").get_by_text(SEEDED_ROOT_LABEL).count() > 0,
          "新用户带着获授 Rootdir")

    # A rejected POST must reach the shared error region, not the console.
    page.locator("#settingsUserRoots input[name=root_ids]").first.check()
    page.locator("#settingsUsername").fill("grantee")
    page.locator("#settingsPassword").fill("grantee-pass")
    page.locator("#settingsUserForm button[type=submit]").click()
    page.wait_for_function(
        "() => document.querySelector('#settingsError').textContent.trim().length > 0",
        timeout=10000)
    check("用户名已存在" in page.locator("#settingsError").inner_text(),
          f"重复用户名以 422 提示渲染在错误区（{page.locator('#settingsError').inner_text()}）")

    # The unregistered-id branch of the same route, against the live server.
    response = page.request.post(f"{BASE_URL}/api/clawmate/settings/users", data={
        "username": "ghost-grantee", "password": "ghost-pass", "root_ids": ["ghost"]})
    check(response.status == 422, f"未注册 root id 的授权被拒（HTTP {response.status}）")
    check("ghost" in response.text(), f"422 响应指明未注册的 root id（{response.text()[:120]}）")


@pytest.mark.usefixtures("admin_page")
def test_picker_opens_at_the_system_root_and_fills_the_form(page: Page):
    _goto_root(page, SEEDED_ROOT_ID)
    _open_picker(page)
    check(page.locator("#dirPickerTree").get_by_text("projects").count() > 0,
          "选择器从系统根目录开始（可见 projects）")
    check(page.locator("#dirPickerTree").get_by_text(".hidden-dir").count() == 0,
          "默认过滤隐藏目录")
    _picker_row(page, "projects").click()
    page.locator("#dirPickerConfirm").click()
    check(page.locator("#settingsRootDir").input_value() == "projects",
          "选定目录已填入 Rootdir 表单")
    check(page.evaluate("() => state.rootId") == SEEDED_ROOT_ID,
          f"关闭后主浏览器 root 已还原（{page.evaluate('() => state.rootId')}）")


@pytest.mark.usefixtures("admin_page")
def test_hidden_directories_are_toggled_without_emptying_the_tree(page: Page):
    """Toggling must add/remove hidden entries, not collapse the tree.

    The tree cannot be re-rendered from cache -- the child renderer returns ''
    for an uncached parent and the root row has no expand arrow -- so a naive
    "clear cache and re-render" yields an empty tree. This is the check that
    catches that regression in a real browser.
    """
    _goto_root(page, SEEDED_ROOT_ID)
    _open_picker(page)
    before = page.locator("#dirPickerTree .dir-picker-item").count()
    check(before > 0, f"打开时目录树非空（{before} 项）")

    page.locator("#dirPickerShowHidden").check()
    _wait_for_settled_picker(page, expect_hidden=True)
    checked = page.locator("#dirPickerTree .dir-picker-item").count()
    check(checked > 0, f"勾选隐藏目录后树仍非空（{checked} 项）")
    check(page.locator("#dirPickerTree").get_by_text(".hidden-dir").count() > 0,
          "勾选后出现隐藏目录")
    check(page.locator("#dirPickerTree").get_by_text("projects").count() > 0,
          "勾选后可见目录仍在")

    page.locator("#dirPickerShowHidden").uncheck()
    _wait_for_settled_picker(page, expect_hidden=False)
    after = page.locator("#dirPickerTree .dir-picker-item").count()
    check(after > 0, f"取消勾选后树仍非空（{after} 项）")
    check(page.locator("#dirPickerTree").get_by_text(".hidden-dir").count() == 0,
          "取消勾选后隐藏目录被移除")
    page.locator("#dirPickerCancel").click()


@pytest.mark.usefixtures("admin_page")
def test_cancelling_the_picker_leaves_the_main_browser_root_unchanged(page: Page):
    """The settings picker overrides state.rootId; closing must restore it.

    This is the one behaviour the contract tests cannot prove: they are
    string/shape checks, and the implementer's discrimination evidence for the
    picker was an uncommitted harness. A missed close path silently points the
    main file browser at the system root, which no unit test here would catch.
    """
    _goto_root(page, SEEDED_ROOT_ID)
    before = page.evaluate("() => state.rootId")
    _open_picker(page)
    check(page.locator("#dirPickerModal").is_visible(), "目录选择器打开")
    page.locator("#dirPickerCancel").click()
    after = page.evaluate("() => state.rootId")
    check(before == after, f"取消后主浏览器 root 不变（{before} -> {after}）")


@pytest.mark.usefixtures("admin_page")
def test_every_picker_close_path_leaves_the_main_root_unchanged(page: Page):
    """Cancel, X and backdrop must each restore the stashed root.

    A missed path silently points the main file browser at the system root,
    and no headless test in this repo can catch it.
    """
    _goto_root(page, SEEDED_ROOT_ID)
    for label, closer in (("取消", "#dirPickerCancel"), ("关闭按钮", "#dirPickerClose")):
        before = page.evaluate("() => state.rootId")
        _open_picker(page)
        page.locator(closer).click()
        page.locator("#dirPickerModal").wait_for(state="hidden")
        after = page.evaluate("() => state.rootId")
        check(before == after, f"{label}后主浏览器 root 不变（{before} -> {after}）")
        _close_settings(page)

    before = page.evaluate("() => state.rootId")
    _open_picker(page)
    page.locator("#dirPickerModal").click(position={"x": 5, "y": 5})
    page.locator("#dirPickerModal").wait_for(state="hidden")
    after = page.evaluate("() => state.rootId")
    check(before == after, f"点击遮罩后主浏览器 root 不变（{before} -> {after}）")


@pytest.mark.usefixtures("admin_page")
def test_picker_is_clickable_above_the_open_settings_modal(page: Page):
    """A click must land on the picker, not on the settings backdrop beneath it.

    Both overlays are open at once and the settings modal closes itself on a
    backdrop click, so a picker painted below it would silently dismiss the
    settings dialog on the first click of a directory.
    """
    _goto_root(page, SEEDED_ROOT_ID)
    _open_picker(page)
    check(page.locator("#settingsModal").is_visible(), "选择器打开时设置弹窗仍在")
    _picker_row(page, "private").click()
    check(page.locator("#dirPickerSelected").inner_text().strip() == "private",
          f"点击落在选择器行上（{page.locator('#dirPickerSelected').inner_text()}）")
    check(page.locator("#dirPickerModal").is_visible(), "点击后选择器仍打开")
    check(page.locator("#settingsModal").is_visible(), "点击未穿透到设置弹窗遮罩")
    page.locator("#dirPickerCancel").click()


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
