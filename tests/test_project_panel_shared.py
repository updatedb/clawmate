import re
from pathlib import Path


def test_preview_uses_shared_panel_and_single_file_watch_contract():
    root = Path(__file__).resolve().parents[1]
    common = (root / "dev/static/js/preview-common.js").read_text(encoding="utf-8")
    panel = (root / "dev/static/js/project-panel.js").read_text(encoding="utf-8")
    watch = (root / "dev/static/js/file-watch.js").read_text(encoding="utf-8")
    preview = (root / "dev/static/js/preview.js").read_text(encoding="utf-8")
    preview_html = (root / "dev/static/preview.html").read_text(encoding="utf-8")
    assert "project-panel.js" in common
    assert "ClawMateProjectPanel" in panel
    assert "/overview" in panel
    assert "/api/clawmate/fs/events?root=" in watch
    assert "has-update" in watch
    assert watch.count("new global.EventSource") == 1
    assert "EventSource" not in panel
    assert "btnRefreshContent" not in panel
    assert "ClawMateFileWatch.start" in preview
    assert 'src="./js/file-watch.js"' in preview_html
    assert "stopImmediatePropagation" in panel


def test_directory_file_watcher_is_not_changed_by_preview_file_watch():
    root = Path(__file__).resolve().parents[1]
    app = (root / "dev/static/js/app.js").read_text(encoding="utf-8")
    assert "let _fsEventSource = null;" in app
    assert "&dir=" in app


def test_directory_and_preview_mount_the_same_complete_project_panel_renderer():
    root = Path(__file__).resolve().parents[1]
    panel = (root / "dev/static/js/project-panel.js").read_text(encoding="utf-8")
    app = (root / "dev/static/js/app.js").read_text(encoding="utf-8")
    preview = (root / "dev/static/js/preview.js").read_text(encoding="utf-8")
    index = (root / "dev/static/index.html").read_text(encoding="utf-8")
    assert "ClawMateProjectPanel.mount" in app
    assert 'src="./js/project-panel.js"' in index
    assert "mountPreview" in panel and "openFeedback" in panel
    assert "_renderProjectPanel2" not in preview
    for feature in ("project-status-bar", "data-project-runs", "data-project-retry", "backend_actual", "CLAWLIST", "<details>", "推荐任务"):
        assert feature in panel
    assert "#previewFilterBar button" in panel
    assert "window.open" not in panel


def test_project_summary_is_a_conditional_body_section_not_header_chrome():
    root = Path(__file__).resolve().parents[1]
    index = (root / "dev/static/index.html").read_text(encoding="utf-8")
    panel = (root / "dev/static/js/project-panel.js").read_text(encoding="utf-8")
    assert 'id="projectPanelSummary"' not in index
    assert 'id="projectPanelSummary"' not in panel
    assert "项目摘要" in panel
    assert "data.status_summary ?" in panel


ROOT = Path(__file__).resolve().parents[1]


def test_recommendation_controls_present():
    js = (ROOT / "dev/static/js/project-panel.js").read_text(encoding="utf-8")
    assert "data-project-analyze" in js
    assert "data-recommend-delete" in js
    assert "recommendations/analyze" in js
    assert "recommendations/" in js and "delete" in js
    filter_line = next(
        line for line in js.split("\n") if "data.recommendations" in line and ".filter(" in line
    )
    assert (
        "project_json" in filter_line
        and "discover" in filter_line
        and "codex" in filter_line
    ), "recs filter must keep project_json, discover AND codex recommendations"


def _strip_js_comments(source: str) -> str:
    """Drop comments so an assertion cannot be satisfied by prose that quotes
    the very call it is meant to prove is present."""
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", without_blocks)


def _function_body(source: str, name: str) -> str:
    """Return the brace-matched body of `function <name>`.

    Bounding is the point: `classList.toggle` and `btnProjectPanel.focus()` both
    appear in other functions, so only the order *inside this function* proves
    the handoff runs before the panel is hidden.
    """
    open_brace = source.index("{", source.index("function " + name))
    depth = 0
    for index in range(open_brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[open_brace:index + 1]
    raise AssertionError(f"unbalanced braces in {name}")


def test_closing_the_panel_hands_focus_back_to_its_toggle():
    """Hiding a region that still holds focus strands focus inside an
    aria-hidden subtree, which Chrome blocks and warns about. The handoff has to
    run *before* the class lands, and it cannot aim at a toggle that is itself
    folded away on mobile.
    """
    app = (ROOT / "dev/static/js/app.js").read_text(encoding="utf-8")
    body = _strip_js_comments(_function_body(app, "_setProjectPanelOpen"))

    assert "projectPanel.contains(document.activeElement)" in body
    assert "btnProjectPanel.focus()" in body
    # The toggle reads offsetWidth 0 once it folds into the mobile more-menu.
    assert "btnProjectPanel.offsetWidth > 0" in body
    assert "document.activeElement.blur()" in body
    assert body.index("btnProjectPanel.focus()") < body.index("classList.toggle('hidden'")
