/* ClawMate command palette — keyboard-first navigation (Ctrl/Cmd + K).
 *
 * Acts on three things in the file manager:
 *   • configured roots      → switch root            (app.selectRoot)
 *   • current directories   → navigate into a subdir (app.loadDir)
 *   • filename matches      → open the file's preview (preview.html)
 *
 * Loaded AFTER app.js. In a classic script, app.js's top-level `const state`
 * and `function selectRoot/loadDir/authFetch` are in the shared global scope,
 * so this file can reference them by bare name (guarded with typeof). When a
 * helper is missing it degrades safely instead of throwing.
 */
(function () {
  "use strict";

  var PALETTE_ID = "clawmateCommandPalette";
  var debounceTimer = null;
  var items = [];       // { type: root|dir|file, label, sub, icon, activate }
  var activeIndex = 0;

  // ── app.js global access (bare-name, guarded) ─────────────────────
  function getRoots() { return typeof state !== "undefined" ? (state.roots || []) : []; }
  function currentRoot() { return typeof state !== "undefined" ? state.rootId : ""; }
  function currentDir() { return typeof state !== "undefined" ? state.dir : ""; }
  function currentEntries() { return typeof state !== "undefined" ? (state.entries || []) : []; }
  function safeSelectRoot(id) { if (typeof selectRoot === "function") return selectRoot(id); }
  function safeLoadDir(dir) { if (typeof loadDir === "function") return loadDir(dir); }
  function safeAuthFetch(url) {
    if (typeof authFetch === "function") return authFetch(url);
    return fetch(url);
  }

  // ── open / close ─────────────────────────────────────────────────
  function el() { return document.getElementById(PALETTE_ID); }
  function listEl() { var e = el(); return e ? e.querySelector(".cp-list") : null; }
  function inputEl() { var e = el(); return e ? e.querySelector(".cp-input") : null; }
  function isOpen() { var e = el(); return !!e && e.style.display === "flex"; }

  function open() {
    var e = el();
    if (!e) return;
    e.style.display = "flex";
    var inp = inputEl();
    if (inp) { inp.value = ""; inp.focus(); }
    populateHints();
    render("");
  }
  function close() { var e = el(); if (e) e.style.display = "none"; }
  function toggle() { if (isOpen()) close(); else open(); }

  // ── hint items (projects across all roots) ───────────────────────
  // The palette shows only project cards. Selecting one jumps to it
  // (switchProject switches root as needed) and records MRU usage.

  function mruRecord(name, rootId) { if (typeof recordProjectUse === "function") recordProjectUse(rootId, name); }

  function relTime(ms) {
    if (typeof ms !== "number" || ms <= 0) return "—";
    var diff = Date.now() - ms;
    if (diff < 60000) return "刚刚";
    if (diff < 3600000) return Math.floor(diff / 60000) + " 分钟前";
    if (diff < 86400000) return Math.floor(diff / 3600000) + " 小时前";
    return Math.floor(diff / 86400000) + " 天前";
  }

  function projSort(a, b) {
    var am = a.mruAt >= 0 ? 0 : 1, bm = b.mruAt >= 0 ? 0 : 1;
    if (am !== bm) return am - bm;                       // 用过的排前
    var at = (am === 0 ? a.mruAt : a.mtime) - (bm === 0 ? b.mruAt : b.mtime);
    if (at !== 0) return at > 0 ? -1 : 1;                // 时间新→旧
    return a.name.localeCompare(b.name);
  }

  function populateHints() { items = []; activeIndex = 0; loadProjectsForLayout(); }

  // Fetch each root's projects (dirs with a .clawmate/ marker) via the existing
  // list endpoint, attach their MRU timestamp, sort, and render.
  function loadProjectsForLayout() {
    getRoots().forEach(function (r) {
      safeAuthFetch(
        "/api/clawmate/list?root=" + encodeURIComponent(r.id) + "&dir=&marker_filter=true"
      ).then(function (res) { return res.ok ? res.json() : null; })
        .then(function (data) {
          if (!data || !Array.isArray(data.entries)) return;
          data.entries.filter(function (e) { return e && e.is_dir && e.name && e.name.charAt(0) !== "."; })
            .forEach(function (e) {
              var mruAt = typeof projectUseAt === "function" ? projectUseAt(r.id, e.name) : -1;
              items.push({
                type: "project", root: r.id, name: e.name,
                label: e.name, mtime: e.mtime || 0, mruAt: mruAt, icon: "folder",
                activate: function () { switchProject(e.name, r.id); close(); },
              });
            });
          items.sort(projSort);
          render(inputEl() ? inputEl().value : "");
        }).catch(function () { /* ignore network errors */ });
    });
  }

  // Switch to the given project: switch root if it differs, then navigate into
  // the project dir (loadDir reloads dir panel + content + sets state.project).
  function switchProject(name, rootId) {
    if (rootId && rootId !== currentRoot()) safeSelectRoot(rootId);
    safeLoadDir(name);
    mruRecord(name, rootId);
  }

  // ── rendering ────────────────────────────────────────────────────
  function render(query) {
    var list = listEl();
    if (!list) return;
    var q = (query || "").trim().toLowerCase();
    var shown = items.filter(function (it) { return it.label.toLowerCase().indexOf(q) !== -1; });
    if (activeIndex >= shown.length) activeIndex = Math.max(0, shown.length - 1);
    if (!shown.length) { list.innerHTML = '<div class="cp-empty">没有匹配项目</div>'; return; }
    var html = shown.map(function (it, idx) {
      var when = relTime(it.mruAt >= 0 ? it.mruAt : it.mtime);
      return '<div class="cp-card' + (idx === activeIndex ? " active" : "") +
        '" data-index="' + idx + '" role="option" aria-selected="' + (idx === activeIndex) + '">' +
        '<span class="cp-card-ico">' + iconFor(it.icon) + "</span>" +
        '<span class="cp-card-body">' +
        '<span class="cp-card-name">' + escapeHtml(it.label) + "</span>" +
        '<span class="cp-card-root">' + escapeHtml(it.root) + "</span>" +
        '<span class="cp-card-when">最近使用 · ' + when + "</span>" +
        "</span></div>";
    }).join("");
    list.innerHTML = html;
  }

  function setActive(index) {
    var list = listEl(); if (!list) return;
    var shown = list.querySelectorAll(".cp-card");
    if (index < 0 || index >= shown.length) return;
    activeIndex = index;
    shown.forEach(function (n, i) {
      n.classList.toggle("active", i === activeIndex);
      n.setAttribute("aria-selected", i === activeIndex ? "true" : "false");
    });
    if (shown[activeIndex].scrollIntoView) shown[activeIndex].scrollIntoView({ block: "nearest" });
  }

  function activateCurrent() {
    // Recompute the visible list exactly as render() does so the click index
    // and Enter index always agree with what's on screen.
    var query = inputEl() ? inputEl().value : "";
    var shown = items.filter(function (it) { return it.label.toLowerCase().indexOf(query.trim().toLowerCase()) !== -1; });
    var it = shown[activeIndex];
    if (it && typeof it.activate === "function") it.activate();
  }

  // ── search ───────────────────────────────────────────────────────
  // The palette now searches only roots + projects (loaded on open in
  // populateHints). Filtering happens locally in render(query); no async file
  // search is used, so doSearch is a no-op kept for the debounced input path.
  function doSearch() { /* projects already loaded; render(query) filters */ }

  function openFile(relPath) {
    var rootId = currentRoot();
    if (!rootId) return;
    window.open(
      "/clawmate/preview.html?root=" + encodeURIComponent(rootId) +
      "&file=" + encodeURIComponent(relPath), "_blank"
    );
  }

  // ── icons / escaping ─────────────────────────────────────────────
  function iconFor(kind) {
    switch (kind) {
      case "home": return '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>';
      case "folder": return '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>';
      case "file": return '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M13 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/></svg>';
      default: return "";
    }
  }
  function escapeHtml(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  // ── events ───────────────────────────────────────────────────────
  function bindEvents() {
    var e = el();
    if (!e) return;

    var inp = inputEl();
    if (inp) {
      inp.addEventListener("input", function () {
        var q = inp.value;
        if (debounceTimer) clearTimeout(debounceTimer);
        if (!q.trim()) { populateHints(); render(""); return; }
        render(q);
        debounceTimer = setTimeout(function () { doSearch(q.trim()); }, 240);
      });
    }

    var list = listEl();
    if (list) {
      list.addEventListener("click", function (ev) {
        var node = ev.target && ev.target.closest ? ev.target.closest(".cp-card") : null;
        if (!node) return;
        activeIndex = parseInt(node.getAttribute("data-index"), 10) || 0;
        activateCurrent();
      });
      list.addEventListener("mousemove", function (ev) {
        var node = ev.target && ev.target.closest ? ev.target.closest(".cp-card") : null;
        if (!node) return;
        var idx = parseInt(node.getAttribute("data-index"), 10);
        if (!isNaN(idx) && idx !== activeIndex) setActive(idx);
      });
    }
    e.addEventListener("mousedown", function (ev) { if (ev.target === e) close(); });

    document.addEventListener("keydown", function (ev) {
      var k = ev.key;
      if ((ev.ctrlKey || ev.metaKey) && (k.toLowerCase() === "k")) { ev.preventDefault(); toggle(); return; }
      if (k === "Escape" && isOpen()) { ev.preventDefault(); close(); return; }
      if (!isOpen()) return;
      if (document.activeElement !== inp) return;
      if (k === "ArrowDown") { ev.preventDefault(); setActive(activeIndex + 1); }
      else if (k === "ArrowUp") { ev.preventDefault(); setActive(activeIndex - 1); }
      else if (k === "Enter") { ev.preventDefault(); activateCurrent(); }
    });
  }

  // ── search chips ─────────────────────────────────────────────────
  // .cp-chip buttons run the palette input value through the index search.
  function bindSearchChips() {
    var chips = document.querySelectorAll("#cpChips .cp-chip");
    Array.prototype.forEach.call(chips, function (chip) {
      chip.addEventListener("click", function () {
        var q = inputEl() ? inputEl().value : "";
        var kind = chip.getAttribute("data-cp-search");
        if (kind === "content" && typeof contentSearch === "function") contentSearch(q);
        else if (typeof fileSearch === "function") fileSearch(q);
        close();
      });
    });
  }

  function init() {
    if (!document.getElementById(PALETTE_ID)) return;
    bindEvents();
    bindSearchChips();
    var btn = document.getElementById("btnCommandPalette");
    if (btn) btn.addEventListener("click", toggle);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
