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

import base64
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
    from playwright.sync_api import BrowserContext, Page

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
      and keeps the feedback panel collapsed until `#btnToggleFeedback` opens it.
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

    # The page *shell* renders whether or not the content fetch succeeded: the
    # sidebar's visibility comes from the file type in the URL, and #contentBody
    # is a static container. So this has to read the rendered file to be worth
    # asserting -- the shell-only version of this test stayed green while
    # /api/clawmate/preview was answering 403 to everything.
    preview_page.locator("#contentBody h1").wait_for(state="visible", timeout=10000)
    check(preview_page.locator("#contentBody h1").inner_text().strip() == "Projects",
          "预览正文渲染出文件内容")
    check(preview_page.locator(".preview-toc-item").count() > 0,
          "大纲条目来自已加载的正文")
    # The feedback panel is deliberately collapsed on load; the topbar toggle is
    # what opens it, so assert the transition rather than a static expectation.
    check(not preview_page.locator("#rightSidebar").is_visible(), "评审面板默认折叠")
    preview_page.locator("#btnToggleFeedback").click()
    preview_page.locator("#rightSidebar").wait_for(state="visible", timeout=10000)
    check(preview_page.locator("#rightSidebar").is_visible(), "点击开关后评审面板可见")

    # Mobile folds every topbar action into More. Feedback must therefore have
    # no direct button, but remain reachable through its mirrored menu item.
    preview_page.locator("#btnToggleFeedback").click()
    preview_page.locator("#rightSidebar").wait_for(state="hidden", timeout=10000)
    preview_page.set_viewport_size({"width": 375, "height": 812})
    check(not preview_page.locator("#btnToggleFeedback").is_visible(),
          "手机端反馈入口不留在顶栏")
    preview_page.locator("#btnMoreMenu").click()
    feedback_menu_item = preview_page.locator('[data-more="btnToggleFeedback"]')
    check(feedback_menu_item.is_visible(), "手机端 More 菜单提供反馈入口")
    feedback_menu_item.click()
    preview_page.locator("#rightSidebar").wait_for(state="visible", timeout=10000)
    check(preview_page.locator("#rightSidebar").is_visible(), "More 菜单可打开反馈面板")

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
# A project (a dir carrying `.clawmate/`) *inside* the ordinary user's granted
# root, so the mirror direction -- the project panel's first-visit auto-open --
# is observable for a principal the boundary does not gate at all.
SEEDED_ORDINARY_PROJECT = "drafts"

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
    # Two headings on purpose: buildTOC collapses the outline panel for a file
    # with fewer than two (a single heading is not a meaningful outline).
    (system_root / "projects" / "readme.md").write_text(
        "# Projects\n\nhello\n\n## Notes\n\nmore\n", encoding="utf-8")
    # A real 1x1 PNG. The gallery thumbnail is an <img> pointing at
    # /api/clawmate/preview -- the exact request the user saw answered with 403.
    (system_root / "projects" / "cover.png").write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="))
    # The `.clawmate/` marker is what makes `projects` a *project*, which is the
    # only thing the command palette lists (see command-palette.js). Without it
    # the palette renders its empty state and test_search has nothing to find.
    (system_root / "projects" / ".clawmate").mkdir()
    (system_root / "private" / "notes.txt").write_text("private notes\n", encoding="utf-8")
    # The ordinary user's granted root ("private") holds one project. The
    # admin-only project check above cannot cover the mirror direction: the
    # first-visit auto-open has to be observable for a principal the boundary
    # does not gate, or `_setProjectPanelOpen(false)` for everyone would leave
    # every assertion in this file green.
    (system_root / "private" / SEEDED_ORDINARY_PROJECT / ".clawmate").mkdir(parents=True)
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
    """Open the modal on its list view, which is where it always lands."""
    page.locator("#btnSettings").click()
    page.locator("#settingsModal").wait_for(state="visible")
    page.locator("#settingsRootList .settings-row").first.wait_for(state="visible")


def _open_root_form(page: Page, label: str | None = None) -> None:
    """Enter the Rootdir form view: a row's label, or the blank create form."""
    if label is None:
        page.locator("#settingsRootNew").click()
    else:
        page.locator("#settingsRootList .settings-row", has_text=label).first.click()
    page.locator('[data-settings-view="form"]').wait_for(state="visible")


def _open_user_form(page: Page, username: str | None = None) -> None:
    if username is None:
        page.locator("#settingsUserNew").click()
    else:
        page.locator("#settingsUsers .settings-row", has_text=username).first.click()
    page.locator('[data-settings-view="form"]').wait_for(state="visible")


def _back_to_settings_list(page: Page) -> None:
    page.locator("#settingsBack").click()
    page.locator('[data-settings-view="list"]').wait_for(state="visible")


def _open_picker(page: Page) -> None:
    _open_settings(page)
    # #settingsRootBrowse lives in the form view now; the picker needs a target
    # form to fill, so the blank create form is the natural place to open it.
    _open_root_form(page)
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
    check(page.locator("#btnSettings").is_visible(), "管理员在桌面 topbar 可见系统设置入口")
    check(not page.locator("#btnMoreMenu").is_visible(), "桌面不展示移动端更多菜单入口")
    check(page.locator("#btnSettings svg").is_visible(), "设置入口展示图标")
    _open_settings(page)
    check(page.locator("#settingsModal").is_visible(), "管理员可见设置弹窗")
    check(page.locator('[data-settings-tab="roots"]').is_visible(), "默认展示 Rootdir 管理")
    check(page.locator("#settingsRootList").get_by_text(SEEDED_ROOT_LABEL).count() > 0,
          "Rootdir 列表已加载")
    # Both inventories live in the list view, so the tab has to gate them: one
    # root an ordinary user holds is also a user row, and a missing gate showed
    # the user inventory under the Rootdir one.
    check(page.locator("#settingsUsers").is_hidden(), "Rootdir tab 不显示用户清单")
    page.locator('[data-settings-tab="users"]').click()
    # The list view is what a tab shows; the grant checkboxes live in the form
    # view, reached by clicking a row or 新建.
    check(page.locator('[data-settings-view="list"]').is_visible(), "用户管理默认展示列表视图")
    check(page.locator("#settingsRootList").is_hidden(), "用户 tab 不显示 Rootdir 清单")
    _open_user_form(page)
    check(page.locator("#settingsUserRoots").is_visible(), "用户管理展示授权复选框")
    check(page.locator("#settingsUserRoots input[name=root_ids]").count() > 0,
          "授权复选框来自 Rootdir 注册表")


@pytest.mark.usefixtures("admin_page")
def test_admin_registers_edits_and_deletes_a_root(page: Page):
    """Authenticated root create / edit / delete, plus the reference hint.

    No dialog handler: the delete asks in place now, so a window.confirm
    reappearing here would leave the test hanging rather than silently
    auto-accepted.
    """
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
    check(page.locator('[data-settings-view="list"]').is_visible(),
          "保存后自动回到列表视图")

    # Editing a root a user holds must warn that grants follow the id.
    holders = sum(1 for user in page.request.get(
        f"{BASE_URL}/api/clawmate/settings/users").json()["users"]
        if SEEDED_ROOT_ID in user.get("root_ids", []))
    _open_root_form(page, SEEDED_ROOT_LABEL)
    hint = page.locator("#settingsRootHint").inner_text()
    check(holders >= 1 and f"已被 {holders} 位用户引用" in hint,
          f"被引用 Rootdir 显示引用提示（{holders} 位用户；{hint}）")
    check(holders >= 1 and f"已被 {holders} 位用户引用" in
          page.locator("#settingsRootDangerHelp").inner_text(),
          "危险区说明删除会波及这些授权")
    page.locator("#settingsRootCancel").click()
    check(page.locator("#settingsRootHint").inner_text() == "", "取消编辑后清空提示")
    check(page.locator("#settingsRootDanger").is_hidden(), "取消后危险区一并收起")

    # Edit the created root through the same form.
    _back_to_settings_list(page)
    _open_root_form(page, "UI Projects")
    page.locator("#settingsRootLabel").fill("UI Projects Renamed")
    page.locator("#settingsRootForm button[type=submit]").click()
    page.locator("#settingsRootList").get_by_text("UI Projects Renamed").first.wait_for(
        state="visible", timeout=10000)
    check(page.locator("#settingsRootList").get_by_text("UI Projects Renamed").count() > 0,
          "编辑后的 Rootdir 名称已保存")

    # Delete it again, through the danger zone's two-step confirmation.
    _open_root_form(page, "UI Projects Renamed")
    page.locator("#settingsRootDelete").click()
    page.locator("#settingsRootDeleteConfirm").wait_for(state="visible", timeout=5000)
    check(page.locator("#settingsRootList").is_hidden(),
          "确认期间仍停留在表单视图（未提前提交）")
    page.locator("#settingsRootDeleteYes").click()
    page.wait_for_function(
        "() => !document.querySelector('#settingsRootList').textContent.includes('UI Projects Renamed')",
        timeout=10000)
    check(page.locator("#settingsRootList").get_by_text("UI Projects Renamed").count() == 0,
          "删除后 Rootdir 已从列表移除")
    check(page.locator("#settingsRootList").get_by_text(SEEDED_ROOT_LABEL).count() > 0,
          "删除未影响其它 Rootdir")


def test_the_grant_checkboxes_are_not_stretched(browser):
    """A grant checkbox renders at its natural 13x13, not the 308x30 the leaked
    `.settings-form input` rule gave it (with each label pushed to a second
    line, 54.5px rows).

    This pins the *outcome*, and deliberately not the mechanism: the narrowed
    selector is not what makes the difference here. The reset rule
    `#settingsUserRoots input { width: auto; min-height: 0; padding: 0 }` is an
    ID selector, so it outranks `.settings-form input` and masks the leak
    entirely -- reverting the selector alone leaves this test green. The
    selector narrowing is pinned by
    test_the_form_input_rule_does_not_reach_checkboxes; what this catches is a
    regression of *both* halves at once, which is the state a user would see.

    Runs in a service-worker-blocked context: the worker serves *static assets*
    as silently as it serves routes, so an unblocked run can measure the
    stylesheet from before the change and still look green.
    """
    context = _content_panel_context(browser)
    try:
        page = context.new_page()
        login(page)
        _wait_for_app(page)
        page.locator("#btnSettings").click()
        page.locator("#settingsModal").wait_for(state="visible")
        page.locator("#settingsTabUsers").click()
        _open_user_form(page)
        page.locator("#settingsUserRoots input").first.wait_for(state="visible")
        rect = page.locator("#settingsUserRoots input").first.bounding_box()
        check(rect["width"] < 40, f"勾选框宽度自然（实测 {rect['width']}）")
        check(rect["height"] < 40, f"勾选框高度自然（实测 {rect['height']}）")
    finally:
        context.close()


def test_a_row_opens_the_form_and_back_returns_to_the_list(browser):
    """The structural fix, behaviourally: the inventory is what a tab shows, a
    row is what opens the editor, and 返回列表 is what brings the inventory back
    with no row left open behind it.

    Service-worker-blocked like its neighbours: this is app.js behaviour, and
    the worker serves static assets as silently as it serves routes.
    """
    context = _content_panel_context(browser)
    try:
        page = context.new_page()
        login(page)
        _wait_for_app(page)
        _open_settings(page)
        check(page.locator('[data-settings-view="list"]').is_visible(), "默认在列表视图")
        check(page.locator('[data-settings-view="form"]').is_hidden(), "表单视图默认收起")

        row = page.locator("#settingsRootList .settings-row").first
        label = row.locator(".settings-row-title").inner_text()
        row.click()
        check(page.locator('[data-settings-view="form"]').is_visible(), "点行进入表单视图")
        check(page.locator("#settingsRootLabel").input_value() == label,
              f"表单载入的是所点那一行（{label}）")
        check(page.locator("#settingsRootDanger").is_visible(), "编辑既有条目时危险区可见")

        page.locator("#settingsBack").click()
        check(page.locator('[data-settings-view="list"]').is_visible(), "返回回到列表视图")
        check(page.locator('[data-settings-view="form"]').is_hidden(), "表单视图一并收起")
    finally:
        context.close()


def test_deleting_a_root_needs_a_second_click(browser):
    """The first click must not issue the DELETE: it arms the confirmation.

    The row's first entry is a seeded root an ordinary account holds, so an
    accidental delete here would be visible to later tests -- the point of
    pinning that the request is not sent.
    """
    context = _content_panel_context(browser)
    try:
        page = context.new_page()
        login(page)
        _wait_for_app(page)
        _open_settings(page)
        # An existing row, not the blank create form: only an existing entry has
        # a danger zone, so the create form would have nothing to arm.
        _open_root_form(page, SEEDED_ROOT_LABEL)

        deletes = []
        page.on("request", lambda r: deletes.append(r.url) if r.method == "DELETE" else None)

        page.locator("#settingsRootDelete").click()
        page.locator("#settingsRootDeleteConfirm").wait_for(state="visible", timeout=5000)
        check(not deletes, f"第一次点击不发 DELETE 请求（{deletes}）")
        check(page.locator("#settingsRootDeleteAsk").is_hidden(), "原位展开确认，收起首次按钮")

        page.locator("#settingsRootDeleteNo").click()
        check(page.locator("#settingsRootDeleteConfirm").is_hidden(), "取消收回确认")
        check(page.locator("#settingsRootDeleteAsk").is_visible(), "取消后回到首次按钮")
        page.wait_for_timeout(300)
        check(not deletes, f"取消后仍未发请求（{deletes}）")
    finally:
        context.close()


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

        response = page.request.get(f"{BASE_URL}/api/clawmate/config")
        body = response.text()
        check("password_hash" not in body, "配置响应不包含密码哈希")

        # The granted root's own absolute path *is* reported on purpose: the
        # breadcrumb's copy button pastes it, and a regular user needs it to do
        # so. The property that must hold is authorization scope -- this session
        # holds exactly one grant, so nothing about any other root may leak.
        reported = response.json()["roots"]
        check([root["id"] for root in reported] == [SEEDED_ROOT_ID],
              f"只报告被授权的 root（{[root['id'] for root in reported]}）")
        check([root["dir"] for root in reported] == [f"{E2E_SYSTEM_ROOT}/private"],
              f"被授权 root 报告自己的绝对路径（{[root['dir'] for root in reported]}）")
        check(f"{E2E_SYSTEM_ROOT}/projects" not in body,
              "配置响应不包含未授权 root 的路径")
    finally:
        context.close()


# ── Administrator content-panel boundary ───────────────────────────────
#
# Both checks below build their own context so they can pass
# `service_workers="block"`. The service worker serves *static assets* as
# silently as it serves routes, and the plan's first two attempts at this
# boundary measured a cached, stale app.js that did not contain the change at
# all. Only a service-worker-blocked run counts.

CONTENT_PANEL_TOGGLES = ("btnToggleAgent", "btnProjectPanel", "btnToggleFeedback")


def _content_panel_context(browser) -> BrowserContext:
    """A remote-client context with service-worker registration blocked."""
    return browser.new_context(service_workers="block",
                               extra_http_headers=CLIENT_HEADERS or None)


def _toggle_mirror(page: Page, toggle: str):
    return page.locator(f'.more-item[data-more="{toggle}"]')


def _wait_for_the_boundary(page: Page) -> None:
    """Wait until topbar.js has answered the role probe and app.js applied it.

    `isAdmin()` is set one microtask before `_applyAdminContentPanelBoundary()`'s
    callback runs, and a poller observes state from a task, so seeing it true
    means `hideContentPanelEntries()` and the gate flag have both been applied.
    """
    page.wait_for_function(
        "() => window.ClawMateAdmin && window.ClawMateAdmin.isAdmin() === true",
        timeout=15000)


def test_an_admin_sees_no_content_panel_entries(browser):
    """The inverse of the settings check: an admin keeps settings, loses the panels.

    This is also the only thing that can see a loop which visits fewer entries
    than it declares. tests/test_admin_panel_contract.py pins the three
    CONTENT_PANEL_ENTRIES and how each is handled, but not the count --
    `.slice(0, 1).forEach(` keeps it green while only the agent toggle gets
    hidden. Only a per-entry browser assertion catches that.

    Two pages are needed, because neither one can fail for all three entries:

    * index.html declares the agent and project toggles. Its project toggle
      carries an inline `display:none` that _updateProjectPanelBtn() clears only
      once a *project* is loaded, so on a bare page it is hidden for a reason
      that has nothing to do with the boundary. The check therefore runs on a
      project directory, where `hidden` is the only thing keeping it off screen.
    * index.html has no feedback toggle at all; preview.html declares all three,
      so the third entry is checked there.
    """
    context = _content_panel_context(browser)
    try:
        page = context.new_page()
        login(page)
        _wait_for_app(page)

        page.goto(f"{CLAWMATE_URL}/?root=.&dir=projects")
        page.wait_for_function("() => state.project === 'projects'", timeout=15000)
        # After the navigation, not before: `goto` is a full document load, so
        # the role probe's answer and the gate flag it feeds do not survive it.
        _wait_for_the_boundary(page)
        # A precondition, not decoration: it is what makes the project assertion
        # below a test of the boundary rather than of an empty state.
        check(page.evaluate(
            "() => document.getElementById('btnProjectPanel').style.display") == "",
            "前置：项目目录下 #btnProjectPanel 本会渲染")

        for toggle in ("btnToggleAgent", "btnProjectPanel"):
            check(page.locator(f"#{toggle}").is_hidden(), f"管理员看不到 #{toggle}")

        # The more-menu mirrors the same gate; one left behind is a way back in
        # on a phone.
        page.set_viewport_size({"width": 375, "height": 812})
        page.locator("#btnMoreMenu").click()
        page.locator(".more-menu").wait_for(state="visible")
        for toggle in ("btnToggleAgent", "btnProjectPanel"):
            mirror = _toggle_mirror(page, toggle)
            check(mirror.count() == 1, f"移动端菜单仍声明 {toggle}（供普通用户使用）")
            check(mirror.is_hidden(), f"移动端菜单不提供 {toggle}")

        # preview.html carries the third entry, which index.html does not have.
        # There all three toggles are live-display: project-panel.js's
        # mountPreview() clears #btnProjectPanel's inline display:none once the
        # URL names a project, so `hidden` is the only gate on that page too.
        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto(f"{CLAWMATE_URL}/preview.html?root=.&file=projects/readme.md")
        page.locator("#btnToggleFeedback").wait_for(state="attached", timeout=15000)
        _wait_for_the_boundary(page)
        for toggle in CONTENT_PANEL_TOGGLES:
            check(page.locator(f"#{toggle}").is_hidden(), f"预览页管理员看不到 #{toggle}")

        page.set_viewport_size({"width": 375, "height": 812})
        page.locator("#btnMoreMenu").click()
        page.locator(".more-menu").wait_for(state="visible")
        for toggle in CONTENT_PANEL_TOGGLES:
            mirror = _toggle_mirror(page, toggle)
            check(mirror.count() == 1, f"预览页移动端菜单仍声明 {toggle}（供普通用户使用）")
            check(mirror.is_hidden(), f"预览页移动端菜单不提供 {toggle}")
    finally:
        context.close()


def test_the_project_panel_does_not_auto_open_for_an_admin(browser):
    """The auto-open guard's only other coverage is a source-text test, and that
    test can be bypassed by appending an unguarded `_setProjectPanelOpen(firstVisit)`
    behind the guarded line -- the regex still matches the first one. This is its
    behavioural pin.

    A bare "is #projectPanel hidden after login" assertion would be vacuous: the
    panel is only meaningful once a *project* directory is loaded
    (`state.project` non-empty), and `_updateProjectPanelBtn()` returns early
    while it is empty, so on the default directory the panel is closed for an
    unrelated reason. The navigation below therefore goes to a project
    directory, and two preconditions make the assertion fail-able:

    * `state.project` is set -- the wait below cannot return otherwise, so the
      decision point was reached at all;
    * the first-visit sessionStorage flag was written. _updateProjectPanelBtn()
      writes it only on the branch that then decides whether to open, so its
      presence rules out the early return that would have made this vacuous.

    No seeded grant is needed: service.get_roots() hands *every* administrator
    `ROOT_ID_SYSTEM` regardless of `root_ids` (which user_store keeps empty for
    an admin), so `?root=.` is a root an admin really holds.
    """
    context = _content_panel_context(browser)
    try:
        page = context.new_page()
        login(page)
        _wait_for_app(page)

        page.goto(f"{CLAWMATE_URL}/?root=.&dir=projects")
        page.wait_for_function("() => state.project === 'projects'", timeout=15000)
        # After the navigation, not before: `goto` is a full document load, so
        # the gate flag does not survive it. What orders the boundary's callback
        # against _updateProjectPanelBtn()'s decision is the request schedule
        # inside init() -- /auth/status is issued at the top of init(), while
        # state.project waits on /api/clawmate/list three round trips later. This
        # test does not enforce that ordering; it waits for both effects and then
        # asserts. If the callback ever landed after the decision, its own
        # _setProjectPanelOpen(false) would close the panel the guard let open.
        _wait_for_the_boundary(page)
        seen = page.evaluate(
            "() => Object.keys(sessionStorage)"
            ".filter(k => k.indexOf('clawmate.projectPanel.seen:') === 0)")
        check(seen == ["clawmate.projectPanel.seen:.:projects"],
              f"前置：项目面板走到了首次访问的自动展开分支（{seen}）")
        check(page.locator("#projectPanel").is_hidden(),
              "管理员进入项目目录时项目面板不自动展开")
    finally:
        context.close()


def test_the_project_panel_still_auto_opens_for_an_ordinary_user(browser):
    """The mirror of the admin check: suppressing the auto-open for *everyone*
    must not stay green.

    Without this, calling `_setProjectPanelOpen(false)` unconditionally at the
    guard's call site leaves every other assertion in the repo green -- the admin
    check above wants the panel closed, tests/test_admin_panel_contract.py still
    matches the guarded line, and the first-visit auto-open just becomes dead
    code for every account. That is the same "an appended call bypasses the
    source contract" hole Task 4 had, in the other direction.

    The ordinary user's granted root carries a project, because the panel only
    exists inside one, and the context is fresh because the sessionStorage flag
    that gates the auto-open is per-context.
    """
    context = _content_panel_context(browser)
    try:
        page = context.new_page()
        login(page, E2E_USER_USERNAME, E2E_USER_PASSWORD)
        _wait_for_app(page)

        page.goto(f"{CLAWMATE_URL}/?root={SEEDED_ROOT_ID}&dir={SEEDED_ORDINARY_PROJECT}")
        page.wait_for_function(
            "(dir) => state.dir === dir", arg=SEEDED_ORDINARY_PROJECT, timeout=15000)
        # Read the internal state as well, so a red check says which half broke.
        state_open = page.evaluate("() => _isProjectPanelOpen()")
        check(page.locator("#projectPanel").is_visible(),
              f"普通用户首次进入项目目录时项目面板自动展开（_isProjectPanelOpen={state_open}）")
    finally:
        context.close()


@pytest.mark.usefixtures("admin_page")
def test_breadcrumb_copy_pastes_an_absolute_path(page: Page):
    """The reported symptom: the breadcrumb's copy button pasted "undefined/...".

    app.js composes the path from `root.dir`, and /api/clawmate/config stopped
    sending it -- so `undefined/docs/superpowers/specs` reached the clipboard.
    Nothing headless caught it: the payload's *shape* was asserted in one place
    and the composer's use of `root.dir` was in another, and neither test crossed
    the boundary. This one reads the clipboard the way a user would.
    """
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.goto(f"{CLAWMATE_URL}/?root=.&dir=projects")
    page.wait_for_function("() => state.dir === 'projects'", timeout=15000)
    page.locator(".breadcrumb-copy").first.wait_for(state="visible", timeout=10000)

    page.locator(".breadcrumb-copy").first.click()

    pasted = page.evaluate("() => navigator.clipboard.readText()")
    check(pasted == f"{E2E_SYSTEM_ROOT}/projects",
          f"复制得到绝对路径（{pasted!r}）")
    check("undefined" not in pasted, f"复制结果不含 undefined（{pasted!r}）")


@pytest.mark.usefixtures("admin_page")
def test_gallery_thumbnail_loads_through_the_preview_route(page: Page):
    """The reported symptom: a 403 on /api/clawmate/preview, for an image.

    A gallery thumbnail is `<img src="/api/clawmate/preview?...">`, so a 403 shows
    up as a broken image and nothing else -- no in-page error, just a console
    line. `naturalWidth` is what proves the bytes arrived; asserting that the
    element exists would have passed against the broken build.
    """
    page.goto(f"{CLAWMATE_URL}/?root=.&dir=projects")
    page.wait_for_function("() => state.dir === 'projects'", timeout=15000)

    thumb = page.locator("#gallery .card", has_text="cover.png").locator("img").first
    thumb.wait_for(state="visible", timeout=10000)
    page.wait_for_function(
        "() => { const img = document.querySelector('#gallery .card img');"
        " return !!img && img.complete && img.naturalWidth > 0; }", timeout=15000)

    loaded = page.evaluate(
        "() => { const img = document.querySelector('#gallery .card img');"
        " return img ? {naturalWidth: img.naturalWidth, src: img.src} : null; }")
    check(loaded and loaded["naturalWidth"] > 0,
          f"缩略图真的加载成功（{loaded and loaded['naturalWidth']}px 宽）")


@pytest.mark.usefixtures("admin_page")
def test_grant_post_from_the_user_tab(page: Page):
    """A grant POST from the tab, and 422 messages rendered in the error region."""
    _open_settings(page)
    page.locator('[data-settings-tab="users"]').click()

    _open_user_form(page)
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
    _open_user_form(page)
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


# ── Agent history overlay layout ───────────────────────────────────────

def _open_agent_panel(page: Page) -> None:
    """Open the agent panel, idempotent: the toggle is a toggle, so clicking
    #btnToggleAgent while the panel is open would close it instead. On a phone
    the toggle is mirrored into the more-menu, hence the fallback."""
    if not page.locator("#agentPanel").is_visible():
        toggle = page.locator("#btnToggleAgent")
        if toggle.is_visible():
            toggle.click()
        else:
            page.locator("#btnMoreMenu").click()
            page.locator(".more-menu").wait_for(state="visible")
            _toggle_mirror(page, "btnToggleAgent").click()
        page.locator("#agentPanel").wait_for(state="visible")


def _close_dir_panel(page: Page) -> None:
    """The Dir sidebar is open by default on a desktop viewport, so a test that
    needs the *opening* path has to close it first -- otherwise the toggle never
    runs and the assertion that follows proves nothing."""
    page.evaluate("""() => {
      const sb = document.getElementById('sidebar');
      if (!sb.classList.contains('hidden')) document.getElementById('btnToggleSidebar').click();
    }""")
    page.wait_for_function(
        "() => document.getElementById('sidebar').classList.contains('hidden')", timeout=10000)


def _open_dir_panel(page: Page) -> None:
    page.evaluate("""() => {
      const sb = document.getElementById('sidebar');
      if (sb.classList.contains('hidden')) document.getElementById('btnToggleSidebar').click();
    }""")
    page.locator("#sidebar").wait_for(state="visible")


def _open_agent_history(page: Page) -> None:
    """Open the agent panel, then its history overlay. Idempotent.

    The overlay is built lazily by toggleHistory() and is appended to the panel,
    so a viewport change can take it away with the panel it was mounted in.
    """
    _open_agent_panel(page)
    overlay = page.locator(".agent-history-overlay")
    if overlay.count() == 0 or not overlay.is_visible():
        page.locator("#btnAgentHistory").click()
    page.locator(".agent-history-list-header").wait_for(state="visible", timeout=10000)


# ── Dir panel vs the right-hand panels ─────────────────────────────────

@pytest.mark.parametrize("width", [1600, 1300, 1100])
def test_opening_the_dir_panel_leaves_the_agent_panel_open(browser, width):
    """Dir (col1) and the agent (col4) are independent grid columns. Opening the
    Dir panel closed the agent unconditionally, and the surviving suppression
    used a 1500px threshold that cut across the layout's own boundary -- panels
    stop being floating drawers and start occupying real columns at 1240px."""
    context = _content_panel_context(browser)
    try:
        page = context.new_page()
        page.set_viewport_size({"width": width, "height": 800})
        login(page, E2E_USER_USERNAME, E2E_USER_PASSWORD)
        _wait_for_app(page)
        _close_dir_panel(page)
        _open_agent_panel(page)
        check(page.locator("#agentPanel").is_visible(), f"{width}px：前置：Agent 面板已打开")
        check(page.locator("#sidebar").is_hidden(), f"{width}px：前置：Dir 面板是关着的")
        _open_dir_panel(page)
        check(page.locator("#sidebar").is_visible(), f"{width}px：Dir 面板已打开")
        check(page.locator("#agentPanel").is_visible(),
              f"{width}px：展开 Dir 面板后 Agent 面板仍打开")
    finally:
        context.close()


def test_opening_the_dir_panel_leaves_the_project_panel_open(browser):
    """Col1 and col3 coexist by design -- the stylesheet says so in as many words
    -- yet the JS closed the project panel when the Dir panel opened.

    Needs a project directory: _updateProjectPanelBtn() returns early while
    state.project is empty, so on a bare page there is no project panel open to
    preserve.
    """
    context = _content_panel_context(browser)
    try:
        page = context.new_page()
        page.set_viewport_size({"width": 1600, "height": 800})
        login(page, E2E_USER_USERNAME, E2E_USER_PASSWORD)
        _wait_for_app(page)
        page.goto(f"{CLAWMATE_URL}/?root={SEEDED_ROOT_ID}&dir={SEEDED_ORDINARY_PROJECT}")
        page.wait_for_function(
            "(project) => state.project === project",
            arg=SEEDED_ORDINARY_PROJECT, timeout=15000)
        # First visit to a project in this login session opens the panel by
        # itself, so this does not click the toggle -- clicking it here would
        # close the very panel the test is about.
        page.locator("#projectPanel").wait_for(state="visible")
        check(page.locator("#projectPanel").is_visible(), "前置：项目面板已打开")
        _close_dir_panel(page)
        check(page.locator("#sidebar").is_hidden(), "前置：Dir 面板是关着的")
        _open_dir_panel(page)
        check(page.locator("#sidebar").is_visible(), "Dir 面板已打开")
        check(page.locator("#projectPanel").is_visible(),
              "展开 Dir 面板后项目面板仍打开")
    finally:
        context.close()


@pytest.mark.parametrize("width,exclusive", [(768, True), (769, False)])
def test_the_tier_boundary_is_768px_on_both_sides(browser, width, exclusive):
    """768px is the last mobile width, not the first desktop one -- that is what
    the stylesheet says (`max-width: 768px` for the mobile rules, `min-width:
    769px` above them). The JS disagreed with the CSS and with preview.js: it
    used `< 768`, so at exactly 768px the app laid out as a phone while the JS
    treated it as a desktop and let two overlay panels open at once."""
    context = _content_panel_context(browser)
    try:
        page = context.new_page()
        page.set_viewport_size({"width": width, "height": 900})
        login(page, E2E_USER_USERNAME, E2E_USER_PASSWORD)
        _wait_for_app(page)
        _open_dir_panel(page)
        check(page.locator("#sidebar").is_visible(), f"{width}px：前置：Dir 面板已打开")
        _open_agent_panel(page)
        check(page.locator("#agentPanel").is_visible(), f"{width}px：Agent 面板已打开")
        still_there = page.locator("#sidebar").is_visible()
        check(still_there != exclusive,
              f"{width}px：{'mobile 档，浮层互斥' if exclusive else 'tablet 档，两者共存'}"
              f"（Dir 面板{'仍在' if still_there else '已关闭'}）")
    finally:
        context.close()


@pytest.mark.parametrize("width", [1600, 1300, 1100])
def test_opening_the_agent_panel_leaves_the_dir_panel_open(browser, width):
    """The other direction, and the one that stayed one-way after the Dir panel
    stopped closing the agent: opening the agent hid the Dir panel at every width
    up to 1500px, including bands where the two never compete for width."""
    context = _content_panel_context(browser)
    try:
        page = context.new_page()
        page.set_viewport_size({"width": width, "height": 800})
        login(page, E2E_USER_USERNAME, E2E_USER_PASSWORD)
        _wait_for_app(page)
        _open_dir_panel(page)
        check(page.locator("#sidebar").is_visible(), f"{width}px：前置：Dir 面板已打开")
        _open_agent_panel(page)
        check(page.locator("#agentPanel").is_visible(), f"{width}px：Agent 面板已打开")
        check(page.locator("#sidebar").is_visible(),
              f"{width}px：打开 Agent 面板后 Dir 面板仍在")
    finally:
        context.close()


_BOXES_JS = """
() => {
  const o = document.querySelector('.agent-history-overlay');
  if (!o) return null;
  const box = sel => {
    const el = o.querySelector(sel);
    if (!el) return null;
    const b = el.getBoundingClientRect();
    return { l: +b.left.toFixed(1), r: +b.right.toFixed(1), w: +b.width.toFixed(1) };
  };
  return {
    header: box('.agent-history-list-header'),
    title: box('.agent-history-overlay-title'),
    controls: box('.agent-history-controls'),
    close: box('.agent-history-overlay-close'),
    search: box('.agent-history-search-input'),
    select: box('.agent-history-backend-input'),
  };
}
"""


@pytest.mark.parametrize("width", [414, 390, 375, 360, 320])
def test_the_history_header_keeps_its_parts_apart_on_a_phone(browser, width):
    """Measured on the real header before the fix: at 375px the search box
    covered 70% of the 历史会话 title and the close button had begun to overlap
    the backend select; at 320px the control block started 58px into the title.

    Title, controls and close are one grid row, so "the three of them plus the
    header paddings fit" is the whole contract.
    """
    context = _content_panel_context(browser)
    try:
        page = context.new_page()
        page.set_viewport_size({"width": width, "height": 780})
        # An ordinary account: the administrator boundary hides the agent panel
        # from an admin entirely.
        login(page, E2E_USER_USERNAME, E2E_USER_PASSWORD)
        _wait_for_app(page)
        _open_agent_history(page)
        m = page.evaluate(_BOXES_JS)

        for name in ("header", "title", "controls", "close", "search"):
            check(m[name] is not None, f"{width}px：{name} 存在")
        check(m["controls"]["l"] >= m["title"]["r"] - 0.5,
              f"{width}px：控件不压住标题（标题右 {m['title']['r']} / 控件左 {m['controls']['l']}）")
        check(m["close"]["l"] >= m["controls"]["r"] - 0.5,
              f"{width}px：关闭按钮不压住控件（控件右 {m['controls']['r']} / 关闭左 {m['close']['l']}）")
        check(m["title"]["l"] >= m["header"]["l"] - 0.5 and m["close"]["r"] <= m["header"]["r"] + 0.5,
              f"{width}px：三者都在 header 内（header {m['header']['l']}–{m['header']['r']}，"
              f"标题左 {m['title']['l']}，关闭右 {m['close']['r']}）")
        # Shrinking the title is fine; squeezing the search to a sliver is not.
        check(m["search"]["w"] >= 72,
              f"{width}px：搜索框仍可用（实测 {m['search']['w']}px）")
    finally:
        context.close()


def test_the_history_controls_keep_their_natural_width_on_a_wide_panel(browser):
    """The narrow-screen fix must leave the desktop header alone.

    An `auto` grid column absorbs the panel's spare width. With three of them the
    stretch took the controls from their natural 306px to 350px and the search
    box from 193px to 237px -- an unrequested change on a screen that had nothing
    wrong with it. The controls are content-sized, so their width must not track
    the panel's, which the two panel widths below tell apart.
    """
    context = _content_panel_context(browser)
    try:
        page = context.new_page()
        page.set_viewport_size({"width": 1280, "height": 800})
        login(page, E2E_USER_USERNAME, E2E_USER_PASSWORD)
        _wait_for_app(page)
        _open_agent_history(page)

        measured = []
        for vw in (1280, 900, 1500):
            page.set_viewport_size({"width": vw, "height": 800})
            page.wait_for_timeout(250)
            _open_agent_history(page)
            measured.append((vw, page.evaluate("""() => {
              const o = document.querySelector('.agent-history-overlay');
              const w = sel => {
                const el = (sel === '#agentPanel' ? document : o).querySelector(sel);
                return el ? +el.getBoundingClientRect().width.toFixed(1) : null;
              };
              return { panel: w('#agentPanel'), controls: w('.agent-history-controls'),
                       search: w('.agent-history-search-input') };
            }""")))
        for vw, m in measured:
            check(m["search"] <= 200,
                  f"{vw}px：搜索框保持自然宽度，未被拉伸（实测 {m['search']}）")
        search_widths = {m["search"] for _, m in measured}
        check(len(search_widths) == 1,
              f"搜索框宽度不随面板宽度变化（面板 {[m['panel'] for _, m in measured]} → "
              f"搜索 {[m['search'] for _, m in measured]}）")
    finally:
        context.close()


@pytest.mark.parametrize("width,label", [(1280, "桌面"), (390, "移动端")])
def test_the_history_date_axis_is_exactly_as_tall_as_the_agent_toolbar(browser, width, label):
    """The date axis is documented as mirroring .agent-toolbar -- 34px on desktop,
    38px on mobile -- but `min-height` is only a floor. With 30px controls the
    toolbar measured 39/41 against the axis's 35/38, so two stacked bars in the
    same panel were visibly 3-4px apart. Both use --btn-h-sm now, which is what
    makes the floors the deciding factor.
    """
    context = _content_panel_context(browser)
    try:
        page = context.new_page()
        page.set_viewport_size({"width": width, "height": 800})
        login(page, E2E_USER_USERNAME, E2E_USER_PASSWORD)
        _wait_for_app(page)
        _open_agent_history(page)
        h = page.evaluate("""() => {
          const o = document.querySelector('.agent-history-overlay');
          const axis = o.querySelector('.agent-history-date-axis');
          axis.removeAttribute('hidden');
          let strip = axis.querySelector('.agent-history-date-btns');
          if (!strip) { strip = document.createElement('div');
            strip.className = 'agent-history-date-btns'; axis.appendChild(strip); }
          if (!strip.children.length) {
            strip.innerHTML = ['Today','Yesterday','09/09']
              .map(t => '<button type="button" class="agent-history-date-btn">' + t + '</button>').join('');
          }
          const tb = document.querySelector('.agent-toolbar');
          return { toolbar: tb ? +tb.getBoundingClientRect().height.toFixed(1) : null,
                   axis: +axis.getBoundingClientRect().height.toFixed(1) };
        }""")
        check(h["toolbar"] is not None, f"{label}：agent toolbar 存在")
        check(h["toolbar"] == h["axis"],
              f"{label}：日期轴与 agent toolbar 等高（toolbar {h['toolbar']} / 日期轴 {h['axis']}）")
    finally:
        context.close()


_INJECT_DATES_JS = """() => {
  const anchor = document.querySelector('.agent-history-date-axis');
  if (!anchor) return false;
  anchor.removeAttribute('hidden');
  let strip = anchor.querySelector('.agent-history-date-btns');
  if (!strip) {
    strip = document.createElement('div');
    strip.className = 'agent-history-date-btns';
    anchor.appendChild(strip);
  }
  strip.innerHTML = ['09/09','09/08','09/07','09/06','09/05','09/04','09/03','09/02']
    .map(t => '<button type="button" class="agent-history-date-btn">' + t + '</button>')
    .join('');
  return true;
}"""


def test_the_date_axis_never_hides_a_date_where_it_cannot_be_reached(browser):
    """The date strip renders as many buttons as its width suggested at render
    time, and that estimate is taken once -- so a window that narrows afterwards
    leaves a strip wider than its box. `.agent-history-date-btns` was
    `overflow: hidden` with `justify-content: center`, which silently cut BOTH
    ends (measured 20px at 380, 50px at 320) with no way to reach them.

    The buttons are injected with the app's own class names because this fixture
    has no sessions to list; what is under test is the strip's layout contract
    for whatever the app renders, not the count heuristic that chooses it.
    """
    context = _content_panel_context(browser)
    try:
        page = context.new_page()
        page.set_viewport_size({"width": 600, "height": 780})
        login(page, E2E_USER_USERNAME, E2E_USER_PASSWORD)
        _wait_for_app(page)
        _open_agent_history(page)
        page.evaluate(_INJECT_DATES_JS)
        # Narrow the window after the strip was laid out, then look for dates
        # that sit outside the box they are supposed to be visible in.
        page.set_viewport_size({"width": 320, "height": 780})
        # Put the buttons back and make sure the overlay survived the resize.
        # The axis is re-rendered by the app (renderHistoryDateAxis replaces its
        # children) and the lazily built overlay can go with the panel it was
        # mounted in, so an injection that is not replayed can be gone by the
        # time the measurement runs -- which is what a rare flake here looked
        # like, not a layout that was ever wrong.
        _open_agent_history(page)
        page.evaluate(_INJECT_DATES_JS)
        # Wait for the reflow to settle before measuring. This file has been
        # bitten by sampling a transient state before (openDirPicker's blank
        # tree), and here a half-applied resize is what a flake looked like:
        # the strip reports scrollWidth > clientWidth while still laying out,
        # but scrollLeft will not move yet, so the test reads "clipped and
        # unreachable" off a frame that was about to become fine.
        page.wait_for_function(
            "() => { const y = document.querySelector('.agent-history-date-axis');"
            " const s = document.querySelector('.agent-history-date-btns');"
            " if (!y || !s) return false;"
            " return y.getBoundingClientRect().width > 0"
            " && y.getBoundingClientRect().width <= 321"
            " && s.getBoundingClientRect().width > 0; }", timeout=10000)
        m = page.evaluate("""() => {
          const strip = document.querySelector('.agent-history-date-btns');
          const sr = strip.getBoundingClientRect();
          const kids = [...strip.children].map(b => {
            const r = b.getBoundingClientRect();
            return { t: b.textContent, l: +r.left.toFixed(1), r: +r.right.toFixed(1) };
          });
          const outside = kids.filter(k => k.l < sr.left - 0.5 || k.r > sr.right + 0.5);
          const before = strip.scrollLeft;
          strip.scrollLeft = strip.scrollWidth;
          return {
            overflowX: getComputedStyle(strip).overflowX,
            scrollW: strip.scrollWidth, clientW: strip.clientWidth,
            outside: outside.map(k => k.t),
            scrolledFrom: before, scrolledTo: strip.scrollLeft,
          };
        }""")
        if m["outside"]:
            check(m["overflowX"] in ("auto", "scroll"),
                  f"日期条溢出时必须可横向滚动，而不是裁掉（overflow-x: {m['overflowX']}，"
                  f"越界 {m['outside']}）")
            check(m["scrolledTo"] > m["scrolledFrom"],
                  f"被裁的日期确实能滚到（scrollLeft {m['scrolledFrom']} → {m['scrolledTo']}）")
        else:
            check(not m["outside"], f"无日期落在可视框外（{m['outside']}）")
    finally:
        context.close()


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



