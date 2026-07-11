from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_JS = ROOT / "dev" / "static" / "js" / "preview.js"


def test_agent_selection_mode_routes_to_agent_input():
    js = PREVIEW_JS.read_text(encoding="utf-8")

    assert "function isAgentSelectionMode()" in js
    assert "function isSelectionInsideContentBody(sel, range)" in js
    assert "if (isAgentSelectionMode())" in js
    assert "function buildSelectionPosition(range, selText)" in js
    assert "function buildAgentInsertText(positionText, selectionText)" in js
    assert "function quoteBlock(text)" in js
    assert "parts.push('@' + (filePath || ''));" not in js
    assert "parts.push('Location: ' + (positionText || ''));" in js
    assert "return '\\n' + parts.join('\\n') + '\\n';" in js
    assert "if (tooltip.contains(e.target)) return;" in js
    assert "if (!isSelectionInsideContentBody(sel, range))" in js
    assert "window.Agent.insertText(buildAgentInsertText(desktopSelPosition, text));" in js
    assert "savedRange = null;" in js
    assert "clearHL();" in js
    assert "hideDesktopSelBtn(true);" in js
    assert "window.getSelection().removeAllRanges()" in js


def test_agent_open_does_not_send_preview_raw_content():
    js = PREVIEW_JS.read_text(encoding="utf-8")

    assert "content: rawContent || ''" not in js
    assert "var fileCtx = filePath ? { path: filePath } : null;" in js


def test_preview_selection_handler_reuses_single_range_binding():
    js = PREVIEW_JS.read_text(encoding="utf-8")

    assert "let range = null;" in js
    assert "const range = sel.getRangeAt(0);" not in js
