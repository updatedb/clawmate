// ===== Agent Panel — dual-mode: xterm.js (Claude) + markdown chat (OpenClaw) =====
//
// Exposes window.Agent API:
//   Agent.init({ wsUrl, rootId, agentId, backend })  — one-time setup
//   Agent.open(rootId, agentId)             — open panel + connect WebSocket
//   Agent.close()                            — close panel + disconnect
//   Agent.toggle()                           — toggle panel
//   Agent.updateRoot(rootId, agentId)        — update current root

(function () {
  'use strict';

  // --- DOM refs ---
  const panel = document.getElementById('agentPanel');
  const resizeHandle = document.getElementById('agentResizeHandle');
  const xtermContainer = document.getElementById('xtermContainer');
  const chatView = document.getElementById('agentChatView');
  const chatMessages = document.getElementById('agentChatMessages');
  const chatInput = document.getElementById('agentChatInput');
  const chatSendBtn = document.getElementById('agentChatSend');
  const badgeEl = document.getElementById('agentBackendBadge');
  const rootEl = document.getElementById('agentPanelRoot');
  const closeBtn = document.getElementById('btnCloseAgent');
  const toggleBtn = document.getElementById('btnToggleAgent');

  // --- State ---
  let term = null;
  let fitAddon = null;
  let ws = null;
  let wsUrl = '';
  let panelWidth = 0;
  let collapseTimer = null;
  let animatingOut = false; // true during slide-out animation
  let currentRootId = '';
  let currentAgentId = '';
  let backendMode = 'claude';
  let reconnectTimer = null;
  let reconnectAttempts = 0;
  const MAX_RECONNECT_ATTEMPTS = 10;
  let chatBuf = '';     // accumulating assistant text
  let chatBufEl = null; // current assistant bubble being built
  let chatStatusEl = null; // reconnection status element

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
    if (!panelWidth) panelWidth = Math.min(Math.floor(window.innerWidth * 0.45), 680);
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
    panelWidth = Math.max(360, Math.min(680, dragStartWidth + delta));
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
    if (term) return;
    const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
    const bg = isDark ? '#111827' : '#f8fafc';
    const fg = isDark ? '#e2e8f0' : '#1e293b';
    const cursor = '#14b8a6';

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
    }
    if (typeof WebglAddon !== 'undefined') {
      try { term.loadAddon(new WebglAddon.WebglAddon()); } catch (_) {}
    }

    term.open(xtermContainer);

    term.attachCustomKeyEventHandler(function (e) {
      if (e.type === 'keydown') {
        if (e.ctrlKey && !e.altKey && !e.metaKey) {
          if (e.key === 'c' && term.hasSelection()) {
            var sel = term.getSelection();
            if (sel && navigator.clipboard && navigator.clipboard.writeText) {
              navigator.clipboard.writeText(sel).catch(function () {});
            }
            return false;
          }
          if (e.key === 'v') {
            if (navigator.clipboard && navigator.clipboard.readText) {
              navigator.clipboard.readText().then(function (text) {
                if (text && ws && ws.readyState === WebSocket.OPEN) { ws.send(text); }
              }).catch(function () {});
            }
            return false;
          }
        }
      }
      return true;
    });

    if (fitAddon) { setTimeout(function () { try { fitAddon.fit(); } catch (_) {} }, 50); }

    term.onData(function (data) {
      if (ws && ws.readyState === WebSocket.OPEN) { ws.send(data); }
    });
    term.onResize(function (size) {
      if (ws && ws.readyState === WebSocket.OPEN) {
        try { ws.send(JSON.stringify({ type: 'resize', cols: size.cols, rows: size.rows })); } catch (_) {}
      }
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
      '&agentId=' + encodeURIComponent(currentAgentId || '');

    try { ws = new WebSocket(url); } catch (e) { scheduleReconnect(); return; }

    ws.onopen = function () {
      reconnectAttempts = 0;
      if (backendMode === 'claude' && term) {
        term.writeln('\x1b[1;36m✓ 已连接 Agent 终端\x1b[0m');
        term.writeln('');
      }
      if (backendMode === 'openclaw') {
        clearChatStatus();
      }
    };

    ws.onmessage = function (e) {
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
      wsUrl = config.wsUrl || '';
      currentAgentId = config.agentId || '';
      currentRootId = config.rootId || '';
      backendMode = config.backend || 'claude';
      if (badgeEl) badgeEl.textContent = backendMode;

      if (backendMode === 'openclaw') {
        showChatMode();
      } else {
        showXtermMode();
      }
    },

    open: function (rootId, agentId) {
      if (rootId) currentRootId = rootId;
      if (agentId) currentAgentId = agentId;

      animatingOut = false;
      clearTimeout(collapseTimer);
      // Force grid expansion before removing hidden for slide-in
      updateGridColumns(true);
      panel.offsetHeight; // force reflow
      panel.classList.remove('hidden');
      document.body.classList.add('agent-open');
      setTimeout(function () { if (typeof syncSidebarBtn === 'function') syncSidebarBtn(); }, 0);
      if (rootEl) rootEl.textContent = currentRootId || '';

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

      if (fitAddon) {
        setTimeout(function () { try { fitAddon.fit(); } catch (_) {} }, 100);
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
        window.Agent.open(currentRootId, currentAgentId);
        if (toggleBtn) toggleBtn.classList.add('active');
      } else {
        window.Agent.close();
      }
    },

    updateRoot: function (rootId, agentId) {
      if (rootId) currentRootId = rootId;
      if (agentId) currentAgentId = agentId;
      if (rootEl) rootEl.textContent = currentRootId || '';
      if (!panel.classList.contains('hidden') && ws && ws.readyState === WebSocket.OPEN) {
        try { ws.send(JSON.stringify({ type: 'chdir', root: currentRootId, agentId: currentAgentId })); } catch (_) {}
      }
    },

    isOpen: function () {
      return !panel.classList.contains('hidden');
    },

    /** Recompute grid columns (called externally on sidebar toggle) */
    updateGrid: function () { updateGridColumns(); },
  };

})();
