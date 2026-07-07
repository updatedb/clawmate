from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_JS = ROOT / "dev" / "static" / "js" / "agent.js"


def test_agent_reopen_reuses_last_file_context_and_insert_triggers_input():
    js = AGENT_JS.read_text(encoding="utf-8")

    assert "let _lastFileContext = null;" in js
    assert "if (fileContext) {" in js
    assert "_lastFileContext = fileContext;" in js
    assert "window.Agent.open(currentRootId, currentDir, _lastFileContext);" in js
    assert "var fileContext = _pendingFileContext || _lastFileContext;" in js
    assert "ta.dispatchEvent(new Event('input'" in js
