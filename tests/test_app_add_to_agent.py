from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "dev" / "static" / "js" / "app.js"
INDEX_HTML = ROOT / "dev" / "static" / "index.html"


def test_index_add_to_agent_uses_insert_text_with_at_path_newline():
    js = APP_JS.read_text(encoding="utf-8")

    assert "window.Agent.sendText(entry.relPath + ' ');" not in js
    assert "window.Agent.sendText(relPath + ' ');" not in js
    assert "window.Agent.insertText('@' + entry.relPath + '\\n');" in js
    assert "window.Agent.insertText('@' + relPath + '\\n');" in js


def test_index_create_menu_supports_single_file_picker_upload():
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")

    assert 'id="createFileInput"' in html
    assert 'type="file"' in html
    input_start = html.index('id="createFileInput"')
    assert "multiple" not in html[input_start:input_start + 180]
    assert "选择文件上传" in js
    assert "createFileInput.click()" in js
    assert "/api/clawmate/upload?root=" in js
    assert "formData.append('file', file)" in js
    assert "invalidateDirCache();" in js
