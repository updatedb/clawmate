from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_HTML = ROOT / "dev" / "static" / "preview.html"
PREVIEW_JS = ROOT / "dev" / "static" / "js" / "preview.js"


def test_preview_defers_pdf_and_terminal_bundles_until_the_feature_is_used():
    html = PREVIEW_HTML.read_text(encoding="utf-8")
    js = PREVIEW_JS.read_text(encoding="utf-8")

    assert '<script src="/clawmate/pdfjs/pdf.min.js" defer>' not in html
    assert '<script src="./dist/terminal.js" defer>' not in html
    assert "await loadScript('/clawmate/pdfjs/pdf.min.js')" in js
    assert "await loadScript('./dist/terminal.js')" in js
    assert "Promise.all([ensureTerminal(), _fetchAgentConfig()])" in js


def test_pdf_outline_loads_pdfjs_before_reading_the_document():
    js = PREVIEW_JS.read_text(encoding="utf-8")
    outline = js.split("async function fetchPdfOutline(rawUrl)", 1)[1].split(
        "/** Render a page-number list", 1
    )[0]

    assert outline.index("await ensurePdfJs()") < outline.index("pdfjsLib.getDocument(")


def test_markdown_text_is_shown_before_optional_diagram_and_math_assets_load():
    js = PREVIEW_JS.read_text(encoding="utf-8")

    assert "var needsMermaid = content.indexOf('```mermaid') !== -1;" in js
    assert "var enhancementLoads = [];" in js
    assert js.index("removeLoading();\n        updateMarkdownDynamicButtons();\n        var enhancementLoads") < js.index(
        "if (needsMermaid) enhancementLoads.push(ensureMermaid());"
    )
