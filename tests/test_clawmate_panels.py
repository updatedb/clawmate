from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_panel_registry_is_idempotent_and_scopes_surfaces_and_endpoints():
    source = ROOT / "dev/static/js/clawmate-panels.js"
    probe = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const calls = [], events = {};
const window = {
  addEventListener: (name, fn) => { events[name] = fn; },
  fetch: async (url, init) => { calls.push([url, init]); return {ok: true, json: async () => ({items: []})}; }
};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {window, encodeURIComponent, Object, JSON, Error});
const panels = window.ClawMatePanels;
const indexProject = {close() {}}, previewProject = {close() {}};
assert.strictEqual(panels.install('index', {project: {controller: indexProject}}).project, indexProject);
assert.strictEqual(panels.install('index', {project: {controller: {close() {}}}}).project, indexProject);
assert.strictEqual(panels.install('preview', {project: {controller: previewProject}}).project, previewProject);
assert.notStrictEqual(panels.getPanel('project', 'index'), panels.getPanel('project', 'preview'));
(async () => {
  const installed = panels.install('preview', {
    feedback: {context: {root: 'r', project: 'p', file: 'f'}},
    review: {context: {root: 'r', project: 'p'}}
  });
  await installed.feedback.refresh();
  await installed.review.decide(['one'], 'approved');
  await installed.review.execute(['one']);
  assert(calls[0][0].includes('/api/clawmate/feedback/list?root=r&project=p&file=f'));
  assert.strictEqual(calls[1][0], '/api/clawmate/review/decision');
  assert.strictEqual(calls[2][0], '/api/clawmate/review/execute');
  assert(panels.closePanel('feedback', 'preview'));
  assert.strictEqual(panels.getPanel('feedback', 'preview'), null);
})().catch(error => { console.error(error); process.exit(1); });
'''
    result = subprocess.run(
        ["node", "-e", probe, str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_index_and_preview_load_the_scoped_registry_without_duplicate_project_renderer():
    index = (ROOT / "dev/static/index.html").read_text(encoding="utf-8")
    app = (ROOT / "dev/static/js/app.js").read_text(encoding="utf-8")
    common = (ROOT / "dev/static/js/preview-common.js").read_text(encoding="utf-8")
    project = (ROOT / "dev/static/js/project-panel.js").read_text(encoding="utf-8")

    assert 'src="./js/clawmate-panels.js"' in index
    assert "ClawMatePanels.install('index'" in app
    assert "data-clawmate-panels" in common
    assert "ClawMatePanels.install('preview'" in project
    assert project.count("function mountPreview()") == 1
