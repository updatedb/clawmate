// ── Shared Topbar Logic (used by index.html + preview.html) ──
// Provides: theme cycling, logout, agent toggle placeholder.
// Include AFTER icons.js, BEFORE page-specific app.js / preview.js.

(function () {
  'use strict';

  // ── Theme ──
  var currentTheme = localStorage.getItem('clawmate-theme') || 'auto';

  function applyTheme(theme) {
    var html = document.documentElement;
    html.setAttribute('data-theme', theme);
  }

  function cycleTheme() {
    var map = { auto: 'dark', dark: 'light', light: 'auto' };
    currentTheme = map[currentTheme] || 'auto';
    var resolved = currentTheme === 'auto'
      ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : currentTheme;
    applyTheme(resolved);
    updateThemeButton();
    localStorage.setItem('clawmate-theme', currentTheme);
    if (window.Agent && window.Agent.syncTheme) window.Agent.syncTheme();
    // Notify page-specific handlers
    if (typeof window._onThemeChange === 'function') window._onThemeChange(resolved);
  }

  function updateThemeButton() {
    var btn = document.getElementById('themeToggle');
    if (!btn) return;
    var icons = { auto: 'sun-moon', dark: 'moon', light: 'sun' };
    var titles = { auto: '自动主题', dark: '深色模式', light: '浅色模式' };
    var icon = icons[currentTheme] || 'sun';
    btn.title = titles[currentTheme] || '切换主题';
    if (typeof iconSVG === 'function') {
      btn.innerHTML = iconSVG(icon, 16);
    }
  }

  // Init — respect the theme already set by the anti-flash <script> in <head>.
  // The sync script handles dark & auto-dark; for light, no attribute is needed.
  var resolvedInit = currentTheme === 'dark' ? 'dark'
    : currentTheme === 'auto' ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : 'light';
  applyTheme(resolvedInit);
  updateThemeButton();

  // Listen for system theme changes when in auto mode
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () {
    if (currentTheme === 'auto') {
      var r = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
      applyTheme(r);
      if (window.Agent && window.Agent.syncTheme) window.Agent.syncTheme();
      if (typeof window._onThemeChange === 'function') window._onThemeChange(r);
    }
  });
  var themeBtn = document.getElementById('themeToggle');
  if (themeBtn) themeBtn.addEventListener('click', cycleTheme);

  // ── Logout ──
  var logoutBtn = document.getElementById('btnLogout');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', function () {
      if (typeof authFetch === 'function') {
        authFetch('/api/clawmate/auth/logout', { method: 'POST' }).finally(function () {
          window.location.href = '/clawmate/login.html';
        });
      } else {
        fetch('/api/clawmate/auth/logout', { method: 'POST' }).finally(function () {
          window.location.href = '/clawmate/login.html';
        });
      }
    });
  }

  // ── Agent toggle placeholder ──
  // Each page wires its own agent panel open/close.
  // This module just ensures the toggle button exists and hands off to
  // page-specific Agent facade caller via a global hook.
  window._topbarToggleAgent = function () {
    var btn = document.getElementById('btnToggleAgent');
    if (btn) btn.click();
  };

  // ── Theme helpers (for page-specific use like Mermaid theme) ──
  window._topbarResolvedTheme = function () {
    if (currentTheme === 'auto') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    return currentTheme;
  };
  window._topbarGetTheme = function () { return currentTheme; };
})();
