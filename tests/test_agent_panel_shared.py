from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_agent_panel_mount_is_idempotent_scoped_and_cleans_up():
    registry = ROOT / "dev/static/js/clawmate-panels.js"
    panel = ROOT / "dev/static/js/agent-panel.js"
    probe = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const events = {}, nodes = {};
function node() { return nodes[this.id]; }
function makeNode(id) { return nodes[id] = {id:id, style:{}, classList:{values:{hidden:true}, contains(k){return !!this.values[k]}, toggle(k, on){this.values[k] = on}, add(k){this.values[k]=true}, remove(k){this.values[k]=false}}}; }
makeNode('indexAgent'); makeNode('previewAgent'); makeNode('indexButton'); makeNode('previewButton');
const window = {addEventListener:(name, fn) => { events[name] = fn; }, document:{getElementById:id => nodes[id]}};
const context = {window, Object, Boolean, String};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), context);
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), context);
let indexClosed = 0, previewClosed = 0;
const index = window.ClawMateAgentPanel.mount({surface:'index', panelId:'indexAgent', buttonId:'indexButton', close:() => indexClosed++});
assert.strictEqual(window.ClawMateAgentPanel.mount({surface:'index', panelId:'indexAgent'}), index);
const preview = window.ClawMateAgentPanel.mount({surface:'preview', panelId:'previewAgent', close:() => previewClosed++});
assert.notStrictEqual(index, preview);
index.open();
assert(!nodes.indexAgent.classList.contains('hidden'));
assert(nodes.indexButton.classList.contains('active'));
assert(window.ClawMateAgentPanel.close('index'));
assert.strictEqual(indexClosed, 1);
assert.strictEqual(window.ClawMatePanels.getPanel('agent', 'index'), null);
assert(window.ClawMatePanels.getPanel('agent', 'preview'));
events.pagehide();
assert.strictEqual(previewClosed, 1);
assert.strictEqual(window.ClawMatePanels.getPanel('agent', 'preview'), null);
'''
    result = subprocess.run(
        ["node", "-e", probe, str(registry), str(panel)], cwd=ROOT,
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_index_and_preview_mount_the_shared_agent_adapter_lazily():
    index = (ROOT / "dev/static/index.html").read_text(encoding="utf-8")
    app = (ROOT / "dev/static/js/app.js").read_text(encoding="utf-8")
    common = (ROOT / "dev/static/js/preview-common.js").read_text(encoding="utf-8")

    assert 'src="./js/agent-panel.js"' in index
    assert "ClawMateAgentPanel.mount({\n  surface: 'index'" in app
    assert "agentPanelScript.src = './js/agent-panel.js'" in common
    assert "surface:'preview'" in common
