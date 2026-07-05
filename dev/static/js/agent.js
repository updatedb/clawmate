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
  let _pendingFileContext = null;  // {path, content} — sent on next ws.onopen

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
    page: 0,
    total: 0,
    query: '',
    currentSessionId: null,
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
        xlog('focus', 'textarea blur relatedTarget=' + rtTag + ' panel.hidden=' + panel.classList.contains('hidden'));
        if (panel.classList.contains('hidden')) return;
        if (e.relatedTarget === null) {
          xlog('focus', 'refocus (IME window stole focus)');
          setTimeout(function () { term.focus(); }, 0);
        }
      });
      textarea.addEventListener('focus', function () { xlog('focus', 'textarea gained focus'); });
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
      if (ws && ws.readyState === WebSocket.OPEN) { ws.send(data); }
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
        term.writeln('\x1b[2m  ' + term.cols + '×' + term.rows + '  |  调整面板宽度后运行的程序会自动适配新宽度\x1b[0m');
        term.writeln('');
        if (_pendingFileContext) {
          try {
            ws.send(JSON.stringify({ type: 'file_context', path: _pendingFileContext.path || '', content: _pendingFileContext.content || '' }));
          } catch (_) {}
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
    currentSessionKey = '';
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
        '<input type="text" class="agent-header-search" placeholder="搜索会话...">' +
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

    return historyOverlay;
  }

  function openHistoryOverlay() {
    if (historyOverlayOpen) return;
    var overlay = ensureHistoryOverlay();
    historyState.page = 0;
    historyState.query = '';
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
    if (mode === 'list') {
      header.innerHTML =
        clockIcon +
        '<span class="agent-history-overlay-title">历史会话</span>' +
        '<input type="text" class="agent-header-search" placeholder="搜索会话..." value="' + escHtml(historyState.query || '') + '">' +
        '<button class="agent-history-overlay-close" title="关闭历史会话">' + xIcon + '</button>';
      var searchInput = header.querySelector('.agent-header-search');
      searchInput.addEventListener('input', function () {
        historyState.query = this.value;
        historyState.page = 0;
        loadHistorySessions();
      });
      header.querySelector('.agent-history-overlay-close').addEventListener('click', closeHistoryOverlay);
    } else if (mode === 'detail') {
      header.innerHTML =
        '<button class="agent-history-overlay-back" title="返回列表">' + backIcon + '</button>' +
        '<span class="agent-history-overlay-title">' + escHtml(title || '') + '</span>' +
        '<button class="agent-history-overlay-close" title="关闭历史会话">' + xIcon + '</button>';
      header.querySelector('.agent-history-overlay-back').addEventListener('click', function () {
        renderOverlayList();
      });
      header.querySelector('.agent-history-overlay-close').addEventListener('click', closeHistoryOverlay);
    }
  }

  function loadHistorySessions() {
    var params = new URLSearchParams();
    params.set('limit', '50');
    params.set('offset', String(historyState.page * 50));
    if (historyState.query) params.set('q', historyState.query);

    if (currentRootId) params.set('root', currentRootId);
    if (currentDir) params.set('dir', currentDir);

    var url = '/api/clawmate/agent/sessions?' + params.toString();
    (typeof authFetch === 'function' ? authFetch(url) : fetch(url))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        historyState.total = data.total || 0;
        historyState.sessions = data.sessions || [];
        renderOverlayList();
      })
      .catch(function(err) {
        console.error('Failed to load sessions:', err);
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

    if (!historyState.sessions.length) {
      body.innerHTML = '<div class="agent-history-empty">暂无历史会话</div>';
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

    // Create scrollable list wrapper
    var listEl = document.createElement('div');
    listEl.className = 'agent-history-list';
    body.appendChild(listEl);

    // Render groups
    var groupKeys = Object.keys(groups);
    groupKeys.sort(function(a, b) {
      var order = ['今天', '昨天'];
      var ai = order.indexOf(a);
      var bi = order.indexOf(b);
      if (ai !== -1 && bi !== -1) return ai - bi;
      if (ai !== -1) return -1;
      if (bi !== -1) return 1;
      return a < b ? 1 : -1; // reverse date strings (newer first)
    });

    groupKeys.forEach(function(label) {
      var groupEl = document.createElement('div');
      groupEl.className = 'agent-history-group';
      groupEl.innerHTML = '<div class="agent-history-group-title">' + escHtml(label) + '</div>';

      groups[label].forEach(function(s) {
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

        groupEl.appendChild(item);
      });

      listEl.appendChild(groupEl);
    });

    // Pagination
    if (historyState.total > 50) {
      var pag = document.createElement('div');
      pag.className = 'agent-history-pagination';
      var totalPages = Math.ceil(historyState.total / 50);
      pag.innerHTML =
        '<button class="agent-hist-prev"' + (historyState.page === 0 ? ' disabled' : '') + '>&larr;</button>' +
        '<span>' + (historyState.page + 1) + '/' + totalPages + '</span>' +
        '<button class="agent-hist-next"' + ((historyState.page + 1) * 50 >= historyState.total ? ' disabled' : '') + '>&rarr;</button>';
      body.appendChild(pag);

      var prevBtn = pag.querySelector('.agent-hist-prev');
      var nextBtn = pag.querySelector('.agent-hist-next');
      if (prevBtn) prevBtn.addEventListener('click', function() {
        if (historyState.page > 0) { historyState.page--; loadHistorySessions(); }
      });
      if (nextBtn) nextBtn.addEventListener('click', function() {
        if ((historyState.page + 1) * 50 < historyState.total) { historyState.page++; loadHistorySessions(); }
      });
    }
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
      if (fileContext) _pendingFileContext = fileContext;

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
        window.Agent.open(currentRootId, currentDir);
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
        loadHistorySessions();
      }
    },

    isOpen: function () {
      return !panel.classList.contains('hidden');
    },

    focus: function () {
      if (term) {
        term.focus();
      } else if (chatInput && !chatView.classList.contains('hidden')) {
        chatInput.focus();
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
