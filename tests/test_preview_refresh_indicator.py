from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_file_watch_change_and_manual_refresh_contract():
    """One file EventSource owns its indicator, callback, and panel refreshes."""
    source = ROOT / "dev/static/js/file-watch.js"
    probe = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const sources = [], classes = new Set(), calls = [];
function EventSource(url) { this.url = url; sources.push(this); }
EventSource.prototype.close = function () { this.closed = true; };
const button = {title: '', classList: {toggle(name, enabled) { enabled ? classes.add(name) : classes.delete(name); }}, setAttribute(name, value) { this[name] = value; }};
const panels = {project:{refresh() { calls.push('project'); }}, feedback:{refresh() { calls.push('feedback'); }}, review:{refresh() { calls.push('review'); }}, agent:{}};
const window = {EventSource, ClawMatePanels:{getPanel(name, surface) { assert.equal(surface, 'preview'); return panels[name]; }}};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {window, Boolean, Promise, JSON, encodeURIComponent});
(async function () {
  let changes = 0;
  const watch = window.ClawMateFileWatch.start({root:'main', file:'project/README.md', button, onChange() { changes++; return watch.refreshPanels(); }});
  assert.equal(sources.length, 1);
  assert(sources[0].url.includes('root=main') && sources[0].url.includes('file=project%2FREADME.md'));
  sources[0].onmessage({data: JSON.stringify({type:'change', path:'project/README.md'})});
  assert(classes.has('has-update') && button.title === '有更新，点击刷新' && button['aria-label'] === '有更新，点击刷新');
  assert.equal(changes, 1);
  await Promise.resolve();
  assert.deepEqual(calls.sort(), ['feedback', 'project', 'review']);
  calls.length = 0;
  let content = 0;
  await watch.manualRefresh(async () => { content++; });
  assert.equal(content, 1);
  assert(!classes.has('has-update') && button.title === '刷新大纲和内容');
  assert(sources[0].closed && sources.length === 2, 'manual refresh replaces the one source');
  assert.deepEqual(calls.sort(), ['feedback', 'project', 'review']);
})().catch(error => { console.error(error); process.exit(1); });
'''
    result = subprocess.run(["node", "-e", probe, str(source)], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_preview_refresh_delegates_to_file_watch_and_keeps_spinning_feedback():
    source = (ROOT / "dev/static/js/preview.js").read_text(encoding="utf-8")
    assert "ClawMateFileWatch.start" in source
    assert "previewFileWatch.manualRefresh(refreshContent)" in source
    assert "btnRefreshContent.classList.add('spinning')" in source
    assert "btnRefreshContent.classList.remove('spinning')" in source
