from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_JS = ROOT / "dev" / "static" / "js" / "agent.js"


def test_agent_reopen_reuses_last_file_context_and_insert_triggers_input():
    js = AGENT_JS.read_text(encoding="utf-8")

    assert "let _lastFileContext = null;" in js
    assert "let _knownFilesBySession = Object.create(null);" in js
    assert "if (fileContext) {" in js
    assert "_lastFileContext = fileContext;" in js
    assert "window.Agent.open(currentRootId, currentDir, _lastFileContext);" in js
    assert "var fileContext = _pendingFileContext || _lastFileContext;" in js
    assert "return 'pending:' + backendMode + ':' + (currentRootId || '') + ':' + (currentDir || '');" in js
    assert "function normalizeKnownFilePath(path)" in js
    assert "function trackTypedFileReferences(data)" in js
    assert "if (filePath && !hasKnownFile(filePath)) {" in js
    assert "migrateKnownFiles(pendingFileScopeKey(), msg.key);" in js
    assert "trackTypedFileReferences(data);" in js
    assert "function stripAnsiText(text)" not in js
    assert "function writeInsertEcho(payload)" not in js
    assert "let _pendingInsertEcho = null;" not in js
    assert "_pendingInsertEcho = payload.echo;" not in js
    assert "function restoreTerminalImeTarget()" in js
    assert "if (term && typeof term.input === 'function')" in js
    assert "term.input(rawText, true);" in js
    assert "restoreTerminalImeTarget();" in js
    assert "term.paste(rawText);" not in js
    assert "var ta = term.textarea;" in js
    assert "ta.value = '';" in js
    assert "ta.setSelectionRange(0, 0);" in js
    assert "setTimeout(function () {" in js
    assert "ta.value = ta.value.slice(0, start) + rawText + ta.value.slice(end);" not in js
    assert "if (_pendingInsertEcho && (data.indexOf('\\r') !== -1 || data.indexOf('\\n') !== -1))" not in js
    assert "type: 'suppress_echo_once'" not in js
    assert "if (filePath && !hasKnownFile(filePath)) {" in js
    assert "ws.send(JSON.stringify({ type: 'file_context', path: fileContext.path || '' }));" in js
    assert "rememberKnownFile(filePath);" in js
    assert "insertFileReference: function (path)" not in js
    assert "this.insertText('@' + normalizedPath + '\\n');" not in js
    assert "content: fileContext.content" not in js
    assert "_input_batch" not in js
    assert "record_user(_clean_content)" not in js
    assert "Ctrl+A 行首" in js
    assert "Ctrl+E 行尾" in js
    assert "Ctrl+L 清屏" in js
    assert "term.onData(function (data)" in js
