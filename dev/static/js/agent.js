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
  let modeBtn, domTermOutput, domTermInput;
  let panelTitleEl;
  var domTermId, domInputId, modeBtnId;
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
    modeBtn       = document.getElementById(p + 'BtnAgentMode') || document.getElementById(p + 'btnAgentMode') || document.getElementById('btnAgentMode');
    panelTitleEl  = document.getElementById(p + 'AgentPanelTitle') || document.getElementById(p + 'agentPanelTitle') || document.getElementById('agentPanelTitle');
    domTermOutput = document.getElementById(p + 'DomTermOutput') || document.getElementById(p + 'domTermOutput') || document.getElementById('domTermOutput');
    domTermInput  = document.getElementById(p + 'DomTermInput') || document.getElementById(p + 'domTermInput') || document.getElementById('domTermInput');
    // Update ID strings for DOM terminal functions
    domTermId = domTermOutput ? domTermOutput.id : (p + 'DomTermOutput');
    domInputId = domTermInput ? domTermInput.id : (p + 'DomTermInput');
    modeBtnId = modeBtn ? modeBtn.id : (p + 'BtnAgentMode');
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

  // ── DOM renderer state ──
  let _renderMode = 'dom'; // 'dom' | 'xterm'
  let _domOutput = null;
  let _domInput = null;
  let _ansiUp = null;
  let _domLines = [''];

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
    if (_renderMode === 'xterm' && fitAddon) { try { fitAddon.fit(); } catch (_) {} }
  }

  function onResizeMouseUp() {
    resizeHandle.classList.remove('active');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    document.removeEventListener('mousemove', onResizeMouseMove);
    document.removeEventListener('mouseup', onResizeMouseUp);
    // Flush final resize dimensions to backend
    _flushResize();
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
    if (_renderMode === 'dom') { _createDomTerminal(); return; }
    _createXterm();
  }

  // ── DOM terminal (ansi-up) ──
  function _createDomTerminal() {
    // Load ansi-up if needed
    if (!window.AnsiUp && typeof AnsiUp === 'undefined') {
      var s = document.createElement('script');
      s.src = './vendor/ansi-up.min.js';
      s.onload = function () { _initDomTerminal(); };
      document.head.appendChild(s);
    } else {
      _initDomTerminal();
    }
  }

  function _initDomTerminal() {
    _domOutput = document.getElementById(domTermId);
    _domInput = document.getElementById(domInputId);
    if (!_domOutput || !_domInput) return;

    _domOutput.classList.remove('hidden');
    _domInput.classList.remove('hidden');
    xtermContainer.classList.add('hidden');

    _domOutput.innerHTML = '';
    _domLines = [''];
    _ansiUp = new (window.AnsiUp || AnsiUp)();
    _ansiUp.use_classes = true;

    _domInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        var text = _domInput.value;
        _domInput.value = '';
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(text + '\r');
        }
      }
    });

    _addDomLine('\x1b[1;36m✓ DOM 终端已连接\x1b[0m');
    _addDomLine('\x1b[2m  ' + _domOutput.clientWidth + 'px  |  输入命令后按 Enter 发送\x1b[0m');
  }

  function _addDomLine(html) {
    if (!_domOutput) return;
    var div = document.createElement('div');
    div.className = 'dom-line';
    div.innerHTML = html;
    _domOutput.appendChild(div);
    _domOutput.scrollTop = _domOutput.scrollHeight;
  }

  function _domWrite(data) {
    if (!_domOutput || !_ansiUp) return;
    var html = _ansiUp.ansi_to_html(data);
    if (!html) return;
    // Split by newlines, update last line or append new lines
    var parts = html.split('\n');
    for (var i = 0; i < parts.length; i++) {
      if (i === 0 && _domLines.length > 0) {
        // Append to last line
        var last = _domOutput.lastElementChild;
        if (last && last.classList.contains('dom-line')) {
          last.innerHTML += parts[i];
        } else {
          _addDomLine(parts[i]);
        }
      } else {
        _addDomLine(parts[i]);
      }
    }
    _domLines = [parts[parts.length - 1]];
  }

  function _toggleAgentMode() {
    if (!term && _renderMode === 'xterm') return; // xterm not created yet
    var modeBtn = document.getElementById(modeBtnId);
    if (_renderMode === 'dom') {
      _renderMode = 'xterm';
      if (!term) _createXterm();
      if (modeBtn) modeBtn.textContent = 'TERM';
      if (_domOutput) _domOutput.classList.add('hidden');
      if (_domInput) _domInput.classList.add('hidden');
      xtermContainer.classList.remove('hidden');
    } else {
      _renderMode = 'dom';
      if (modeBtn) modeBtn.textContent = 'DOM';
      xtermContainer.classList.add('hidden');
      if (_domOutput) _domOutput.classList.remove('hidden');
      if (_domInput) _domInput.classList.remove('hidden');
    }
  }

  // ── xterm terminal (original) ──
  function _createXterm() {
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

    // ── Estimate cols/rows from container before Terminal creation ──
    // This avoids the hardcoded 100×30 → fit mismatch that garbles initial output.
    // Measure actual character width instead of hardcoded 8.4px
    var fontFamily = '"JetBrains Mono", "Cascadia Code", "Fira Code", "Consolas", "SF Mono", "DejaVu Sans Mono", monospace';
    var _measureSpan = document.createElement('span');
    _measureSpan.style.cssText = 'position:absolute;visibility:hidden;font-family:' + fontFamily + ';font-size:14px;white-space:pre;';
    _measureSpan.textContent = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    document.body.appendChild(_measureSpan);
    var CHAR_W = _measureSpan.offsetWidth / 62;
    document.body.removeChild(_measureSpan);
    if (!(CHAR_W > 4 && CHAR_W < 16)) CHAR_W = 8.4; // fallback if measurement fails
    var CHAR_H = 19.6;  // fontSize * lineHeight = 14 * 1.4
    var containerW = xtermContainer.clientWidth || 600;
    var containerH = xtermContainer.clientHeight || 400;
    var usableW = Math.max(100, containerW - 12 - 6);
    var usableH = Math.max(100, containerH - 8);
    var estimatedCols = Math.max(40, Math.floor(usableW / CHAR_W));
    var estimatedRows = Math.max(10, Math.floor(usableH / CHAR_H));

    xlog('init', 'container=' + containerW + 'x' + containerH +
      ' usable=' + Math.round(usableW) + 'x' + Math.round(usableH) +
      ' estimated cols=' + estimatedCols + ' rows=' + estimatedRows);
    xlog('init', 'theme bg=' + bg + ' fg=' + fg + ' cursor=' + cursor);

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
      allowProposedApi: true, scrollback: 5000, cols: estimatedCols, rows: estimatedRows,
    });

    // Store estimated dimensions so connectWs() can pass them to the backend
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
    // Immediate rough fit — refined later when fonts load
    if (fitAddon) {
      try { fitAddon.fit(); } catch (_) {}
      if (term) { try { term.refresh(0, term.rows - 1); } catch (_) {} }
    }
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
        var deltaCols = term.cols - (before ? before.cols : 0);
        xlog('fit', 'result rows=' + term.rows + ' cols=' + term.cols +
          ' (Δ rows:' + (term.rows - (before ? before.rows : 0)) +
          ' cols:' + deltaCols + ')');
        // Refresh WebGL renderer; double-rAF ensures the framebuffer
        // reallocates at the new character-grid dimensions.
        try { term.refresh(0, term.rows - 1); } catch (_) {}
        requestAnimationFrame(function () {
          try { term.refresh(0, term.rows - 1); } catch (_) {}
        });
      }
    }

    if (fitAddon) {
      xlog('fit', 'waiting for fonts.ready...');
      var fontFitted = false;
      var fontTimer = setTimeout(function () {
        if (!fontFitted) { fontFitted = true; doFit('font-timeout'); }
      }, 1000);
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

    // --- ResizeObserver (debounced 200ms) ---
    if (typeof ResizeObserver !== 'undefined') {
      if (termResizeObserver) termResizeObserver.disconnect();
      var _roDebounce = null;
      termResizeObserver = new ResizeObserver(function (entries) {
        if (_roDebounce) clearTimeout(_roDebounce);
        _roDebounce = setTimeout(function () {
          _roDebounce = null;
          var r = entries[0] && entries[0].contentRect;
          xlog('resize-observer', 'fired container=' + (r ? Math.round(r.width) + 'x' + Math.round(r.height) : '?') + ' hidden=' + panel.classList.contains('hidden'));
          if (fitAddon && !panel.classList.contains('hidden')) {
            try { fitAddon.fit(); } catch (_) {}
          }
        }, 200);
      });
      termResizeObserver.observe(xtermContainer);
      xlog('init', 'ResizeObserver active on xtermContainer (200ms debounce)');
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
    // ── Resize strategy: first immediate, then throttle 50ms, skip dupes ──
    term.onResize(function (size) {
      xlog('resize', 'term.onResize cols=' + size.cols + ' rows=' + size.rows);
      _scheduleResize(size.cols, size.rows);
    });

    function _scheduleResize(cols, rows) {
      // Send immediately if this is the very first resize (initial sync)
      if (_lastResizeSent.cols === 0 && _lastResizeSent.rows === 0) {
        _sendResize(cols, rows);
        return;
      }
      // Throttle rapid consecutive resizes to 50ms
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

    // Flush pending resize on drag end
    function _flushResize() {
      if (_pendingResize) { clearTimeout(_pendingResize); _pendingResize = null; }
      if (term) { _sendResize(term.cols, term.rows); }
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
          if (panelTitleEl) panelTitleEl.textContent = msg.key;
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

      if (isPtyBackend()) {
        if (_renderMode === 'dom' && _domOutput) {
          _domWrite(e.data);
          return;
        }
        if (term) {
          // Respect xterm.js flow control
          if (flowPaused) { return; }
          term.write(e.data);
        }
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
    if (panelTitleEl) panelTitleEl.textContent = 'Agent';
    if (ws) { ws.onclose = null; ws.close(); ws = null; }
    if (_renderMode === 'dom' && _domOutput) {
      _addDomLine('\x1b[2m终端已断开。\x1b[0m');
    }
    if (_renderMode === 'xterm' && term) {
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
      if (fitAddon && !panel.classList.contains('hidden')) {
        try { fitAddon.fit(); } catch (_) {}
      }
    }, 200);
  });

  // --- Close button ---
  if (closeBtn) {
    closeBtn.addEventListener('click', function () { window.Agent.close(); });
  }

  // --- Mode switch button ---
  if (modeBtn) {
    modeBtn.addEventListener('click', function () { _toggleAgentMode(); });
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
