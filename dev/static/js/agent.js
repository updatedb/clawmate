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
  let panel, resizeHandle, xtermContainer, chatView, chatMessages, chatInput, chatSendBtn, backendSelect, closeBtn, toggleBtn, clearBtn;
  let panelTitleEl;
  // Resize tracking shared between createTerminal & disconnectWs
  var _lastResizeSent = { cols: 0, rows: 0 };
  var _pendingResize = null;

  function _resolveDom(prefix) {
    _domPrefix = prefix || '';
    var p = _domPrefix;
    // Try prefixed IDs first, fall back to unprefixed (for main page where prefix is '')
    panel         = document.getElementById(p + 'AgentPanel') || document.getElementById(p + 'agentPanel') || document.getElementById('agentPanel');
    resizeHandle  = document.getElementById(p + 'agentResizeHandle') || document.getElementById('agentResizeHandle');
    xtermContainer = document.getElementById(p + 'XtermContainer') || document.getElementById(p + 'xtermContainer') || document.getElementById('xtermContainer');
    chatView      = document.getElementById(p + 'AgentChatView') || document.getElementById(p + 'agentChatView') || document.getElementById('agentChatView');
    chatMessages  = document.getElementById(p + 'AgentChatMessages') || document.getElementById(p + 'agentChatMessages') || document.getElementById('agentChatMessages');
    chatInput     = document.getElementById(p + 'AgentChatInput') || document.getElementById(p + 'agentChatInput') || document.getElementById('agentChatInput');
    chatSendBtn   = document.getElementById(p + 'AgentChatSend') || document.getElementById(p + 'agentChatSend') || document.getElementById('agentChatSend');
    backendSelect = document.getElementById(p + 'AgentBackendSelect') || document.getElementById(p + 'agentBackendSelect') || document.getElementById('agentBackendSelect');
    closeBtn      = document.getElementById(p + 'BtnCloseAgent') || document.getElementById(p + 'btnCloseAgent') || document.getElementById('btnCloseAgent');
    toggleBtn     = document.getElementById(p + 'BtnToggleAgent') || document.getElementById(p + 'btnToggleAgent') || document.getElementById('btnToggleAgent');
    panelTitleEl  = document.getElementById(p + 'AgentPanelTitle') || document.getElementById(p + 'agentPanelTitle') || document.getElementById(p + 'AgentTitle') || document.getElementById(p + 'agentTitle') || document.getElementById('agentPanelTitle');
    clearBtn      = document.getElementById(p + 'BtnClearAgent') || document.getElementById(p + 'btnClearAgent') || document.getElementById('btnClearAgent');
    // Re-bind backend select handler (may change after prefix update, e.g. on preview page)
    if (backendSelect) {
      backendSelect.onchange = function () {
        var bm = backendSelect.value;
        if (bm) switchBackend(bm);
      };
    }
  }
  _resolveDom('');  // default: main page IDs

  // --- Debug logging ---
  const XLOG = 'font-weight:bold;color:#14b8a6';
  function xlog(tag, msg, data) {
    var args = ['%c[xterm:' + tag + '] %c' + msg, XLOG, 'color:inherit'];
    if (data !== undefined) args.push(data);
    console.log.apply(console, args);
  }
  function rectJson(el) {
    if (!el) return null;
    var r = el.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height), t: Math.round(r.top), l: Math.round(r.left) };
  }

  // --- State ---
  let term = null;
  let fitAddon = null;
  let termResizeObserver = null;
  let ws = null;
  let wsUrl = '';
  let panelWidth = 0;
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

  // --- Grid update ---
  function updateGridColumns(forceExpand) {
    const content = document.querySelector('.content');
    if (!content) return;
    if (window.innerWidth < 768) {
      content.style.gridTemplateColumns = '';
      if (resizeHandle) resizeHandle.classList.add('hidden');
      return;
    }
    const sidebar = document.getElementById('sidebar');
    const sidebarHidden = sidebar && (sidebar.classList.contains('hidden') || getComputedStyle(sidebar).display === 'none');
    const lW = sidebarHidden ? '0px' : '240px';
    const hidden = panel.classList.contains('hidden');
    panelWidth = AGENT_PANEL_WIDTH;
    if (hidden && !animatingOut && !forceExpand) {
      // Collapsed — no panel visible
      content.style.gridTemplateColumns = lW + ' 1fr 0px 0px';
      if (resizeHandle) resizeHandle.classList.add('hidden');
    } else {
      // Panel visible or animating out — fixed width, hide resize handle
      content.style.gridTemplateColumns = lW + ' 1fr 5px ' + AGENT_PANEL_WIDTH + 'px';
      if (resizeHandle) resizeHandle.classList.add('hidden');
    }
  }

  // --- Resize drag (disabled: agent panel has fixed width for PTY) ---
  if (resizeHandle) {
    resizeHandle.addEventListener('mousedown', function(e) { e.preventDefault(); });
  }

  // --- View mode switching ---
  function showXtermMode() {
    xtermContainer.classList.remove('hidden');
    chatView.classList.add('hidden');
  }
  function showChatMode() {
    xtermContainer.classList.add('hidden');
    chatView.classList.remove('hidden');
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
      allowProposedApi: true, scrollback: 5000, cols: estimatedCols, rows: estimatedRows,
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
    if (typeof WebglAddon !== 'undefined') {
      try { term.loadAddon(new WebglAddon.WebglAddon()); xlog('init', 'WebglAddon loaded'); } catch (_) { xlog('init', 'WebglAddon failed', _); }
    }

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
      if (rw < 50) { xlog('fit', (label||'doFit') + ' skipped — container too narrow (' + rw + 'px)'); return; }
      var before = term ? { rows: term.rows, cols: term.cols } : null;
      xlog('fit', (label || 'doFit') + ' container=' + JSON.stringify(rectJson(xtermContainer)) + ' before=' + JSON.stringify(before));
      try { fitAddon.fit(); } catch (e) { xlog('fit', 'ERROR', e); }
      if (term) {
        var deltaCols = term.cols - (before ? before.cols : 0);
        xlog('fit', 'result rows=' + term.rows + ' cols=' + term.cols +
          ' (Δ rows:' + (term.rows - (before ? before.rows : 0)) + ' cols:' + deltaCols + ')');
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

  function renderMarkdown(el, rawText) {
    if (typeof window.markdownit !== 'undefined') {
      try {
        var md = window.markdownit({ html: false, linkify: true, breaks: true });
        el.innerHTML = md.render(rawText || '');
      } catch (_) {}
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
            if (currentSessionKey && msg.key === currentSessionKey) {
              term.writeln('\r\n\x1b[1;36m⟳ 已重连会话: ' + msg.key + '\x1b[0m');
            } else {
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

  // --- Resize handler (debounced 200ms) ---
  var _winResizeDebounce = null;
  window.addEventListener('resize', function () {
    updateGridColumns();
    if (_winResizeDebounce) clearTimeout(_winResizeDebounce);
    _winResizeDebounce = setTimeout(function () {
      _winResizeDebounce = null;
      doFit('win-resize');
    }, 200);
  });
  // --- Close button ---
  if (closeBtn) {
    closeBtn.addEventListener('click', function () { window.Agent.close(); });
  }

  // --- Clear button (clears local terminal + re-syncs PTY dimensions) ---
  if (clearBtn) {
    clearBtn.addEventListener('click', function () {
      if (term) {
        term.clear();
        term.writeln('\x1b[1;36m✓ 已清屏\x1b[0m');
        // Cancel any pending resize — a debounced resize that fires AFTER clear
        // would send stale dimensions and desync the PTY.
        if (_pendingResize) { clearTimeout(_pendingResize); _pendingResize = null; }
        // Reset PTY row/col — force re-sync so backend tty matches xterm dimensions
        _lastResizeSent = { cols: 0, rows: 0 };
        if (ws && ws.readyState === WebSocket.OPEN) {
          try {
            ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
          } catch (_) {}
        }
      }
    });
  }

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
      updateGridColumns(true);
      panel.offsetHeight; // force reflow
      panel.classList.remove('hidden');
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
      if (rootId) currentRootId = rootId;
      if (dir !== undefined) currentDir = dir;
      if (!panel.classList.contains('hidden') && ws && ws.readyState === WebSocket.OPEN) {
        try { ws.send(JSON.stringify({ type: 'chdir', root: currentRootId, dir: currentDir })); } catch (_) {}
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
