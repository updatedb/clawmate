import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_share_and_preview_load_one_feedback_panel_contract():
    """Both surfaces load the card factory; only share keeps its token endpoint."""
    share = (ROOT / "dev/static/share-view.html").read_text(encoding="utf-8")
    common = (ROOT / "dev/static/js/preview-common.js").read_text(encoding="utf-8")
    panel = ROOT / "dev/static/js/feedback-panel.js"
    assert panel.exists()
    assert "feedback-panel.js" in share
    assert "feedback-panel.js" in common
    assert "ClawMateFeedbackPanel.buildCard" in share
    assert "ClawMateFeedbackPanel.selectionPosition" in share
    assert "ClawMateFeedbackPanel.submissionPayload" in share
    assert "'/share/' + TOKEN + '/feedback'" in share
    assert "TOKEN" not in panel.read_text(encoding="utf-8")


def test_shared_panel_filters_actions_and_normalizes_submission_payload():
    common = ROOT / "dev/static/js/preview-common.js"
    panel = ROOT / "dev/static/js/feedback-panel.js"
    script = r'''
const fs = require('fs'), vm = require('vm');
const context = { window: {}, document: { head: null } };
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), context);
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), context);
const api = context.window.ClawMateFeedbackPanel;
const templates = [
  {id:'md', source:'selection', action:'modify', scope:'document', frontend:{panel:true}, match_ext:['md']},
  {id:'exe', source:'selection', action:'execute', scope:'document', frontend:{panel:true}, match_ext:['exe']}
];
console.log(JSON.stringify({
  md: api.actions(templates, 'note.md').map(x => x.action),
  payload: api.submissionPayload([{text:'x', note:'n', action:'modify', location:'Line 4'}], 'reviewer')
}));
'''
    result = subprocess.run(["node", "-e", script, str(common), str(panel)], check=True, capture_output=True, text=True)
    outcome = json.loads(result.stdout)
    assert outcome["md"] == ["modify"]
    assert outcome["payload"] == {"author": "reviewer", "selections": [{
        "text": "x", "note": "n", "action": "modify", "scope": "document",
        "task_id": "", "position": "Line 4",
    }]}
