from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "dev" / "static" / "js" / "app.js"


def test_index_add_to_agent_uses_insert_text_with_at_path_newline():
    js = APP_JS.read_text(encoding="utf-8")

    assert "window.Agent.sendText(entry.relPath + ' ');" not in js
    assert "window.Agent.sendText(relPath + ' ');" not in js
    assert "window.Agent.insertText('@' + entry.relPath + '\\n');" in js
    assert "window.Agent.insertText('@' + relPath + '\\n');" in js
