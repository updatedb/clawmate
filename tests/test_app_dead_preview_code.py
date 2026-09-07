from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "dev" / "static" / "js" / "app.js"
INDEX_HTML = ROOT / "dev" / "static" / "index.html"


def test_directory_page_excludes_unused_preview_rendering_helpers():
    source = APP_JS.read_text(encoding="utf-8")

    for helper in (
        "buildTOC",
        "addCopyButtons",
        "parseCodeOutline",
        "openLinksInNewTab",
        "ensureMermaid",
        "ensureKatex",
        "renderMermaid",
        "setupMermaidResizeHandles",
        "createMarkdownRenderer",
    ):
        assert f"function {helper}(" not in source
        assert f"async function {helper}(" not in source


def test_directory_page_keeps_its_lightweight_script_boundary():
    index = INDEX_HTML.read_text(encoding="utf-8")
    app = APP_JS.read_text(encoding="utf-8")

    assert './js/preview-common.js' not in index
    assert index.index('./js/utils.js') < index.index('./js/app.js')
    assert "async function loadDir" in app
