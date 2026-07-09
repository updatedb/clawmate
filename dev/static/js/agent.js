// ===== Agent Panel — xterm.js (Claude/Codex) + markdown chat (OpenClaw) =====
//
// Exposes window.Agent API:
//   Agent.init({ wsUrl, rootId, dir, agentId, backend })  — one-time setup
//   Agent.open(rootId, dir, fileContext)     — open panel + connect WebSocket, optionally with file context
//   Agent.close()                            — close panel + disconnect
//   Agent.toggle()                           — toggle panel
//   Agent.updateRoot(rootId, dir)            — update current root/dir

(function () {
  'use strict';

  // --- xterm.js CDN (update version here → index.html <link>/<script> + preview.js follow) ---
  var XTERM_VERSION = '5.5.0';
  var XTERM_CDN_BASE = 'https://cdn.jsdelivr.net/npm/@xterm/xterm@' + XTERM_VERSION;

  // --- DOM refs (re-initializable with prefix for reuse in preview page) ---
  let _domPrefix = '';
  let panel, xtermContainer, chatView, chatMessages, chatInput, chatSendBtn, backendSelect, closeBtn, toggleBtn;
  let panelTitleEl;
  // Resize tracking shared between createTerminal & disconnectWs
  var _lastResizeSent = { cols: 0, rows: 0 };
  var _pendingResize = null;

  function _resolveDom(prefix) {
    _domPrefix = prefix || '';
    var p = _domPrefix;
    // Try prefixed IDs first, fall back to unprefixed (for main page where prefix is '')
    panel         = document.getElementById(p + 'AgentPanel') || document.getElementById(p + 'agentPanel') || document.getElementById('agentPanel');
    xtermContainer = document.getElementById(p + 'XtermContainer') || document.getElementById(p + 'xtermContainer') || document.getElementById('xtermContainer');
    chatView      = document.getElementById(p + 'AgentChatView') || document.getElementById(p + 'agentChatView') || document.getElementById('agentChatView');
    chatMessages  = document.getElementById(p + 'AgentChatMessages') || document.getElementById(p + 'agentChatMessages') || document.getElementById('agentChatMessages');
    chatInput     = document.getElementById(p + 'AgentChatInput') || document.getElementById(p + 'agentChatInput') || document.getElementById('agentChatInput');
    chatSendBtn   = document.getElementById(p + 'AgentChatSend') || document.getElementById(p + 'agentChatSend') || document.getElementById('agentChatSend');
    backendSelect = document.getElementById(p + 'AgentBackendSelect') || document.getElementById(p + 'agentBackendSelect') || document.getElementById('agentBackendSelect');
    closeBtn      = document.getElementById(p + 'BtnCloseAgent') || document.getElementById(p + 'btnCloseAgent') || document.getElementById('btnCloseAgent');
    toggleBtn     = document.getElementById(p + 'BtnToggleAgent') || document.getElementById(p + 'btnToggleAgent') || document.getElementById('btnToggleAgent');
    panelTitleEl  = document.getElementById(p + 'AgentPanelTitle') || document.getElementById(p + 'agentPanelTitle') || document.getElementById(p + 'AgentTitle') || document.getElementById(p + 'agentTitle') || document.getElementById('agentPanelTitle');
    // Re-bind backend select handler (may change after prefix update, e.g. on preview page)
    if (backendSelect) {
      backendSelect.onchange = function () {
        var bm = backendSelect.value;
        if (bm) switchBackend(bm);
      };
    }
    bindHeaderControls();
  }
  function xlog() {} // debug logging disabled

  // --- State ---
  let term = null;
  let fitAddon = null;
  let termResizeObserver = null;
  let ws = null;
  let wsUrl = '';
  const AGENT_PANEL_WIDTH = 750; // fixed: ~86 cols PTY at 14px monospace, matches terminal
  let collapseTimer = null;
  let animatingOut = false; // true during slide-out animation
  let currentRootId = '';
  let currentDir = '';
  let currentAgentId = '';  // kept for OpenClaw backend session routing
  let backendMode = 'claude';
  let _pendingFileContext = null;  // {path} sent on next ws.onopen
  let _lastFileContext = null;     // last preview file context, reused on reopen/toggle
  let _lastMousedownInPanel = false;  // tracks whether last click was inside agent panel
  let _knownFilesBySession = Object.create(null);  // sessionKey or pending scope -> { normalizedPath: true }
  let _typedInputBuffer = '';

  function isPtyBackend() {
    return backendMode === 'claude' || backendMode === 'codex';
  }
  let reconnectTimer = null;
  let reconnectAttempts = 0;
  const MAX_RECONNECT_ATTEMPTS = 10;
  let chatBuf = '';     // accumulating assistant text
  let chatBufEl = null; // current assistant bubble being built
  let chatStatusEl = null; // reconnection status element
  let currentSessionKey = '';  // tracks last session key from backend
  let flowPaused = false;    // xterm.js flow control: true when write buffer > HIGH watermark

  // --- Session history state ---
  var historyState = {
    sessions: [],
    page: 0,              // per-date page index
    pageSize: 20,         // sessions per page for pagination
    total: 0,             // total sessions in current query
    query: '',
    currentSessionId: null,

    // Date axis fields (when not searching)
    availableDates: [],   // ["2026-07-06", "2026-07-05", ...] sorted newest-first
    selectedDateIndex: 0, // index into availableDates
    axisScrollIndex: 0,   // first visible date index in the axis bar
  };
  var historyOverlay = null;
  var historyOverlayOpen = false;

  _resolveDom('');  // default: main page IDs

  function bindHeaderControls() {
    if (closeBtn) {
      closeBtn.onclick = function () { window.Agent.close(); };
    }

    if (!closeBtn || !closeBtn.parentNode) return;

    // "历史会话" button — placed before closeBtn in the header
    var toggleId = _domPrefix ? (_domPrefix + 'AgentSessionToggleBtn') : 'agentSessionToggleBtn';
    var sessionToggleBtn = document.getElementById(toggleId);
    if (!sessionToggleBtn) {
      sessionToggleBtn = document.createElement('button');
      sessionToggleBtn.id = toggleId;
      sessionToggleBtn.className = 'agent-panel-header-btn';
      var svgEl = typeof iconSVG === 'function' ? iconSVG('clock', 14) : '\u{1F4CB}';
      sessionToggleBtn.innerHTML = svgEl + '<span> 历史会话</span>';
      sessionToggleBtn.title = '历史会话';
      closeBtn.parentNode.insertBefore(sessionToggleBtn, closeBtn);
    }
    sessionToggleBtn.onclick = function () {
      openHistoryOverlay();
    };
  }


  // --- Grid update ---
  function updateGridColumns() {
    const content = document.querySelector('.content');
    if (!content) return;
    if (window.innerWidth < 768) {
      content.style.gridTemplateColumns = '';
      return;
    }
    const sidebar = document.getElementById('sidebar');
    const sidebarHidden = sidebar && (sidebar.classList.contains('hidden') || getComputedStyle(sidebar).display === 'none');
    const lW = sidebarHidden ? '0px' : '240px';
    const hidden = panel.classList.contains('hidden');
    if (hidden && !animatingOut) {
      content.style.gridTemplateColumns = lW + ' 1fr 0px 0px';
    } else {
      content.style.gridTemplateColumns = lW + ' 1fr 5px ' + AGENT_PANEL_WIDTH + 'px';
    }
  }

  // --- View mode switching ---
  function showXtermMode() {
    xtermContainer.classList.remove('hidden');
    xtermContainer.style.display = '';
    chatView.classList.add('hidden');
    chatView.style.display = '';
  }
  function showChatMode() {
    xtermContainer.classList.add('hidden');
    xtermContainer.style.display = '';
    chatView.classList.remove('hidden');
    chatView.style.display = '';
    if (chatInput) chatInput.focus();
  }

  function restoreTerminalImeTarget() {
    if (!term || !term.textarea) {
      if (term) term.focus();
      return;
    }
    var ta = term.textarea;
    function refocus() {
      try { ta.focus({ preventScroll: true }); } catch (_) { ta.focus(); }
      try {
        ta.value = '';
        ta.setSelectionRange(0, 0);
      } catch (_) {}
    }
    refocus();
    setTimeout(function () {
      refocus();
    }, 0);
  }

  function normalizeKnownFilePath(path) {
    var value = String(path || '').trim();
    if (!value) return '';
    if (value.charAt(0) === '@') value = value.slice(1).trim();
    return value;
  }

  function pendingFileScopeKey() {
    return 'pending:' + backendMode + ':' + (currentRootId || '') + ':' + (currentDir || '');
  }

  function currentFileScopeKey() {
    return currentSessionKey || pendingFileScopeKey();
  }

  function ensureKnownFileBucket(scopeKey) {
    if (!_knownFilesBySession[scopeKey]) {
      _knownFilesBySession[scopeKey] = Object.create(null);
    }
    return _knownFilesBySession[scopeKey];
  }

  function rememberKnownFile(path, scopeKey) {
    var normalized = normalizeKnownFilePath(path);
    if (!normalized) return '';
    ensureKnownFileBucket(scopeKey || currentFileScopeKey())[normalized] = true;
    return normalized;
  }

  function hasKnownFile(path, scopeKey) {
    var normalized = normalizeKnownFilePath(path);
    if (!normalized) return false;
    var bucket = _knownFilesBySession[scopeKey || currentFileScopeKey()];
    return !!(bucket && bucket[normalized]);
  }

  function migrateKnownFiles(fromScopeKey, toScopeKey) {
    if (!fromScopeKey || !toScopeKey || fromScopeKey === toScopeKey) return;
    var fromBucket = _knownFilesBySession[fromScopeKey];
    if (!fromBucket) return;
    var toBucket = ensureKnownFileBucket(toScopeKey);
    Object.keys(fromBucket).forEach(function (path) {
      toBucket[path] = true;
    });
    delete _knownFilesBySession[fromScopeKey];
  }

  function extractKnownFilePath(text) {
    var line = cleanTerminalInput(String(text || '')).trim();
    if (!line || line.charAt(0) !== '@') return '';
    return normalizeKnownFilePath(line);
  }

  function trackTypedFileReferences(data) {
    _typedInputBuffer += String(data || '');
    if (_typedInputBuffer.indexOf('\r') === -1 && _typedInputBuffer.indexOf('\n') === -1) return;
    var parts = _typedInputBuffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
    for (var i = 0; i < parts.length - 1; i++) {
      var path = extractKnownFilePath(parts[i]);
      if (path) rememberKnownFile(path);
    }
    _typedInputBuffer = parts[parts.length - 1];
  }

  // --- xterm.js init ---
  function createTerminal() {
    if (term) { xlog('init', 'term already exists, skipping'); return; }
    const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
    var bg, fg, selBg, selFg, selInactiveBg;
    if (isDark) {
      bg = '#111827';
      fg = '#e2e8f0';
      selBg = '#1e3a5f';
      selFg = '#f0f9ff';
      selInactiveBg = '#1a2332';
    } else {
      bg = '#ffffff';
      fg = '#1e293b';
      selBg = '#bfdbfe';
      selFg = '#1e293b';
      selInactiveBg = '#e2e8f0';
    }
    const cursor = '#14b8a6';

    // Estimate cols/rows from container before Terminal creation
    var fontFamily = '"JetBrains Mono", "Cascadia Code", "Fira Code", "Consolas", "SF Mono", "DejaVu Sans Mono", monospace';
    var _measureSpan = document.createElement('span');
    _measureSpan.style.cssText = 'position:absolute;visibility:hidden;font-family:' + fontFamily + ';font-size:14px;white-space:pre;';
    _measureSpan.textContent = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    document.body.appendChild(_measureSpan);
    var CHAR_W = _measureSpan.offsetWidth / 62;
    document.body.removeChild(_measureSpan);
    if (!(CHAR_W > 4 && CHAR_W < 16)) CHAR_W = 8.4;
    var CHAR_H = 19.6;
    // Guard against tiny dimensions during CSS transitions — the panel
    // slides in with translate(), and the container can report ~4px
    // before the animation finishes.  Treat <50px as invalid.
    var rawW = xtermContainer.clientWidth;
    var rawH = xtermContainer.clientHeight;
    var containerW = (rawW != null && rawW > 50) ? rawW : 600;
    var containerH = (rawH != null && rawH > 50) ? rawH : 400;
    var usableW = Math.max(100, containerW - 12 - 6);
    var usableH = Math.max(100, containerH - 8);
    var estimatedCols = Math.max(40, Math.floor(usableW / CHAR_W));
    var estimatedRows = Math.max(10, Math.floor(usableH / CHAR_H));

    xlog('init', 'raw=' + rawW + 'x' + rawH +
      ' container=' + containerW + 'x' + containerH +
      ' usable=' + Math.round(usableW) + 'x' + Math.round(usableH) +
      ' estimated cols=' + estimatedCols + ' rows=' + estimatedRows);

    term = new Terminal({
      cursorBlink: true, cursorStyle: 'bar',
      fontSize: 14, fontFamily: '"JetBrains Mono", "Cascadia Code", "Fira Code", "Consolas", "SF Mono", "DejaVu Sans Mono", monospace',
      letterSpacing: 0, lineHeight: 1.4,
      allowTransparency: false,
      drawBoldTextInBrightColors: false,
      theme: {
        background: bg, foreground: fg, cursor: cursor,
        selectionBackground: selBg, selectionForeground: selFg,
        selectionInactiveBackground: selInactiveBg,
      },
      allowProposedApi: true, scrollback: 65535, cols: estimatedCols, rows: estimatedRows,
    });

    // Save estimated dimensions BEFORE FitAddon.fit() potentially shrinks
    // them to match the animating container (see guard above).
    window._agentInitCols = estimatedCols;
    window._agentInitRows = estimatedRows;

    if (typeof FitAddon !== 'undefined') {
      fitAddon = new FitAddon.FitAddon();
      term.loadAddon(fitAddon);
      xlog('init', 'FitAddon loaded');
    } else {
      xlog('init', 'FitAddon NOT available — terminal will NOT auto-resize');
    }
    // if (typeof WebglAddon !== 'undefined') {
    //   try { term.loadAddon(new WebglAddon.WebglAddon()); xlog('init', 'WebglAddon loaded'); } catch (_) { xlog('init', 'WebglAddon failed', _); }
    // }

    term.open(xtermContainer);
    // Defer FitAddon.fit() — during slide-in transition the container
    // may report a tiny width (4px).  The ResizeObserver + font-ready
    // callbacks handle the real fit after layout settles.
    if (fitAddon && rawW > 200) {
      try { fitAddon.fit(); } catch (_) {}
      if (term) { try { term.refresh(0, term.rows - 1); } catch (_) {} }
    } else if (fitAddon) {
      xlog('init', 'skipping immediate fit — container too narrow (' + rawW + 'px), waiting for layout');
    }
    xlog('init', 'term.open() done — term.element=' + (!!term.element) + ' term.textarea=' + (!!term.textarea));

    // IME recovery
    var termElement = term.element;
    if (termElement) {
      termElement.addEventListener('click', function () { xlog('focus', 'click → term.focus()'); term.focus(); });
      termElement.addEventListener('mousedown', function () { term.focus(); });
    }

    var textarea = term.textarea;
    if (textarea) {
      textarea.addEventListener('compositionstart', function () { xlog('ime', 'compositionstart'); });
      textarea.addEventListener('compositionend', function () {
        xlog('ime', 'compositionend → refocus');
        setTimeout(function () { term.focus(); }, 0);
      });
      textarea.addEventListener('blur', function (e) {
        var rtTag = e.relatedTarget ? (e.relatedTarget.tagName || 'unknown') : 'null';
        xlog('focus', 'textarea blur relatedTarget=' + rtTag + ' panel.hidden=' + panel.classList.contains('hidden') + ' lastMousedownInPanel=' + _lastMousedownInPanel);
        if (panel.classList.contains('hidden')) return;
        // Only refocus if the user clicked inside the agent panel.
        // When clicking on non-focusable content (markdown body), relatedTarget is null
        // and refocusing would steal focus back, breaking text selection.
        if (e.relatedTarget === null && _lastMousedownInPanel) {
          xlog('focus', 'refocus (IME window or panel click)');
          setTimeout(function () { term.focus(); }, 0);
        }
      });
      textarea.addEventListener('focus', function () { xlog('focus', 'textarea gained focus'); });

      // Track whether last click was inside the agent panel (capture phase)
      document.addEventListener('mousedown', function(e) {
        _lastMousedownInPanel = !!(panel && panel.contains(e.target));
      }, true);
    }

    // Fit after layout (with font-ready guard)
    function doFit(label) {
      if (panel.classList.contains('hidden') || !fitAddon) return;
      // Skip fit during slide-in transition — container can report ~4px
      var rw = xtermContainer.clientWidth;
      if (rw < 50) return;
      try { fitAddon.fit(); } catch (_) {}
      if (term) {
        try { term.refresh(0, term.rows - 1); } catch (_) {}
        requestAnimationFrame(function () { try { term.refresh(0, term.rows - 1); } catch (_) {} });
      }
    }

    if (fitAddon) {
      var fontFitted = false;
      var fontTimer = setTimeout(function () {
        if (!fontFitted) { fontFitted = true; doFit('font-timeout'); }
      }, 1000);
      if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(function () {
          clearTimeout(fontTimer);
          if (!fontFitted) { fontFitted = true; requestAnimationFrame(function () { doFit('fonts-ready'); }); }
        }).catch(function () {
          clearTimeout(fontTimer);
          if (!fontFitted) { fontFitted = true; requestAnimationFrame(function () { requestAnimationFrame(function () { doFit('fonts-fallback'); }); }); }
        });
      } else {
        clearTimeout(fontTimer);
        fontFitted = true;
        requestAnimationFrame(function () { requestAnimationFrame(function () { doFit('rAFx2'); }); });
      }
    }

    // ResizeObserver (debounced 200ms)
    if (typeof ResizeObserver !== 'undefined') {
      if (termResizeObserver) termResizeObserver.disconnect();
      var _roDebounce = null;
      termResizeObserver = new ResizeObserver(function (entries) {
        if (_roDebounce) clearTimeout(_roDebounce);
        _roDebounce = setTimeout(function () {
          _roDebounce = null;
          var r = entries[0] && entries[0].contentRect;
          xlog('resize-observer', 'fired container=' + (r ? Math.round(r.width) + 'x' + Math.round(r.height) : '?') + ' hidden=' + panel.classList.contains('hidden'));
          doFit('resize-observer');
        }, 200);
      });
      termResizeObserver.observe(xtermContainer);
      xlog('init', 'ResizeObserver active on xtermContainer (200ms debounce)');
    }

    // Data / resize forward to WebSocket
    term.onData(function (data) {
      xlog('data', 'len=' + data.length + ' preview=' + JSON.stringify(data.slice(0, 40)) + ' ws=' + (ws ? ws.readyState : 'null'));
      trackTypedFileReferences(data);
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(data);
      }
    });

    term.onResize(function (size) {
      xlog('resize', 'term.onResize cols=' + size.cols + ' rows=' + size.rows);
      _scheduleResize(size.cols, size.rows);
    });

    function _scheduleResize(cols, rows) {
      if (_lastResizeSent.cols === 0 && _lastResizeSent.rows === 0) {
        _sendResize(cols, rows);
        return;
      }
      if (_pendingResize) clearTimeout(_pendingResize);
      _pendingResize = setTimeout(function () {
        _pendingResize = null;
        _sendResize(cols, rows);
      }, 50);
    }

    function _sendResize(cols, rows) {
      if (cols === _lastResizeSent.cols && rows === _lastResizeSent.rows) return;
      _lastResizeSent = { cols: cols, rows: rows };
      if (ws && ws.readyState === WebSocket.OPEN) {
        try { ws.send(JSON.stringify({ type: 'resize', cols: cols, rows: rows })); } catch (_) {}
      }
    }

    function _flushResize() {
      if (_pendingResize) { clearTimeout(_pendingResize); _pendingResize = null; }
      if (term) { _sendResize(term.cols, term.rows); }
    }

    // Flow control
    if (term.onFlowControlPause) {
      term.onFlowControlPause(function () { flowPaused = true; xlog('flow', 'PAUSE'); });
      term.onFlowControlResume(function () { flowPaused = false; xlog('flow', 'RESUME'); });
      xlog('init', 'Flow control handlers registered');
    }
  }

  // --- Chat view (OpenClaw backend) ---
  function addChatBubble(role, text) {
    var div = document.createElement('div');
    div.className = 'agent-chat-msg agent-chat-' + role;
    if (role === 'assistant') {
      div.innerHTML = text;
    } else {
      div.textContent = text;
    }
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
  }

  function showChatStatus(text, type) {
    if (!chatMessages) return;
    if (chatStatusEl) { chatStatusEl.remove(); chatStatusEl = null; }
    if (!text) return;
    chatStatusEl = document.createElement('div');
    chatStatusEl.className = type === 'error' ? 'agent-chat-error' : 'agent-chat-info';
    chatStatusEl.textContent = text;
    chatMessages.appendChild(chatStatusEl);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function clearChatStatus() {
    if (chatStatusEl) { chatStatusEl.remove(); chatStatusEl = null; }
  }

  // Pre-bind markdownit so it's always available inside the IIFE
  var _mdRenderer = typeof window.markdownit !== 'undefined'
    ? window.markdownit({ html: false, linkify: true, breaks: true })
    : null;

  function cleanTerminalInput(raw) {
    // Strip ANSI escape codes and process backspace characters
    if (!raw) return '';
    // Remove OSC sequences: ESC ] ... (ST = ESC \ or BEL)
    var s = raw.replace(/\x1b\][^\x1b\x07]*(?:\x1b\\|\x07)/g, '');
    // Remove CSI sequences: ESC [ param* intermediate* byte
    s = s.replace(/\x1b\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]/g, '');
    // Remove remaining bare ESC + any char
    s = s.replace(/\x1b./g, '');
    // Strip non-printable control chars (keep tab, newline)
    var out = '';
    for (var i = 0; i < s.length; i++) {
      var c = s.charAt(i);
      if (c >= ' ' || c === '\t' || c === '\n' || c === '\r') {
        out += c;
      }
    }
    // Process backspace (DEL = \x7f, BS = \b)
    var buf = [];
    for (var i = 0; i < out.length; i++) {
      var c = out.charAt(i);
      if (c === '\x7f' || c === '\b') {
        if (buf.length > 0) buf.pop();
      } else {
        buf.push(c);
      }
    }
    return buf.join('').trim();
  }

  function renderMarkdown(el, rawText) {
    if (_mdRenderer) {
      try {
        el.innerHTML = _mdRenderer.render(rawText || '');
      } catch (_) {
        el.textContent = rawText || '';
      }
    } else {
      el.textContent = rawText || '';
    }
  }

  function handleChatMessage(msg) {
    var type = msg.type || '';

    if (type === 'info') {
      if (msg.sessionKey && panelTitleEl) {
        panelTitleEl.textContent = msg.sessionKey;
      }
      var info = document.createElement('div');
      info.className = 'agent-chat-info';
      info.textContent = msg.text || '';
      chatMessages.appendChild(info);
      chatMessages.scrollTop = chatMessages.scrollHeight;
      return;
    }

    if (type === 'error') {
      // Replace pending '...' placeholder bubble if present
      if (chatBufEl) {
        chatBufEl.textContent = '✕ ' + (msg.text || 'Unknown error');
        chatBufEl.className = 'agent-chat-msg agent-chat-error';
        chatBufEl = null;
        chatBuf = '';
      } else {
        var err = document.createElement('div');
        err.className = 'agent-chat-error';
        err.textContent = '✕ ' + (msg.text || 'Unknown error');
        chatMessages.appendChild(err);
      }
      chatMessages.scrollTop = chatMessages.scrollHeight;
      return;
    }

    if (type === 'user') {
      addChatBubble('user', msg.text || '');
      chatBuf = '';
      chatBufEl = addChatBubble('assistant', '...');
      return;
    }

    if (type === 'assistant') {
      if (msg.text) {
        chatBuf += msg.text;
        if (chatBufEl) {
          chatBufEl.textContent = chatBuf;
          renderMarkdown(chatBufEl, chatBuf);
          chatMessages.scrollTop = chatMessages.scrollHeight;
        }
      }
      if (msg.final) {
        chatBuf = '';
        chatBufEl = null;
        chatMessages.scrollTop = chatMessages.scrollHeight;
      }
      return;
    }
  }

  // --- Chat input ---
  function sendChatMessage() {
    var text = chatInput.value.trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(text + '\r');
    chatInput.value = '';
    chatInput.focus();
  }

  if (chatInput) {
    chatInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendChatMessage();
      }
    });
  }
  if (chatSendBtn) {
    chatSendBtn.addEventListener('click', sendChatMessage);
  }

  // --- WebSocket ---
  function connectWs() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    if (!wsUrl) return;

    // Prefer saved init dimensions (pre-fit) over live term.cols/rows
    // which may have been shrunk by FitAddon during a CSS transition.
    var initCols = window._agentInitCols;
    var initRows = window._agentInitRows;
    if (!initCols || initCols < 10) {
      initCols = (term && term.cols && term.cols >= 10) ? term.cols : 80;
    }
    if (!initRows || initRows < 5) {
      initRows = (term && term.rows && term.rows >= 5) ? term.rows : 24;
    }

    var url = wsUrl +
      '?root=' + encodeURIComponent(currentRootId || '') +
      '&dir=' + encodeURIComponent(currentDir || '') +
      '&agentId=' + encodeURIComponent(currentAgentId || '') +
      '&backend=' + encodeURIComponent(backendMode) +
      '&cols=' + initCols +
      '&rows=' + initRows;

    xlog('ws', 'connecting backend=' + backendMode + ' url=' + url);
    try { ws = new WebSocket(url); } catch (e) { xlog('ws', 'constructor failed', e); scheduleReconnect(); return; }

    ws.onopen = function () {
      xlog('ws', 'OPEN');
      reconnectAttempts = 0;
      if (isPtyBackend() && term) {
        try { ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows })); } catch (_) {}
        term.clear();
        term.writeln('\x1b[1;36m✓ 已连接 Agent 终端\x1b[0m');
        term.writeln('\x1b[2m  Ctrl+A 行首  \x1b[0m\x1b[1;90m|\x1b[0m\x1b[2m  Ctrl+E 行尾  \x1b[0m\x1b[1;90m|\x1b[0m\x1b[2m  Ctrl+U 删除当前行  \x1b[0m\x1b[1;90m|\x1b[0m\x1b[2m  Ctrl+K 删除光标到行尾  \x1b[0m\x1b[1;90m|\x1b[0m\x1b[2m  Ctrl+L 清屏\x1b[0m');
        term.writeln('');
        var fileContext = _pendingFileContext || _lastFileContext;
        if (fileContext) {
          var filePath = normalizeKnownFilePath(fileContext.path || '');
          // On reconnect (currentSessionKey already set), always re-inject
          // so the agent knows about the previewed file even if the path
          // was already known from a previous WS connection.
          if (filePath && (!hasKnownFile(filePath) || currentSessionKey)) {
            try {
              ws.send(JSON.stringify({ type: 'file_context', path: fileContext.path || '' }));
              rememberKnownFile(filePath);
            } catch (_) {}
          }
          _pendingFileContext = null;
        }
      }
      if (backendMode === 'openclaw') {
        clearChatStatus();
      }
    };

    ws.onmessage = function (e) {
      // Intercept session info messages (works for both backends)
      try {
        var msg = JSON.parse(e.data);
        if (msg.type === 'session' && msg.key) {
          if (!currentSessionKey) {
            migrateKnownFiles(pendingFileScopeKey(), msg.key);
          }
          if (panelTitleEl) panelTitleEl.textContent = msg.key;
          // Write session info to terminal for PTY backends (claude/codex)
          if (isPtyBackend() && term) {
            if (!currentSessionKey) {
              // First connection — show session key
              term.writeln('\x1b[1;36m📋 会话: ' + msg.key + '\x1b[0m');
            }
          }
          if (currentSessionKey && msg.key !== currentSessionKey) {
            xlog('session', 'key changed: ' + currentSessionKey + ' -> ' + msg.key);
            currentSessionKey = msg.key;
            setTimeout(function () { reconnectToNewSession(); }, 0);
            return;
          }
          currentSessionKey = msg.key;
          return;
        }
      } catch (_) {}

      if (isPtyBackend() && term) {
        if (flowPaused) { return; }
        term.write(e.data);
        return;
      }
      if (backendMode === 'openclaw') {
        try {
          var chatMsg = JSON.parse(e.data);
          handleChatMessage(chatMsg);
        } catch (_) {
          // Raw text fallback (banner etc.)
        }
      }
    };

    ws.onclose = function () {
      xlog('ws', 'CLOSE');
      if (isPtyBackend() && term) {
        term.writeln('\r\n\x1b[1;33m⚠ 连接已断开\x1b[0m');
      }
      if (backendMode === 'openclaw') {
        // Replace pending '...' placeholder if present
        if (chatBufEl) {
          chatBufEl.textContent = '⚠ 连接已断开，正在重连...';
          chatBufEl.className = 'agent-chat-msg agent-chat-error';
          chatBufEl = null;
          chatBuf = '';
        }
        showChatStatus('⚠ 连接已断开，正在重连...', 'error');
      }
      ws = null;
      scheduleReconnect();
    };

    ws.onerror = function () {
      xlog('ws', 'ERROR');
      // onclose always fires after onerror and handles reconnect messaging;
      // avoid duplicate error messages in the terminal / chat view.
    };
  }

  function disconnectWs() {
    clearReconnect();
    if (panelTitleEl) panelTitleEl.textContent = 'Agent';
    if (ws) { ws.onclose = null; ws.close(); ws = null; }
    if (term) {
      try { term.blur(); } catch (_) {}
      term.clear(); term.writeln('\x1b[2m终端已断开。\x1b[0m');
    }
    if (chatMessages) { chatMessages.innerHTML = ''; }
    chatBuf = ''; chatBufEl = null; chatStatusEl = null;
    _lastResizeSent = { cols: 0, rows: 0 };
    if (_pendingResize) { clearTimeout(_pendingResize); _pendingResize = null; }
    flowPaused = false;
  }

  function scheduleReconnect() {
    clearReconnect();
    if (panel.classList.contains('hidden')) return;
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      if (term) { term.writeln('\r\n\x1b[1;31m已达最大重连次数\x1b[0m'); }
      return;
    }
    var delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 15000);
    reconnectAttempts++;
    if (term) { term.writeln('\r\n\x1b[2m' + delay / 1000 + 's 后自动重连...\x1b[0m'); }
    reconnectTimer = setTimeout(function () {
      if (!panel.classList.contains('hidden')) { connectWs(); }
    }, delay);
  }

  function clearReconnect() {
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  }

  // --- Session key change → reconnect to new project ---
  function reconnectToNewSession() {
    xlog('session', 'reconnecting to new session...');
    clearReconnect();

    if (ws) {
      ws.onclose = null;
      ws.onerror = null;
      try { ws.close(); } catch (_) {}
      ws = null;
    }

    if (isPtyBackend() && term) {
      term.reset();
      term.writeln('\x1b[1;36m⟳ 项目已切换，重新连接...\x1b[0m');
    }
    if (backendMode === 'openclaw' && chatMessages) {
      chatMessages.innerHTML = '';
      chatBuf = '';
      chatBufEl = null;
      chatStatusEl = null;
    }

    reconnectAttempts = 0;
    connectWs();
  }

  // --- Resize handler ---
  window.addEventListener('resize', function () {
    updateGridColumns();
    // xtermContainer ResizeObserver handles terminal fit on size change
  });
  // --- Backend select dropdown ---
  function switchBackend(newBackend) {
    if (newBackend !== 'claude' && newBackend !== 'codex' && newBackend !== 'openclaw') return;
    if (backendMode === newBackend) return;

    xlog('backend', 'switching: ' + backendMode + ' → ' + newBackend);
    backendMode = newBackend;

    // Persist per-project preference
    if (currentRootId) {
      try { localStorage.setItem('clawmate_backend_' + currentRootId, backendMode); } catch (_) {}
    }

    // Update select if it doesn't match (e.g. set programmatically)
    if (backendSelect && backendSelect.value !== backendMode) {
      backendSelect.value = backendMode;
    }

    // If panel is not open, just save the preference — next open will use it
    var wasOpen = panel && !panel.classList.contains('hidden');
    if (!wasOpen) return;

    // Force-close current connection
    clearReconnect();
    if (ws) {
      ws.onclose = null;
      ws.onerror = null;
      try { ws.close(); } catch (_) {}
      ws = null;
    }
    currentSessionKey = '';

    // Dispose old terminal before creating a new one
    if (term) {
      try { term.dispose(); } catch (_) {}
      term = null;
    }
    if (xtermContainer) xtermContainer.innerHTML = '';

    // Clear terminal display
    if (chatMessages) { chatMessages.innerHTML = ''; }
    chatBuf = ''; chatBufEl = null; chatStatusEl = null;

    // Switch view mode
    if (backendMode === 'openclaw') {
      showChatMode();
      chatMessages.innerHTML = '';
      chatBuf = ''; chatBufEl = null;
    } else {
      showXtermMode();
      createTerminal();
    }

    // Reset state
    _lastResizeSent = { cols: 0, rows: 0 };
    if (_pendingResize) { clearTimeout(_pendingResize); _pendingResize = null; }
    flowPaused = false;

    reconnectAttempts = 0;
    connectWs();

    // Reconnect ResizeObserver
    if (termResizeObserver && xtermContainer) {
      try { termResizeObserver.unobserve(xtermContainer); } catch (_) {}
      try { termResizeObserver.observe(xtermContainer); } catch (_) {}
    }

    // Focus after switch
    setTimeout(function () {
      if (backendMode === 'openclaw') {
        if (chatInput) chatInput.focus();
      } else {
        if (term) term.focus();
      }
    }, 200);
  }

  // ── History Overlay ──

  function ensureHistoryOverlay() {
    if (historyOverlay) return historyOverlay;
    var p = _domPrefix;
    historyOverlay = document.createElement('div');
    historyOverlay.id = p + 'AgentHistoryOverlay';
    historyOverlay.className = 'agent-history-overlay hidden';
    historyOverlay.innerHTML =
      '<div class="agent-history-overlay-header">' +
        '<span class="agent-history-overlay-title">历史会话</span>' +
        '<span class="agent-header-search-wrap">' +
          '<input type="text" class="agent-header-search" placeholder="搜索会话...">' +
          '<button class="agent-header-search-clear" title="清除搜索">' + iconSVG('broom', 14) + '</button>' +
        '</span>' +
        '<button class="agent-history-overlay-close" title="关闭历史会话">&times;</button>' +
      '</div>' +
      '<div class="agent-history-overlay-body"></div>';
    panel.appendChild(historyOverlay);

    // Bind search
    var searchInput = historyOverlay.querySelector('.agent-header-search');
    searchInput.addEventListener('input', function () {
      historyState.query = this.value;
      historyState.page = 0;
      loadHistorySessions();
    });

    // Bind overlay close
    historyOverlay.querySelector('.agent-history-overlay-close').addEventListener('click', closeHistoryOverlay);

    // Bind clear search button
    var clearBtn = historyOverlay.querySelector('.agent-header-search-clear');
    if (clearBtn) {
      clearBtn.addEventListener('click', function () {
        var input = historyOverlay.querySelector('.agent-header-search');
        if (input) input.value = '';
        historyState.query = '';
        historyState.page = 0;
        loadHistorySessions();
        if (input) input.focus();
      });
    }

    historyOverlay.querySelector('.agent-history-overlay-header')._overlayHeaderMode = 'list';

    return historyOverlay;
  }

  function openHistoryOverlay() {
    if (historyOverlayOpen) return;
    var overlay = ensureHistoryOverlay();
    historyState.page = 0;
    historyState.query = '';
    historyState.selectedDateIndex = 0;
    historyState.axisScrollIndex = 0;
    historyState.availableDates = [];
    var searchInput = overlay.querySelector('.agent-header-search');
    if (searchInput) searchInput.value = '';
    historyOverlayOpen = true;
    overlay.classList.remove('hidden');
    loadHistorySessions();
  }

  function closeHistoryOverlay() {
    if (!historyOverlayOpen || !historyOverlay) return;
    historyOverlayOpen = false;
    historyOverlay.classList.add('hidden');
  }

  function setOverlayHeaderMode(mode, title) {
    var overlay = ensureHistoryOverlay();
    var header = overlay.querySelector('.agent-history-overlay-header');
    var xIcon = typeof iconSVG === 'function' ? iconSVG('x', 14) : '×';
    var backIcon = typeof iconSVG === 'function' ? iconSVG('chevron-left', 14) : '←';
    var clockIcon = typeof iconSVG === 'function' ? iconSVG('clock', 14) : '';
    // Skip rebuild if already in list mode — avoids destroying the search input (and losing focus)
    if (mode === 'list' && header._overlayHeaderMode === 'list') {
      var searchInput = header.querySelector('.agent-header-search');
      if (searchInput && searchInput.value !== historyState.query) {
        searchInput.value = historyState.query || '';
      }
      return;
    }
    if (mode === 'list') {
      header.innerHTML =
        clockIcon +
        '<span class="agent-history-overlay-title">历史会话</span>' +
        '<span class="agent-header-search-wrap">' +
          '<input type="text" class="agent-header-search" placeholder="搜索会话..." value="' + escHtml(historyState.query || '') + '">' +
          '<button class="agent-header-search-clear" title="清除搜索">' + iconSVG('broom', 14) + '</button>' +
        '</span>' +
        '<button class="agent-history-overlay-close" title="关闭历史会话">' + xIcon + '</button>';
      var searchInput = header.querySelector('.agent-header-search');
      searchInput.addEventListener('input', function () {
        historyState.query = this.value;
        historyState.page = 0;
        loadHistorySessions();
      });
      var clearBtn = header.querySelector('.agent-header-search-clear');
      if (clearBtn) {
        clearBtn.addEventListener('click', function () {
          searchInput.value = '';
          historyState.query = '';
          historyState.page = 0;
          loadHistorySessions();
          searchInput.focus();
        });
      }
      header.querySelector('.agent-history-overlay-close').addEventListener('click', closeHistoryOverlay);
      header._overlayHeaderMode = 'list';
    } else if (mode === 'detail') {
      header.innerHTML =
        '<button class="agent-history-overlay-back" title="返回列表">' + backIcon + '</button>' +
        '<span class="agent-history-overlay-title">' + escHtml(title || '') + '</span>' +
        '<button class="agent-history-overlay-close" title="关闭历史会话">' + xIcon + '</button>';
      header.querySelector('.agent-history-overlay-back').addEventListener('click', function () {
        renderOverlayList();
      });
      header.querySelector('.agent-history-overlay-close').addEventListener('click', closeHistoryOverlay);
      header._overlayHeaderMode = 'detail';
    }
  }

  function loadHistorySessions() {
    if (historyState.query) {
      // Search mode: offset-based pagination across all sessions
      doSearchSessions();
    } else {
      // Date-axis mode: load available dates, then sessions for selected date
      doLoadAvailableDates();
    }
  }

  function doLoadAvailableDates() {
    var params = new URLSearchParams();
    if (currentRootId) params.set('root', currentRootId);
    if (currentDir) params.set('dir', currentDir);

    var fetcher = (typeof authFetch === 'function') ? authFetch : fetch;
    fetcher('/api/clawmate/agent/sessions/dates?' + params.toString())
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var dates = data.dates || [];
        historyState.availableDates = dates;
        historyState.page = 0;  // reset page when entering date-axis mode
        // Keep selectedDateIndex valid
        if (historyState.selectedDateIndex >= dates.length) {
          historyState.selectedDateIndex = dates.length > 0 ? 0 : -1;
        }
        historyState.axisScrollIndex = 0;
        // If we have a selected date, load its sessions
        if (dates.length > 0 && historyState.selectedDateIndex >= 0) {
          doLoadSessionsForDate(dates[historyState.selectedDateIndex]);
        } else {
          historyState.sessions = [];
          historyState.total = 0;
          renderOverlayList();
        }
      })
      .catch(function(err) {
        console.error('Failed to load session dates:', err);
        historyState.availableDates = [];
        historyState.sessions = [];
        renderOverlayList();
      });
  }

  function doLoadSessionsForDate(dateStr) {
    if (!dateStr) {
      historyState.sessions = [];
      historyState.total = 0;
      renderOverlayList();
      return;
    }
    var params = new URLSearchParams();
    params.set('date', dateStr);
    params.set('offset', String(historyState.page * historyState.pageSize));
    params.set('limit', String(historyState.pageSize));
    if (currentRootId) params.set('root', currentRootId);
    if (currentDir) params.set('dir', currentDir);

    var fetcher = (typeof authFetch === 'function') ? authFetch : fetch;
    fetcher('/api/clawmate/agent/sessions?' + params.toString())
      .then(function(r) { return r.json(); })
      .then(function(data) {
        historyState.sessions = data.sessions || [];
        historyState.total = data.total || 0;
        renderOverlayList();
      })
      .catch(function(err) {
        console.error('Failed to load sessions:', err);
        historyState.sessions = [];
        renderOverlayList();
      });
  }

  function doSearchSessions() {
    var params = new URLSearchParams();
    params.set('limit', String(historyState.pageSize));
    params.set('offset', String(historyState.page * historyState.pageSize));
    params.set('q', historyState.query);
    if (currentRootId) params.set('root', currentRootId);
    if (currentDir) params.set('dir', currentDir);

    var fetcher = (typeof authFetch === 'function') ? authFetch : fetch;
    fetcher('/api/clawmate/agent/sessions?' + params.toString())
      .then(function(r) { return r.json(); })
      .then(function(data) {
        historyState.sessions = data.sessions || [];
        historyState.total = data.total || 0;
        renderOverlayList();
      })
      .catch(function(err) {
        console.error('Failed to search sessions:', err);
        historyState.sessions = [];
        renderOverlayList();
      });
  }

  function pad2(n) { return n < 10 ? '0' + n : '' + n; }

  function escHtml(s) {
    var d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

  function formatDate(ts) {
    var d = new Date((ts || 0) * 1000);
    return (d.getMonth() + 1) + '/' + d.getDate();
  }

  function formatSessionTime(ts) {
    if (!ts) return '';
    var d = new Date(ts * 1000);
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) +
      ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
  }

  function sanitizeDownloadName(name) {
    return String(name || 'agent-session')
      .replace(/[\\/:*?"<>|]+/g, '-')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 100) || 'agent-session';
  }

  function markdownEscapeHeading(text) {
    return String(text || '').replace(/\r/g, '').replace(/\n+/g, ' ').trim();
  }

  function sessionToMarkdown(detail, logData) {
    var meta = (detail && detail.meta) || {};
    var title = markdownEscapeHeading(meta.title || (detail && detail.session_id) || 'Agent Session');
    var lines = ['# ' + title, ''];

    if (meta.backend || detail.root || detail.project || meta.started_at || meta.ended_at) {
      lines.push('## Metadata');
      if (meta.backend) lines.push('- Backend: ' + meta.backend);
      if (detail.root || detail.project) lines.push('- Project: ' + [detail.root, detail.project].filter(Boolean).join('/'));
      if (meta.started_at) lines.push('- Started: ' + formatSessionTime(meta.started_at));
      if (meta.ended_at) lines.push('- Ended: ' + formatSessionTime(meta.ended_at));
      lines.push('');
    }

    var turns = (logData && logData.turns) || [];
    if (!turns.length) {
      lines.push('暂无对话记录');
      lines.push('');
      return lines.join('\n');
    }

    for (var i = 0; i < turns.length; i++) {
      var turn = turns[i] || {};
      var role = turn.role === 'user' ? '问题' : '回复';
      var when = '';
      if (turn.ts) {
        var d = new Date(turn.ts * 1000);
        when = ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
      }
      lines.push('## ' + role + when);
      lines.push('');
      lines.push(cleanTerminalInput(turn.content || '').trim() || '(empty)');
      lines.push('');
    }

    return lines.join('\n');
  }

  function downloadTextFile(filename, content, mimeType) {
    var blob = new Blob([content], { type: mimeType || 'text/plain;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function() { URL.revokeObjectURL(url); }, 1000);
  }

  function fetchSessionDetailAndLog(sessionId, root, project) {
    var params = new URLSearchParams();
    if (root) params.set('root', root);
    if (project) params.set('project', project);

    var detailUrl = '/api/clawmate/agent/sessions/' + encodeURIComponent(sessionId) + '?' + params.toString();
    var logUrl = '/api/clawmate/agent/sessions/' + encodeURIComponent(sessionId) + '/log?' + params.toString();
    var fetcher = (typeof authFetch === 'function') ? authFetch : fetch;
    return Promise.all([
      fetcher(detailUrl).then(function(r) {
        if (!r.ok) throw new Error('加载会话详情失败');
        return r.json();
      }),
      fetcher(logUrl).then(function(r) {
        if (!r.ok) throw new Error('加载会话日志失败');
        return r.json();
      }),
    ]);
  }

  function exportSessionMarkdown(sessionId, root, project) {
    return fetchSessionDetailAndLog(sessionId, root, project).then(function(results) {
      var detail = results[0];
      var logData = results[1];
      var title = (detail.meta && detail.meta.title) || detail.session_id || sessionId;
      downloadTextFile(
        sanitizeDownloadName(title) + '.md',
        sessionToMarkdown(detail, logData),
        'text/markdown;charset=utf-8'
      );
    }).catch(function(err) {
      console.error('export failed:', err);
      alert('导出失败：' + err.message);
    });
  }

  function deleteHistorySession(sessionId, root, project) {
    if (!confirm('确定删除此会话？')) return;
    var params = new URLSearchParams();
    if (root) params.set('root', root);
    if (project) params.set('project', project);
    var url = '/api/clawmate/agent/sessions/' + encodeURIComponent(sessionId) + '?' + params.toString();
    var fetcher = (typeof authFetch === 'function') ? authFetch : fetch;
    fetcher(url, { method: 'DELETE' }).then(function(r) {
      if (!r.ok) {
        return r.json().catch(function() { return {}; }).then(function(data) {
          throw new Error(data.detail || '删除失败');
        });
      }
      loadHistorySessions();
    }).catch(function(err) {
      console.error('delete failed:', err);
      alert('删除失败：' + err.message);
    });
  }

  function renderOverlayList() {
    var overlay = ensureHistoryOverlay();
    var body = overlay.querySelector('.agent-history-overlay-body');
    body.innerHTML = '';

    setOverlayHeaderMode('list');

    if (historyState.query) {
      // ── Search mode ──
      renderSearchResults(body);
    } else if (!historyState.availableDates.length) {
      // ── No dates at all ──
      body.innerHTML = '<div class="agent-history-empty">无会话记录</div>';
    } else {
      // ── Date-axis mode ──
      renderDateAxisBar(body);
      renderDateSessionList(body);
      if (historyState.total > historyState.pageSize) {
        renderDatePagination(body);
      }
    }
  }

  // ── Date-axis mode helpers ──

  function getDateLabel(dateStr) {
    if (!dateStr) return '';
    var now = new Date();
    var todayStr = now.getFullYear() + '-' + pad2(now.getMonth() + 1) + '-' + pad2(now.getDate());
    if (dateStr === todayStr) return '今天';
    var yesterdayTs = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000 - 86400;
    var yesterdayDate = new Date(yesterdayTs * 1000);
    var yesterdayStr = yesterdayDate.getFullYear() + '-' + pad2(yesterdayDate.getMonth() + 1) + '-' + pad2(yesterdayDate.getDate());
    if (dateStr === yesterdayStr) return '昨天';
    var parts = dateStr.split('-');
    return parseInt(parts[1], 10) + '/' + parseInt(parts[2], 10);
  }

  function renderDateAxisBar(body) {
    var axisWrap = document.createElement('div');
    axisWrap.className = 'agent-history-date-axis';

    // Compute how many date buttons fit in the axis bar
    var panelWidth = panel ? panel.clientWidth : 750;
    var axisAvailWidth = panelWidth - 60; // overlay padding + axis padding + margin
    var approxBtnWidth = 52; // ~42-52px per button (label + padding + gap)
    var maxVisible = Math.max(3, Math.floor(axisAvailWidth / approxBtnWidth));

    // Clamp axisScrollIndex so we don't go past the end
    var total = historyState.availableDates.length;
    if (historyState.axisScrollIndex + maxVisible > total) {
      historyState.axisScrollIndex = Math.max(0, total - maxVisible);
    }

    // Prev arrow
    var prevBtn = document.createElement('button');
    prevBtn.className = 'agent-history-date-arrow';
    prevBtn.innerHTML = '&lsaquo;';
    prevBtn.title = '更早日期';
    prevBtn.disabled = historyState.axisScrollIndex <= 0;
    prevBtn.addEventListener('click', function () {
      if (historyState.axisScrollIndex > 0) {
        historyState.axisScrollIndex = Math.max(0, historyState.axisScrollIndex - maxVisible);
        renderOverlayList();
      }
    });
    axisWrap.appendChild(prevBtn);

    // Date buttons
    var btnContainer = document.createElement('div');
    btnContainer.className = 'agent-history-date-btns';

    var visibleDates = historyState.availableDates.slice(
      historyState.axisScrollIndex,
      historyState.axisScrollIndex + maxVisible
    );

    visibleDates.forEach(function(dateStr, idx) {
      var actualIdx = historyState.axisScrollIndex + idx;
      var btn = document.createElement('button');
      btn.className = 'agent-history-date-btn';
      if (actualIdx === historyState.selectedDateIndex) btn.classList.add('active');

      btn.textContent = getDateLabel(dateStr);
      btn.addEventListener('click', function () {
        if (actualIdx !== historyState.selectedDateIndex) {
          historyState.selectedDateIndex = actualIdx;
          historyState.page = 0;
          doLoadSessionsForDate(historyState.availableDates[actualIdx]);
        }
      });
      btnContainer.appendChild(btn);
    });

    axisWrap.appendChild(btnContainer);

    // Next arrow
    var nextBtn = document.createElement('button');
    nextBtn.className = 'agent-history-date-arrow';
    nextBtn.innerHTML = '&rsaquo;';
    nextBtn.title = '更晚日期';
    nextBtn.disabled = historyState.axisScrollIndex + maxVisible >= total;
    nextBtn.addEventListener('click', function () {
      if (historyState.axisScrollIndex + maxVisible < total) {
        historyState.axisScrollIndex = Math.min(historyState.axisScrollIndex + maxVisible, total - maxVisible);
        renderOverlayList();
      }
    });
    axisWrap.appendChild(nextBtn);

    body.appendChild(axisWrap);
  }

  function renderDateSessionList(body) {
    var listEl = document.createElement('div');
    listEl.className = 'agent-history-list';
    body.appendChild(listEl);

    if (!historyState.sessions.length) {
      listEl.innerHTML = '<div class="agent-history-empty">该日期无会话记录</div>';
      return;
    }

    // Date-axis mode: no group title needed — pagination handles navigation
    historyState.sessions.forEach(function(s) {
      listEl.appendChild(createSessionItem(s));
    });
  }

  function renderDatePagination(body) {
    var totalPages = Math.ceil(historyState.total / historyState.pageSize);
    var pag = document.createElement('div');
    pag.className = 'agent-history-pagination';
    pag.innerHTML =
      '<button class="agent-hist-prev"' + (historyState.page <= 0 ? ' disabled' : '') + '>&larr; 上一页</button>' +
      '<span class="agent-history-page-info">第' + (historyState.page + 1) + '/' + totalPages + '页</span>' +
      '<button class="agent-hist-next"' + ((historyState.page + 1) * historyState.pageSize >= historyState.total ? ' disabled' : '') + '>下一页 &rarr;</button>';

    body.appendChild(pag);

    var prevBtn = pag.querySelector('.agent-hist-prev');
    var nextBtn = pag.querySelector('.agent-hist-next');
    if (prevBtn) prevBtn.addEventListener('click', function () {
      if (historyState.page > 0) {
        historyState.page--;
        var selectedDate = historyState.availableDates[historyState.selectedDateIndex];
        if (selectedDate) doLoadSessionsForDate(selectedDate);
      }
    });
    if (nextBtn) nextBtn.addEventListener('click', function () {
      if ((historyState.page + 1) * historyState.pageSize < historyState.total) {
        historyState.page++;
        var selectedDate = historyState.availableDates[historyState.selectedDateIndex];
        if (selectedDate) doLoadSessionsForDate(selectedDate);
      }
    });
  }

  // ── Search mode helpers ──

  function renderSearchResults(body) {
    var listEl = document.createElement('div');
    listEl.className = 'agent-history-list';
    body.appendChild(listEl);

    if (!historyState.sessions.length) {
      listEl.innerHTML = '<div class="agent-history-empty">无匹配的搜索结果</div>';
      return;
    }

    // Group by date
    var groups = {};
    var now = new Date();
    var todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
    var yesterdayStart = todayStart - 86400;

    historyState.sessions.forEach(function(s) {
      var t = s.started_at || 0;
      var label;
      if (t >= todayStart) label = '今天';
      else if (t >= yesterdayStart) label = '昨天';
      else label = formatDate(t);
      if (!groups[label]) groups[label] = [];
      groups[label].push(s);
    });

    var groupKeys = Object.keys(groups);
    groupKeys.sort(function(a, b) {
      var order = ['今天', '昨天'];
      var ai = order.indexOf(a);
      var bi = order.indexOf(b);
      if (ai !== -1 && bi !== -1) return ai - bi;
      if (ai !== -1) return -1;
      if (bi !== -1) return 1;
      return a < b ? 1 : -1;
    });

    groupKeys.forEach(function(label) {
      var groupEl = document.createElement('div');
      groupEl.className = 'agent-history-group';
      groupEl.innerHTML = '<div class="agent-history-group-title">' + escHtml(label) + '</div>';

      groups[label].forEach(function(s) {
        groupEl.appendChild(createSessionItem(s));
      });

      listEl.appendChild(groupEl);
    });

    // Search pagination
    var totalPages = Math.ceil(historyState.total / historyState.pageSize);
    var pag = document.createElement('div');
    pag.className = 'agent-history-pagination';
    pag.innerHTML =
      '<button class="agent-hist-prev"' + (historyState.page <= 0 ? ' disabled' : '') + '>&larr; 上一页</button>' +
      '<span class="agent-history-page-info">第' + (historyState.page + 1) + '/' + totalPages + '页</span>' +
      '<button class="agent-hist-next"' + ((historyState.page + 1) * historyState.pageSize >= historyState.total ? ' disabled' : '') + '>下一页 &rarr;</button>';
    body.appendChild(pag);

    bindPaginationHandlers(pag);
  }

  function bindPaginationHandlers(pag) {
    var prevBtn = pag.querySelector('.agent-hist-prev');
    var nextBtn = pag.querySelector('.agent-hist-next');
    if (prevBtn) prevBtn.addEventListener('click', function () {
      if (historyState.page > 0) {
        historyState.page--;
        loadHistorySessions();
      }
    });
    if (nextBtn) nextBtn.addEventListener('click', function () {
      var pageSize = historyState.pageSize;
      if ((historyState.page + 1) * pageSize < historyState.total) {
        historyState.page++;
        loadHistorySessions();
      }
    });
  }

  function createSessionItem(s) {
    var item = document.createElement('div');
    item.className = 'agent-history-item';
    item.dataset.sid = s.id;

    var startDate = new Date((s.started_at || 0) * 1000);
    var timeStr = pad2(startDate.getHours()) + ':' + pad2(startDate.getMinutes());
    var durStr = '';
    if (s.first_ts && s.last_ts) {
      var durMin = Math.round((s.last_ts - s.first_ts) / 60);
      if (durMin >= 1) durStr = durMin + '分钟';
      else durStr = '<1分钟';
    }

    var title = s.title || s.id || 'Unknown';
    var turnCount = Number(s.turn_count || 0);
    var instrCount = Number(s.instruction_count || 0);
    var sessionKey = s.sessionKey || s.key || ((s.backend || '?') + ':' + (s.root || '') + (s.project ? ':' + s.project : ''));
    var turnLabel = instrCount > 0 ? '<span class="agent-history-turn-count" title="用户指令数">' + instrCount + '条指令</span>' : '';

    var downloadIcon = (typeof iconSVG === 'function') ? iconSVG('download', 14) : '导出';
    var deleteIcon = (typeof iconSVG === 'function') ? iconSVG('trash-2', 14) : '删除';
    item.innerHTML =
      '<div class="agent-history-item-main">' +
        '<div class="agent-history-item-title">' + escHtml(title) + '</div>' +
        '<div class="agent-history-item-meta">' +
          '<span>' + timeStr + '</span>' +
          '<span>' + escHtml(sessionKey) + '</span>' +
          '<span>' + turnCount + '轮对话</span>' +
          turnLabel +
          (durStr ? '<span>时长' + durStr + '</span>' : '') +
        '</div>' +
      '</div>' +
      '<div class="agent-history-item-actions">' +
        '<button type="button" class="agent-history-action agent-history-export" title="导出会话" aria-label="导出会话">' + downloadIcon + '</button>' +
        '<button type="button" class="agent-history-action agent-history-delete" title="删除会话" aria-label="删除会话">' + deleteIcon + '</button>' +
      '</div>';

    item.addEventListener('click', function() {
      openSessionView(s.id, s.root, s.project);
    });

    item.querySelector('.agent-history-export').addEventListener('click', function(evt) {
      evt.stopPropagation();
      exportSessionMarkdown(s.id, s.root, s.project);
    });

    item.querySelector('.agent-history-delete').addEventListener('click', function(evt) {
      evt.stopPropagation();
      deleteHistorySession(s.id, s.root, s.project);
    });

    return item;
  }

  function openSessionView(sessionId, root, project) {
    historyState.currentSessionId = sessionId;

    var overlay = ensureHistoryOverlay();
    var body = overlay.querySelector('.agent-history-overlay-body');
    body.innerHTML = '<div class="agent-session-viewer" style="height:100%">加载中...</div>';

    fetchSessionDetailAndLog(sessionId, root, project).then(function(results) {
      renderOverlayDetail(results[0], results[1]);
    }).catch(function(err) {
      body.innerHTML = '<div class="agent-session-viewer" style="height:100%">加载失败: ' + err.message + '</div>';
    });
  }

  function renderOverlayDetail(detail, logData) {
    var overlay = ensureHistoryOverlay();
    var body = overlay.querySelector('.agent-history-overlay-body');

    var title = detail.meta ? detail.meta.title || detail.session_id : detail.session_id;
    setOverlayHeaderMode('detail', title);

    var viewer = document.createElement('div');
    viewer.className = 'agent-session-viewer';

    // Content area - chat bubbles
    var content = document.createElement('div');
    content.className = 'agent-chat-content';

    var rawTurns = logData.turns || [];
    // Merge consecutive user turns ≤1s apart — terminal multi-line paste
    var turns = [];
    for (var i = 0; i < rawTurns.length; i++) {
      var t = rawTurns[i];
      var prev = turns.length > 0 ? turns[turns.length - 1] : null;
      if (prev && prev.role === 'user' && t.role === 'user' &&
          t.ts && prev.ts && Math.abs(t.ts - prev.ts) <= 1.0) {
        prev.content = (prev.content || '') + '\n' + (t.content || '');
      } else {
        turns.push(t);
      }
    }
    if (!turns.length) {
      content.innerHTML = '<div class="agent-chat-empty">暂无对话记录</div>';
    } else {
      var currentTurnIndex = 0;
      for (var i = 0; i < turns.length; i++) {
        var turn = turns[i];
        if (turn.role === 'user') currentTurnIndex += 1;
        var turnIndex = Number(turn.turn_index || currentTurnIndex || 0);
        var bubble = document.createElement('div');
        bubble.className = 'agent-chat-bubble agent-chat-bubble-' + (turn.role === 'user' ? 'user' : 'assistant');

        var meta = document.createElement('div');
        meta.className = 'agent-chat-meta';
        meta.textContent = (turnIndex ? '第 ' + turnIndex + ' 轮 · ' : '') + (turn.role === 'user' ? '你' : 'Agent');
        if (turn.ts) {
          var d = new Date(turn.ts * 1000);
          var timeStr = d.getHours().toString().padStart(2,'0') + ':' + d.getMinutes().toString().padStart(2,'0');
          meta.textContent += ' · ' + timeStr;
        }
        bubble.appendChild(meta);

        var bodyEl = document.createElement('div');
        bodyEl.className = 'agent-chat-body';
        if (turn.content) {
          renderMarkdown(bodyEl, cleanTerminalInput(turn.content));
        }
        bubble.appendChild(bodyEl);

        content.appendChild(bubble);
      }
    }

    viewer.appendChild(content);
    body.innerHTML = '';
    body.appendChild(viewer);
  }
  // --- Public API ---
  window.Agent = {
    XTERM_CDN_BASE: XTERM_CDN_BASE,

    init: function (config) {
      if (config.domPrefix) { _resolveDom(config.domPrefix); }
      wsUrl = config.wsUrl || '';
      currentRootId = config.rootId || '';
      currentDir = config.dir || '';
      currentAgentId = config.agentId || '';

      // Restore per-project saved backend, falling back to config default
      var savedBackend = '';
      if (currentRootId) {
        try { savedBackend = localStorage.getItem('clawmate_backend_' + currentRootId) || ''; } catch (_) {}
      }
      backendMode = (savedBackend && ['claude','codex','openclaw'].indexOf(savedBackend) !== -1)
        ? savedBackend
        : (config.backend || 'claude');

      // Sync select to initial backend
      if (backendSelect) backendSelect.value = backendMode;

      if (backendMode === 'openclaw') {
        showChatMode();
      } else {
        showXtermMode();
      }
    },

    open: function (rootId, dir, fileContext) {
      if (rootId) currentRootId = rootId;
      if (dir !== undefined) currentDir = dir;
      if (fileContext) {
        _lastFileContext = fileContext;
        _pendingFileContext = fileContext;
      } else if (_lastFileContext) {
        _pendingFileContext = _lastFileContext;
      }

      animatingOut = false;
      clearTimeout(collapseTimer);
      panel.style.display = 'flex';
      panel.offsetHeight; // force reflow
      panel.classList.remove('hidden');
      updateGridColumns(); // grid expands — hidden is now false
      panel.style.display = '';
      document.body.classList.add('agent-open');
      setTimeout(function () { if (typeof syncSidebarBtn === 'function') syncSidebarBtn(); }, 0);

      if (backendMode === 'openclaw') {
        showChatMode();
        chatMessages.innerHTML = '';
        chatBuf = ''; chatBufEl = null;
      } else {
        showXtermMode();
        createTerminal();
        if (term) { term.focus(); }
      }

      reconnectAttempts = 0;
      connectWs();

      if (termResizeObserver && xtermContainer) {
        try { termResizeObserver.unobserve(xtermContainer); } catch (_) {}
        try { termResizeObserver.observe(xtermContainer); xlog('init', 'ResizeObserver reconnected'); } catch (_) {}
      }

      if (fitAddon) {
        var transitionFitted = false;
        var onPanelTransitionEnd = function (e) {
          if (e.propertyName === 'transform' || e.propertyName === 'all') {
            panel.removeEventListener('transitionend', onPanelTransitionEnd);
            if (!transitionFitted) {
              transitionFitted = true;
              try { fitAddon.fit(); } catch (_) {}
              if (term) { try { term.refresh(0, term.rows - 1); } catch (_) {} }
            }
          }
        };
        panel.addEventListener('transitionend', onPanelTransitionEnd);
        setTimeout(function () {
          panel.removeEventListener('transitionend', onPanelTransitionEnd);
          if (!transitionFitted) {
            transitionFitted = true;
            try { fitAddon.fit(); } catch (_) {}
            if (term) { try { term.refresh(0, term.rows - 1); } catch (_) {} }
          }
        }, 500);
      }
    },

    close: function () {
      if (panel.classList.contains('hidden') && !animatingOut) return;
      // Close overlay if open
      if (historyOverlayOpen) {
        historyOverlayOpen = false;
        if (historyOverlay) historyOverlay.classList.add('hidden');
      }
      disconnectWs();
      animatingOut = true;
      if (termResizeObserver) {
        try { termResizeObserver.disconnect(); } catch (_) {}
      }
      panel.style.display = 'flex';
      panel.classList.add('hidden');
      document.body.classList.remove('agent-open');
      setTimeout(function () { if (typeof syncSidebarBtn === 'function') syncSidebarBtn(); }, 0);
      updateGridColumns();
      clearTimeout(collapseTimer);
      collapseTimer = setTimeout(function () {
        animatingOut = false;
        panel.style.display = '';
        updateGridColumns();
      }, 300);
      if (toggleBtn) toggleBtn.classList.remove('active');
    },

    toggle: function () {
      if (panel.classList.contains('hidden')) {
        window.Agent.open(currentRootId, currentDir, _lastFileContext);
        if (toggleBtn) toggleBtn.classList.add('active');
      } else {
        window.Agent.close();
      }
    },

    updateRoot: function (rootId, dir) {
      var previousRootId = currentRootId;
      var previousDir = currentDir;
      if (rootId) currentRootId = rootId;
      if (dir !== undefined) currentDir = dir;
      if (!panel.classList.contains('hidden') && ws && ws.readyState === WebSocket.OPEN) {
        try { ws.send(JSON.stringify({ type: 'chdir', root: currentRootId, dir: currentDir })); } catch (_) {}
      }
      if (historyOverlayOpen && (previousRootId !== currentRootId || previousDir !== currentDir)) {
        historyState.page = 0;
        historyState.selectedDateIndex = 0;
        historyState.axisScrollIndex = 0;
        historyState.availableDates = [];
        historyState.query = '';
        var searchInput = ensureHistoryOverlay().querySelector('.agent-header-search');
        if (searchInput) searchInput.value = '';
        loadHistorySessions();
      }
    },

    isOpen: function () {
      return panel && !panel.classList.contains('hidden');
    },

    focus: function () {
      if (term) {
        term.focus();
      } else if (chatInput && !chatView.classList.contains('hidden')) {
        chatInput.focus();
      }
    },

    sendText: function (text) {
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        if (typeof showToast === 'function') showToast('Agent 未连接', 2000);
        return;
      }
      if (isPtyBackend()) {
        // PTY mode: send raw text through WebSocket to the shell
        ws.send(text);
        if (term) term.focus();
      } else {
        // Chat mode: append to chat input textarea
        chatInput.value += text;
        chatInput.focus();
        chatInput.selectionStart = chatInput.selectionEnd = chatInput.value.length;
      }
    },

    insertText: function (text) {
      if (!text) return;
      var insertedPath = extractKnownFilePath(text);
      if (insertedPath) rememberKnownFile(insertedPath);
      if (isPtyBackend()) {
        var rawText = String(text);
        if (term && typeof term.input === 'function') {
          restoreTerminalImeTarget();
          term.input(rawText, true);
          return;
        }
        if (term && term.textarea) {
          var ta = term.textarea;
          var start = typeof ta.selectionStart === 'number' ? ta.selectionStart : ta.value.length;
          var end = typeof ta.selectionEnd === 'number' ? ta.selectionEnd : ta.value.length;
          ta.setRangeText(rawText, start, end, 'end');
          ta.focus();
          try {
            if (typeof InputEvent !== 'undefined') {
              ta.dispatchEvent(new InputEvent('input', {
                bubbles: true,
                cancelable: true,
                inputType: 'insertText',
                data: rawText,
              }));
            } else {
              ta.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
            }
          } catch (_) {}
          restoreTerminalImeTarget();
        }
        if (term) term.focus();
        return;
      }
      if (chatInput) {
        chatInput.value += text;
        chatInput.focus();
        chatInput.selectionStart = chatInput.selectionEnd = chatInput.value.length;
      }
    },

    updateGrid: function () { updateGridColumns(); },

    syncTheme: function () {
      if (!term) return;
      var isDark = document.documentElement.getAttribute('data-theme') !== 'light';
      var bg, fg, selBg, selFg, selInactiveBg;
      if (isDark) {
        bg = '#111827'; fg = '#e2e8f0';
        selBg = '#1e3a5f'; selFg = '#f0f9ff'; selInactiveBg = '#1a2332';
      } else {
        bg = '#ffffff'; fg = '#1e293b';
        selBg = '#bfdbfe'; selFg = '#1e293b'; selInactiveBg = '#e2e8f0';
      }
      term.options.theme = {
        background: bg, foreground: fg, cursor: '#14b8a6',
        selectionBackground: selBg, selectionForeground: selFg,
        selectionInactiveBackground: selInactiveBg,
      };
      try { term.refresh(0, term.rows - 1); } catch (_) {}
      if (xtermContainer) {
        xtermContainer.style.setProperty('--xterm-bg', bg);
      }
    },
  };

})();
