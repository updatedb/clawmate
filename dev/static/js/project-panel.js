/* The one project-panel renderer used by the directory and preview surfaces. */
(function (global) {
  'use strict';
  function esc(value) { return global.escHtml ? global.escHtml(String(value || '')) : String(value || ''); }
  function runCard(run, active) {
    var task = run.task || {}, rawStatus = run.status || 'running';
    var status = rawStatus === 'waiting_input' ? 'needs_attention' : rawStatus;
    var elapsed = run.started_at ? Math.max(0, Math.floor((Date.now() - Date.parse(run.started_at)) / 60000)) + ' 分钟' : '';
    var started = run.started_at ? run.started_at.replace('T', ' ').replace(/\+00:00$/, ' UTC').slice(0, 19) : '启动时间未知';
    var detail = run.latest_feedback || run.result || run.error || run.failure_reason || '';
    var retry = !active && status === 'failed' && task.id ? '<button class="project-panel-action" data-project-retry="' + esc(run.task_run_id) + '">重试</button>' : '';
    return '<article class="project-run project-run-' + esc(status) + '"><div><b>' + esc(task.label || '项目任务') + '</b><span class="project-run-state">' + esc(status) + '</span></div><small>后端 ' + esc(run.backend_actual || '—') + ' · 启动 ' + esc(started) + (elapsed ? ' · 已用 ' + elapsed : '') + '</small>' + (detail ? '<p>' + esc(detail).slice(0, 120) + '</p>' : '') + retry + '</article>';
  }
  function staticSignature(data) { return JSON.stringify({status_summary:data.status_summary, actions:data.actions, recommendations:data.recommendations, project_tasks:data.project_tasks, review:data.review, type:data.type}); }
  function runsSignature(data) { var status = data.status || {}; return JSON.stringify({runs:data.runs, status:{running:status.running, pending:status.pending, failed:status.failed}}); }
  function mount(options) {
    var body = options.body, overview = null, staticKey = '', runsKey = '', timer = null;
    function context() { return options.getContext ? options.getContext() : null; }
    function isOpen() { return options.isOpen ? options.isOpen() : Boolean(body && body.closest('.project-panel') && !body.closest('.project-panel').classList.contains('hidden')); }
    function request(url, init) { return (options.fetch || global.fetch)(url, init); }
    function endpoint(path) { var c = context(); return '/api/clawmate/project/' + encodeURIComponent(c.root) + '/' + encodeURIComponent(c.project) + path; }
    function stopPolling() { if (timer) { clearTimeout(timer); timer = null; } }
    function schedulePolling() { stopPolling(); if (isOpen() && overview && ((overview.runs || {}).active || []).length) timer = setTimeout(refresh, 7000); }
    function renderRuns() {
      var data = overview || {}, runs = data.runs || {active:[], recent:[]}, summary = data.status || {};
      var target = body && body.querySelector('[data-project-runs]'); if (!target) return;
      var visible = (runs.active.length ? runs.active : runs.recent).slice(0, 3);
      target.previousElementSibling.textContent = runs.active.length ? '正在执行' : '最近执行';
      target.innerHTML = visible.map(function (run) { return runCard(run, runs.active.indexOf(run) >= 0); }).join('') || '<p class="project-panel-hint">暂无执行记录</p>';
      var statusBar = body.querySelector('[data-project-status]'); if (statusBar) statusBar.textContent = '执行中 ' + (summary.running || 0) + ' · 待处理 ' + (summary.pending || 0) + ' · 失败 ' + (summary.failed || 0);
      target.querySelectorAll('[data-project-retry]').forEach(function (button) { button.onclick = async function () { button.disabled = true; var res = await request(endpoint('/runs/' + encodeURIComponent(button.getAttribute('data-project-retry')) + '/retry'), {method:'POST'}); if (res.ok) await refresh(); else { button.disabled = false; notify('项目任务未能重试'); } }; });
    }
    function notify(message) { if (options.setStatus) options.setStatus(message); else if (global.showToast) global.showToast(message); }
    function render() {
      var data = overview; if (!data || !data.ok || !body) return;
      var recs = (data.recommendations || []).filter(function (r) { return r.source === 'project_json' || r.source === 'discover' || r.source === 'codex'; });
      var actions = data.actions || [], projectTasks = data.project_tasks || [], runs = data.runs || {active:[], recent:[]}, summary = data.status || {};
      if (options.summary) options.summary.textContent = data.status_summary || data.project || '';
      var html = '<div class="project-status-bar"><span>更新于 ' + esc((summary.refreshed_at || '').replace('T', ' ').slice(0, 16)) + '</span><span data-project-status>执行中 ' + (summary.running || 0) + ' · 待处理 ' + (summary.pending || 0) + ' · 失败 ' + (summary.failed || 0) + '</span></div>';
      html += '<section class="project-panel-section"><b>现在要处理</b><div class="project-actions">' + (actions.slice(0,3).map(function (item) { return '<div class="project-panel-signal"><span>' + esc(item.label) + '</span><button class="project-panel-action" data-project-action="' + esc(item.id) + '" title="来源：' + esc(item.source) + '">' + esc(item.action) + '</button></div>'; }).join('') || '<p class="project-panel-hint">暂无条件行动</p>') + '</div></section>';
      html += '<section class="project-panel-section"><b>' + (runs.active.length ? '正在执行' : '最近执行') + '</b><div class="project-runs" data-project-runs></div></section>';
      html += '<section class="project-panel-section"><div class="project-panel-section-head"><b>推荐任务</b><button class="project-panel-action" data-project-analyze>分析项目（Codex）</button></div><p class="project-panel-hint">来自项目配置；规则提示不作为可执行任务。</p><ul class="recommended-list">' + (recs.map(function (r) { return '<li><span><strong>' + esc(r.label) + '</strong><small>频率 ' + (r.frequency || 0) + ' · ' + (r.estimated_minutes != null ? esc(String(r.estimated_minutes)) + ' 分钟' : '时长未知') + '</small></span><span class="recommend-actions"><button class="project-panel-action" data-project-task="' + esc(r.id) + '">执行</button><button class="project-panel-action" data-recommend-delete="' + esc(r.id) + '">删除</button></span></li>'; }).join('') || '<li>暂无可执行推荐任务</li>') + '</ul></section><section class="project-panel-section"><b>CLAWLIST</b><ul class="claw-list">' + (projectTasks.filter(function (item) { return !item.completed; }).map(function (item) { return '<li class="claw-row"><span class="claw-check" aria-hidden="true"></span><span class="claw-text">' + esc(item.task) + '</span><button class="project-panel-action" data-clawlist-task="' + esc(item.task) + '">完成</button></li>'; }).join('') || '<li>暂无未完成任务</li>');
      var done = projectTasks.filter(function (item) { return item.completed; }); if (done.length) html += '<details><summary>已完成（' + done.length + '）</summary>' + done.map(function (item) { return '<li class="claw-row claw-done"><span class="claw-check" aria-hidden="true"></span><span class="claw-text">' + esc(item.task) + '</span></li>'; }).join('') + '</details>';
      body.innerHTML = html + '</ul></section>';
      body.querySelectorAll('[data-project-action]').forEach(function (button) { button.onclick = function () { var action = button.getAttribute('data-project-action'); if (action === 'review_feedback' || action === 'implement_feedback') { options.openFeedback && options.openFeedback(action === 'review_feedback' ? 'pending_review' : 'approved'); return; } var task = recs.find(function (item) { return item.id === action || ((action === 'update_meeting_agenda' || action === 'update_meeting_conclusion') && item.id === 'update_meeting_info'); }); if (task) { var taskButton = body.querySelector('[data-project-task="' + (global.CSS && CSS.escape ? CSS.escape(task.id) : task.id) + '"]'); if (taskButton) taskButton.click(); } else notify('该行动需要先在 project.json 的 recommended_tasks 中配置对应任务'); }; });
      body.querySelectorAll('[data-clawlist-task]').forEach(function (button) { button.onclick = async function () { var task = button.getAttribute('data-clawlist-task'); button.disabled = true; var res = await request(endpoint('/clawlist/complete'), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({task:task})}); if (res.ok) refresh(); else { button.disabled = false; notify('无法完成该 CLAWLIST 任务'); } }; });
      body.querySelectorAll('[data-project-task]').forEach(function (button) { button.onclick = async function () { button.disabled = true; var res = await request(endpoint('/tasks/' + encodeURIComponent(button.getAttribute('data-project-task')) + '/run'), {method:'POST'}); if (res.ok) { notify('项目 Agent 任务已启动'); await refresh(); } else { button.disabled = false; notify('项目 Agent 任务未启动'); } }; });
      var analyzeBtn = body.querySelector('[data-project-analyze]');
      if (analyzeBtn) analyzeBtn.onclick = async function () {
        analyzeBtn.disabled = true; analyzeBtn.textContent = '分析中…';
        var res = await request(endpoint('/recommendations/analyze'), {method:'POST'});
        analyzeBtn.disabled = false; analyzeBtn.textContent = '分析项目（Codex）';
        if (res.ok) { notify('项目分析完成，推荐已更新'); await refresh(); }
        else { var detail = ''; try { detail = (await res.json()).detail || ''; } catch (_) {} notify('项目分析失败' + (detail ? '：' + detail : '')); }
      };
      body.querySelectorAll('[data-recommend-delete]').forEach(function (button) {
        button.onclick = async function () {
          button.disabled = true;
          var id = button.getAttribute('data-recommend-delete');
          var res = await request(endpoint('/recommendations/' + encodeURIComponent(id) + '/delete'), {method:'POST'});
          if (res.ok) { notify('推荐任务已删除'); await refresh(); }
          else { button.disabled = false; notify('无法删除推荐任务'); }
        };
      });
      renderRuns();
    }
    async function refresh() { var c = context(); if (!c || !c.root || !c.project || !body) return; try { var res = await request(endpoint('/overview')); var next = await res.json(); var nextStatic = staticSignature(next), nextRuns = runsSignature(next); overview = next; if (nextStatic !== staticKey || !body.querySelector('[data-project-runs]')) { staticKey = nextStatic; render(); } else if (nextRuns !== runsKey) renderRuns(); runsKey = nextRuns; schedulePolling(); } catch (_) { body.textContent = '加载项目概况失败'; } }
    return {refresh:refresh, render:render, renderRuns:renderRuns, stop:stopPolling};
  }
  global.ClawMateProjectPanel = {mount:mount, runCard:runCard};

  // Preview has no directory state object.  Its URL is the context, while the
  // feedback action deliberately stays in this document and uses its existing
  // right-sidebar filter controls.
  function mountPreview() {
    var button = document.getElementById('btnProjectPanel');
    if (!button || button.dataset.sharedPanelBound) return;
    var query = new URLSearchParams(global.location.search), root = query.get('root'), file = query.get('file') || '';
    var project = file.split('/')[0];
    if (!root || !project) return;
    button.style.display = '';
    var panel = null, controller = null;
    function close() {
      if (controller) controller.stop();
      if (panel) panel.remove();
      panel = null; controller = null;
      button.classList.remove('active'); button.setAttribute('aria-expanded', 'false');
      // The project panel is a right-side grid column on preview; on close, let
      // the grid refresh so the content reclaims the column.
      var grid = global.document.querySelector('.preview-three-col');
      if (grid) {
        var g = (grid.style.gridTemplateColumns || '240px 1fr 0px 0px').split(' ');
        g[3] = '0px';
        grid.style.gridTemplateColumns = g.join(' ');
      }
      // Let preview.js reconcile the grid + mutually-exclusive button states.
      global.dispatchEvent(new Event('previewPanelChange'));
    }
    function openFeedback(filter) {
      var toggle = document.getElementById('btnToggleRight');
      var bar = document.getElementById('previewFilterBar');
      if (toggle && (!bar || bar.classList.contains('hidden') || bar.offsetParent === null)) toggle.click();
      var desired = filter === 'approved' ? '已评审' : '待评审';
      var choose = function () { var choices = Array.prototype.slice.call(document.querySelectorAll('#previewFilterBar button')); var match = choices.find(function (item) { return item.textContent.indexOf(desired) >= 0; }); if (match) match.click(); };
      global.setTimeout(choose, 0);
    }
    function open() {
      panel = document.createElement('aside'); panel.id = 'previewProjectPanel'; panel.className = 'project-panel';
      panel.innerHTML = '<header class="project-panel-header"><strong>项目面板</strong><span id="projectPanelSummary"></span><button class="panel-close-btn" aria-label="关闭项目面板"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg></button></header><div class="project-panel-body">加载项目概况…</div>';
      // The project panel is a right-side grid column (col4) on the preview surface:
      // it should push content and be mutually exclusive with feedback/agent right panels.
      var grid = global.document.querySelector('.preview-three-col');
      if (grid) {
        var rightSb = global.document.getElementById('rightSidebar');
        if (rightSb && !rightSb.classList.contains('hidden')) { rightSb.classList.add('hidden'); rightSb.style.display = 'none'; var rt = global.document.getElementById('btnToggleRight'); if (rt) rt.classList.remove('active'); }
        ['agentPanel', 'previewAgentPanel'].forEach(function (agentId) {
          var agent = global.document.getElementById(agentId);
          if (agent && !agent.classList.contains('hidden')) { agent.classList.add('hidden'); agent.style.display = 'none'; var ab = global.document.getElementById('btnToggleAgent'); if (ab) ab.classList.remove('active'); }
        });
        // The grid columns are owned by preview.js's updateGridColumns(), which runs on
        // the previewPanelChange event dispatched below: narrow screens draw the panel as
        // a bounded overlay drawer (col4=0, content-first); desktop shows it as a 420px
        // column beside content. Only append the panel here.
        grid.appendChild(panel);
      } else {
        global.document.body.appendChild(panel);
      }
      button.classList.add('active'); button.setAttribute('aria-expanded', 'true');
      // Let preview.js reconcile the grid + mutually-exclusive button states.
      global.dispatchEvent(new Event('previewPanelChange'));
      panel.querySelector('.panel-close-btn').onclick = close;
      controller = mount({body:panel.querySelector('.project-panel-body'), summary:panel.querySelector('#projectPanelSummary'), getContext:function () { return {root:root, project:project}; }, isOpen:function () { return Boolean(panel); }, openFeedback:openFeedback});
      controller.refresh();
    }
    button.dataset.sharedPanelBound = '1';
    button.addEventListener('click', function (event) { event.preventDefault(); event.stopImmediatePropagation(); if (panel) close(); else open(); }, true);
    global.addEventListener('pagehide', close, {once:true});
    return {close:close, refresh:function () { return controller && controller.refresh ? controller.refresh() : undefined; }};
  }
  function installPreviewPanel() {
    if (global.ClawMatePanels) {
      var query = new URLSearchParams(global.location.search);
      var root = query.get('root'), file = query.get('file') || '', project = file.split('/')[0];
      global.ClawMatePanels.install('preview', {
        project:{mount:mountPreview},
        // Preview keeps its mature card/filter renderer. These lightweight
        // controllers expose the same data/action sources for independent
        // consumers without binding a second set of UI handlers.
        feedback:{context:{root:root, project:project, file:file}},
        review:{context:{root:root, project:project, file:file}}
      });
      return;
    }
    // preview-common normally appends this asset first. Dynamic scripts do not
    // participate in defer ordering, so wait for its load rather than creating
    // a second project mount or losing this initialization.
    var script = document.querySelector('script[data-clawmate-panels]');
    if (!script) {
      script = document.createElement('script');
      script.src = './js/clawmate-panels.js';
      script.dataset.clawmatePanels = '1';
      document.head.appendChild(script);
    }
    if (!script.dataset.clawmatePanelsWaiting) {
      script.dataset.clawmatePanelsWaiting = '1';
      script.addEventListener('load', installPreviewPanel, {once:true});
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', installPreviewPanel); else installPreviewPanel();
})(window);
