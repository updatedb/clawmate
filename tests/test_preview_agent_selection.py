from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_JS = ROOT / "dev" / "static" / "js" / "preview.js"


def test_agent_selection_mode_routes_to_agent_input():
    js = PREVIEW_JS.read_text(encoding="utf-8")

    assert "function isAgentSelectionMode()" in js
    assert "if (isAgentSelectionMode())" in js
    assert "function buildSelectionPosition(range, selText)" in js
    assert "function buildAgentInsertText(positionText, selectionText)" in js
    assert "function quoteBlock(text)" in js
    assert "return '> ' + line;" in js
    assert "parts.push('---');" in js
    assert "parts.push('position: ' + (positionText || ''));" in js
    assert "parts.push(quoteBlock(selectionText || ''));" in js
    assert "return '\\n' + parts.join('\\n') + '\\n';" in js
    assert "if (tooltip.contains(e.target)) return;" in js
    assert "window.Agent.insertText(buildAgentInsertText(desktopSelPosition, text));" in js
    assert "savedRange = null;" in js
    assert "clearHL();" in js
    assert "hideDesktopSelBtn(true);" in js
    assert "window.getSelection().removeAllRanges()" in js
