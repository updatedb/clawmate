/* Surface-scoped adapter for the existing Agent runtime.  It owns no terminal
 * or session protocol: pages supply their established open/close callbacks. */
(function (global) {
  'use strict';
  if (global.ClawMateAgentPanel) return;

  function panelOf(options) {
    if (options.panel) return options.panel;
    return global.document && options.panelId ? global.document.getElementById(options.panelId) : null;
  }
  function mount(options) {
    options = options || {};
    var surface = options.surface || 'shared';
    var registry = global.ClawMatePanels;
    var existing = registry && registry.getPanel('agent', surface);
    if (existing) return existing;
    var panel = panelOf(options), button = options.button || (global.document && options.buttonId ? global.document.getElementById(options.buttonId) : null);
    function runtime() { return options.getAgent ? options.getAgent() : global.Agent; }
    function isOpen() {
      if (typeof options.isOpen === 'function') return Boolean(options.isOpen());
      var agent = runtime();
      return agent && typeof agent.isOpen === 'function' ? Boolean(agent.isOpen()) : Boolean(panel && !panel.classList.contains('hidden'));
    }
    function setVisible(open) {
      if (!panel) return;
      panel.classList.toggle('hidden', !open);
      if (!open && options.hideDisplay) panel.style.display = 'none';
      if (open && options.hideDisplay) panel.style.display = '';
      if (button) button.classList.toggle('active', open);
    }
    function open() {
      if (typeof options.open === 'function') return options.open();
      setVisible(true);
      var agent = runtime();
      if (agent && typeof agent.open === 'function') return agent.open.apply(agent, options.openArgs ? options.openArgs() : []);
    }
    function close() {
      if (typeof options.close === 'function') return options.close();
      setVisible(false);
      var agent = runtime();
      if (agent && typeof agent.close === 'function') return agent.close();
    }
    var controller = {open:open, close:close, isOpen:isOpen, toggle:function () { return isOpen() ? close() : open();}, panel:function () { return panel; }};
    if (registry) registry.install(surface, {agent:{controller:controller}});
    return controller;
  }
  function install(options) { return mount(options); }
  function close(surface) { return global.ClawMatePanels ? global.ClawMatePanels.closePanel('agent', surface || 'shared') : false; }
  global.ClawMateAgentPanel = {install:install, mount:mount, close:close, get:function (surface) { return global.ClawMatePanels && global.ClawMatePanels.getPanel('agent', surface || 'shared'); }};
})(window);
