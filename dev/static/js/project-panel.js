/* Shared project-panel renderer.  Preview loads this through preview-common;
 * the directory page can adopt the same renderer without duplicating markup. */
(function (global) {
  'use strict';
  function esc(value) { return global.escHtml ? global.escHtml(String(value || '')) : String(value || ''); }
  function render(body, data) {
    var summary = data.status || {}, recs = (data.recommendations || []).filter(function (r) { return r.source === 'project_json' || r.source === 'discover'; });
    body.innerHTML = '<div class="project-status-bar">执行中 ' + (summary.running || 0) + ' · 待处理 ' + (summary.pending || 0) + ' · 失败 ' + (summary.failed || 0) + ' <button data-project-discover>重新学习</button></div>' +
      '<section class="project-panel-section"><b>现在要处理</b>' + (data.actions || []).slice(0, 3).map(function (x) { return '<p>' + esc(x.label) + ' <button data-feedback="' + esc(x.id) + '">' + esc(x.action) + '</button></p>'; }).join('') + '</section>' +
      '<section class="project-panel-section"><b>推荐任务</b><p class="project-panel-hint">仅显示可执行的项目配置任务；规则提示单独保留。</p><ul>' + recs.map(function (x) { return '<li><strong>' + esc(x.label) + '</strong><small> ' + esc(x.execution || 'agent') + '</small></li>'; }).join('') + '</ul></section>' +
      '<section class="project-panel-section"><b>CLAWLIST</b><ul>' + (data.project_tasks || []).filter(function (x) { return !x.completed; }).map(function (x) { return '<li>☐ ' + esc(x.task) + '</li>'; }).join('') + '</ul></section>';
  }
  global.ClawMateProjectPanel = { render: render };
  function previewPanel() {
    var btn = document.getElementById('btnProjectPanel');
    if (!btn || btn.dataset.sharedPanelBound) return;
    btn.dataset.sharedPanelBound = '1';
    btn.addEventListener('click', function (event) {
      event.stopImmediatePropagation();
      var existing = document.getElementById('previewProjectPanel');
      if (existing) { existing.remove(); return; }
      var query = new URLSearchParams(location.search), root = query.get('root'), file = query.get('file') || '';
      if (!root || !file) return;
      var project = file.split('/')[0], panel = document.createElement('aside');
      panel.id = 'previewProjectPanel'; panel.className = 'project-panel'; panel.style.cssText = 'position:fixed;right:0;top:0;bottom:0;z-index:10000;width:min(400px,90vw);background:var(--bg,#fff);overflow:auto';
      panel.textContent = '加载项目概况…'; document.body.appendChild(panel);
      fetch('/api/clawmate/project/' + encodeURIComponent(root) + '/' + encodeURIComponent(project) + '/overview').then(function (r) { return r.json(); }).then(function (data) {
        render(panel, data);
        panel.querySelector('[data-project-discover]').onclick = function () { fetch('/api/clawmate/project/' + encodeURIComponent(root) + '/' + encodeURIComponent(project) + '/discover', {method: 'POST'}).then(function () { return fetch('/api/clawmate/project/' + encodeURIComponent(root) + '/' + encodeURIComponent(project) + '/overview'); }).then(function (r) { return r.json(); }).then(function (next) { render(panel, next); }); };
        panel.querySelectorAll('[data-feedback]').forEach(function (action) { action.onclick = function () { var toggle = document.getElementById('btnToggleRight'); if (toggle) toggle.click(); var desired = action.dataset.feedback === 'implement_feedback' ? '已评审' : '待评审'; setTimeout(function () { Array.prototype.slice.call(document.querySelectorAll('#previewFilterBar button')).find(function (x) { return x.textContent.indexOf(desired) >= 0; })?.click(); }, 0); }; });
      }).catch(function () { panel.textContent = '加载项目概况失败'; });
    }, true);
    var query = new URLSearchParams(location.search), root = query.get('root'), file = query.get('file');
    var refresh = document.getElementById('btnRefreshContent');
    if (root && file && refresh && global.EventSource) {
      var changed = false;
      var source = new EventSource('/api/clawmate/fs/events?root=' + encodeURIComponent(root) + '&file=' + encodeURIComponent(file));
      source.onmessage = function (event) {
        try { var data = JSON.parse(event.data); } catch (_) { return; }
        if (data.type === 'refresh' || data.path === file) {
          changed = true; refresh.classList.add('has-update'); refresh.title = '有更新，点击刷新'; refresh.setAttribute('aria-label', '有更新，点击刷新');
        }
      };
      refresh.addEventListener('click', function () { if (changed) { changed = false; refresh.classList.remove('has-update'); refresh.title = '刷新大纲和内容'; } }, true);
      global.addEventListener('pagehide', function () { source.close(); }, {once: true});
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', previewPanel); else previewPanel();
})(window);
