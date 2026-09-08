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


ROOT = Path(__file__).resolve().parents[1]


def test_recommendation_controls_present():
    js = (ROOT / "dev/static/js/project-panel.js").read_text(encoding="utf-8")
    assert "data-project-analyze" in js
    assert "data-recommend-delete" in js
    assert "recommendations/analyze" in js
    assert "recommendations/" in js and "delete" in js
