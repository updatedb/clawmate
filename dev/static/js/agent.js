// ===== Agent Panel — dual-mode: xterm.js (Claude) + markdown chat (OpenClaw) =====
//
// Exposes window.Agent API:
//   Agent.init({ wsUrl, rootId, dir, agentId, backend })  — one-time setup
//   Agent.open(rootId, dir)                  — open panel + connect WebSocket
//   Agent.close()                            — close panel + disconnect
//   Agent.toggle()                           — toggle panel
//   Agent.updateRoot(rootId, dir)            — update current root/dir

(function () {
  'use strict';

  // --- DOM refs (re-initializable with prefix for reuse in preview page) ---
  let _domPrefix = '';
  let panel, resizeHandle, xtermContainer, chatView, chatMessages, chatInput, chatSendBtn, badgeEl, rootEl, closeBtn, toggleBtn;

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
    badgeEl       = document.getElementById(p + 'AgentBackendBadge') || document.getElementById(p + 'agentBackendBadge') || document.getElementById('agentBackendBadge');
    rootEl        = document.getElementById(p + 'AgentPanelRoot') || document.getElementById(p + 'agentPanelRoot') || document.getElementById('agentPanelRoot');
    closeBtn      = document.getElementById(p + 'BtnCloseAgent') || document.getElementById(p + 'btnCloseAgent') || document.getElementById('btnCloseAgent');
    toggleBtn     = document.getElementById(p + 'BtnToggleAgent') || document.getElementById(p + 'btnToggleAgent') || document.getElementById('btnToggleAgent');
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
  let collapseTimer = null;
  let animatingOut = false; // true during slide-out animation
  let currentRootId = '';
  let currentDir = '';
  let currentAgentId = '';  // kept for OpenClaw backend session routing
  let backendMode = 'claude';
  let reconnectTimer = null;
  let reconnectAttempts = 0;
  const MAX_RECONNECT_ATTEMPTS = 10;
  let chatBuf = '';     // accumulating assistant text
  let chatBufEl = null; // current assistant bubble being built
  let chatStatusEl = null; // reconnection status element
  let currentSessionKey = '';  // tracks last session key from backend

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
    if (!panelWidth) panelWidth = Math.min(Math.floor(window.innerWidth * 0.45), 700);
    if (hidden && !animatingOut && !forceExpand) {
      // Collapsed — no panel visible
      content.style.gridTemplateColumns = lW + ' 1fr 0px 0px';
      if (resizeHandle) resizeHandle.classList.add('hidden');
    } else {
      // Panel visible or animating out — keep column width
      content.style.gridTemplateColumns = lW + ' 1fr 5px ' + panelWidth + 'px';
      if (resizeHandle) resizeHandle.classList.remove('hidden');
    }
  }

  // --- Resize drag ---
  let dragStartX = 0;
  let dragStartWidth = 0;

  function onResizeMouseDown(e) {
    e.preventDefault();
    dragStartX = e.clientX;
    dragStartWidth = panelWidth;
    resizeHandle.classList.add('active');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', onResizeMouseMove);
    document.addEventListener('mouseup', onResizeMouseUp);
  }

  function onResizeMouseMove(e) {
    const delta = dragStartX - e.clientX;
    const content = document.querySelector('.content');
    if (!content) return;
    panelWidth = Math.max(360, Math.min(800, dragStartWidth + delta));
    const sb = document.getElementById('sidebar');
    const sbHidden = sb && (sb.classList.contains('hidden') || getComputedStyle(sb).display === 'none');
    const lW = sbHidden ? '0px' : '240px';
    content.style.gridTemplateColumns = lW + ' 1fr 5px ' + panelWidth + 'px';
    if (fitAddon) { try { fitAddon.fit(); } catch (_) {} }
  }

  function onResizeMouseUp() {
    resizeHandle.classList.remove('active');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    document.removeEventListener('mousemove', onResizeMouseMove);
    document.removeEventListener('mouseup', onResizeMouseUp);
  }

  if (resizeHandle) {
    resizeHandle.addEventListener('mousedown', onResizeMouseDown);
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

  // --- xterm.js init (Claude backend) ---
  function createTerminal() {
    if (term) { xlog('init', 'term already exists, skipping'); return; }
    const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
    const bg = isDark ? '#111827' : '#f8fafc';
    const fg = isDark ? '#e2e8f0' : '#1e293b';
    const cursor = '#14b8a6';

    xlog('init', 'creating Terminal { fontSize:14, lineHeight:1.4, cols:100, rows:30, scrollback:5000 }');
    xlog('init', 'theme bg=' + bg + ' fg=' + fg + ' cursor=' + cursor);

    term = new Terminal({
      cursorBlink: true, cursorStyle: 'bar',
      fontSize: 14, fontFamily: '"JetBrains Mono", "Cascadia Code", "Fira Code", monospace',
      letterSpacing: 0, lineHeight: 1.4,
      theme: { background: bg, foreground: fg, cursor: cursor },
      allowProposedApi: true, scrollback: 5000, cols: 100, rows: 30,
    });

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
    xlog('init', 'term.open() done — term.element=' + (!!term.element) + ' term.textarea=' + (!!term.textarea));
    xlog('init', 'xtermContainer rect', JSON.stringify(rectJson(xtermContainer)));

    xlog('init', 'xtermContainer rect', JSON.stringify(rectJson(xtermContainer)));

    term.attachCustomKeyEventHandler(function (e) {
      if (e.type === 'keydown') {
        // Ctrl+C with selection → copy to clipboard (keep default xterm behavior)
        // Let xterm.js handle paste natively (Ctrl+V) — it flows through
        // term.onData → ws.send(), keeping the same pipeline as keyboard input.
        if (e.ctrlKey && !e.altKey && !e.metaKey) {
          if (e.key === 'c' && term.hasSelection()) {
            var sel = term.getSelection();
            if (sel && navigator.clipboard && navigator.clipboard.writeText) {
              navigator.clipboard.writeText(sel).catch(function () {});
            }
            xlog('key', 'Ctrl+C (copy) key=' + e.key + ' composing=' + e.isComposing);
            return false;
          }
        }
        // IME composition — never suppress, let xterm handle composition events
        if (e.isComposing || e.key === 'Dead' || e.key === 'Process') {
          xlog('key', 'IME composing key=' + e.key + ' isComposing=' + e.isComposing);
          return true;
        }
        xlog('key', 'keydown key=' + e.key + ' ctrl=' + e.ctrlKey + ' composing=' + e.isComposing);
      }
      return true;
    });

    // --- IME recovery ---
    // CJK input-method switching can steal focus from xterm's hidden textarea;
    // clicks on the terminal surface must always restore focus.
    var termElement = term.element;
    if (termElement) {
      termElement.addEventListener('click', function () { xlog('focus', 'click → term.focus()'); term.focus(); });
      termElement.addEventListener('mousedown', function () { term.focus(); });
      xlog('init', 'IME click/focus handlers registered on term.element');
    }

    // After composition ends (IME candidate selected or cancelled), refocus to
    // guarantee keystrokes keep flowing to the terminal.
    var textarea = term.textarea;
    if (textarea) {
      textarea.addEventListener('compositionstart', function () {
        xlog('ime', 'compositionstart');
      });
      textarea.addEventListener('compositionend', function () {
        xlog('ime', 'compositionend → refocus');
        setTimeout(function () { term.focus(); }, 0);
      });
      // When IME popup/candidate-window opens, the textarea loses focus with
      // relatedTarget === null (the IME window is a native OS surface, not a
      // DOM element).  Pull focus back only in that case.
      textarea.addEventListener('blur', function (e) {
        var rtTag = e.relatedTarget ? (e.relatedTarget.tagName || 'unknown') : 'null';
        xlog('focus', 'textarea blur relatedTarget=' + rtTag + ' panel.hidden=' + panel.classList.contains('hidden'));
        if (panel.classList.contains('hidden')) return;
        if (e.relatedTarget === null) {
          xlog('focus', 'refocus (IME window stole focus)');
          setTimeout(function () { term.focus(); }, 0);
        }
      });
      textarea.addEventListener('focus', function () {
        xlog('focus', 'textarea gained focus');
      });
      xlog('init', 'IME composition/focus handlers registered on textarea');
    } else {
      xlog('init', 'WARNING: term.textarea is null — IME recovery disabled');
    }

    // --- Fit after layout (with font-ready guard) ---
    function doFit(label) {
      if (panel.classList.contains('hidden') || !fitAddon) return;
      var before = term ? { rows: term.rows, cols: term.cols } : null;
      xlog('fit', (label || 'doFit') + ' container=' + JSON.stringify(rectJson(xtermContainer)) + ' before=' + JSON.stringify(before));
      try { fitAddon.fit(); } catch (e) { xlog('fit', 'ERROR', e); }
      if (term) {
        xlog('fit', 'result rows=' + term.rows + ' cols=' + term.cols +
          ' (Δ rows:' + (term.rows - (before ? before.rows : 0)) +
          ' cols:' + (term.cols - (before ? before.cols : 0)) + ')');
        // Refresh WebGL renderer after fit to sync framebuffer dimensions
        try { term.refresh(0, term.rows - 1); } catch (_) {}
      }
    }

    if (fitAddon) {
      xlog('fit', 'waiting for fonts.ready...');
      var fontFitted = false;
      var fontTimer = setTimeout(function () {
        if (!fontFitted) { fontFitted = true; doFit('font-timeout'); }
      }, 3000);
      if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(function () {
          clearTimeout(fontTimer);
          if (!fontFitted) {
            fontFitted = true;
            xlog('fit', 'fonts.ready resolved');
            // Wait one rAF so the browser applies the font to layout
            requestAnimationFrame(function () { doFit('fonts-ready'); });
          }
        }).catch(function () {
          clearTimeout(fontTimer);
          if (!fontFitted) { fontFitted = true; requestAnimationFrame(function () { requestAnimationFrame(function () { doFit('fonts-fallback'); }); }); }
        });
      } else {
        // document.fonts not supported — immediate fit
        clearTimeout(fontTimer);
        fontFitted = true;
        requestAnimationFrame(function () { requestAnimationFrame(function () { doFit('rAFx2'); }); });
      }
    } else {
      xlog('fit', 'SKIP — fitAddon is null');
    }

    // --- ResizeObserver ---
    if (typeof ResizeObserver !== 'undefined') {
      if (termResizeObserver) termResizeObserver.disconnect();
      termResizeObserver = new ResizeObserver(function (entries) {
        var r = entries[0] && entries[0].contentRect;
        xlog('resize-observer', 'fired container=' + (r ? Math.round(r.width) + 'x' + Math.round(r.height) : '?') + ' hidden=' + panel.classList.contains('hidden'));
        if (fitAddon && !panel.classList.contains('hidden')) {
          try { fitAddon.fit(); } catch (_) {}
        }
      });
      termResizeObserver.observe(xtermContainer);
      xlog('init', 'ResizeObserver active on xtermContainer');
    }

    // --- Data / resize forward to WebSocket ---
    var _inputBatch = '';
    var _inputBatchTimer = null;
    var INPUT_BATCH_MS = 30;
    function _flushInputBatch() {
      var batch = _inputBatch;
      _inputBatch = '';
      if (batch && ws && ws.readyState === WebSocket.OPEN) {
        ws.send(batch);
      }
    }
    term.onData(function (data) {
      xlog('data', 'len=' + data.length + ' preview=' + JSON.stringify(data.slice(0, 40)) + ' ws=' + (ws ? ws.readyState : 'null'));
      _inputBatch += data;
      // Send Enter immediately for zero-latency command submission
      if (data === '\r' || data === '\n') {
        clearTimeout(_inputBatchTimer);
        _inputBatchTimer = null;
        _flushInputBatch();
        return;
      }
      if (_inputBatchTimer) clearTimeout(_inputBatchTimer);
      _inputBatchTimer = setTimeout(_flushInputBatch, INPUT_BATCH_MS);
    });
    var _resizeDebounce = null;
    term.onResize(function (size) {
      xlog('resize', 'term.onResize cols=' + size.cols + ' rows=' + size.rows);
      if (_resizeDebounce) clearTimeout(_resizeDebounce);
      _resizeDebounce = setTimeout(function () {
        if (ws && ws.readyState === WebSocket.OPEN) {
          try { ws.send(JSON.stringify({ type: 'resize', cols: size.cols, rows: size.rows })); } catch (_) {}
        }
      }, 150);
    });
  }

  // --- Chat view (OpenClaw backend) ---
  function addChatBubble(role, text) {
    var div = document.createElement('div');
    div.className = 'agent-chat-msg agent-chat-' + role;
    if (role === 'assistant') {
      div.innerHTML = text; // markdown rendered by markdown-it if available
    } else {
      div.textContent = text;
    }
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
  }

  function showChatStatus(text, type) {
    if (!chatMessages) return;
    // Remove previous status
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
      // Fallback: extract sessionKey from OpenClaw info message
      if (msg.sessionKey && rootEl && !rootEl.textContent) {
        rootEl.textContent = msg.sessionKey;
      }
      var info = document.createElement('div');
      info.className = 'agent-chat-info';
      info.textContent = msg.text || '';
      chatMessages.appendChild(info);
      chatMessages.scrollTop = chatMessages.scrollHeight;
      return;
    }

    if (type === 'error') {
      var err = document.createElement('div');
      err.className = 'agent-chat-error';
      err.textContent = '✕ ' + (msg.text || 'Unknown error');
      chatMessages.appendChild(err);
      chatMessages.scrollTop = chatMessages.scrollHeight;
      return;
    }

    if (type === 'user') {
      addChatBubble('user', msg.text || '');
      // Create placeholder for assistant response
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
          // Auto-scroll to show new content
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

    var url = wsUrl +
      '?root=' + encodeURIComponent(currentRootId || '') +
      '&dir=' + encodeURIComponent(currentDir || '') +
      '&agentId=' + encodeURIComponent(currentAgentId || '');

    try { ws = new WebSocket(url); } catch (e) { xlog('ws', 'constructor failed', e); scheduleReconnect(); return; }

    ws.onopen = function () {
      xlog('ws', 'OPEN');
      reconnectAttempts = 0;
      if (backendMode === 'claude' && term) {
        term.writeln('\x1b[1;36m✓ 已连接 Agent 终端\x1b[0m');
        term.writeln('\x1b[2m  ' + term.cols + '×' + term.rows + '  |  调整面板宽度后运行的程序会自动适配新宽度\x1b[0m');
        term.writeln('');
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
          if (rootEl) rootEl.textContent = msg.key;
          // Detect session key change — skip initial connection (currentSessionKey empty)
          if (currentSessionKey && msg.key !== currentSessionKey) {
            xlog('session', 'key changed: ' + currentSessionKey + ' -> ' + msg.key);
            currentSessionKey = msg.key;
            // Defer reconnect so we exit onmessage before old WS is torn down
            setTimeout(function () { reconnectToNewSession(); }, 0);
            return;
          }
          currentSessionKey = msg.key;
          return;
        }
      } catch (_) {}

      if (backendMode === 'claude' && term) {
        term.write(e.data);
        return;
      }
      // OpenClaw chat mode: parse JSON messages
      if (backendMode === 'openclaw') {
        try {
          var msg = JSON.parse(e.data);
          handleChatMessage(msg);
        } catch (_) {
          // Raw text fallback (banner etc.)
        }
      }
    };

    ws.onclose = function () {
      xlog('ws', 'CLOSE');
      if (backendMode === 'claude' && term) {
        term.writeln('\r\n\x1b[1;33m⚠ 连接已断开\x1b[0m');
      }
      if (backendMode === 'openclaw') {
        showChatStatus('⚠ 连接已断开，正在重连...', 'error');
      }
      ws = null;
      scheduleReconnect();
    };

    ws.onerror = function () {
      xlog('ws', 'ERROR');
      if (backendMode === 'claude' && term) {
        term.writeln('\r\n\x1b[1;31m✕ 连接失败\x1b[0m');
      }
      if (backendMode === 'openclaw') {
        showChatStatus('✕ 连接失败', 'error');
      }
    };
  }

  function disconnectWs() {
    clearReconnect();
    currentSessionKey = '';
    if (ws) { ws.onclose = null; ws.close(); ws = null; }
    if (term) { term.clear(); term.writeln('\x1b[2m终端已断开。\x1b[0m'); }
    if (chatMessages) { chatMessages.innerHTML = ''; }
    chatBuf = ''; chatBufEl = null; chatStatusEl = null;
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

    // Close old WS silently — prevent onclose/onerror from firing
    if (ws) {
      ws.onclose = null;
      ws.onerror = null;
      try { ws.close(); } catch (_) {}
      ws = null;
    }

    // Clear display for clean transition — use reset() instead of clear()
    // because clear() can leave the WebGL renderer in a broken state
    if (backendMode === 'claude' && term) {
      term.reset();
      term.writeln('\x1b[1;36m⟳ 项目已切换，重新连接...\x1b[0m');
    }
    if (backendMode === 'openclaw' && chatMessages) {
      chatMessages.innerHTML = '';
      chatBuf = '';
      chatBufEl = null;
      chatStatusEl = null;
    }

    // Reset reconnect counter — this is intentional, not a failure
    reconnectAttempts = 0;

    // Open new WebSocket — currentRootId/currentDir were already
    // updated by Agent.updateRoot() before the chdir was sent
    connectWs();
  }

  // --- Resize handler ---
  window.addEventListener('resize', function () {
    updateGridColumns();
    if (fitAddon && !panel.classList.contains('hidden')) {
      try { fitAddon.fit(); } catch (_) {}
    }
  });

  // --- Close button ---
  if (closeBtn) {
    closeBtn.addEventListener('click', function () { window.Agent.close(); });
  }

  // --- Public API ---
  window.Agent = {
    init: function (config) {
      // Re-resolve DOM if a custom prefix is provided (e.g. 'preview' for preview page)
      if (config.domPrefix) { _resolveDom(config.domPrefix); }
      wsUrl = config.wsUrl || '';
      currentRootId = config.rootId || '';
      currentDir = config.dir || '';
      currentAgentId = config.agentId || '';
      backendMode = config.backend || 'claude';
      if (badgeEl) badgeEl.textContent = backendMode;

      if (backendMode === 'openclaw') {
        showChatMode();
      } else {
        showXtermMode();
      }
    },

    open: function (rootId, dir) {
      if (rootId) currentRootId = rootId;
      if (dir !== undefined) currentDir = dir;

      animatingOut = false;
      clearTimeout(collapseTimer);
      // Force grid expansion before removing hidden for slide-in
      updateGridColumns(true);
      panel.offsetHeight; // force reflow
      panel.classList.remove('hidden');
      document.body.classList.add('agent-open');
      setTimeout(function () { if (typeof syncSidebarBtn === 'function') syncSidebarBtn(); }, 0);
      if (backendMode === 'openclaw') {
        showChatMode();
        chatMessages.innerHTML = '';
        chatBuf = ''; chatBufEl = null;
      } else {
        showXtermMode();
        createTerminal();
        if (term) {
          term.clear();
          term.writeln('\x1b[1;36m╔══════════════════════════════════════╗\x1b[0m');
          term.writeln('\x1b[1;36m║     ClawMate Agent Terminal         ║\x1b[0m');
          term.writeln('\x1b[1;36m╚══════════════════════════════════════╝\x1b[0m');
          term.writeln('');
        }
      }

      reconnectAttempts = 0;
      connectWs();

      // Fit after panel slide-in transition completes (instead of 200ms blind timer)
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
        // Safety net: 500ms regardless
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
      panel.classList.add('hidden');
      document.body.classList.remove('agent-open');
      setTimeout(function () { if (typeof syncSidebarBtn === 'function') syncSidebarBtn(); }, 0);
      updateGridColumns(); // keep column for slide-out animation
      clearTimeout(collapseTimer);
      collapseTimer = setTimeout(function () {
        animatingOut = false;
        updateGridColumns(); // collapse to 0px
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
      // session key is updated via backend "session" message in response to chdir
      if (!panel.classList.contains('hidden') && ws && ws.readyState === WebSocket.OPEN) {
        try { ws.send(JSON.stringify({ type: 'chdir', root: currentRootId, dir: currentDir })); } catch (_) {}
      }
    },

    isOpen: function () {
      return !panel.classList.contains('hidden');
    },

    /** Recompute grid columns (called externally on sidebar toggle) */
    updateGrid: function () { updateGridColumns(); },
  };

})();
