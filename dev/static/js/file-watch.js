/* Preview-file change watcher. This is separate from app.js's directory watcher:
 * a preview owns one file EventSource only. */
(function (global) {
  'use strict';

  var active = null;
  var DEFAULT_LABEL = '刷新大纲和内容';
  var UPDATE_LABEL = '有更新，点击刷新';

  function matches(update, file) {
    return Boolean(update) && Boolean(file) && (update.type === 'refresh' || update.path === file);
  }
  function setIndicator(button, hasUpdate) {
    if (!button) return;
    button.classList.toggle('has-update', Boolean(hasUpdate));
    var label = hasUpdate ? UPDATE_LABEL : DEFAULT_LABEL;
    button.title = label;
    button.setAttribute('aria-label', label);
  }
  function panelControllers() {
    var registry = global.ClawMatePanels;
    if (!registry || typeof registry.getPanel !== 'function') return [];
    return ['project', 'feedback', 'review', 'agent'].map(function (name) {
      return registry.getPanel(name, 'preview');
    }).filter(Boolean);
  }
  function create(options) {
    options = options || {};
    var root = options.root || '', file = options.file || '';
    var button = options.button || null, source = null, disposed = false;
    var onChange = typeof options.onChange === 'function' ? options.onChange : null;
    function close() { if (source) source.close(); source = null; }
    function refreshPanels() {
      return Promise.all(panelControllers().map(function (controller) {
        return typeof controller.refresh === 'function' ? Promise.resolve(controller.refresh()).catch(function () {}) : null;
      }).filter(Boolean));
    }
    function subscribe() {
      close();
      if (disposed || !root || !file || !global.EventSource) return;
      source = new global.EventSource('/api/clawmate/fs/events?root=' + encodeURIComponent(root) + '&file=' + encodeURIComponent(file));
      source.onmessage = function (event) {
        var update;
        try { update = JSON.parse(event.data); } catch (_) { return; }
        if (!matches(update, file)) return;
        setIndicator(button, true);
        if (onChange) onChange(update);
      };
    }
    async function manualRefresh(refreshContent) {
      setIndicator(button, false);
      try {
        if (typeof refreshContent === 'function') await refreshContent();
      } finally {
        // Replacing the source drops any stale connection before panels refresh.
        subscribe();
        await refreshPanels();
      }
    }
    function destroy() { disposed = true; close(); }
    subscribe();
    return {subscribe:subscribe, clear:function () { setIndicator(button, false); }, refreshPanels:refreshPanels, manualRefresh:manualRefresh, destroy:destroy};
  }
  function start(options) { if (active) active.destroy(); active = create(options); return active; }
  global.ClawMateFileWatch = {start:start, matches:matches, setIndicator:setIndicator};
})(window);
