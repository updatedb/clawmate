// ===== Agent Panel — dual-mode: xterm.js (Claude) + markdown chat (OpenClaw) =====
//
// Exposes window.Agent API:
//   Agent.init({ wsUrl, rootId, dir, agentId, backend })  — one-time setup
//   Agent.open(rootId, dir, fileContext)     — open panel + connect WebSocket, optionally with file context
//   Agent.close()                            — close panel + disconnect
//   Agent.toggle()                           — toggle panel
//   Agent.updateRoot(rootId, dir)            — update current root/dir

(function () {
  'use strict';

  // --- DOM refs (re-initializable with prefix for reuse in preview page) ---
  let _domPrefix = '';
  let panel, resizeHandle, xtermContainer, chatView, chatMessages, chatInput, chatSendBtn, badgeEl, rootEl, closeBtn, toggleBtn;
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
    if (!panelWidth) panelWidth = Math.min(Math.floor(window.innerWidth * 0.45), 800);
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
    panelWidth = Math.max(420, Math.min(900, dragStartWidth + delta));
    const sb = document.getElementById('sidebar');
    const sbHidden = sb && (sb.classList.contains('hidden') || getComputedStyle(sb).display === 'none');
    const lW = sbHidden ? '0px' : '240px';
    content.style.gridTemplateColumns = lW + ' 1fr 5px ' + panelWidth + 'px';
    applyScale();
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

    // ── Fixed 80-column terminal + CSS scale to fit panel width ──
    // PTY always sees 80 cols — output format never changes.
    // Visual adaptation by CSS transform:scale on the container.
    var FIXED_COLS = 80;
    var containerH = xtermContainer.parentElement.clientHeight || 400; // wrapper height
    var CHAR_H = 19.6;  // fontSize * lineHeight = 14 * 1.4
    var estimatedRows = Math.max(10, Math.floor((containerH - 8) / CHAR_H));

    xlog('init', 'cols=' + FIXED_COLS + ' rows=' + estimatedRows + ' theme bg=' + bg + ' fg=' + fg);

    term = new Terminal({
      cursorBlink: true, cursorStyle: 'bar',
      fontSize: 14, fontFamily: '"JetBrains Mono", "Cascadia Code", "Fira Code", "Consolas", "SF Mono", "DejaVu Sans Mono", monospace',
      letterSpacing: 0, lineHeight: 1.4,
      allowTransparency: false,
      drawBoldTextInBrightColors: false,
      theme: {
        background: bg,
        foreground: fg,
        cursor: cursor,
        selectionBackground: selBg,
        selectionForeground: selFg,
        selectionInactiveBackground: selInactiveBg,
      },
      allowProposedApi: true, scrollback: 5000, cols: FIXED_COLS, rows: estimatedRows,
    });

    // Fixed dimensions — PTY never resizes
    window._agentInitCols = FIXED_COLS;
    window._agentInitRows = estimatedRows;

    // FitAddon not needed for resizing; kept only for WebglAddon loading
    if (typeof FitAddon !== 'undefined') {
      fitAddon = new FitAddon.FitAddon();
      term.loadAddon(fitAddon);
    }
    if (typeof WebglAddon !== 'undefined') {
      try { term.loadAddon(new WebglAddon.WebglAddon()); xlog('init', 'WebglAddon loaded'); } catch (_) { xlog('init', 'WebglAddon failed', _); }
    }

    term.open(xtermContainer);
    xlog('init', 'term.open() done');

    // ── CSS scale to fit terminal within panel width ──
    var scaleWrapper = xtermContainer.parentElement; // .xterm-scale-wrapper
    var _naturalWidth = 0; // set after first render

    function applyScale() {
      if (!scaleWrapper || !term) return;
      if (!_naturalWidth) {
        // Measure terminal's natural pixel width at 80 cols × 14px font
        _naturalWidth = xtermContainer.scrollWidth || xtermContainer.offsetWidth || 700;
        if (_naturalWidth < 300) _naturalWidth = 700; // sanity floor
        xlog('scale', 'naturalWidth=' + Math.round(_naturalWidth));
      }
      var wrapperW = scaleWrapper.clientWidth;
      if (wrapperW <= 0) return;
      var usableW = Math.max(200, wrapperW - 12); // padding + scrollbar reserve
      var scale = usableW / _naturalWidth;
      scale = Math.max(0.35, Math.min(2.5, scale)); // clamp extreme ratios

      xtermContainer.style.width = _naturalWidth + 'px';
      xtermContainer.style.transform = 'scale(' + scale + ')';
      // Adjust wrapper height to prevent overflow
      var h = xtermContainer.scrollHeight || (term.rows * CHAR_H + 8);
      scaleWrapper.style.height = Math.ceil(h * scale) + 'px';

      xlog('scale', 'wrapper=' + Math.round(wrapperW) + ' scale=' + scale.toFixed(3) + ' natural=' + Math.round(_naturalWidth));
    }

    // Measure after xterm has rendered its first frame
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { applyScale(); });
    });

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

    // Re-measure natural width after fonts load
    if (document.fonts && document.fonts.ready) {
      var _fontsDone = false;
      var _fontTimer = setTimeout(function () {
        if (!_fontsDone) { _fontsDone = true; _naturalWidth = 0; applyScale(); }
      }, 1000);
      document.fonts.ready.then(function () {
        clearTimeout(_fontTimer);
        if (!_fontsDone) { _fontsDone = true; _naturalWidth = 0; applyScale(); }
      }).catch(function () {
        clearTimeout(_fontTimer);
        if (!_fontsDone) { _fontsDone = true; _naturalWidth = 0; applyScale(); }
      });
    }

    // --- ResizeObserver on scale wrapper (debounced 200ms) ---
    if (typeof ResizeObserver !== 'undefined') {
      if (termResizeObserver) termResizeObserver.disconnect();
      var _roDebounce = null;
      termResizeObserver = new ResizeObserver(function () {
        if (_roDebounce) clearTimeout(_roDebounce);
        _roDebounce = setTimeout(function () {
          _roDebounce = null;
          if (!panel.classList.contains('hidden')) applyScale();
        }, 200);
      });
      termResizeObserver.observe(scaleWrapper);
      xlog('init', 'ResizeObserver active on scale wrapper (200ms debounce)');
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
      // Flush immediately so that PTY echo arrives without avoidable delay.
      // The user sees characters only after the server echoes them back,
      // so any batching here directly adds to perceived input lag.
      _flushInputBatch();
    });
    // ── PTY resize: cols always 80, only rows may change ──
    term.onResize(function (size) {
      xlog('resize', 'term.onResize cols=' + size.cols + ' rows=' + size.rows);
      _sendResize(FIXED_COLS, size.rows);
    });

    function _sendResize(cols, rows) {
      if (cols === _lastResizeSent.cols && rows === _lastResizeSent.rows) return;
      _lastResizeSent = { cols: cols, rows: rows };
      if (ws && ws.readyState === WebSocket.OPEN) {
        try { ws.send(JSON.stringify({ type: 'resize', cols: cols, rows: rows })); } catch (_) {}
      }
    }

    // ── Flow control: prevent xterm.js write buffer from growing unbounded ──
    // xterm.js processes ALL terminal output (including echoes) on the main thread
    // with a ~12ms per-frame budget. When the write buffer exceeds the HIGH
    // watermark we stop feeding data — xterm.js already buffers internally, so
    // additional external buffering would only create a ping-pong effect where
    // the resume dump immediately re-triggers flow-pause.
    // Data arriving during flow-pause is dropped; this is intentional — the
    // terminal renderer is the bottleneck, and dropping frames is the standard
    // approach for real-time output streams.
    if (term.onFlowControlPause) {
      term.onFlowControlPause(function () {
        flowPaused = true;
        xlog('flow', 'PAUSE — write buffer full, pausing terminal writes');
      });
      term.onFlowControlResume(function () {
        flowPaused = false;
        xlog('flow', 'RESUME — accepting data again');
      });
      xlog('init', 'Flow control handlers registered');
    }
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

    // Pass current terminal dimensions so the backend PTY starts at the right size
    var initCols = (term && term.cols) || window._agentInitCols || 80;
    var initRows = (term && term.rows) || window._agentInitRows || 24;

    var url = wsUrl +
      '?root=' + encodeURIComponent(currentRootId || '') +
      '&dir=' + encodeURIComponent(currentDir || '') +
      '&agentId=' + encodeURIComponent(currentAgentId || '') +
      '&cols=' + initCols +
      '&rows=' + initRows;

    try { ws = new WebSocket(url); } catch (e) { xlog('ws', 'constructor failed', e); scheduleReconnect(); return; }

    ws.onopen = function () {
      xlog('ws', 'OPEN');
      reconnectAttempts = 0;
      if (isPtyBackend() && term) {
        // Send current dimensions immediately so backend PTY output is
        // formatted at the correct column width from the very first byte.
        try {
          ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
        } catch (_) {}
        // Now show the connection banner — the backend already has the
        // correct dimensions, and fit() has already run once.
        term.clear();
        term.writeln('\x1b[1;36m✓ 已连接 Agent 终端\x1b[0m');
        term.writeln('\x1b[2m  ' + term.cols + '×' + term.rows + '  |  调整面板宽度后运行的程序会自动适配新宽度\x1b[0m');
        term.writeln('');
        // Send file context if preview page opened agent with a file
        if (_pendingFileContext) {
          try {
            ws.send(JSON.stringify({
              type: 'file_context',
              path: _pendingFileContext.path || '',
              content: _pendingFileContext.content || '',
            }));
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

      if (isPtyBackend() && term) {
        // Respect xterm.js flow control: if the internal write buffer is
        // over the HIGH watermark, drop incoming data. xterm.js already
        // buffers internally, so an external buffer just creates a ping-pong
        // effect on resume. Dropping frames is the standard approach for
        // real-time terminal output that can't keep up with rendering.
        if (flowPaused) { return; }
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
      if (isPtyBackend() && term) {
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
      if (isPtyBackend() && term) {
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
    if (term) {
      // Suspend cursor blink timer — hidden terminals that keep blinking
      // waste main-thread time every ~500ms competing with active UI.
      try { term.blur(); } catch (_) {}
      term.clear(); term.writeln('\x1b[2m终端已断开。\x1b[0m');
    }
    if (chatMessages) { chatMessages.innerHTML = ''; }
    chatBuf = ''; chatBufEl = null; chatStatusEl = null;
    // Reset resize tracking so next connection sends dimensions immediately
    _lastResizeSent = { cols: 0, rows: 0 };
    if (_pendingResize) { clearTimeout(_pendingResize); _pendingResize = null; }
    // Reset flow control state for clean reconnection
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

    // Close old WS silently — prevent onclose/onerror from firing
    if (ws) {
      ws.onclose = null;
      ws.onerror = null;
      try { ws.close(); } catch (_) {}
      ws = null;
    }

    // Clear display for clean transition — use reset() instead of clear()
    // because clear() can leave the WebGL renderer in a broken state
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

    // Reset reconnect counter — this is intentional, not a failure
    reconnectAttempts = 0;

    // Open new WebSocket — currentRootId/currentDir were already
    // updated by Agent.updateRoot() before the chdir was sent
    connectWs();
  }

  // --- Resize handler (debounced 200ms) ---
  var _winResizeDebounce = null;
  window.addEventListener('resize', function () {
    updateGridColumns();
    if (_winResizeDebounce) clearTimeout(_winResizeDebounce);
    _winResizeDebounce = setTimeout(function () {
      _winResizeDebounce = null;
      if (!panel.classList.contains('hidden')) applyScale();
    }, 200);
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

    open: function (rootId, dir, fileContext) {
      if (rootId) currentRootId = rootId;
      if (dir !== undefined) currentDir = dir;
      if (fileContext) _pendingFileContext = fileContext;

      animatingOut = false;
      clearTimeout(collapseTimer);
      // Temporarily override display:none so the panel is rendered
      // (off-screen via translateX(100%)) before the slide-in transition.
      panel.style.display = 'flex';
      // Force grid expansion before removing hidden for slide-in
      updateGridColumns(true);
      panel.offsetHeight; // force reflow (sync layout)
      panel.classList.remove('hidden');
      // Let CSS .agent-panel handle display from now on
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
        // Banner is now shown in ws.onopen after initial resize sync
      }

      reconnectAttempts = 0;
      connectWs();

      // Reconnect ResizeObserver if it was disconnected on close.
      // unobserve first to avoid InvalidStateError on Firefox when the
      // element is already being observed (e.g. rapid open→close→open).
      if (termResizeObserver && xtermContainer) {
        try { termResizeObserver.unobserve(xtermContainer); } catch (_) {}
        try { termResizeObserver.observe(xtermContainer); xlog('init', 'ResizeObserver reconnected'); } catch (_) {}
      }

      // Fit after panel slide-in transition completes (instead of 200ms blind timer)
      if (fitAddon) {
        var transitionFitted = false;
        var onPanelTransitionEnd = function (e) {
          if (e.propertyName === 'transform' || e.propertyName === 'all') {
            panel.removeEventListener('transitionend', onPanelTransitionEnd);
            if (!transitionFitted) {
              transitionFitted = true;
              applyScale();
            }
          }
        };
        panel.addEventListener('transitionend', onPanelTransitionEnd);
        // Safety net: 500ms regardless
        setTimeout(function () {
          panel.removeEventListener('transitionend', onPanelTransitionEnd);
          if (!transitionFitted) {
            transitionFitted = true;
            applyScale();
          }
        }, 500);
      }
    },

    close: function () {
      disconnectWs();
      animatingOut = true;
      // Disconnect ResizeObserver while panel is hidden — avoids wasted
      // callbacks competing for main-thread time with visible UI elements.
      if (termResizeObserver) {
        try { termResizeObserver.disconnect(); } catch (_) {}
      }
      // Override global .hidden display:none so the slide-out
      // transition (translateX(0) → translateX(100%)) actually plays.
      panel.style.display = 'flex';
      panel.classList.add('hidden');
      document.body.classList.remove('agent-open');
      setTimeout(function () { if (typeof syncSidebarBtn === 'function') syncSidebarBtn(); }, 0);
      updateGridColumns(); // keep column for slide-out animation
      clearTimeout(collapseTimer);
      collapseTimer = setTimeout(function () {
        animatingOut = false;
        panel.style.display = ''; // let CSS .hidden handle display again
        updateGridColumns(); // collapse to 0px
        // Cursor blink timer is now fully stopped after slide-out completes.
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

    /** Focus terminal or chat input so keyboard input goes to the right place */
    focus: function () {
      if (term) {
        term.focus();
      } else if (chatInput && !chatView.classList.contains('hidden')) {
        chatInput.focus();
      }
    },

    /** Recompute grid columns (called externally on sidebar toggle) */
    updateGrid: function () { updateGridColumns(); },

    /** Re-theme the xterm terminal to match current app theme */
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
