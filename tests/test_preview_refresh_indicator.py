from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_preview_sse_matching_and_refresh_indicator_contract():
    """A real write event path marks the control; refresh clears it."""
    source = ROOT / "dev/static/js/project-panel.js"
    probe = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const document = {readyState: 'loading', addEventListener() {}};
const window = {addEventListener() {}};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {window, document, Boolean});
const panel = window.ClawMateProjectPanel;
const classes = new Set();
const button = {title: '', classList: {toggle(name, enabled) { enabled ? classes.add(name) : classes.delete(name); }}, setAttribute(name, value) { this[name] = value; }};
assert(panel.previewUpdateMatches({type: 'change', path: 'clawmate/README.md', kind: 'modified'}, 'clawmate/README.md'));
assert(!panel.previewUpdateMatches({type: 'change', path: 'clawmate/readme.md', kind: 'modified'}, 'clawmate/README.md'));
assert(panel.previewUpdateMatches({type: 'refresh'}, 'clawmate/README.md'));
panel.setPreviewUpdateIndicator(button, true);
assert(classes.has('has-update') && button.title === '有更新，点击刷新' && button['aria-label'] === '有更新，点击刷新');
panel.setPreviewUpdateIndicator(button, false);
assert(!classes.has('has-update') && button.title === '刷新大纲和内容' && button['aria-label'] === '刷新大纲和内容');
'''
    result = subprocess.run(["node", "-e", probe, str(source)], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
