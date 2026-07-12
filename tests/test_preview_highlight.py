import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_JS = ROOT / "dev" / "static" / "js" / "preview.js"


def test_dark_markdown_theme_does_not_override_highlight_tokens():
    source = PREVIEW_JS.read_text(encoding="utf-8")

    assert "[data-theme=dark] .markdown-body * { color:#f0f6fc; }" not in source


def test_visible_line_number_views_receive_highlighted_html():
    source = PREVIEW_JS.read_text(encoding="utf-8")
    renderer = re.search(
        r"function renderCodeWithLineNumbers\([^)]*\) \{(?P<body>.*?)\n  \}",
        source,
        flags=re.S,
    )

    assert renderer, "line-number renderer not found"
    assert "highlightSourceLines(rawContent, language)" in renderer.group("body")
    assert "renderCodeWithLineNumbers(content, 'markdown')" in source
    assert "renderCodeWithLineNumbers(content, 'html')" in source
    assert "renderCodeWithLineNumbers(rawContent, ext)" in source


def test_multiline_highlight_spans_are_reopened_for_each_visible_line():
    source = PREVIEW_JS.read_text(encoding="utf-8")
    splitter = re.search(
        r"function splitHighlightedHtmlByLines\([^)]*\) \{(?P<body>.*?)\n  \}",
        source,
        flags=re.S,
    )

    assert splitter, "highlighted HTML line splitter not found"
    assert "activeTags" in splitter.group("body")
    assert "closeActiveTags" in splitter.group("body")
    assert "reopenActiveTags" in splitter.group("body")


def test_unknown_preview_extensions_fall_back_to_auto_detection():
    source = PREVIEW_JS.read_text(encoding="utf-8")

    assert "window.hljs.highlightAuto(content).value" in source
