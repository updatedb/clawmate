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

  // ── Theme helpers (for page-specific use like Mermaid theme) ──
  window._topbarResolvedTheme = function () {
    if (currentTheme === 'auto') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    return currentTheme;
  };

  // ── Mobile "more" menu (index + preview) ──
  // Folds the topbar action buttons (theme / logout / project / agent) into a
  // dropdown on mobile. Each mirrored item's `data-more` is the TARGET button id,
  // so clicking dispatches a native click and the page-specific handlers run
  // unchanged. Standalone menu actions, such as Settings, own their handlers.
  (function initMoreMenu() {
    var btn = document.getElementById('btnMoreMenu');
    var menu = document.querySelector('.more-menu');
    if (!btn || !menu) return;
    // Only show an item when its feature is actually available on the page — mirrored
    // from the corresponding topbar action button. A target is gated off either with an
    // inline `display:none` (e.g. the project panel only exists inside a project
    // directory) or with the `hidden` attribute (the admin-only settings gear) — NOT by
    // being merely CSS-folded on mobile, which leaves both of those empty. Both the
    // inline style and the attribute are written back so each mirrored item's
    // own `hidden` default stays in step with the target it mirrors.
    function _syncItems() {
      Array.prototype.forEach.call(menu.querySelectorAll('.more-item'), function (item) {
        var id = item.getAttribute('data-more');
        if (!id) return;
        var target = id ? document.getElementById(id) : null;
        var off = !target || target.style.display === 'none' || target.hidden;
        item.style.display = off ? 'none' : '';
        item.hidden = off;
      });
    }
    function setOpen(open) {
      menu.hidden = !open;
      btn.setAttribute('aria-expanded', String(open));
      btn.classList.toggle('active', open);
      if (open) _syncItems();
    }
    btn.addEventListener('click', function (e) { e.stopPropagation(); setOpen(menu.hidden); });
    menu.addEventListener('click', function (e) {
      var item = e.target.closest ? e.target.closest('.more-item') : null;
      if (item) {
        var id = item.getAttribute('data-more');
        var b = id && document.getElementById(id);
        if (b) b.click();
        setOpen(false);
      }
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setOpen(false); });
    document.addEventListener('click', function (e) {
      if (!menu.hidden && !menu.contains(e.target)) setOpen(false);
    });
  })();
})();
