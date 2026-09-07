from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_directory_sse_change_reloads_current_listing_and_tracks_marks():
    """An SSE add/delete is reflected by a cache-bypassing load of the open dir."""
    source = ROOT / "dev/static/js/app.js"
    probe = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const app = fs.readFileSync(process.argv[1], 'utf8');
const start = app.indexOf('// ── Live directory watch');
const end = app.indexOf('async function loadDir', start);
assert(start >= 0 && end > start, 'directory watch section must be present');
const timers = [], sources = [], loads = [], statuses = [];
function EventSource(url, options) { this.url = url; this.options = options; sources.push(this); }
EventSource.prototype.close = function () { this.closed = true; };
const state = {rootId:'main', dir:'sub'};
const window = {EventSource, addEventListener() {}, console:{warn() {}}};
const context = {
  window, EventSource, state, assert, sources, timers, loads, statuses,
  _dirCache: {'main:sub': {stale:true}},
  updateStatus: value => statuses.push(value),
  loadDir: dir => loads.push(dir), encodeURIComponent, JSON, console: window.console,
  setTimeout: (fn, delay) => { timers.push({fn, delay}); return timers.length; },
  clearTimeout() {}
};
vm.runInNewContext(app.slice(start, end) + `
  _connectFsWatch();
  assert.equal(sources.length, 1);
  assert(sources[0].url.includes('root=main') && sources[0].url.includes('dir=sub'));
  assert.equal(sources[0].options.withCredentials, true);
  sources[0].onopen();
  sources[0].onmessage({data: JSON.stringify({type:'change', path:'sub/new.txt', kind:'added'})});
  assert.equal(_recentChanges['sub/new.txt'], 'added');
  assert.equal(timers.length, 1);
  timers.shift().fn();
  assert.deepEqual(loads, ['sub']);
  sources[0].onmessage({data: JSON.stringify({type:'change', path:'sub/new.txt', kind:'deleted'})});
  assert.equal(_recentChanges['sub/new.txt'], undefined);
  timers.shift().fn();
  assert.deepEqual(loads, ['sub', 'sub']);
  sources[0].onerror();
  assert(statuses.some(value => value.includes('目录监听暂时断开')));
`, context);
'''
    result = subprocess.run(
        ["node", "-e", probe, str(source)], cwd=ROOT, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
