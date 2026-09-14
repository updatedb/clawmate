/* Small, surface-scoped panel registry. It adapts existing controllers rather
 * than owning page-level DOM/event wiring. */
(function (global) {
  'use strict';
  if (global.ClawMatePanels) return;
  var mounted = Object.create(null), teardownBound = false;
  function key(surface, name) { return String(surface || 'shared') + ':' + name; }
  function contextOf(options) { return typeof options.getContext === 'function' ? options.getContext() : (options.context || {}); }
  function request(options, url, init) { return (options.fetch || global.fetch)(url, init); }
  function feedbackPanel(options) {
    var target = options.target;
    async function refresh() {
      var context = contextOf(options);
      var url = '/api/clawmate/feedback/list?root=' + encodeURIComponent(context.root || '') + '&project=' + encodeURIComponent(context.project || '') + '&file=' + encodeURIComponent(context.file || '');
      var response = await request(options, url), data = await response.json();
      if (target) target.textContent = (data.items || []).length ? '已加载 ' + data.items.length + ' 条反馈' : '暂无反馈';
      return data;
    }
    return {refresh: refresh, close: function () { if (target && options.clearOnClose) target.textContent = ''; }};
  }
  function reviewPanel(options) {
    var feedback = feedbackPanel(options);
    async function action(path, body) {
      var context = contextOf(options);
      var response = await request(options, '/api/clawmate/review/' + path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(Object.assign({root: context.root, project: context.project}, body))});
      if (!response.ok) throw new Error('评审请求失败');
      return response.json();
    }
    return {refresh: feedback.refresh, close: feedback.close, decide: function (ids, decision) { return action('decision', {ids: ids, decision: decision}); }, execute: function (ids) { return action('execute', {ids: ids}); }};
  }
  function build(name, options) {
    options = options || {};
    if (options.controller) return options.controller;
    if (name === 'project' && typeof options.mount === 'function') return options.mount();
    if (name === 'feedback') return feedbackPanel(options);
    if (name === 'review') return reviewPanel(options);
    if (name === 'agent') return {open: options.open, close: options.close, isOpen: options.isOpen};
    return null;
  }
  function closePanel(name, surface) {
    var id = key(surface, name), panel = mounted[id];
    if (!panel) return false;
    if (typeof panel.close === 'function') panel.close(); else if (typeof panel.destroy === 'function') panel.destroy();
    delete mounted[id]; return true;
  }
  function install(surface, panels) {
    var result = {}, requested = panels || {};
    Object.keys(requested).forEach(function (name) {
      var id = key(surface, name);
      if (!mounted[id]) mounted[id] = build(name, requested[name]);
      result[name] = mounted[id];
    });
    if (!teardownBound && global.addEventListener) {
      teardownBound = true;
      global.addEventListener('pagehide', function () {
        Object.keys(mounted).forEach(function (id) { var panel = mounted[id]; if (panel && typeof panel.close === 'function') panel.close(); });
        mounted = Object.create(null);
      }, {once: true});
    }
    return result;
  }
  global.ClawMatePanels = {install: install, getPanel: function (name, surface) { return mounted[key(surface, name)] || null; }, closePanel: closePanel};
})(window);
