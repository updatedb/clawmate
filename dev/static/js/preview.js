/**
 * ClawMate Preview — 桌面端预览页面脚本。
 * 从 preview.html 内联脚本提取，保持原有 IIFE 结构。
 * 功能：Markdown/Mermaid/KaTeX 渲染、反馈选中提交、字幕编辑、Office/PDF 预览。
 */

(function() {
  'use strict';

  // ============ URL Params ============
  const params = new URLSearchParams(window.location.search);
  const rootId = params.get('root') || '';
  const filePathRaw = params.get('file') || '';
  // Fix double-encoded paths: keep decoding while %XX patterns remain
  var filePath = filePathRaw;
  try {
    while (/%[0-9A-Fa-f]{2}/.test(filePath)) {
      var decoded = decodeURIComponent(filePath);
      if (decoded === filePath) break; // no change, stop
      filePath = decoded;
    }
  } catch(_) { filePath = filePathRaw; }
  const sessionKey = params.get('session') || '';
  let fileName = filePath.split('/').pop() || '未命名';
  const ext = fileName.includes('.') ? fileName.split('.').pop().toLowerCase() : '';
  // isMarkdown defined above
  const AUDIO_EXTS = window.AUDIO_EXTS;
  const VIDEO_EXTS = window.VIDEO_EXTS;
  const PLAIN_TEXT_EXTS = window.PLAIN_TEXT_EXTS;
  const MARKDOWN_EXTS = window.MARKDOWN_EXTS;
  const HTML_EXTS = window.HTML_EXTS;
  const OFFICE_EXTS = window.OFFICE_EXTS;
  const ARCHIVE_EXTS = window.ARCHIVE_EXTS;
  const PDF_EXT = 'pdf';

  // ── Auth session expiry handler ──────────────────────────────
  const _origFetch = window.fetch;
  window.fetch = function(url, options) {
    return _origFetch.apply(this, arguments).then(function(res) {
      if (res.status === 401 || res.status === 302) {
        const redirectTo = '/clawmate/login.html?redirect=' + encodeURIComponent(window.location.pathname + window.location.search);
        window.location.href = redirectTo;
        return Promise.reject(new Error('auth_redirect'));
      }
      return res;
    });
  };

  const isAudioMode = AUDIO_EXTS.includes(ext);
  const isVideoMode = VIDEO_EXTS.includes(ext);
  const isMediaMode = isAudioMode || isVideoMode;
  const isPlainTextMode = PLAIN_TEXT_EXTS.includes(ext);
  const isMarkdownMode = MARKDOWN_EXTS.includes(ext);
  const isHtmlMode = HTML_EXTS.includes(ext);
  const isOfficeMode = OFFICE_EXTS.includes(ext);
  const isPdfMode = ext === PDF_EXT;
  const isOfficePdfMode = isOfficeMode || isPdfMode;
  // Archive: check extension + compound suffixes (.tar.gz etc.)
  var nameLower = fileName.toLowerCase();
  var isArchiveMode = (ext && ARCHIVE_EXTS.includes(ext)) ||
    nameLower.endsWith('.tar.gz') || nameLower.endsWith('.tar.bz2') ||
    nameLower.endsWith('.tar.xz') || nameLower.endsWith('.tgz') ||
    nameLower.endsWith('.tbz2') || nameLower.endsWith('.txz');
  // OnlyOffice mode: view or edit (for iframe src)
  // Non-PDF Office documents default to edit mode; PDF stays in view mode
  const isEditableOffice = OFFICE_EXTS.includes(ext) && ext !== 'pdf';
  let onlyofficeMode = isEditableOffice ? 'edit' : 'view';
  let project = filePath.includes('/') ? filePath.split('/')[0] : (rootId || '');

  // ── Image sort state (server-side sort, client displays in returned order) ──
  var imgNav = { prev: null, next: null, idx: 0, total: 0 };
  var imgNavAll = [];   // full sorted sibling images for thumbnail outline
  var imgWrapEl = null;
  var imgSortKey = 'time';
  var imgSortDir = 'desc';
  var IMAGE_EXTS = ['png','jpg','jpeg','svg','webp','gif','bmp','ico'];
  const isImageMode = IMAGE_EXTS.includes(ext);

  // Update page title
  document.title = `${fileName} — ClawMate`;
  document.getElementById('docTitle').textContent = fileName;

  // Back button
  const parentDir = filePath.split('/').slice(0, -1).join('/');
  const backHref = `/clawmate/?root=${encodeURIComponent(rootId)}&dir=${encodeURIComponent(parentDir)}`;
  const btnBack = document.getElementById('btnBack');
  if (btnBack) btnBack.href = backHref;
  const btnBackMobile = document.getElementById('btnBackMobile');
  if (btnBackMobile) btnBackMobile.href = backHref;

  // Theme change hook — called by topbar.js after theme cycles
  window._onThemeChange = function (resolved) {
    if (resolved === 'dark') {
      document.body.classList.add('dark');
    } else {
      document.body.classList.remove('dark');
    }
    applyPreviewTheme(resolved);
    // Sync xterm terminal theme
    if (window.Agent && window.Agent.syncTheme) window.Agent.syncTheme();
    // Reload ONLYOFFICE iframe with new theme (if active)
    var ooIframe = document.querySelector('iframe[src*="onlyoffice.html"]');
    if (ooIframe) {
      var src = ooIframe.src;
      src = src.replace(/[?&]theme=[^&]*/, '&theme=' + resolved);
      if (src.indexOf('&theme=') === -1) src += '&theme=' + resolved;
      ooIframe.src = src;
    }
  };

  // Initial theme — apply immediately (topbar.js already set data-theme before this script ran)
  var _initResolved = window._topbarResolvedTheme
    ? window._topbarResolvedTheme()
    : (document.documentElement.getAttribute('data-theme') || 'light');
  window._onThemeChange(_initResolved);

  function applyPreviewTheme(resolved) {
    const hlCss = document.getElementById('highlight-theme-css');
    if (resolved === 'dark') {
      hlCss.href = './vendor/github-dark.min.css';
    } else {
      hlCss.href = './vendor/github.min.css';
    }
    // 用 inline style 覆盖 markdown 主题色（CDN CSS 的变量被 @media 包裹，不可靠）
    const varsEl = document.getElementById('clawmate-theme-vars') || (() => {
      const el = document.createElement('style');
      el.id = 'clawmate-theme-vars';
      document.head.appendChild(el);
      return el;
    })();
    // 统一字体栈：优先使用 Noto Sans SC 确保中英文混排时字体一致
    var _mdFontStack = '-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans SC","Noto Sans",Helvetica,Arial,sans-serif,"Apple Color Emoji","Segoe UI Emoji"';
    if (resolved === 'dark') {
      varsEl.textContent = '[data-theme=dark] .markdown-body { color:#f0f6fc; background-color:#0d1117; font-family:' + _mdFontStack + '; } [data-theme=dark] .markdown-body * { color:#f0f6fc; } [data-theme=dark] .markdown-body table tr { background-color:#0d1117; border-top:1px solid #3d444db3; } [data-theme=dark] .markdown-body table td,[data-theme=dark] .markdown-body table th { border:1px solid #3d444d; } [data-theme=dark] .markdown-body code { background-color:#656c7633; color:#e1e4e8; } [data-theme=dark] .markdown-body pre { background-color:#151b23; color:#f0f6fc; } [data-theme=dark] .markdown-body pre code { background:transparent; color:#f0f6fc; } [data-theme=dark] .markdown-body blockquote { color:#9198a1; border-left-color:#3d444d; }';
    } else {
      varsEl.textContent = '[data-theme=light] .markdown-body { color:#1f2328; background-color:#ffffff; font-family:' + _mdFontStack + '; } [data-theme=light] .markdown-body table tr { background-color:#ffffff; border-top:1px solid #d1d9e0b3; } [data-theme=light] .markdown-body table td,[data-theme=light] .markdown-body table th { border:1px solid #d1d9e0; } [data-theme=light] .markdown-body code { background:rgba(175,184,193,0.2); color:#d73a49; } [data-theme=light] .markdown-body pre { background:#f6f8fa; color:#1f2328; } [data-theme=light] .markdown-body pre code { background:transparent; color:#1f2328; } [data-theme=light] .markdown-body blockquote { color:#656d76; border-left-color:#d0d7de; }';
    }
  }  // escHtml / formatSize / copyText / showToast: defined in preview-common.js

  function buildDownloadLink(path) {
    return `/api/clawmate/download?root=${encodeURIComponent(rootId)}&path=${encodeURIComponent(path)}`;
  }

  function buildDeleteUrl(path) {
    return `/api/clawmate/delete?root=${encodeURIComponent(rootId)}&path=${encodeURIComponent(path)}`;
  }

  function removeLoading() {
    const el = document.querySelector('.preview-loading');
    if (el) el.remove();
  }

  // ============ Dynamic vendor loading ============
  function loadScript(src) {
    return new Promise(function(resolve, reject) {
      var s = document.createElement('script');
      s.src = src;
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  var _mermaidLoaded = false, _katexLoaded = false;

  async function ensureMermaid() {
    if (_mermaidLoaded) return;
    if (window.mermaid) { _mermaidLoaded = true; return; }
    await loadScript('./vendor/mermaid-v11.min.js');
    _mermaidLoaded = true;
  }

  async function ensureKatex() {
    if (_katexLoaded) return;
    if (window.renderMathInElement) { _katexLoaded = true; return; }
    // Load CSS first so fonts begin fetching
    var css = document.createElement('link');
    css.rel = 'stylesheet'; css.href = './vendor/katex.min.css';
    document.head.appendChild(css);
    await loadScript('./vendor/katex.min.js');
    await loadScript('./vendor/auto-render.min.js');
    _katexLoaded = true;
  }

  // ============ Markdown Renderer Setup ============
  if (window.hljs) window.hljs.configure({ ignoreUnescapedHTML: true });

  function createMarkdownRenderer(entryRelPath) {
    let mermaidIdx = 0;
    const mermaidStore = [];

    const md = window.markdownit({
      html: true,
      linkify: true,
      typographer: true,
      breaks: true,
    })
      .use(window.markdownitContainer, 'note')
      .use(window.markdownitContainer, 'warning')
      .use(window.markdownitContainer, 'tip')
      .use(window.markdownitEmoji)
      .use(window.markdownitFootnote)
      .use(window.markdownitTaskLists, { enabled: true, label: true, labelAfter: true });

    // Rewrite relative image paths
    md.renderer.rules.image = function(tokens, idx, options, env, slf) {
      const token = tokens[idx];
      let href = token.attrGet('src') || '';
      const title = token.attrGet('title') || '';
      const text = token.content || '';
      if (!/^https?:\/\//i.test(href) && !href.startsWith('/')) {
        const dir = entryRelPath.split('/').slice(0, -1).join('/');
        const fullPath = dir ? dir + '/' + href : href;
        href = `/api/clawmate/preview?root=${encodeURIComponent(rootId)}&path=${encodeURIComponent(fullPath)}`;
      }
      return `<img src="${href}" alt="${escHtml(text)}"${title ? ` title="${escHtml(title)}"` : ''}>`;
    };

    // Rewrite relative markdown links to ClawMate preview URLs
    const defaultLinkOpen = md.renderer.rules.link_open || function(tokens, idx, options, env, slf) {
      return slf.renderToken(tokens, idx, options);
    };
    md.renderer.rules.link_open = function(tokens, idx, options, env, slf) {
      const token = tokens[idx];
      let href = token.attrGet('href') || '';
      if (href && !/^https?:\/\//i.test(href) && !href.startsWith('/') && !href.startsWith('#')) {
        const dir = entryRelPath.split('/').slice(0, -1).join('/');
        const fullPath = dir ? dir + '/' + href : href;
        href = `preview.html?root=${encodeURIComponent(rootId)}&file=${encodeURIComponent(fullPath)}`;
        token.attrSet('href', href);
      }
      return defaultLinkOpen(tokens, idx, options, env, slf);
    };

    // Handle fenced code blocks (mermaid + syntax highlighting)
    md.renderer.rules.fence = function(tokens, idx, options, env, slf) {
      const token = tokens[idx];
      const language = token.info.trim();
      const raw = token.content;
      const className = language ? `language-${language}` : '';

      if (language === 'mermaid') {
        const id = mermaidIdx++;
        mermaidStore[id] = raw;
        return `<div class="mermaid" data-mermaid-id="${id}"></div>`;
      }

      // Let window.hljs.highlightAll() handle syntax highlighting after DOM insertion
      return `<pre><code class="${className}">${escHtml(raw)}</code></pre>`;
    };

    return { md, mermaidStore };
  }

  async function renderMermaid(div, mermaidStore) {
    var blocks = div.querySelectorAll('.mermaid');
    if (!blocks.length) return;
    // DEBUG:  renderMermaid: found ' + blocks.length + ' mermaid block(s), store size=' + mermaidStore.length);

    var scopeClass = 'mermaid-scope-' + Date.now();
    div.classList.add(scopeClass);

    if (!window.mermaid) {
      console.warn('[ClawMate] Mermaid \u5e93\u672a\u52a0\u8f7d');
      for (var i = 0; i < blocks.length; i++) {
        blocks[i].classList.add('mermaid-error');
        blocks[i].textContent = '\u26a0\ufe0f Mermaid \u5e93\u672a\u52a0\u8f7d\uff0c\u8bf7\u5237\u65b0\u9875\u9762\u91cd\u8bd5';
      }
      return;
    }

    try {
      var resolvedTheme = window._topbarResolvedTheme ? window._topbarResolvedTheme() : 'light';
      var mermaidTheme = resolvedTheme === 'dark' ? 'dark' : 'default';

      window.mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        fontFamily: 'ui-monospace, SF Mono, Cascadia Code, Consolas, monospace',
        maxWidth: 800,
        theme: mermaidTheme
      });

      // Restore stored code into each .mermaid block before calling mermaid.run()
      for (var i = 0; i < blocks.length; i++) {
        var b = blocks[i];
        var id = b.getAttribute('data-mermaid-id');
        if (id == null || !mermaidStore[id]) {
          b.classList.add('mermaid-error');
          b.textContent = '\u26a0\ufe0f \u56fe\u8868\u6570\u636e\u4e22\u5931\uff08id=' + (id || 'null') + '\uff09';
          continue;
        }
        b.textContent = mermaidStore[id];
      }

      // DEBUG:  Calling mermaid.run() with scope=' + scopeClass + ', store has ' + mermaidStore.length + ' entries');
      await window.mermaid.run({ querySelector: '.' + scopeClass + ' .mermaid' });
      // DEBUG:  mermaid.run() completed successfully');

      // Setup zoom for each rendered SVG
      await new Promise(r => setTimeout(r, 100));
      for (var i = 0; i < blocks.length; i++) {
        var svg = blocks[i].querySelector('svg');
        if (svg) setupMermaidZoomDesktop(svg);
      }

      // Fix quadrantChart NaN% colors (Mermaid v11 bug)
      for (var i = 0; i < blocks.length; i++) {
        blocks[i].querySelectorAll('[fill*="NaN%"], [stroke*="NaN%"]').forEach(function(el) {
          var fill = el.getAttribute('fill') || '';
          var stroke = el.getAttribute('stroke') || '';
          if (fill.indexOf('NaN%') !== -1) el.setAttribute('fill', fill.replace(/hsl\([^)]*NaN%[^)]*\)/g, resolvedTheme === 'dark' ? '#58a6ff' : '#4f46e5'));
          if (stroke.indexOf('NaN%') !== -1) el.setAttribute('stroke', stroke.replace(/hsl\([^)]*NaN%[^)]*\)/g, resolvedTheme === 'dark' ? '#58a6ff' : '#4f46e5'));
        });
      }
    } catch (err) {
      var errMsg = err && (err.message || err.str || String(err));
      console.error('[ClawMate] Mermaid \u6e32\u67d3\u5931\u8d25:', errMsg, err);
      for (var i = 0; i < blocks.length; i++) {
        blocks[i].classList.add('mermaid-error');
        blocks[i].textContent = '\u26a0\ufe0f Mermaid \u6e32\u67d3\u5931\u8d25 \u2014 ' + errMsg + '\n\n\u2193 \u539f\u6587\u5185\u5bb9\u89c1\u4e0b\u65b9\u6e90\u7801\u6a21\u5f0f';
      }
    } finally {
      div.classList.remove(scopeClass);
    }
  }

  // ── Mermaid resize handles ──
  function setupMermaidResizeHandles(container) {
    var blocks = container.querySelectorAll('.mermaid');
    for (var i = 0; i < blocks.length; i++) {
      (function(block) {
        if (block.querySelector('.mermaid-resize-handle')) return;

        // Wrap existing content in an inner scrollable div so the resize
        // handle (a sibling) never scrolls with the content.
        var inner = document.createElement('div');
        inner.className = 'mermaid-inner';
        while (block.firstChild) {
          inner.appendChild(block.firstChild);
        }
        block.appendChild(inner);

        // Clear outer container constraints — .mermaid-inner handles scrolling now.
        block.style.overflow = 'visible';
        block.style.maxHeight = 'none';

        // Pull zoom controls back to the outer container so they stay
        // visible (fixed at top-right) when the inner content scrolls.
        var zoomControls = inner.querySelector('.mermaid-zoom-controls');
        if (zoomControls) block.appendChild(zoomControls);

        // Create the resize handle — always pinned to the outer bottom edge.
        var handle = document.createElement('div');
        handle.className = 'mermaid-resize-handle';
        handle.style.touchAction = 'none';
        block.appendChild(handle);

        var dragging = false, startY, startHeight, pointerId;

        function onPointerDown(e) {
          if (e.target.closest('.mermaid-zoom-controls')) return;
          dragging = true;
          pointerId = e.pointerId;
          startY = e.clientY;
          startHeight = inner.getBoundingClientRect().height;
          handle.classList.add('dragging');
          handle.setPointerCapture(e.pointerId);
          document.body.style.userSelect = 'none';
          document.body.style.cursor = 'ns-resize';
          e.preventDefault();
          e.stopPropagation();
        }

        function onPointerMove(e) {
          if (!dragging) return;
          var delta = e.clientY - startY;
          var newH = Math.max(100, Math.min(window.innerHeight * 0.9, startHeight + delta));
          inner.style.maxHeight = 'none';
          inner.style.height = newH + 'px';
          inner.style.overflow = 'auto';
        }

        function onPointerUp(e) {
          if (!dragging) return;
          dragging = false;
          handle.classList.remove('dragging');
          handle.releasePointerCapture(pointerId);
          document.body.style.userSelect = '';
          document.body.style.cursor = '';
        }

        handle.addEventListener('pointerdown', onPointerDown);
        handle.addEventListener('pointermove', onPointerMove);
        handle.addEventListener('pointerup', onPointerUp);
        handle.addEventListener('pointercancel', onPointerUp);
      })(blocks[i]);
    }
  }

  // ── Mermaid zoom (desktop: mouse wheel + buttons) ──
  function setupMermaidZoomDesktop(svg) {
    var container = svg.parentElement;
    if (!container || container._mermaidZoom) return;
    container._mermaidZoom = true;
    var scale = 1;
    var originX = 0, originY = 0;
    var isPanning = false, panStartX = 0, panStartY = 0;

    container.style.overflow = 'hidden';
    container.style.position = 'relative';
    container.style.cursor = 'grab';

    // Zoom controls
    var controls = document.createElement('div');
    controls.className = 'mermaid-zoom-controls';
    controls.innerHTML = '<button class="mermaid-zoom-btn" data-zoom="out">−</button><button class="mermaid-zoom-btn" data-zoom="reset">⊙</button><button class="mermaid-zoom-btn" data-zoom="in">+</button><button class="mermaid-zoom-btn mermaid-expand-btn" data-zoom="expand" title="Expand diagram">□</button>';
    container.appendChild(controls);

    function applyZoom() {
      svg.style.transformOrigin = '0 0';
      svg.style.transform = 'translate(' + originX + 'px, ' + originY + 'px) scale(' + scale + ')';
      container.classList.toggle('mermaid-zoomed', scale !== 1);
    }

    // Button zoom
    controls.addEventListener('click', function(e) {
      var btn = e.target.closest('.mermaid-zoom-btn');
      if (!btn) return;
      if (btn.dataset.zoom === 'expand') { openMermaidDialog(svg); return; }
      if (btn.dataset.zoom === 'in') { scale = Math.min(5, scale + 0.1); }
      else if (btn.dataset.zoom === 'out') { scale = Math.max(0.3, scale - 0.1); }
      else { scale = 1; originX = 0; originY = 0; }
      applyZoom();
    });

    // Mouse wheel
    container.addEventListener('wheel', function(e) {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        var delta = e.deltaY > 0 ? -0.2 : 0.2;
        var oldScale = scale;
        scale = Math.max(0.3, Math.min(5, scale + delta));
        var rect = container.getBoundingClientRect();
        var mx = e.clientX - rect.left;
        var my = e.clientY - rect.top;
        originX = mx - (mx - originX) * scale / oldScale;
        originY = my - (my - originY) * scale / oldScale;
        applyZoom();
      }
    }, { passive: false });

    // Pan (drag)
    container.addEventListener('mousedown', function(e) {
      if (e.button !== 0 || e.ctrlKey || e.metaKey) return;
      isPanning = true;
      panStartX = e.clientX - originX;
      panStartY = e.clientY - originY;
      container.style.cursor = 'grabbing';
    });

    document.addEventListener('mousemove', function(e) {
      if (!isPanning) return;
      originX = e.clientX - panStartX;
      originY = e.clientY - panStartY;
      applyZoom();
    });

    document.addEventListener('mouseup', function() {
      if (isPanning) {
        isPanning = false;
        container.style.cursor = 'grab';
      }
    });

    // Double-click to fit
    container.addEventListener('dblclick', function() {
      scale = 1; originX = 0; originY = 0;
      applyZoom();
    });
  }

  function openMermaidDialog(svg) {
    // Remove any existing dialog
    var existing = document.querySelector('.mermaid-expand-overlay');
    if (existing) existing.remove();

    // Overlay
    var overlay = document.createElement('div');
    overlay.className = 'mermaid-expand-overlay';

    // Dialog panel
    var dialog = document.createElement('div');
    dialog.className = 'mermaid-expand-dialog';

    // Header with zoom controls + close button
    var header = document.createElement('div');
    header.className = 'mermaid-expand-header';

    var zoomGroup = document.createElement('div');
    zoomGroup.className = 'mermaid-zoom-controls';
    zoomGroup.style.cssText = 'position:static;display:flex;background:transparent;backdrop-filter:none;padding:0;';
    zoomGroup.innerHTML = '<button class="mermaid-zoom-btn" data-dzoom="out">−</button>' +
      '<button class="mermaid-zoom-btn" data-dzoom="reset">⊙</button>' +
      '<button class="mermaid-zoom-btn" data-dzoom="in">+</button>';
    header.appendChild(zoomGroup);

    var closeBtn = document.createElement('button');
    closeBtn.className = 'mermaid-expand-close';
    closeBtn.setAttribute('aria-label', 'Close');
    closeBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
    header.appendChild(closeBtn);

    // Scrollable body
    var body = document.createElement('div');
    body.className = 'mermaid-expand-body';

    // Deep-clone the SVG and clear any inline zoom transforms
    var clonedSvg = svg.cloneNode(true);
    clonedSvg.style.transform = '';
    clonedSvg.style.transformOrigin = '';
    clonedSvg.style.cursor = 'grab';
    body.appendChild(clonedSvg);

    // Assemble
    dialog.appendChild(header);
    dialog.appendChild(body);
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    // Prevent background scroll
    document.body.style.overflow = 'hidden';

    // Animate in
    requestAnimationFrame(function() {
      overlay.classList.add('active');
    });

    // ── Dialog-internal zoom & pan (centered) ──
    var dScale = 1;
    var dPanX = 0, dPanY = 0;
    var dPanning = false, dPanStartX = 0, dPanStartY = 0;

    function applyDialogZoom() {
      clonedSvg.style.transformOrigin = 'center center';
      clonedSvg.style.transform = 'translate(' + dPanX + 'px, ' + dPanY + 'px) scale(' + dScale + ')';
    }

    zoomGroup.addEventListener('click', function(e) {
      var btn = e.target.closest('.mermaid-zoom-btn');
      if (!btn) return;
      if (btn.dataset.dzoom === 'in') { dScale = Math.min(5, dScale + 0.1); }
      else if (btn.dataset.dzoom === 'out') { dScale = Math.max(0.3, dScale - 0.1); }
      else { dScale = 1; dPanX = 0; dPanY = 0; }
      applyDialogZoom();
    });

    // Mouse wheel — zoom over the SVG, native scroll elsewhere
    body.addEventListener('wheel', function(e) {
      if (!clonedSvg.contains(e.target) && e.target !== clonedSvg) return;
      e.preventDefault();
      var delta = e.deltaY > 0 ? -0.2 : 0.2;
      var oldScale = dScale;
      dScale = Math.max(0.3, Math.min(5, dScale + delta));
      var rect = body.getBoundingClientRect();
      var cx = e.clientX - rect.left - rect.width / 2;
      var cy = e.clientY - rect.top - rect.height / 2;
      var ratio = dScale / oldScale;
      dPanX = cx + (dPanX - cx) * ratio;
      dPanY = cy + (dPanY - cy) * ratio;
      applyDialogZoom();
    }, { passive: false });

    // Pan (drag)
    body.addEventListener('mousedown', function(e) {
      if (e.button !== 0 || e.ctrlKey || e.metaKey) return;
      dPanning = true;
      dPanStartX = e.clientX - dPanX;
      dPanStartY = e.clientY - dPanY;
      body.style.cursor = 'grabbing';
      clonedSvg.style.cursor = 'grabbing';
    });

    document.addEventListener('mousemove', function(e) {
      if (!dPanning) return;
      dPanX = e.clientX - dPanStartX;
      dPanY = e.clientY - dPanStartY;
      applyDialogZoom();
    });

    document.addEventListener('mouseup', function() {
      if (dPanning) {
        dPanning = false;
        body.style.cursor = '';
        clonedSvg.style.cursor = 'grab';
      }
    });

    // Double-click to reset
    body.addEventListener('dblclick', function() {
      dScale = 1; dPanX = 0; dPanY = 0;
      applyDialogZoom();
    });
    // ── End zoom & pan ──

    // Close function
    function closeDialog() {
      overlay.classList.remove('active');
      document.body.style.overflow = '';
      overlay.addEventListener('transitionend', function() {
        if (overlay.parentNode) overlay.remove();
      }, { once: true });
      // Fallback cleanup
      setTimeout(function() {
        if (overlay.parentNode) overlay.remove();
      }, 350);
    }

    // Close via X button
    closeBtn.addEventListener('click', closeDialog);

    // Close via overlay backdrop click
    overlay.addEventListener('click', function(e) {
      if (e.target === overlay) closeDialog();
    });

    // Close via ESC key
    var escHandler = function(e) {
      if (e.key === 'Escape') {
        closeDialog();
        document.removeEventListener('keydown', escHandler);
      }
    };
    document.addEventListener('keydown', escHandler);
  }

  function buildTOC(div) {
    const headings = div.querySelectorAll('h1, h2, h3, h4');
    if (headings.length < 2) {
      // No meaningful TOC — collapse left sidebar
      closeLeftSidebar();
      return;
    }
    // Show sidebar and build TOC (on mobile: keep hidden, user opens via topbar)
    if (window.innerWidth >= 768) {
      openLeftSidebar();
    }
    headings.forEach((h, i) => { if (!h.id) h.id = `heading-${i}`; });

    const list = document.createElement('ul');
    list.className = 'preview-toc-list';

    headings.forEach(h => {
      const level = parseInt(h.tagName[1]);
      const li = document.createElement('li');
      li.className = `preview-toc-item toc-h${level}`;
      const a = document.createElement('a');
      a.href = `#${h.id}`;
      a.textContent = h.textContent;
      a.addEventListener('click', e => {
        e.preventDefault();
        if (window.innerWidth < 768) {
          leftSidebar.classList.add('hidden');
          btnToggleLeft.classList.remove('active');
          updateGridColumns();
        }
        var headingText = h.textContent.trim();
        var lines = rawContent.split('\n');
        // Find the line number of this heading in raw source
        var foundLine = 0;
        for (var li = 0; li < lines.length; li++) {
          if (lines[li].indexOf(headingText) !== -1 || lines[li].replace(/^#+\s*/, '').trim() === headingText) {
            foundLine = li + 1; break;
          }
        }

        var ta = document.getElementById('plainTextEditor');
        var srcPre = document.getElementById('sourceRawPre');

        if (ta && isPlainTextEditMode) {
          // Edit textarea mode
          if (foundLine) {
            var lh = parseFloat(getComputedStyle(ta).lineHeight) || 22;
            ta.scrollTop = Math.max(0, (foundLine - 3) * lh);
            var pos = 0;
            for (var i = 0; i < Math.min(foundLine - 1, lines.length); i++) pos += lines[i].length + 1;
            ta.setSelectionRange(pos, pos);
            ta.focus();
          }
        } else if (isRawMode && (isMarkdownMode || isHtmlMode)) {
          // Source view mode: scroll to the target row
          if (foundLine) {
            var wrapper2 = document.querySelector('.code-with-lines');
            var container = document.getElementById('contentBody');
            if (wrapper2 && container) {
              var rows2 = wrapper2.querySelectorAll('.code-row');
              var targetRow2 = rows2[foundLine - 1];
              if (targetRow2) {
                var rowTop2 = targetRow2.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop;
                container.scrollTo({ top: Math.max(0, rowTop2 - 60), behavior: 'smooth' });
                // Try to select the heading text within the target row
                var textEl = targetRow2.querySelector('.code-row-text');
                if (textEl && document.createRange) {
                  try {
                    var walker2 = document.createTreeWalker(textEl, NodeFilter.SHOW_TEXT);
                    while (node = walker2.nextNode()) {
                      var ni2 = node.textContent.indexOf(headingText);
                      if (ni2 >= 0) {
                        var range2 = document.createRange();
                        range2.setStart(node, ni2);
                        range2.setEnd(node, ni2 + headingText.length);
                        window.getSelection().removeAllRanges();
                        window.getSelection().addRange(range2);
                        break;
                      }
                    }
                  } catch(_) {}
                }
              }
            }
          }
        } else {
          // Rendered view mode: scroll to heading DOM element
          var container = document.getElementById('contentBody');
          var top = h.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop - 30;
          container.scrollTo({ top: top, behavior: 'smooth' });
        }
      });
      li.appendChild(a);
      list.appendChild(li);
    });

    const tocBody = document.getElementById('tocBody');
    tocBody.innerHTML = '';
    tocBody.appendChild(list);

    // IntersectionObserver for active TOC highlight
    if (typeof IntersectionObserver !== 'undefined') {
      const links = list.querySelectorAll('a');
      let activeLink = null;
      const observer = new IntersectionObserver(entries => {
        const visible = entries.filter(e => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible.length > 0) {
          const link = list.querySelector(`a[href="#${visible[0].target.id}"]`);
          if (link && link !== activeLink) {
            if (activeLink) activeLink.classList.remove('toc-active');
            link.classList.add('toc-active');
            activeLink = link;
          }
        }
      }, { root: null, rootMargin: '-10% 0px -80% 0px', threshold: 0 });
      headings.forEach(h => observer.observe(h));
    }
  }

  function addCopyButtons(div) {
    div.querySelectorAll('pre').forEach(pre => {
      if (pre.querySelector('.code-copy-btn')) return;
      const btn = document.createElement('button');
      btn.className = 'code-copy-btn';
      btn.textContent = '复制';
      btn.addEventListener('click', async () => {
        const code = pre.querySelector('code');
        const text = code ? code.textContent : pre.textContent;
        await copyText(text, '代码已复制');
        btn.textContent = '已复制';
        btn.classList.add('copied');
        setTimeout(() => { btn.textContent = '复制'; btn.classList.remove('copied'); }, 1500);
      });
      pre.style.position = 'relative';
      pre.appendChild(btn);
    });
  }

  function openLinksInNewTab(div) {
    div.querySelectorAll('a').forEach(a => {
      var href = a.getAttribute('href') || '';
      // Internal ClawMate links: open in same tab
      if (href.indexOf('preview.html?root=') !== -1 || href.startsWith('#')) {
        a.setAttribute('target', '_self');
        return;
      }
      a.setAttribute('target', '_blank');
      a.setAttribute('rel', 'noopener noreferrer');
    });
  }

  // ============ Code Outline ============
  let codeOutlineItems = [];

  function parseCodeOutline(content, ext) {
    var lines = content.split('\n');
    var items = [];
    var patterns = {
      py: [
        [/^\s*def\s+(\w+)\s*\(/, function(m) { return 'def ' + m[1] + '(...)'; }],
        [/^\s*class\s+(\w+)/, function(m) { return 'class ' + m[1]; }],
        [/^\s*async\s+def\s+(\w+)\s*\(/, function(m) { return 'async def ' + m[1] + '(...)'; }],
      ],
      js: [
        [/^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)/, function(m) { return 'function ' + m[1] + '()'; }],
        [/^\s*(?:export\s+)?class\s+(\w+)/, function(m) { return 'class ' + m[1]; }],
        [/^\s*(?:static\s+)?(?:async\s+)?(\w+)\s*\([^)]*\)\s*\{/, function(m) { return m[1] + '()'; }, true],
        [/^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(/, function(m) { return 'const ' + m[1] + ' = (...) =>'; }],
        [/^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function/, function(m) { return 'const ' + m[1] + ' = function'; }],
      ],
      ts: [
        [/^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)/, function(m) { return 'function ' + m[1] + '()'; }],
        [/^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)/, function(m) { return 'class ' + m[1]; }],
        [/^\s*(?:export\s+)?interface\s+(\w+)/, function(m) { return 'interface ' + m[1]; }],
        [/^\s*(?:async\s+)?(\w+)\s*\([^)]*\)\s*(?::\s*\w+)?\s*\{/, function(m) { return m[1] + '()'; }, true],
        [/^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*:\s*(?:.*=>|[\w<>]+)\s*=/, function(m) { return 'const ' + m[1]; }],
      ],
      tsx: [
        [/^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)/, function(m) { return 'function ' + m[1] + '()'; }],
        [/^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)/, function(m) { return 'class ' + m[1]; }],
        [/^\s*(?:export\s+)?interface\s+(\w+)/, function(m) { return 'interface ' + m[1]; }],
        [/^\s*(?:async\s+)?(\w+)\s*\([^)]*\)\s*(?::\s*\w+)?\s*\{/, function(m) { return m[1] + '()'; }, true],
      ],
      go: [
        [/^\s*func\s+\((\w+)\s+(\*?\w+)\)\s+(\w+)\s*\(/, function(m) { return 'func (' + m[1] + ' ' + m[2] + ') ' + m[3] + '(...)'; }],
        [/^\s*func\s+(\w+)\s*\(/, function(m) { return 'func ' + m[1] + '(...)'; }],
        [/^\s*type\s+(\w+)\s+(?:struct|interface)/, function(m) { return 'type ' + m[1]; }],
      ],
      java: [
        [/^\s*(?:public|private|protected)?\s*(?:static|final|abstract)?\s*(?:class|interface)\s+(\w+)/, function(m) { return m[0].trim().split(/\s+/)[0] + ' ' + m[1]; }],
        [/^\s*(?:public|private|protected)?\s*(?:static|final|abstract|\s)+[\w<>\[\],\s]+\s+(\w+)\s*\(/, function(m) { return m[1] + '()'; }],
      ],
      rs: [
        [/^\s*(?:pub\s+)?fn\s+(\w+)/, function(m) { return 'fn ' + m[1] + '()'; }],
        [/^\s*(?:pub\s+)?struct\s+(\w+)/, function(m) { return 'struct ' + m[1]; }],
        [/^\s*(?:pub\s+)?trait\s+(\w+)/, function(m) { return 'trait ' + m[1]; }],
        [/^\s*(?:pub\s+)?impl\s+(\w+)/, function(m) { return 'impl ' + m[1]; }],
        [/^\s*(?:pub\s+)?enum\s+(\w+)/, function(m) { return 'enum ' + m[1]; }],
      ],
      c: [
        [/^\s*(?:static\s+)?(?:inline\s+)?(?:\w+[\s*]+)+(\w+)\s*\([^)]*\)\s*\{/, function(m) { return m[1] + '()'; }],
      ],
      cpp: [
        [/^\s*(?:static\s+)?(?:inline\s+)?(?:virtual\s+)?(?:\w+(?:::)?)+[\s*&]+(\w+)\s*\([^)]*\)\s*(?:const\s*)?\{/, function(m) { return m[1] + '()'; }],
        [/^\s*(?:template\s*<[^>]*>\s*)?class\s+(\w+)/, function(m) { return 'class ' + m[1]; }],
      ],
      h: [
        [/^\s*(?:static\s+)?(?:inline\s+)?(?:\w+[\s*]+)+(\w+)\s*\([^)]*\)\s*(?:const\s*)?;/, function(m) { return m[1] + '()'; }],
        [/^\s*(?:template\s*<[^>]*>\s*)?class\s+(\w+)/, function(m) { return 'class ' + m[1]; }],
      ],
      sh: [
        [/^\s*(\w+)\s*\(\)\s*\{/, function(m) { return m[1] + '()'; }],
        [/^\s*function\s+(\w+)/, function(m) { return 'function ' + m[1] + '()'; }],
      ],
      bash: [
        [/^\s*(\w+)\s*\(\)\s*\{/, function(m) { return m[1] + '()'; }],
        [/^\s*function\s+(\w+)/, function(m) { return 'function ' + m[1] + '()'; }],
      ],
    };
    var langPatterns = patterns[ext] || [];
    var JS_KEYS = [
      'if','else','for','while','switch','case','break','continue','return',
      'throw','try','catch','finally','do','with','new','delete','typeof',
      'instanceof','void','in','of','await','debugger','export','import',
      'yield','super','this','async','true','false','null','undefined',
      'let','var','const','function','class','extends','implements','static',
      'get','set','enum','interface','type','namespace','module','require',
      'from','as','default','public','private','protected','readonly'
    ];
    var JS_KEYWORDS = {};
    for (var k = 0; k < JS_KEYS.length; k++) JS_KEYWORDS[JS_KEYS[k]] = true;
    if (!langPatterns.length) return items;
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      for (var j = 0; j < langPatterns.length; j++) {
        var entry = langPatterns[j];
        var regex = entry[0];
        var formatter = entry[1];
        var skipKws = entry[2];
        var m = line.match(regex);
        if (m) {
          if (skipKws && JS_KEYWORDS[m[1]]) break;
          items.push({ text: formatter(m).trim(), line: i + 1 });
          break;
        }
      }
    }
    return items;
  }

  function scrollToCodeLine(lineNum) {
    // Check textarea (edit mode) first
    var ta = document.getElementById('plainTextEditor');
    if (ta) {
      var lineHeight = parseFloat(getComputedStyle(ta).lineHeight) || 22;
      ta.scrollTop = Math.max(0, (lineNum - 4) * lineHeight);
      var lines = ta.value.split('\n');
      var pos = 0;
      for (var i = 0; i < Math.min(lineNum - 1, lines.length); i++) pos += lines[i].length + 1;
      ta.setSelectionRange(pos, pos + (lines[lineNum - 1] || '').length);
      ta.focus();
      setTimeout(function() { ta.setSelectionRange(pos, pos); }, 1500);
      return;
    }

    var srcPre = document.getElementById('sourceRawPre');
    var wrapper = document.querySelector('.code-with-lines');
    var wasHidden = false;

    if (srcPre && wrapper && window.getComputedStyle(wrapper).display === 'none') {
      // Rendered mode for markdown: scroll rendered content, don't switch views
      if (!isRawMode && document.getElementById('markdownRenderedDiv')) {
        _scrollRenderedMarkdownToLine(lineNum);
        return;
      }
      // Source view is hidden but user is in source mode — show it
      var mdDiv = document.getElementById('markdownRenderedDiv');
      var htmlIframe = document.getElementById('htmlIframe');
      if (mdDiv) mdDiv.style.display = 'none';
      if (htmlIframe) htmlIframe.style.display = 'none';
      var editBtn = document.getElementById('btnSourceEdit');
      var srcToggle = document.getElementById('btnSrcToggle');
      if (editBtn) editBtn.style.display = '';
      if (srcToggle) { srcToggle.textContent = '📝 渲染'; srcToggle.classList.add('active'); }
      wrapper.style.display = '';
      wasHidden = true;
    }

    var ct = document.getElementById('contentBody');
    if (!ct || !wrapper) return;

    var rows = wrapper.querySelectorAll('.code-row');
    var targetRow = rows[lineNum - 1];
    if (!targetRow) return;

    // Scroll to the target row
    var rowTop = targetRow.getBoundingClientRect().top - ct.getBoundingClientRect().top + ct.scrollTop;
    var rowHeight = targetRow.offsetHeight;
    ct.scrollTop = Math.max(0, rowTop - 4 * rowHeight);

    // Flash highlight bar
    var flash = document.createElement('div');
    flash.className = 'code-line-flash';
    flash.style.top = targetRow.offsetTop + 'px';
    flash.style.height = rowHeight + 'px';
    flash.style.left = '0';
    flash.style.right = '0';
    wrapper.appendChild(flash);
    setTimeout(function() { if (flash.parentNode) flash.remove(); }, 1600);
  }

  // Scroll rendered markdown to the section containing line N
  function _scrollRenderedMarkdownToLine(lineNum) {
    var srcPre = document.getElementById('sourceRawPre');
    var mdDiv = document.getElementById('markdownRenderedDiv');
    if (!srcPre || !mdDiv) return;

    var sourceText = srcPre.textContent || '';
    var lines = sourceText.split('\n');
    var totalLines = lines.length;

    // Walk backwards from lineNum-1 to find the nearest heading
    var headingText = null;
    for (var i = Math.min(lineNum - 1, totalLines - 1); i >= 0; i--) {
      var m = lines[i].match(/^#{1,4}\s+(.+)/);
      if (m) { headingText = m[1].trim(); break; }
    }

    if (headingText) {
      // Generate heading ID the same way markdown-it does:
      // lowercase, replace spaces with -, strip non-word chars, collapse dashes
      var headingId = headingText
        .toLowerCase()
        .replace(/\s+/g, '-')
        .replace(/[^\w一-鿿㐀-䶿-]/g, '')
        .replace(/-+/g, '-')
        .replace(/^-|-$/g, '');

      // Try to find the heading by ID first, then by text content
      var target = document.getElementById(headingId);
      if (!target) {
        // Fallback: search headings by text content
        var headings = mdDiv.querySelectorAll('h1, h2, h3, h4');
        for (var h = 0; h < headings.length; h++) {
          if (headings[h].textContent.trim() === headingText) {
            target = headings[h];
            break;
          }
        }
      }

      if (target) {
        var ct = document.getElementById('contentBody');
        if (ct) {
          var targetTop = target.getBoundingClientRect().top - ct.getBoundingClientRect().top + ct.scrollTop;
          ct.scrollTo({ top: Math.max(0, targetTop - 20), behavior: 'smooth' });
        }
        // Brief highlight on the heading
        var origBg = target.style.transition;
        target.style.transition = 'background-color 0.3s';
        target.style.backgroundColor = 'var(--line-flash-bg, rgba(255,213,79,0.35))';
        setTimeout(function() {
          target.style.backgroundColor = '';
          target.style.transition = origBg;
        }, 1500);
        return;
      }
    }

    // Fallback: scroll to proportional position
    var ct = document.getElementById('contentBody');
    if (ct) {
      var ratio = Math.min(1, Math.max(0, lineNum / Math.max(1, totalLines)));
      var scrollTarget = ratio * mdDiv.scrollHeight;
      ct.scrollTo({ top: Math.max(0, scrollTarget - 60), behavior: 'smooth' });
    }
  }

  function renderCodeOutline(items) {
    var tocBody = document.getElementById('tocBody');
    // Only update content; do NOT change sidebar visibility
    // (sidebar visibility is controlled by the outline toggle button)
    if (items.length < 2) {
      tocBody.innerHTML = '<div class="preview-toc-empty">无可索引的函数或类定义</div>';
      return false;
    }
    var list = document.createElement('ul');
    list.className = 'preview-toc-list';
    items.forEach(function(item) {
      var li = document.createElement('li');
      li.className = 'preview-toc-item toc-code';
      var a = document.createElement('a');
      a.href = '#';
      a.textContent = item.text;
      a.addEventListener('click', function(e) {
        e.preventDefault();
        if (window.innerWidth < 768) {
          leftSidebar.classList.add('hidden');
          btnToggleLeft.classList.remove('active');
          updateGridColumns();
        }
        scrollToCodeLine(item.line);
      });
      li.appendChild(a);
      list.appendChild(li);
    });
    tocBody.innerHTML = '';
    tocBody.appendChild(list);
    return true;
  }

  // ============ PDF Outline (via pdf.js getOutline API) ============

  /** Fetch PDF outline via pdf.js, render in left sidebar.
   *  Falls back to page-number list when no outline exists. */
  async function fetchPdfOutline(rawUrl) {
    var tocBody = document.getElementById('tocBody');
    if (typeof pdfjsLib === 'undefined') {
      tocBody.innerHTML = '<div class="preview-toc-empty">PDF.js 未加载</div>';
      return;
    }
    try {
      pdfjsLib.GlobalWorkerOptions.workerSrc = '/clawmate/pdfjs/pdf.worker.min.js';
      var pdf = await pdfjsLib.getDocument(rawUrl).promise;
      var outline = await pdf.getOutline();
      if (!outline || outline.length === 0) {
        // Fallback: show page number list
        renderPdfPageList(pdf.numPages);
        return;
      }
      renderPdfOutline(outline, pdf);
    } catch (e) {
      console.warn('[pdf-outline] Failed to fetch outline:', e);
      // Fallback: try to at least show page list if we got the PDF object
      tocBody.innerHTML = '<div class="preview-toc-empty">无法读取 PDF 大纲</div>';
    }
  }

  /** Render a page-number list as TOC fallback when PDF has no outline */
  function renderPdfPageList(numPages) {
    var tocBody = document.getElementById('tocBody');
    var list = document.createElement('ul');
    list.className = 'preview-toc-list';
    for (var i = 1; i <= numPages; i++) {
      var li = document.createElement('li');
      li.className = 'preview-toc-item toc-h1';
      var a = document.createElement('a');
      a.href = '#';
      a.textContent = '第 ' + i + ' 页';
      a.style.paddingLeft = '16px';
      (function(p) {
        a.addEventListener('click', function(e) {
          e.preventDefault();
          if (window.innerWidth < 768) {
            leftSidebar.classList.add('hidden');
            btnToggleLeft.classList.remove('active');
            updateGridColumns();
          }
          scrollPdfToPage(p);
        });
      })(i);
      li.appendChild(a);
      list.appendChild(li);
    }
    tocBody.innerHTML = '';
    tocBody.appendChild(list);
    // Show left sidebar on desktop
    if (window.innerWidth >= 768) {
      openLeftSidebar();
    }
  }

  /** Render hierarchical PDF outline into #tocBody */
  function renderPdfOutline(outline, pdf) {
    var tocBody = document.getElementById('tocBody');
    var list = document.createElement('ul');
    list.className = 'preview-toc-list';

    function addItems(items, parentList, depth) {
      items.forEach(function(item) {
        var li = document.createElement('li');
        li.className = 'preview-toc-item';
        if (depth === 0) li.classList.add('toc-h1');

        var a = document.createElement('a');
        a.href = '#';
        a.textContent = item.title || '(无标题)';
        a.title = item.title || '';
        // Indent: h1=16px, h2=28px, h3=40px, h4=52px per CSS
        var pad = 16 + depth * 12;
        a.style.paddingLeft = pad + 'px';
        if (depth >= 3) { a.style.fontSize = '12px'; a.style.color = 'var(--text-secondary)'; }

        a.addEventListener('click', function(e) {
          e.preventDefault();
          // On mobile, close sidebar after click
          if (window.innerWidth < 768) {
            leftSidebar.classList.add('hidden');
            btnToggleLeft.classList.remove('active');
            updateGridColumns();
          }
          // Resolve destination → page number
          resolveAndScroll(item.dest, pdf);
        });

        li.appendChild(a);
        parentList.appendChild(li);

        if (item.items && item.items.length > 0) {
          addItems(item.items, parentList, depth + 1);
        }
      });
    }

    addItems(outline, list, 0);
    tocBody.innerHTML = '';
    tocBody.appendChild(list);

    // Show left sidebar on desktop when outline is available
    if (window.innerWidth >= 768) {
      openLeftSidebar();
    }
  }

  /** Resolve a PDF destination (named or explicit) to a page index, then scroll */
  async function resolveAndScroll(dest, pdf) {
    try {
      var explicit = await pdf.getDestination(dest);
      if (explicit) {
        // explicit is typically [pageRef, {name:'XYZ', ...}]
        var pageRef = Array.isArray(explicit) ? explicit[0] : explicit;
        var pageIndex;
        if (typeof pageRef === 'number') {
          pageIndex = pageRef;
        } else {
          // pageRef is a Ref object — get the page index
          pageIndex = await pdf.getPageIndex(pageRef);
        }
        scrollPdfToPage((typeof pageIndex === 'number' ? pageIndex : 0) + 1);
        return;
      }
    } catch (_) {}
    // Fallback: try as named destination string
    try {
      if (typeof dest === 'string') {
        var pageIndex = await pdf.getPageIndex(dest);
        scrollPdfToPage(pageIndex + 1);
      }
    } catch (_) {}
  }

  /** Post scroll-to-page message to pdf.js iframe */
  function scrollPdfToPage(pageNum) {
    var iframe = document.getElementById('officeIframe');
    if (iframe && iframe.contentWindow) {
      iframe.contentWindow.postMessage({ type: 'scroll-to-page', page: pageNum }, '*');
    }
  }

  // ============ Source Edit Mode (Markdown / HTML raw) ============
  let isPlainTextEditMode = false;
  let sourceDirty = false;

  // ── Line numbers for code / source views (per-row flex layout) ──
  function renderCodeWithLineNumbers(rawContent, preEl) {
    const wrapper = document.createElement('div');
    wrapper.className = 'code-with-lines';
    const lines = (rawContent || '').split('\n');
    for (var i = 0; i < lines.length; i++) {
      wrapper.appendChild(createCodeRow(i + 1, lines[i]));
    }
    return wrapper;
  }

  function createCodeRow(num, text) {
    var row = document.createElement('div');
    row.className = 'code-row';

    var numSpan = document.createElement('span');
    numSpan.className = 'code-row-num';
    numSpan.textContent = num;

    var textSpan = document.createElement('code');
    textSpan.className = 'code-row-text';
    textSpan.textContent = text;

    row.appendChild(numSpan);
    row.appendChild(textSpan);
    return row;
  }

  function updateCodeLineNumbers(wrapper, rawContent) {
    if (!wrapper) return;
    var lines = (rawContent || '').split('\n');
    var rows = wrapper.querySelectorAll('.code-row');

    // Update existing rows
    for (var i = 0; i < lines.length; i++) {
      if (i < rows.length) {
        rows[i].querySelector('.code-row-num').textContent = i + 1;
        rows[i].querySelector('.code-row-text').textContent = lines[i];
      } else {
        wrapper.appendChild(createCodeRow(i + 1, lines[i]));
      }
    }

    // Remove excess rows
    while (wrapper.querySelectorAll('.code-row').length > lines.length) {
      wrapper.removeChild(wrapper.lastChild);
    }
  }

  // ── Transform hljs-highlighted code blocks to line-numbered rows ──
  // Used on rendered markdown pages (not source view)
  function addLineNumbersToRenderedCodeBlocks(container) {
    if (!container) return;
    var pres = container.querySelectorAll('pre');
    pres.forEach(function(pre) {
      var code = pre.querySelector('code');
      if (!code) return;
      // Skip mermaid blocks
      if (code.className.indexOf('language-mermaid') >= 0) return;
      transformCodeBlockToLineNumbered(pre, code);
    });
  }

  function transformCodeBlockToLineNumbered(pre, code) {
    var lineHtmls = splitHighlightedHtmlByLines(code);
    var wrapper = document.createElement('div');
    wrapper.className = 'code-with-lines code-block-inline';

    for (var i = 0; i < lineHtmls.length; i++) {
      var row = document.createElement('div');
      row.className = 'code-row';

      var num = document.createElement('span');
      num.className = 'code-row-num';
      num.textContent = i + 1;

      var text = document.createElement('code');
      text.className = 'code-row-text';
      text.innerHTML = lineHtmls[i] || '&nbsp;';

      row.appendChild(num);
      row.appendChild(text);
      wrapper.appendChild(row);
    }

    pre.parentNode.replaceChild(wrapper, pre);
  }

  function splitHighlightedHtmlByLines(codeEl) {
    var lines = [];
    var currentLine = [];

    function collect(nodes) {
      for (var i = 0; i < nodes.length; i++) {
        var node = nodes[i];
        if (node.nodeType === Node.TEXT_NODE) {
          var parts = node.textContent.split('\n');
          for (var j = 0; j < parts.length; j++) {
            if (j > 0) {
              lines.push(currentLine.join(''));
              currentLine = [];
            }
            currentLine.push(escHtml(parts[j]));
          }
        } else if (node.nodeType === Node.ELEMENT_NODE) {
          var tag = node.tagName.toLowerCase();
          var cls = node.className ? ' class="' + node.className + '"' : '';
          currentLine.push('<' + tag + cls + '>');
          collect(node.childNodes);
          currentLine.push('</' + tag + '>');
        }
      }
    }

    collect(codeEl.childNodes);
    if (currentLine.length > 0) {
      lines.push(currentLine.join(''));
    }

    return lines;
  }

  function _updateSourcePre(pre, content) {
    // pre is kept as a hidden element; sync its text for backward compat
    if (pre) pre.textContent = content;
    // Update the visual rows
    var wrapper = document.querySelector('.code-with-lines');
    if (wrapper) updateCodeLineNumbers(wrapper, content);
  }

  function enterSourceEditMode() {
    const srcPre = document.getElementById('sourceRawPre');
    if (!srcPre) return;
    isPlainTextEditMode = true;
    sourceDirty = false;
    var wrapper = document.querySelector('.code-with-lines');
    if (wrapper) wrapper.style.display = 'none';
    else if (srcPre) srcPre.style.display = 'none';
    // Also hide the HTML iframe when entering edit mode (HTML mode only)
    if (isHtmlMode) {
      const htmlIframe = document.getElementById('htmlIframe');
      if (htmlIframe) htmlIframe.style.display = 'none';
    }
    const ta = document.createElement('textarea');
    ta.id = 'plainTextEditor';
    ta.className = 'edit-textarea';
    ta.value = rawContent;
    ta.spellcheck = false;
    ta.style.height = Math.max(300, window.innerHeight - 48 - 42 - 40) + 'px';
    // Insert after the wrapper (or banner)
    const banner = document.getElementById('sourceEditBanner');
    // HTML: the wrapper lives inside htmlWrap, but textarea belongs in contentBody
    var insertAfter = (isHtmlMode ? document.getElementById('htmlContentWrap') : null) || wrapper || srcPre;
    if (banner) {
      banner.style.display = '';
      insertAfter.parentNode.insertBefore(ta, banner.nextSibling);
    } else {
      insertAfter.parentNode.insertBefore(ta, insertAfter.nextSibling);
    }
    // Fix: position cursor and scroll at file beginning
    ta.selectionStart = 0;
    ta.selectionEnd = 0;
    ta.scrollTop = 0;
    updateMarkdownDynamicButtons();
    ta.focus();
    ta.addEventListener('input', () => {
      sourceDirty = ta.value !== rawContent;
      updateMarkdownDynamicButtons();
    });
  }

  function exitSourceEditMode() {
    const ta = document.getElementById('plainTextEditor');
    const srcPre = document.getElementById('sourceRawPre');
    const banner = document.getElementById('sourceEditBanner');
    if (ta) ta.remove();
    if (banner) banner.style.display = 'none';
    var wrapper = document.querySelector('.code-with-lines');
    if (wrapper) {
      wrapper.style.display = isRawMode ? '' : 'none';
      updateCodeLineNumbers(wrapper, rawContent);
    } else if (srcPre) {
      srcPre.style.display = isRawMode ? '' : 'none';
    }
    // Restore iframe visibility when exiting HTML edit mode
    if (isHtmlMode) {
      const htmlIframe = document.getElementById('htmlIframe');
      if (htmlIframe) htmlIframe.style.display = isRawMode ? 'none' : '';
    }
    isPlainTextEditMode = false;
    sourceDirty = false;
    updateMarkdownDynamicButtons();
  }

  async function saveSourceEdit() {
    const ta = document.getElementById('plainTextEditor');
    if (!ta) return;
    const newContent = ta.value;
    try {
      const res = await fetch('/api/clawmate/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root: rootId, path: filePath, content: newContent }),
      });
      const data = await res.json();
      if (data.ok) {
        showToast('已保存', 2000);
        rawContent = newContent;
        const srcPre = document.getElementById('sourceRawPre');
        if (srcPre) _updateSourcePre(srcPre, newContent);
        exitSourceEditMode();
        commitAfterSave();
      } else {
        const isSyntaxErr = data.error && data.error.includes('syntax_error');
        showToast('❌ ' + (data.detail || '未知错误'), isSyntaxErr ? 8000 : 3000);
      }
    } catch (e) {
      showToast('保存失败: ' + e.message, 3000);
    }
  }

  // Plain text edit mode (separate, used for non-markdown plain text)
  function enterPlainTextEditMode() {
    isPlainTextEditMode = true;
    sourceDirty = false;
    loadContent();
    // loadContent already calls updatePlainTextDynamicButtons; no need to call again here
    // Fix: position cursor and scroll at file beginning
    setTimeout(() => {
      const ta = document.getElementById('plainTextEditor');
      if (ta) {
        ta.selectionStart = 0;
        ta.selectionEnd = 0;
        ta.scrollTop = 0;
        ta.focus();
      }
    }, 50);
  }

  async function savePlainTextContent() {
    const ta = document.getElementById('plainTextEditor');
    if (!ta) return;
    const newContent = ta.value;
    try {
      const res = await fetch('/api/clawmate/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root: rootId, path: filePath, content: newContent }),
      });
      const data = await res.json();
      if (data.ok) {
        showToast('已保存', 2000);
        rawContent = newContent;
        isPlainTextEditMode = false;
        sourceDirty = false;
        loadContent();
        commitAfterSave();
        // loadContent already calls updatePlainTextDynamicButtons for non-edit mode
      } else {
        const isSyntaxErr = data.error && data.error.includes('syntax_error');
        showToast('❌ ' + (data.detail || '未知错误'), isSyntaxErr ? 8000 : 3000);
      }
    } catch (e) {
      showToast('保存失败: ' + e.message, 3000);
    }
  }

  function updatePlainTextDynamicButtons() {
    var dyn = document.getElementById('bottombarDynamic');
    dyn.innerHTML = '';
    dyn.style.display = 'none'; // hide when empty to avoid double gap

    var pg = document.getElementById('bottombarEditGroup');
    var sep = document.getElementById('bottombarEditSep');
    pg.innerHTML = '';
    pg.style.display = 'none';
    if (sep) sep.style.display = 'flex';
    if (isPlainTextEditMode) {
      pg.style.display = 'flex';
      if (sourceDirty) {
        var saveBtn = document.createElement('button');
        saveBtn.className = 'preview-bottom-btn active';
        saveBtn.id = 'btnPlainTextSave';
        saveBtn.textContent = '💾 保存';
        saveBtn.addEventListener('click', savePlainTextContent);
        pg.appendChild(saveBtn);
      }
      var cancelBtn = document.createElement('button');
      cancelBtn.className = 'preview-bottom-btn active';
      cancelBtn.id = 'btnPlainTextCancel';
      cancelBtn.textContent = '❌ 取消';
      cancelBtn.addEventListener('click', function() {
        isPlainTextEditMode = false;
        sourceDirty = false;
        loadContent();
      });
      pg.appendChild(cancelBtn);
    } else {
      var editBtn = document.createElement('button');
      editBtn.className = 'preview-bottom-btn';
      editBtn.id = 'btnPlainTextEdit';
      editBtn.textContent = '✏️ 编辑';
      editBtn.addEventListener('click', enterPlainTextEditMode);
      pg.appendChild(editBtn);
      pg.style.display = 'flex';
    }
  }

  // ============ Markdown Dynamic Toolbar ============
  function updateMarkdownDynamicButtons() {
    const dyn = document.getElementById('bottombarDynamic');
    dyn.innerHTML = '';
    dyn.style.display = 'flex'; // visible: source/render toggle

    // Source/Render toggle (Markdown/HTML)
    const srcBtn = document.createElement('button');
    srcBtn.className = 'preview-bottom-btn';
    srcBtn.id = 'btnSrcToggle';
    srcBtn.textContent = isRawMode ? '📝 渲染' : '📝 源码';
    srcBtn.addEventListener('click', toggleRawMode);
    dyn.appendChild(srcBtn);

    // Edit/Save (only in raw/source mode for Markdown/HTML) — appended to separate group
    var editGroup = document.getElementById('bottombarEditGroup');
    var editSep = document.getElementById('bottombarEditSep');
    editGroup.innerHTML = '';
    editGroup.style.display = 'none';
    if (editSep) editSep.style.display = 'none';
    if ((isRawMode && isMarkdownMode) || (isRawMode && isHtmlMode)) {
      editGroup.style.display = 'flex';
      if (editSep) editSep.style.display = 'flex';
      if (isPlainTextEditMode) {
        // Save button: only visible when content is dirty
        if (sourceDirty) {
          const saveBtn = document.createElement('button');
          saveBtn.className = 'preview-bottom-btn active';
          saveBtn.id = 'btnSrcSave';
          saveBtn.textContent = '💾 保存';
          saveBtn.addEventListener('click', saveSourceEdit);
          editGroup.appendChild(saveBtn);
        }
        // Edit toggle button (active while editing, click to cancel)
        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'preview-bottom-btn active';
        cancelBtn.id = 'btnSrcEdit';
        cancelBtn.textContent = '❌ 取消';
        cancelBtn.addEventListener('click', exitSourceEditMode);
        editGroup.appendChild(cancelBtn);
      } else {
        // Edit button (not editing): enter edit mode
        const editBtn = document.createElement('button');
        editBtn.className = 'preview-bottom-btn';
        editBtn.id = 'btnSrcEdit';
        editBtn.textContent = '✏️ 编辑';
        editBtn.addEventListener('click', enterSourceEditMode);
        editGroup.appendChild(editBtn);
      }
    }
  }

  // ============ Raw Mode Toggle ============
  let isRawMode = false;
  // isHtmlMode defined above

  // Mode toggle via bottom toolbar (btnSrcToggle) — no longer uses topbar btnRawToggle
  function toggleRawMode() {
    const prevRawMode = isRawMode;
    isRawMode = !isRawMode;

    // If currently in source edit mode, exit it first (before any DOM changes)
    if (isPlainTextEditMode) {
      exitSourceEditMode();
    }
    sourceDirty = false;

    // Plain text / code edit mode: always rebuild (transitions pre ↔ textarea)
    if (isPlainTextMode) {
      loadContent();
      updateMarkdownDynamicButtons();
      return;
    }

    // Markdown / HTML: avoid full rebuild — only toggle visibility of existing elements
    if (isMarkdownMode || isHtmlMode) {
      const mdDiv = document.getElementById('markdownRenderedDiv');
      const srcPre = document.getElementById('sourceRawPre');
      const htmlIframe = document.getElementById('htmlIframe');

      if (isRawMode) {
        // Switch to source view
        if (mdDiv) mdDiv.style.display = 'none';
        if (htmlIframe) htmlIframe.style.display = 'none';
        var wrapper = document.querySelector('.code-with-lines');
        if (wrapper) {
          wrapper.style.display = '';
          // Refresh source content and line numbers
          if (srcPre) {
            if (srcPre.textContent !== rawContent) _updateSourcePre(srcPre, rawContent);
            updateCodeLineNumbers(wrapper, rawContent);
          }
        } else if (srcPre) {
          srcPre.style.display = '';
          if (srcPre.textContent !== rawContent) _updateSourcePre(srcPre, rawContent);
        }
      } else {
        // Switch to rendered view — 重新加载内容确保渲染最新
        loadContent();
      }
      updateMarkdownDynamicButtons();
      return;
    }

    // Fallback: full reload for any other type
    loadContent();
    updateMarkdownDynamicButtons();
  }

  function applyMarkdownModeView() {
    const mdDiv = document.getElementById('markdownRenderedDiv');
    const srcPre = document.getElementById('sourceRawPre');
    const htmlIframe = document.getElementById('htmlIframe');
    if (!mdDiv && !srcPre && !htmlIframe) return;
    var wrapper = document.querySelector('.code-with-lines');
    if (isRawMode) {
      if (mdDiv) mdDiv.style.display = 'none';
      if (htmlIframe) htmlIframe.style.display = 'none';
      if (wrapper) {
        wrapper.style.display = '';
        if (srcPre) {
          _updateSourcePre(srcPre, rawContent);
          updateCodeLineNumbers(wrapper, rawContent);
        }
      } else if (srcPre) {
        srcPre.style.display = '';
        _updateSourcePre(srcPre, rawContent);
      }
    } else {
      if (mdDiv) mdDiv.style.display = '';
      if (htmlIframe) htmlIframe.style.display = '';
      if (wrapper) {
        wrapper.style.display = 'none';
      } else if (srcPre) {
        srcPre.style.display = 'none';
      }
    }
  }

  // Toggle right (feedback) panel
  document.getElementById('btnToggleRight').addEventListener('click', () => {
    if (rightSidebar.classList.contains('hidden')) {
      // Opening sidebar — start auto-refresh and do an immediate load
      _startSidebarRefresh();
      reloadCurrentFeedback();
      openRightSidebar();
    } else {
      // Closing sidebar
      clearHL(); hideTooltip();
      if (_desktopPollTimer) { clearInterval(_desktopPollTimer); _desktopPollTimer = null; }
      _stopSidebarRefresh();
      closeRightSidebar();
    }
  });

  // Close buttons on panel headers
  document.getElementById('btnCloseLeft').addEventListener('click', () => {
    closeLeftSidebar();
  });
  document.getElementById('btnCloseRight').addEventListener('click', () => {
    clearHL();
    hideTooltip();
    if (_desktopPollTimer) { clearInterval(_desktopPollTimer); _desktopPollTimer = null; }
    _stopSidebarRefresh();
    closeRightSidebar();
  });

  // ============ Raw Markdown Content (for accurate line number calculation) ============
  let rawContent = '';
  var _skipFeedbackLoad = false;

  // ============ Image Sort ============
  // ── Client-side image navigation (no full page reload) ──────
  function navigateToImage(newFilePath) {
    if (newFilePath === filePath) return;

    // Update module-level path state
    filePath = newFilePath;
    fileName = newFilePath.split('/').pop() || '未命名';
    project = newFilePath.includes('/') ? newFilePath.split('/')[0] : (rootId || '');

    // Update browser URL without reload
    var newUrl = 'preview.html?root=' + encodeURIComponent(rootId) + '&file=' + encodeURIComponent(newFilePath);
    history.replaceState(null, '', newUrl);

    // Update document title and topbar
    document.title = fileName + ' — ClawMate';
    document.getElementById('docTitle').textContent = fileName;

    // Update the image in-place
    var imgEl = document.getElementById('previewImage');
    if (imgEl) {
      imgEl.src = '/api/clawmate/preview?root=' + encodeURIComponent(rootId) + '&path=' + encodeURIComponent(newFilePath);
      imgEl.style.display = '';
      // Remove any lingering error message from a previous failed image
      var errDiv = imgEl.parentElement ? imgEl.parentElement.querySelector('.preview-error') : null;
      if (errDiv) errDiv.remove();
    }

    // Reset feedback state for the new image
    imagePendingItems = [];
    imageCompletedItems = [];
    _skipFeedbackLoad = false;
    renderImageFeedbackPanel();
    loadImageCompletedFeedback();

    // Re-fetch nav data from API, skip outline rebuild (just update highlight)
    imgNav = { prev: null, next: null, idx: 0, total: 0 };
    fetchImageNav({ skipOutlineRebuild: true });
    // Refresh share status for the new image
    checkShareStatus();
  }

  // Reusable: fetch sibling images from the API with current sort params,
  // filter to images, update imgNav, then re-render prev/next buttons.
  // Pass { skipOutlineRebuild: true } to only update the highlight.
  async function fetchImageNav(opts) {
    opts = opts || {};
    const parentDir = filePath.split('/').slice(0, -1).join('/');
    try {
      const listRes = await fetch(
        `/api/clawmate/list?root=${encodeURIComponent(rootId)}&dir=${encodeURIComponent(parentDir)}&sort_key=${imgSortKey}&sort_dir=${imgSortDir}`
      );
      const listData = await listRes.json();
      const allEntries = listData.entries || [];
      const images = allEntries.filter(e => IMAGE_EXTS.includes((e.name.split('.').pop() || '').toLowerCase()));
      imgNav.total = images.length;
      imgNavAll = images;   // store full sorted list for thumbnail outline
      const curIdx = images.findIndex(e => (e.path || e.relPath || e.name) === filePath);
      if (curIdx >= 0) {
        imgNav.idx = curIdx + 1;
        imgNav.prev = curIdx > 0 ? images[curIdx - 1] : null;
        imgNav.next = curIdx < images.length - 1 ? images[curIdx + 1] : null;
      }
    } catch (_) {}
    if (opts.skipOutlineRebuild) {
      updateImageOutlineHighlight();
    } else {
      buildImageOutline();
    }
    renderImgNav();
  }

  // Render prev/next overlay buttons on the image. Uses module-level imgNav
  // and imgWrapEl so sort-change re-fetches can refresh the buttons in place.
  function renderImgNav() {
    if (!imgWrapEl) return;
    const hasPrev = imgNav.prev;
    const hasNext = imgNav.next;

    // Remove old buttons (supports re-render on sort change)
    const oldPrev = document.getElementById('imgNavPrev');
    if (oldPrev) oldPrev.remove();
    const oldNext = document.getElementById('imgNavNext');
    if (oldNext) oldNext.remove();

    if (hasPrev) {
      const prevBtn = document.createElement('button');
      prevBtn.id = 'imgNavPrev';
      prevBtn.innerHTML = '‹';
      prevBtn.className = 'img-nav-btn';
      prevBtn.style.left = '20px';
      prevBtn.title = '上一张';
      const p = imgNav.prev.path || imgNav.prev.relPath || imgNav.prev.name;
      prevBtn.addEventListener('click', function() { navigateToImage(p); });
      imgWrapEl.appendChild(prevBtn);
    }
    if (hasNext) {
      const nextBtn = document.createElement('button');
      nextBtn.id = 'imgNavNext';
      nextBtn.innerHTML = '›';
      nextBtn.className = 'img-nav-btn';
      nextBtn.style.right = '20px';
      nextBtn.title = '下一张';
      const n = imgNav.next.path || imgNav.next.relPath || imgNav.next.name;
      nextBtn.addEventListener('click', function() { navigateToImage(n); });
      imgWrapEl.appendChild(nextBtn);
    }

    const infoEl = document.getElementById('imgNavInfo');
    if (infoEl && imgNav.total > 0) {
      infoEl.textContent = fileName + ' (' + imgNav.idx + '/' + imgNav.total + ')';
    }
  }

  // Build thumbnail outline in the left sidebar for image mode.
  // Uses imgNavAll (populated by fetchImageNav) sorted by current imgSortKey/imgSortDir.
  function buildImageOutline() {
    const tocBody = document.getElementById('tocBody');
    if (!tocBody) return;

    // Only build outline in image mode
    if (!isImageMode) return;

    // Update sidebar header: show count
    const headerSpan = document.querySelector('.preview-left-header span');
    if (headerSpan) {
      headerSpan.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg> 图片 (' + imgNavAll.length + ')';
    }

    tocBody.innerHTML = '';

    if (imgNavAll.length === 0) {
      tocBody.innerHTML = '<div class="preview-toc-empty">目录中没有图片</div>';
      return;
    }

    const list = document.createElement('ul');
    list.className = 'preview-toc-list';

    imgNavAll.forEach(function(imgEntry) {
      const li = document.createElement('li');
      li.className = 'preview-toc-item';

      const a = document.createElement('a');
      a.href = '#';
      const imgPath = imgEntry.path || imgEntry.relPath || imgEntry.name;
      a.dataset.file = imgPath;
      const isCurrent = imgPath === filePath;
      if (isCurrent) {
        a.classList.add('toc-active');
      }

      // Thumbnail only (no filename)
      a.style.cssText = 'display:flex;align-items:center;justify-content:center;padding:4px 8px;';

      const thumb = document.createElement('img');
      thumb.src = '/api/clawmate/preview?root=' + encodeURIComponent(rootId) + '&path=' + encodeURIComponent(imgPath);
      thumb.style.cssText = 'max-width:100%;max-height:80px;object-fit:contain;border-radius:4px;flex-shrink:0;border:1px solid var(--border-color);';
      thumb.loading = 'lazy';
      thumb.alt = imgEntry.name;
      thumb.title = imgEntry.name;
      a.appendChild(thumb);

      a.addEventListener('click', function(e) {
        e.preventDefault();
        navigateToImage(imgPath);
      });

      li.appendChild(a);
      list.appendChild(li);
    });

    tocBody.appendChild(list);

    // Scroll current image into view
    var activeLink = tocBody.querySelector('.toc-active');
    if (activeLink) {
      setTimeout(function() {
        activeLink.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }, 100);
    }
  }

  // Update the active highlight in the image outline without rebuilding the DOM.
  // Relies on data-file attributes set by buildImageOutline().
  function updateImageOutlineHighlight() {
    const tocBody = document.getElementById('tocBody');
    if (!tocBody) return;

    // Remove existing active highlight
    const oldActive = tocBody.querySelector('.toc-active');
    if (oldActive) oldActive.classList.remove('toc-active');

    // Find and highlight the new current image
    const allLinks = tocBody.querySelectorAll('a[data-file]');
    for (var i = 0; i < allLinks.length; i++) {
      if (allLinks[i].dataset.file === filePath) {
        allLinks[i].classList.add('toc-active');
        setTimeout(function() {
          allLinks[i].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }, 100);
        break;
      }
    }

    // Refresh the sidebar header count
    var headerSpan = document.querySelector('.preview-left-header span');
    if (headerSpan) {
      headerSpan.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg> 图片 (' + imgNavAll.length + ')';
    }
  }

  // Build sort-pill buttons in the bottom toolbar
  function buildImageSortPills() {
    const dyn = document.getElementById('bottombarDynamic');
    if (!dyn) return;
    dyn.innerHTML = '';

    const pills = [
      { key: 'time', desc: '↓ 最新', asc: '↑ 最早' },
      { key: 'name', desc: '↓ Z→A', asc: '↑ A→Z' },
      { key: 'size', desc: '↓ 最大', asc: '↑ 最小' },
    ];

    pills.forEach(function(p) {
      const btn = document.createElement('button');
      btn.className = 'sort-pill';
      btn.dataset.key = p.key;
      if (imgSortKey === p.key) {
        btn.classList.add('active');
        const isDesc = imgSortDir === 'desc';
        btn.textContent = isDesc ? p.desc : p.asc;
        btn.dataset.dir = imgSortDir;
      } else {
        btn.textContent = p.desc;
      }
      btn.addEventListener('click', function() { handleImageSortPill(btn); });
      dyn.appendChild(btn);
    });
  }

  function handleImageSortPill(btn) {
    const key = btn.dataset.key;
    if (imgSortKey === key) {
      imgSortDir = imgSortDir === 'asc' ? 'desc' : 'asc';
    } else {
      imgSortKey = key;
    }
    updateImageSortPills();
    fetchImageNav();
  }

  function updateImageSortPills() {
    const pills = document.querySelectorAll('#bottombarDynamic .sort-pill');
    const labels = {
      time: { desc: '↓ 最新', asc: '↑ 最早' },
      name: { desc: '↓ Z→A', asc: '↑ A→Z' },
      size: { desc: '↓ 最大', asc: '↑ 最小' },
    };
    pills.forEach(function(btn) {
      const key = btn.dataset.key;
      const active = imgSortKey === key;
      btn.classList.toggle('active', active);
      if (active) {
        const isDesc = imgSortDir === 'desc';
        btn.textContent = isDesc ? labels[key].desc : labels[key].asc;
        btn.dataset.dir = imgSortDir;
      }
    });
  }

  // ============ Load & Render Content ============
  async function loadContent() {
    // Clean up Office/PDF mode class from body (will be re-added if needed)
    const contentBody = document.getElementById('contentBody');
    codeOutlineItems = [];

    try {
      // For binary file types, the API returns raw bytes — do NOT call res.json()
      if (isImageMode) {
        contentBody.innerHTML = '';
        contentBody.style.cssText = 'display:flex;align-items:center;justify-content:center;position:relative;padding:12px;';

        // Reset nav state and fetch sorted directory listing for prev/next
        imgNav = { prev: null, next: null, idx: 0, total: 0 };
        fetchImageNav();

        // Image and counter wrapper
        const wrap = document.createElement('div');
        wrap.style.cssText = 'display:flex;flex-direction:column;align-items:center;position:relative;';

        const imgWrap = document.createElement('div');
        imgWrap.style.cssText = 'display:flex;align-items:center;justify-content:center;position:relative;width:100%;';
        imgWrapEl = imgWrap;

        const img = document.createElement('img');
        img.id = 'previewImage';
        img.src = `/api/clawmate/preview?root=${encodeURIComponent(rootId)}&path=${encodeURIComponent(filePath)}`;
        img.style.cssText = 'max-width:100%;max-height:70vh;object-fit:contain;border-radius:8px;';
        img.onerror = function() {
          this.style.display = 'none';
          const errDiv = document.createElement('div');
          errDiv.className = 'preview-error';
          errDiv.textContent = '图片加载失败，文件可能已损坏或格式不支持';
          imgWrap.appendChild(errDiv);
        };
        imgWrap.appendChild(img);
        wrap.appendChild(imgWrap);

        const info = document.createElement('div');
        info.id = 'imgNavInfo';
        info.style.cssText = 'text-align:center;font-size:12px;color:var(--text-muted);padding:4px 0 2px;';
        info.textContent = fileName + ' (1/1)';
        wrap.appendChild(info);

        contentBody.appendChild(wrap);
        removeLoading();
        setupMediaToolbar();
        buildImageSortPills();
        renderImageFeedbackPanel();
        if (!_skipFeedbackLoad) loadCompletedFeedback();

        return;
      }

      if (isVideoMode) {
        setupMediaMode('video');
        removeLoading();
        if (!_skipFeedbackLoad) loadCompletedFeedback();
        return;
      }

      const res = await fetch(`/api/clawmate/preview?root=${encodeURIComponent(rootId)}&path=${encodeURIComponent(filePath)}`);
      if (!res.ok) {
        contentBody.innerHTML = `<div class="preview-error">无法加载文件 (${res.status})</div>`;
        return;
      }

      const ct = res.headers.get('content-type') || '';
      if (ct.startsWith('image/') || ct.startsWith('video/') || ct.startsWith('audio/') || ct.startsWith('application/octet-stream')) {
        // Binary response — render directly without JSON parsing
        if (ct.startsWith('video/') || isVideoMode) {
          setupMediaMode('video');
          removeLoading();
          if (!_skipFeedbackLoad) loadCompletedFeedback();
          return;
        }
        if (ct.startsWith('audio/') || isAudioMode) {
          setupMediaMode('audio');
          removeLoading();
          if (!_skipFeedbackLoad) loadCompletedFeedback();
          return;
        }
        // Fallback for unknown binary
        contentBody.innerHTML = `<div class="preview-error">无法预览此文件类型</div>`;
        removeLoading();
        return;
      }

      const data = await res.json();
      const content = data.content || '';

      // Office/PDF files: supported via ONLYOFFICE/pdf.js, skip fallback
      if (isOfficeMode || isPdfMode) {
        // handled below
      } else if (!data.content && data.download_url) {
      // Unsupported file type: has download_url but no previewable content
        const meta = data.meta || {};
        const ext = (meta.ext || '').toUpperCase();
        const sizeStr = typeof formatSize === 'function' ? formatSize(meta.size || 0) : (meta.size || 0) + ' B';

        contentBody.innerHTML = `
          <div class="preview-unsupported">
            <div class="preview-unsupported-icon">
              <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="9" y1="15" x2="15" y2="15"/>
              </svg>
            </div>
            <div class="preview-unsupported-title">无法预览此文件类型</div>
            <div class="preview-unsupported-meta">
              <span class="preview-unsupported-name">${escHtml(meta.name || fileName)}</span>
              ${ext ? `<span class="preview-unsupported-badge">${escHtml(ext)}</span>` : ''}
              <span class="preview-unsupported-size">${escHtml(sizeStr)}</span>
            </div>
            <div class="preview-unsupported-hint">该文件格式不支持在线预览，请下载后用本地应用打开</div>
            <a class="preview-unsupported-download-btn" href="${escHtml(data.download_url)}" download>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-4px;margin-right:6px;">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
              下载文件
            </a>
          </div>`;
        removeLoading();
        return;
      }

      // ======== Archive: tree view of compressed file contents ========
      if (isArchiveMode && data.archive) {
        renderArchiveView(data.meta, data.archive, data.download_url);
        removeLoading();
        return;
      }

      // Truncation notice
      if (data.truncated) {
        const notice = document.createElement('div');
        notice.className = 'preview-truncated-notice';
        notice.style.cssText = 'background:var(--warning-bg);color:var(--warning-text);padding:8px 16px;font-size:12px;margin-bottom:12px;border-radius:6px;';
        notice.textContent = '⚠️ 文件过大（>5MB），内容已截断';
        contentBody.appendChild(notice);
      }

      // Store raw content for selection feedback and line number calculation
      rawContent = content;
      contentBody.dataset.rawContent = content;
      contentBody.dataset.feedbackRoot = rootId;
      contentBody.dataset.feedbackPath = filePath;
      contentBody.dataset.feedbackProject = project;

      // ======== PDF: lightweight pdf.js viewer (no editing needed) ========
      if (isPdfMode) {
        const wrap = document.createElement('div');
        wrap.className = 'office-iframe-wrap';
        wrap.id = 'officeIframeWrap';

        const iframe = document.createElement('iframe');
        iframe.id = 'officeIframe';
        const rawUrl = `${window.location.origin}/api/clawmate/raw?root=${encodeURIComponent(rootId)}&path=${encodeURIComponent(filePath)}`;
        iframe.src = `/clawmate/pdfjs/viewer.html?file=${encodeURIComponent(rawUrl)}`;
        iframe.style.cssText = 'width:100%;height:100%;border:none;overflow:hidden;';
        wrap.appendChild(iframe);

        contentBody.style.cssText = 'display:flex;flex-direction:column;flex:1;min-height:0;padding:0;';
        contentBody.appendChild(wrap);
        removeLoading();

        setupOfficePdfToolbar();
        if (!_skipFeedbackLoad) loadOfficePdfCompletedFeedback();
        fetchPdfOutline(rawUrl);
        return;
      }

      // ======== Office (ONLYOFFICE) ========
      if (isOfficeMode) {
        const wrap = document.createElement('div');
        wrap.className = 'office-iframe-wrap';
        wrap.id = 'officeIframeWrap';

        const iframe = document.createElement('iframe');
        iframe.id = 'officeIframe';
              var ooTheme = document.documentElement.getAttribute('data-theme') || 'light';
      iframe.src = './onlyoffice.html?root=' + encodeURIComponent(rootId) + '&path=' + encodeURIComponent(filePath) + '&mode=' + encodeURIComponent(onlyofficeMode) + '&theme=' + ooTheme;
        iframe.style.cssText = 'width:100%;height:100%;border:none;overflow:hidden;';
        wrap.appendChild(iframe);

        contentBody.style.cssText = 'display:flex;flex-direction:column;flex:1;min-height:0;padding:0;';
        contentBody.appendChild(wrap);
        removeLoading();

        setupOfficePdfToolbar();
        if (!_skipFeedbackLoad) loadOfficePdfCompletedFeedback();
        return;
      }

      // ======== Markdown: render both views, then apply mode ========
      if (isMarkdownMode && window.markdownit && window.DOMPurify) {
        // Clear any previous content before building
        contentBody.innerHTML = '';
        // Create edit banner (hidden until edit mode is entered)
        const banner = document.createElement('div');
        banner.id = 'sourceEditBanner';
        banner.className = 'edit-mode-banner';
        banner.innerHTML = '<span class="edit-badge">编辑中</span><span>点击左侧大纲可跳转到函数/段落</span><span class="edit-hint">Ctrl+S 保存</span>';
        banner.style.display = 'none';
        contentBody.appendChild(banner);

        // Create source view (per-line rows, hidden by default unless isRawMode)
        const srcPre = document.createElement('pre');
        srcPre.id = 'sourceRawPre';
        srcPre.style.display = 'none';  // hidden content holder for backward compat
        if (window.hljs) {
          try {
            const highlighted = window.hljs.highlight(content, { language: 'markdown', ignoreIllegals: true }).value;
            const code = document.createElement('code');
            code.className = 'language-markdown';
            code.innerHTML = highlighted;
            srcPre.appendChild(code);
            srcPre.className = 'code-highlighted';
          } catch (_) {
            srcPre.textContent = content;
            srcPre.className = 'raw-text';
          }
        } else {
          srcPre.textContent = content;
          srcPre.className = 'raw-text';
        }
        contentBody.appendChild(srcPre);
        const mdSrcWrapper = renderCodeWithLineNumbers(content);
        mdSrcWrapper.style.display = isRawMode ? '' : 'none';
        contentBody.appendChild(mdSrcWrapper);

        // Create rendered markdown div
        const mdDiv = document.createElement('div');
        mdDiv.id = 'markdownRenderedDiv';
        mdDiv.className = 'markdown-body';
        mdDiv.style.display = isRawMode ? 'none' : '';

        let html;
        let mermaidStore = [];
        // Conditional load heavy vendors only when content needs them
        var loadPromises = [];
        if (content.indexOf('```mermaid') !== -1) loadPromises.push(ensureMermaid());
        if (content.indexOf('$') !== -1) loadPromises.push(ensureKatex());
        if (loadPromises.length) await Promise.all(loadPromises);
        try {
          const result = createMarkdownRenderer(filePath);
          const md = result.md;
          mermaidStore = result.mermaidStore;
          html = md.render(content);
          if (window.DOMPurify) {
            html = DOMPurify.sanitize(html, { ADD_ATTR: ['class', 'target', 'data-highlighted'] });
          }
        } catch (e) {
          const errMsg = e && e.message ? (e.message + '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') : String(e || '未知错误');
          // Use mdDiv to show error so source <-> render toggle works both ways
          mdDiv.innerHTML = '<div style="padding:40px;color:var(--danger);font-family:monospace;font-size:14px;line-height:1.6;"><strong>\u26a0\ufe0f Markdown \u6e32\u67d3\u5931\u8d25</strong><br><br>' + errMsg + '<br><br><span style="color:var(--text-secondary)">\u4e0b\u65b9\u5df2\u5207\u6362\u81f3\u6e90\u7801\u6a21\u5f0f\uff0c\u53ef\u70b9\u51fb\u300c\ud83d\udcdd \u6e32\u67d3\u300d\u5207\u56de\u9519\u8bef\u63d0\u793a</span></div>';
          mdDiv.style.display = 'none';
          contentBody.appendChild(mdDiv);
          // Force source view so user can still read the file
          if (mdSrcWrapper) mdSrcWrapper.style.display = '';
          isRawMode = true;
          leftSidebar.classList.add('hidden');
          btnToggleLeft.classList.remove('active');
          updateGridColumns();
          removeLoading();
          updateMarkdownDynamicButtons();
          return;
        }
        // Parse succeeded — render markdown
        mdDiv.innerHTML = html;
        contentBody.appendChild(mdDiv);

        buildTOC(mdDiv);
        openLinksInNewTab(mdDiv);
        addCopyButtons(mdDiv);

        if (window.hljs) {
          try { window.hljs.highlightAll(); } catch (_) {}
        }
        // Add line numbers to code blocks in rendered markdown
        addLineNumbersToRenderedCodeBlocks(mdDiv);

        if (window.renderMathInElement) {
          try {
            renderMathInElement(mdDiv, {
              delimiters: [
                {left: '$$', right: '$$', display: true},
                {left: '$', right: '$', display: false}
              ],
              throwOnError: false,
              errorColor: '#dc2626',
              strict: false,
              ignoredClasses: ['mermaid', 'mermaid-error', 'pre', 'code']
            });
          } catch (_) {}
        }

        // DEBUG:  About to call renderMermaid, mermaidStore has ' + mermaidStore.length + ' entries');
        try { await renderMermaid(mdDiv, mermaidStore); } catch (e) { console.error('[ClawMate] renderMermaid threw:', e); }
        setupMermaidResizeHandles(mdDiv);
        removeLoading();
        updateMarkdownDynamicButtons();
        if (!_skipFeedbackLoad) loadCompletedFeedback();
        _handleLineScroll();
        return;
      }

      // ======== HTML: render via iframe + source view with hljs ========
      if (isHtmlMode) {
        contentBody.innerHTML = '';

        // Edit banner (hidden until edit mode is entered)
        const banner = document.createElement('div');
        banner.id = 'sourceEditBanner';
        banner.className = 'edit-mode-banner';
        banner.innerHTML = '<span class="edit-badge">编辑中</span><span>点击左侧大纲可跳转到函数/段落</span><span class="edit-hint">Ctrl+S 保存</span>';
        banner.style.display = 'none';
        contentBody.appendChild(banner);

        // Make contentBody a flex column so htmlWrap fills remaining space
        contentBody.style.cssText = 'display:flex;flex-direction:column;flex:1;min-height:0;overflow:hidden;padding:0;';

        // Wrapper for iframe + source pre (allows coordinated show/hide)
        const htmlWrap = document.createElement('div');
        htmlWrap.id = 'htmlContentWrap';
        htmlWrap.style.cssText = 'display:flex;flex-direction:column;flex:1;overflow:hidden;';
        contentBody.appendChild(htmlWrap);

        // iframe for rendered HTML view
        const htmlIframe = document.createElement('iframe');
        htmlIframe.id = 'htmlIframe';
        htmlIframe.style.cssText = 'flex:1;border:none;overflow:auto;background:#fff;';
        // Use raw HTML content directly (files come from white-listed dirs)
        // DOMPurify would strip scripts/styles needed by complex HTML pages
        htmlIframe.srcdoc = content;
        htmlIframe.style.display = isRawMode ? 'none' : '';
        htmlWrap.appendChild(htmlIframe);

        // Source view (per-line rows, hidden by default unless isRawMode)
        const srcPre = document.createElement('pre');
        srcPre.id = 'sourceRawPre';
        srcPre.style.display = 'none';  // hidden content holder
        if (window.hljs) {
          try {
            const highlighted = window.hljs.highlight(content, { language: 'html', ignoreIllegals: true }).value;
            const code = document.createElement('code');
            code.className = 'language-html';
            code.innerHTML = highlighted;
            srcPre.appendChild(code);
          } catch (_) {
            srcPre.textContent = content;
          }
        } else {
          srcPre.textContent = content;
        }
        htmlWrap.appendChild(srcPre);
        var htmlSrcWrapper = renderCodeWithLineNumbers(content);
        htmlSrcWrapper.style.display = isRawMode ? '' : 'none';
        htmlSrcWrapper.style.flex = '1';
        htmlSrcWrapper.style.borderRadius = '0';
        htmlWrap.appendChild(htmlSrcWrapper);

        removeLoading();
        updateMarkdownDynamicButtons();
        if (!_skipFeedbackLoad) loadCompletedFeedback();
        _handleLineScroll();
        return;
      }

      // Plain text / code with highlight + optional edit mode
        // Parse code outline once for both edit and display modes
        codeOutlineItems = parseCodeOutline(rawContent, ext);
        contentBody.innerHTML = '';

        if (isPlainTextEditMode) {
          // Edit mode: show textarea
          const banner = document.createElement('div');
          banner.className = 'edit-mode-banner';
          banner.innerHTML = '<span class="edit-badge">编辑中</span><span>点击左侧大纲可跳转到函数/段落</span><span class="edit-hint">Ctrl+S 保存</span>';
          contentBody.appendChild(banner);

          const ta = document.createElement('textarea');
          ta.className = 'edit-textarea';
          ta.id = 'plainTextEditor';
          ta.value = rawContent;
          ta.spellcheck = false;
          // Fill available height: viewport - topbar - banner - bottombar
          var availH = window.innerHeight - 48 - 42 - 40;
          ta.style.height = Math.max(300, availH) + 'px';
          ta.addEventListener('input', () => {
            sourceDirty = ta.value !== rawContent;
            updatePlainTextDynamicButtons();
          });
          contentBody.appendChild(ta);
          removeLoading();
          // Render outline sidebar for code (edit mode: populate content, don't change visibility)
          if (codeOutlineItems.length >= 2) {
            renderCodeOutline(codeOutlineItems);
          }
          updatePlainTextDynamicButtons();
        } else {
          // Display mode: per-line rows with line numbers
          contentBody.appendChild(renderCodeWithLineNumbers(rawContent));
          removeLoading();
          // Render outline sidebar for code (display mode: auto-open on desktop only)
          if (codeOutlineItems.length >= 2) {
            renderCodeOutline(codeOutlineItems);
            if (window.innerWidth >= 768) {
              openLeftSidebar();
            }
          }
          updatePlainTextDynamicButtons();
        }

      // Load completed feedback items from API
      if (!_skipFeedbackLoad) loadCompletedFeedback();

      // Handle ?line= / #LN scroll after initial load
      _handleLineScroll();

    } catch (e) {
      const loadingEl3 = document.querySelector('.preview-loading');
      if (loadingEl3) loadingEl3.remove();
      contentBody.innerHTML = `<div class="preview-error">加载失败: ${escHtml(e.message)}</div>`;
    }
  }

  // ============ Sidebar Toggle (Grid Adaptive) ============
  const leftSidebar = document.getElementById('leftSidebar');
  const rightSidebar = document.getElementById('rightSidebar');
  const agentPanel = document.getElementById('previewAgentPanel');
  const threeCol = document.querySelector('.preview-three-col');

  // CSS .preview-right.hidden / .preview-agent-panel.hidden include display:none
  // but the CSSOM drops it. Explicitly set display:none on initially-hidden panels.
  if (rightSidebar.classList.contains('hidden')) { rightSidebar.style.display = 'none'; console.log('[init] rightSidebar display:none'); }
  if (agentPanel.classList.contains('hidden')) { agentPanel.style.display = 'none'; console.log('[init] agentPanel display:none'); }

  // Topbar outline toggle button (must be after sidebar declarations)
  const btnToggleLeft = document.getElementById('btnToggleLeft');
  btnToggleLeft.addEventListener('click', () => {
    if (leftSidebar.classList.contains('hidden')) {
      openLeftSidebar();
    } else {
      closeLeftSidebar();
    }
    if (isMarkdownMode) updateMarkdownDynamicButtons();
    if (isPlainTextMode && codeOutlineItems.length >= 2) updatePlainTextDynamicButtons();
  });
  // Initialize active state based on current sidebar visibility
  btnToggleLeft.classList.toggle('active', !leftSidebar.classList.contains('hidden'));

  // --- Right panel resize ---
  const resizeHandle = document.getElementById('previewResizeHandle');
  let rightPanelWidth = 380;   // feedback panel default
  const AGENT_PANEL_WIDTH = 750; // fixed: ~86 cols PTY at 14px monospace, matches terminal
  let dragStartX = 0;
  let dragStartWidth = 0;

  function updateGridColumns() {
    var lHidden = leftSidebar.classList.contains('hidden');
    // Also account for CSS-driven hide at narrow width (≤1500px + panel open)
    if (!lHidden && window.innerWidth <= 1500) {
      var rightOpen = rightSidebar && !rightSidebar.classList.contains('hidden');
      var agentOpen = agentPanel && !agentPanel.classList.contains('hidden');
      if (rightOpen || agentOpen) lHidden = true;
    }
    const rHidden = rightSidebar.classList.contains('hidden');
    const agentHidden = agentPanel ? agentPanel.classList.contains('hidden') : true;
    const lW = lHidden ? '0px' : '240px';
    if (rHidden && agentHidden) {
      threeCol.style.gridTemplateColumns = `${lW} 1fr 0px 0px`;
      if (resizeHandle) resizeHandle.classList.add('hidden');
    } else {
      // Hide resize handle when agent panel (fixed width) is open
      if (resizeHandle) resizeHandle.classList.toggle('hidden', !agentHidden);
      var panelW = !agentHidden ? AGENT_PANEL_WIDTH : rightPanelWidth;
      threeCol.style.gridTemplateColumns = `${lW} 1fr 5px ${panelW}px`;
    }
  }

  // ── Animated panel open/close helpers ──
  // All side panels use a uniform slide animation:
  //   left  panels → translateX(-100%) ⇄ translateX(0)
  //   right panels → translateX(100%)  ⇄ translateX(0)
  // transition: transform var(--duration-slow) var(--ease-out)  (300 ms)
  //
  // Pattern: temporarily override global .hidden { display:none }
  // with inline display:flex so the CSS transition can render.

  var _leftCloseTimer = null;
  var _rightCloseTimer = null;

  function openLeftSidebar() {
    if (!leftSidebar.classList.contains('hidden')) return;
    clearTimeout(_leftCloseTimer);
    leftSidebar.style.display = 'flex';        // override global .hidden
    // Expand grid column directly while panel is still "hidden"
    var gridParts = (threeCol.style.gridTemplateColumns || '240px 1fr 0px 0px').split(' ');
    gridParts[0] = '240px';
    threeCol.style.gridTemplateColumns = gridParts.join(' ');
    leftSidebar.offsetHeight;                   // reflow: w=240, translateX(-240px)
    leftSidebar.classList.remove('hidden');     // slide-in: -100% → 0
    leftSidebar.style.display = '';             // let CSS handle display
    btnToggleLeft.classList.add('active');
  }

  function closeLeftSidebar() {
    if (leftSidebar.classList.contains('hidden')) return;
    clearTimeout(_leftCloseTimer);
    leftSidebar.style.display = 'flex';         // override global .hidden
    leftSidebar.classList.add('hidden');        // slide-out: 0 → -100%
    btnToggleLeft.classList.remove('active');
    _leftCloseTimer = setTimeout(function () {
      leftSidebar.style.display = '';           // let global .hidden take over
      updateGridColumns();                      // grid column → 0px
    }, 300);
  }

  function openRightSidebar() {
    if (!rightSidebar.classList.contains('hidden')) return;
    console.log('[ClawMate] openRightSidebar called. Stack:', new Error().stack);
    clearTimeout(_rightCloseTimer);
    // Mutual exclusion: close left sidebar only on narrow screens
    if (window.innerWidth <= 1500 && leftSidebar && !leftSidebar.classList.contains('hidden')) {
      closeLeftSidebar();
    }
    // Snap agent panel closed instantly (no transition) to avoid overlap flicker
    if (agentPanel && !agentPanel.classList.contains('hidden')) {
      agentPanel.style.transition = 'none';
      if (window.Agent) window.Agent.close();
      agentPanel.offsetHeight; // force reflow
      agentPanel.style.transition = '';
      agentPanel.style.display = ''; // let CSS display:none take effect now
    }
    rightSidebar.style.display = 'flex';        // override global .hidden
    // Expand grid column directly while panel is still "hidden"
    var gridParts = (threeCol.style.gridTemplateColumns || '240px 1fr 0px 0px').split(' ');
    gridParts[2] = '5px';
    gridParts[3] = rightPanelWidth + 'px';
    threeCol.style.gridTemplateColumns = gridParts.join(' ');
    rightSidebar.offsetHeight;                  // reflow: w=panelW, translateX(100%)
    rightSidebar.classList.remove('hidden');    // slide-in: 100% → 0
    rightSidebar.style.display = '';            // let CSS handle display
    document.getElementById('btnToggleRight').classList.add('active');
    _syncPanelOpenClass();
  }

  function closeRightSidebar() {
    if (rightSidebar.classList.contains('hidden')) return;
    clearTimeout(_rightCloseTimer);
    rightSidebar.style.display = 'flex';        // override global .hidden
    if (_desktopPollTimer) { clearInterval(_desktopPollTimer); _desktopPollTimer = null; }
    rightSidebar.classList.add('hidden');       // slide-out: 0 → 100%
    _stopSidebarRefresh();
    document.getElementById('btnToggleRight').classList.remove('active');
    _rightCloseTimer = setTimeout(function () {
      rightSidebar.style.display = 'none';      // explicitly hide — CSS .preview-right.hidden broken in CSSOM
      updateGridColumns();                      // grid column → 0px
      _syncPanelOpenClass();
    }, 300);
  }

  if (resizeHandle) {
    resizeHandle.addEventListener('mousedown', function (e) {
      // Agent panel has fixed width — resize only applies to feedback panel
      var agentOpen = agentPanel && !agentPanel.classList.contains('hidden');
      if (agentOpen) return;
      e.preventDefault();
      dragStartX = e.clientX;
      dragStartWidth = rightPanelWidth;
      resizeHandle.classList.add('active');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      document.addEventListener('mousemove', onResizeMove);
      document.addEventListener('mouseup', onResizeUp);
    });

    function onResizeMove(e) {
      const delta = dragStartX - e.clientX;
      var newWidth = Math.max(420, Math.min(900, dragStartWidth + delta));
      rightPanelWidth = newWidth;
      threeCol.style.gridTemplateColumns =
        (leftSidebar.classList.contains('hidden') ? '0px' : '240px') +
        ' 1fr 5px ' + newWidth + 'px';
    }

    function onResizeUp() {
      resizeHandle.classList.remove('active');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', onResizeMove);
      document.removeEventListener('mouseup', onResizeUp);
    }
  }

  // Left sidebar: markdown & image show it, other modes hide it
  // On mobile: always start hidden, user toggles via topbar
  const isMobileViewport = window.innerWidth < 768;
  if (isMobileViewport || (!isMarkdownMode && !isImageMode)) {
    leftSidebar.classList.add('hidden');
    btnToggleLeft.classList.remove('active');
  } else {
    leftSidebar.classList.remove('hidden');
    btnToggleLeft.classList.add('active');
  }
  // Right sidebar: hidden by default, auto-opens when feedback is added
  rightSidebar.classList.add('hidden');
  updateGridColumns();

  // Track body class for CSS-driven left sidebar auto-hide at narrow widths
  function _syncPanelOpenClass() {
    var rightOpen = rightSidebar && !rightSidebar.classList.contains('hidden');
    var agentOpen = agentPanel && !agentPanel.classList.contains('hidden');
    // 防御：如果两个都 open，强制关掉 agent（feedback 优先）
    if (rightOpen && agentOpen) {
      console.warn('[ClawMate] _syncPanelOpenClass: both panels open, forcing agent closed. Stack:', new Error().stack);
      agentPanel.classList.add('hidden');
      agentOpen = false;
    }
    document.body.classList.toggle('preview-panel-open', rightOpen || agentOpen);
  }

  // Watch for CSS-driven left sidebar auto-hide at ≤1500px (same as index logic)
  if (window.matchMedia) {
    window.matchMedia('(max-width: 1500px)').addEventListener('change', function (e) {
      if (!e.matches) {
        // Window widened beyond 1500px — restore outline if it was auto-hidden
        if (leftSidebar.classList.contains('hidden')) {
          var rightOpen = rightSidebar && !rightSidebar.classList.contains('hidden');
          var agentOpen = agentPanel && !agentPanel.classList.contains('hidden');
          if (rightOpen || agentOpen) {
            openLeftSidebar();
            return;
          }
        }
      }
      // Recalculate grid to shrink/expand the left column
      updateGridColumns();
      // Sync button state
      var lHidden = leftSidebar.classList.contains('hidden');
      btnToggleLeft.classList.toggle('active', !lHidden);
    });
  }

  // ============ Image / Media Mode Toolbar Setup ============
  function setupMediaToolbar() {
    // Image mode keeps the left sidebar for thumbnail outline.
    // Media mode (audio/video) callers hide the sidebar in setupMediaMode().
    updateGridColumns();

    const dyn = document.getElementById('bottombarDynamic');
    if (dyn) dyn.style.display = 'flex';
  }

  // ============ Unified Media Mode Setup (audio + video) ============
  let mediaEl = null;         // the <audio> or <video> element
  let currentMediaType = '';  // 'audio' | 'video'
  let subtitleMode = 'view';  // 'view' | 'edit'
  let currentSrt = [];        // parsed SRT entries
  let currentSrtPath = '';    // path of currently loaded SRT
  let subtitleDirty = false;  // unsaved edits flag
  let subtitleEntries = [];   // [{start, end, text}] — editable copies
  let mediaCompletedItems = [];

  function setupMediaMode(type) {
    currentMediaType = type;
    setupMediaToolbar();
    // Media mode has no outline — hide the left sidebar
    leftSidebar.classList.add('hidden');
    updateGridColumns();

    const contentBody = document.getElementById('contentBody');
    contentBody.innerHTML = '';
    contentBody.style.overflow = 'hidden';

    // Build container
    const container = document.createElement('div');
    container.className = 'media-container';
    container.id = 'mediaContainer';

    // Player wrapper
    const playerWrap = document.createElement('div');
    playerWrap.className = 'media-player-wrap';
    playerWrap.style.height = type === 'video' ? '320px' : '80px';
    mediaEl = document.createElement(type === 'video' ? 'video' : 'audio');
    mediaEl.controls = true;
    mediaEl.id = 'mediaEl';
    mediaEl.src = `/api/clawmate/preview?root=${encodeURIComponent(rootId)}&path=${encodeURIComponent(filePath)}`;
    mediaEl.onerror = function() {
      this.style.display = 'none';
      const errDiv = document.createElement('div');
      errDiv.className = 'preview-error';
      errDiv.textContent = (type === 'video' ? '视频' : '音频') + '加载失败，文件可能已损坏或编码格式不支持';
      playerWrap.appendChild(errDiv);
    };
    playerWrap.appendChild(mediaEl);
    container.appendChild(playerWrap);

    // Draggable divider
    const dragHandle = document.createElement('div');
    dragHandle.className = 'drag-handle';
    container.appendChild(dragHandle);

    // Subtitle sync panel (below player)
    const syncPanel = document.getElementById('subtitleSyncPanel');
    syncPanel.classList.remove('hidden');
    container.appendChild(syncPanel);

    contentBody.appendChild(container);

    // Build dynamic toolbar buttons
    buildMediaToolbar();

    // Try auto-loading .srt with same base name
    autoLoadSrt();

    // Set up media feedback panel
    if (!_skipFeedbackLoad) loadMediaCompletedFeedback();

    // Wire subtitle timeupdate
    mediaEl.addEventListener('timeupdate', onMediaTimeUpdate);

    // Init drag handle for resizing player vs subtitle panel
    initDragHandle();
  }

  function buildMediaToolbar() {
    const dyn = document.getElementById('bottombarDynamic');
    dyn.innerHTML = '';
    // Dynamic toolbar for media mode — subtitle buttons in bottombar
    if (!currentSrt.length) {
      // No subtitles: show extract placeholder button
      const extractBtn = document.createElement('button');
      extractBtn.className = 'preview-bottom-btn';
      extractBtn.id = 'btnSubtitleExtract';
      extractBtn.textContent = '🎤 提取字幕';
      extractBtn.title = '提取人声生成 SRT 字幕';
      extractBtn.addEventListener('click', () => {
        extractSubtitle();
      });
      dyn.appendChild(extractBtn);
    } else if (subtitleMode === 'edit') {
      // Editing: show cancel always, save only when dirty
      const cancelBtn = document.createElement('button');
      cancelBtn.className = 'preview-bottom-btn active';
      cancelBtn.id = 'btnSubtitleCancel';
      cancelBtn.textContent = '❌ 取消';
      cancelBtn.addEventListener('click', cancelSubtitleEdit);
      dyn.appendChild(cancelBtn);

      if (subtitleDirty) {
        const saveBtn = document.createElement('button');
        saveBtn.className = 'preview-bottom-btn active';
        saveBtn.id = 'btnSubtitleSave';
        saveBtn.textContent = '💾 保存';
        saveBtn.addEventListener('click', saveSubtitleEdit);
        dyn.appendChild(saveBtn);
      }
    } else {
      // Has subtitles, not editing: show edit button
      const editBtn = document.createElement('button');
      editBtn.className = 'preview-bottom-btn';
      editBtn.id = 'btnSubtitleEdit';
      editBtn.textContent = '✏️ 编辑';
      editBtn.addEventListener('click', enterSubtitleEdit);
      dyn.appendChild(editBtn);

      // AI 纠错按钮（仅在有字幕时显示）
      const correctBtn = document.createElement('button');
      correctBtn.className = 'preview-bottom-btn';
      correctBtn.id = 'btnSubtitleCorrect';
      correctBtn.textContent = '🤖 AI 纠错';
      correctBtn.title = '用大模型修正字幕转录错误（时间戳不变）';
      correctBtn.addEventListener('click', correctSrt);
      dyn.appendChild(correctBtn);
    }
  }

  // ============ SRT AI Correction ============
  async function correctSrt() {
    if (!currentSrtPath) {
      showToast('请先生成或加载字幕文件', 3000);
      return;
    }
    const btn = document.getElementById('btnSubtitleCorrect');
    if (btn) { btn.disabled = true; btn.textContent = '🤖 纠错中...'; }
    try {
      const srtContent = serializeSrt(currentSrt);
      const res = await fetch('/api/clawmate/task/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root: rootId, file: filePath, selections: [{ task_id: 'subtitle_correct', content: srtContent, srt_path: currentSrtPath }] }),
      });
      const data = await res.json();
      if (!res.ok) {
        showToast('❌ ' + (data.detail || data.message || '纠错失败'), 4000);
        return;
      }
      showToast('🤖 纠错任务已提交', 3000);
      loadMediaCompletedFeedback();
      // 等待 agent 处理，然后重新加载字幕
      pollSrtReload(currentSrtPath, 30000);
    } catch(e) {
      showToast('❌ ' + e.message, 3000);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '🤖 AI 纠错'; }
    }
  }

  async function pollSrtReload(srtPath, timeoutMs) {
    const start = Date.now();
    const poll = async () => {
      if (Date.now() - start > timeoutMs) return;
      try {
        const res = await fetch(`/api/clawmate/preview?root=${encodeURIComponent(rootId)}&path=${encodeURIComponent(srtPath)}`);
        if (res.ok) {
          const entries = await parseSrtEntries(await res.text());
          if (entries && entries.length > 0) {
            loadSrtEntries(entries, srtPath);
            showToast('✅ 字幕已更新', 3000);
            return;
          }
        }
      } catch (_) {}
      setTimeout(poll, 2000);
    };
    poll();
  }

  async function parseSrtEntries(text) {
    // 解析 SRT 文本为 entries 数组 [{start, end, text}, ...]
    const blocks = text.trim().split(/\n\n+/);
    const entries = [];
    for (const block of blocks) {
      const lines = block.split('\n');
      if (lines.length < 3) continue;
      const timing = lines[1];
      if (!timing || !timing.includes('-->')) continue;
      const [start, end] = timing.split('-->').map(t => t.trim());
      const text = lines.slice(2).join('\n').trim();
      if (!text) continue;
      entries.push({ start: parseTimestamp(start), end: parseTimestamp(end), text });
    }
    return entries;
  }

  function parseTimestamp(ts) {
    // "00:01:23,456" → 秒数
    const m = ts.match(/(\d+):(\d+):(\d+)[,.](\d+)/);
    if (!m) return 0;
    return (+m[1]) * 3600 + (+m[2]) * 60 + (+m[3]) + (+m[4]) / 1000;
  }


  let _subtitleExtractController = null;  // AbortController for cancellation

  function showExtractProgressModal() {
    // Wire cancel button (one-time)
    const btn = document.getElementById('subtitleExtractCancelBtn');
    if (btn && !btn._wired) {
      btn._wired = true;
      btn.addEventListener('click', cancelSubtitleExtract);
    }
    const modal = document.getElementById('subtitleExtractModal');
    const fill = document.getElementById('subtitleExtractProgressFill');
    const text = document.getElementById('subtitleExtractProgressText');
    const pct = document.getElementById('subtitleExtractProgressPct');
    const err = document.getElementById('subtitleExtractError');
    if (fill) fill.style.width = '0%';
    if (text) text.textContent = '准备中...';
    if (pct) pct.textContent = '0%';
    if (err) err.style.display = 'none';
    if (modal) {
      modal.style.display = 'flex';
      modal.style.alignItems = 'center';
      modal.style.justifyContent = 'center';
    }
  }

  function hideExtractProgressModal() {
    const modal = document.getElementById('subtitleExtractModal');
    if (modal) modal.style.display = 'none';
    _subtitleExtractController = null;
  }

  function updateExtractProgress(phase, progress, detail) {
    const fill = document.getElementById('subtitleExtractProgressFill');
    const text = document.getElementById('subtitleExtractProgressText');
    const pct = document.getElementById('subtitleExtractProgressPct');
    const err = document.getElementById('subtitleExtractError');
    const title = document.getElementById('subtitleExtractModalTitle');
    if (fill) fill.style.width = progress + '%';
    if (pct) pct.textContent = progress + '%';
    if (text) text.textContent = detail || '';
    if (title) {
      if (phase === 'done') {
        title.textContent = '✅ 字幕提取完成';
      } else if (phase === 'error') {
        title.textContent = '❌ 提取失败';
        if (err) {
          err.textContent = detail || '未知错误';
          err.style.display = 'block';
        }
      } else if (phase === 'extracting') {
        title.textContent = '🎙️ 正在提取音频...';
      } else if (phase === 'transcribing') {
        title.textContent = '🎙️ 正在识别语音...';
      }
    }
  }

  function cancelSubtitleExtract() {
    const btn = document.getElementById('subtitleExtractCancelBtn');
    if (btn) btn.disabled = true;
    if (_subtitleExtractController) {
      _subtitleExtractController.abort();
      _subtitleExtractController = null;
    }
    hideExtractProgressModal();
    showToast('已取消字幕提取', 2000);
  }

  async function extractSubtitle() {
    if (!isMediaMode) return;
    showExtractProgressModal();
    _subtitleExtractController = new AbortController();
    try {
      const response = await fetch('/api/clawmate/subtitle/extract', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          root: rootId,
          path: filePath,
          model: 'small',
          language: 'zh',
        }),
        signal: _subtitleExtractController.signal,
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let done = false;

      while (!done) {
        const { value, done: streamDone } = await reader.read();
        done = streamDone;
        if (value) {
          buffer += decoder.decode(value, { stream: !done });
          // Process complete SSE messages in buffer
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';  // keep incomplete last line
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6));
                if (data.phase === 'done') {
                  updateExtractProgress('done', 100, data.detail || '完成');
                  // Auto-load the generated SRT
                  setTimeout(() => {
                    hideExtractProgressModal();
                    reloadSrtForCurrentMedia();
                    showToast('✅ 字幕已生成: ' + (data.srt_path || '').split('/').pop(), 4000);
                  }, 1200);
                  return;
                } else if (data.phase === 'error') {
                  updateExtractProgress('error', 0, data.detail || '未知错误');
                  // error 后可点击取消关闭
                  const cancelBtn = document.getElementById('subtitleExtractCancelBtn');
                  if (cancelBtn) cancelBtn.textContent = '取消';
                  return;
                } else {
                  updateExtractProgress(data.phase, data.progress || 0, data.detail || '');
                }
              } catch (_) {}
            }
          }
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        // Already handled by cancelSubtitleExtract
        return;
      }
      updateExtractProgress('error', 0, err.message || String(err));
    }
  }

  async function reloadSrtForCurrentMedia() {
    // Re-run autoLoadSrt to pick up the newly generated .srt
    const baseName = filePath.replace(/\.[^.]+$/, '');
    for (const srtPath of [baseName + '.srt', baseName + '.SRT']) {
      try {
        const res = await fetch(`/api/clawmate/preview?root=${encodeURIComponent(rootId)}&path=${encodeURIComponent(srtPath)}`);
        if (res.ok) {
          const data = await res.json();
          const entries = parseSrt(data.content);
          if (entries.length > 0) {
            loadSrtEntries(entries, srtPath);
            return;
          }
        }
      } catch (_) {}
    }
  }

  // ============ SRT Parsing ============
  function parseSrt(text) {
    const entries = [];
    // Match blocks: number + timestamp + text (text may span multiple lines)
    const BLOCK_RE = /(\d+)\r?\n([\d:]+,[0-9]+\s*-->\s*[\d:]+,[0-9]+)\r?\n([\s\S]*?)(?=\r?\n\r?\n|\d+\r?\n|$)/g;
    let m;
    while ((m = BLOCK_RE.exec(text)) !== null) {
      const ts = m[2];
      const tsParts = ts.split('-->').map(t => t.trim());
      const start = parseSrtTime(tsParts[0]);
      const end = parseSrtTime(tsParts[1]);
      // SRT text may have \r\n line breaks, collapse to single space
      const rawText = m[3].replace(/\r?\n/g, ' ').trim();
      if (rawText) entries.push({ start, end, text: rawText });
    }
    return entries;
  }

  function parseSrtTime(ts) {
    // Format: 00:12:30,500  or  00:12:30.500
    const parts = ts.replace(',', '.').split(':');
    if (parts.length !== 3) return 0;
    const h = parseInt(parts[0], 10) || 0;
    const m = parseInt(parts[1], 10) || 0;
    const secParts = (parts[2] || '0').split('.');
    const s = parseInt(secParts[0], 10) || 0;
    const ms = parseInt(secParts[1] || '0', 10) || 0;
    return h * 3600 + m * 60 + s + ms / 1000;
  }

  function formatTimestamp(seconds) {
    if (!seconds && seconds !== 0) return '00:00:00';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    return [h, m, s].map(v => String(v).padStart(2, '0')).join(':');
  }

  function serializeSrt(entries) {
    return entries.map((e, i) => {
      const fmt = t => {
        const h = Math.floor(t / 3600);
        const m = Math.floor((t % 3600) / 60);
        const s = Math.floor(t % 60);
        const ms = Math.round((t % 1) * 1000);
        return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')},${String(ms).padStart(3,'0')}`;
      };
      return `${i + 1}\n${fmt(e.start)} --> ${fmt(e.end)}\n${e.text}`;
    }).join('\n\n');
  }

  async function autoLoadSrt() {
    // Look for .srt with same base name in same directory
    const baseName = filePath.replace(/\.[^.]+$/, '');
    const possiblePaths = [
      baseName + '.srt',
      baseName + '.SRT',
    ];
    for (const srtPath of possiblePaths) {
      try {
        const res = await fetch(`/api/clawmate/preview?root=${encodeURIComponent(rootId)}&path=${encodeURIComponent(srtPath)}`);
        if (res.ok) {
          const data = await res.json();
          const entries = parseSrt(data.content);
          if (entries.length > 0) {
            loadSrtEntries(entries, srtPath);
            showToast('已自动加载字幕: ' + srtPath.split('/').pop(), 2500);
            return;
          }
        }
      } catch (_) {}
    }
    // No SRT found — render empty sync panel
    renderSubtitleSyncPanel();
  }

  function loadSrtEntries(entries, srtPath) {
    currentSrt = entries;
    currentSrtPath = srtPath;
    subtitleEntries = entries.map(e => ({ ...e }));
    subtitleDirty = false;
    subtitleMode = 'view';
    renderSubtitleSyncPanel();
    buildMediaToolbar();
  }

  // ============ Subtitle Sync Panel (below player) ============
  function renderSubtitleSyncPanel() {
    const panel = document.getElementById('subtitleSyncPanel');
    panel.innerHTML = '';

    // ---- Subtitle header ----
    const header = document.createElement('div');
    header.className = 'subtitle-header' + (subtitleMode === 'edit' ? ' editing' : '');
    header.id = 'subtitleHeader';

    const headerLabel = document.createElement('span');
    headerLabel.textContent = '📝 字幕';
    header.appendChild(headerLabel);

    panel.appendChild(header);

    if (!currentSrt.length) {
      // No SRT — show empty message
      const empty = document.createElement('div');
      empty.className = 'subtitle-empty';
      empty.textContent = '暂无字幕文件';
      panel.appendChild(empty);
      return;
    }

    // ---- Scrollable subtitle items ----
    const scrollArea = document.createElement('div');
    scrollArea.className = 'subtitle-scroll';

    // In edit mode, use subtitleEntries (editable copy); otherwise use currentSrt (original)
    const entries = subtitleMode === 'edit' ? subtitleEntries : currentSrt;
    entries.forEach((entry, idx) => {
      const row = document.createElement('div');
      row.className = 'subtitle-item';
      row.id = `sub-item-${idx}`;

      const timeSpan = document.createElement('span');
      timeSpan.className = 'subtitle-time';
      timeSpan.textContent = formatTimestamp(entry.start);
      row.appendChild(timeSpan);

      if (subtitleMode === 'edit') {
        const input = document.createElement('input');
        input.type = 'text';
        input.value = entry.text;
        input.dataset.idx = idx;
        input.addEventListener('input', () => {
          subtitleEntries[idx].text = input.value;
          subtitleDirty = true;
          buildMediaToolbar();
        });
        input.addEventListener('click', e => e.stopPropagation());
        row.appendChild(input);
      } else {
        const textSpan = document.createElement('span');
        textSpan.className = 'subtitle-text';
        textSpan.textContent = entry.text;
        row.appendChild(textSpan);

        row.addEventListener('click', () => {
          if (mediaEl) {
            mediaEl.currentTime = entry.start;
            mediaEl.play().catch(() => {});
          }
        });
      }

      scrollArea.appendChild(row);
    });
    panel.appendChild(scrollArea);
  }

  // ============ Subtitle Edit Mode ============
  let subtitleEditSnapshot = [];
  let _subtitleEditWasPlaying = false;  // 编辑前是否在播放

  function enterSubtitleEdit() {
    _subtitleEditWasPlaying = !!(mediaEl && !mediaEl.paused);
    if (mediaEl && !mediaEl.paused) mediaEl.pause();
    subtitleEditSnapshot = currentSrt.map(e => ({ ...e }));
    subtitleMode = 'edit';
    renderSubtitleSyncPanel();
    buildMediaToolbar();
    // 定位到当前播放字幕行，高亮并聚焦输入框
    if (currentSubIdx >= 0 && currentSubIdx < subtitleEntries.length) {
      requestAnimationFrame(() => {
        const el = document.getElementById(`sub-item-${currentSubIdx}`);
        if (el) {
          el.classList.add('active');
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          const input = el.querySelector('input');
          if (input) { input.focus(); input.selectionStart = input.selectionEnd = input.value.length; }
        }
      });
    }
  }

  function cancelSubtitleEdit() {
    subtitleEntries = subtitleEditSnapshot.map(e => ({ ...e }));
    subtitleDirty = false;
    subtitleMode = 'view';
    renderSubtitleSyncPanel();
    buildMediaToolbar();
    if (_subtitleEditWasPlaying && mediaEl) mediaEl.play().catch(() => {});
  }

  async function saveSubtitleEdit() {
    const srtContent = serializeSrt(subtitleEntries);
    const savePath = currentSrtPath || filePath.replace(/\.[^.]+$/, '') + '.srt';
    try {
      const res = await fetch('/api/clawmate/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root: rootId, path: savePath, content: srtContent }),
      });
      const data = await res.json();
      if (data.ok) {
        currentSrt = subtitleEntries.map(e => ({ ...e }));
        subtitleDirty = false;
        subtitleMode = 'view';
        renderSubtitleSyncPanel();
        buildMediaToolbar();
        showToast('字幕已保存', 2000);
        if (_subtitleEditWasPlaying && mediaEl) mediaEl.play().catch(() => {});
      } else {
        const isSyntaxErr = data.error && data.error.includes('syntax_error');
        showToast('❌ ' + (data.detail || '未知错误'), isSyntaxErr ? 8000 : 3000);
      }
    } catch (e) {
      showToast('保存失败: ' + e.message, 3000);
    }
  }

  // ============ Media timeupdate — sync subtitle highlight ============
  let lastHighlightedIdx = -1;
  let currentSubIdx = -1;  // 当前播放位置对应的字幕索引，编辑时用于定位

  function onMediaTimeUpdate() {
    if (!mediaEl || !currentSrt.length || subtitleMode === 'edit') return;
    const t = mediaEl.currentTime;
    let activeIdx = -1;
    for (let i = 0; i < currentSrt.length; i++) {
      if (t >= currentSrt[i].start && t <= currentSrt[i].end) {
      currentSubIdx = i;
        activeIdx = i;
        break;
      }
    }
    if (activeIdx !== lastHighlightedIdx) {
      // Remove old highlight
      if (lastHighlightedIdx >= 0) {
        const oldEl = document.getElementById(`sub-item-${lastHighlightedIdx}`);
        if (oldEl) oldEl.classList.remove('active');
      }
      // Add new highlight
      if (activeIdx >= 0) {
        const newEl = document.getElementById(`sub-item-${activeIdx}`);
        if (newEl) {
          newEl.classList.add('active');
          newEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }
      lastHighlightedIdx = activeIdx;
    }
  }

  // ============ Draggable Resize Handle ============
  function initDragHandle() {
    const handle = document.querySelector('.drag-handle');
    const playerWrap = document.querySelector('.media-player-wrap');
    if (!handle || !playerWrap) return;

    let dragging = false;
    let startY = 0;
    let startHeight = 0;

    function onMouseMove(e) {
      if (!dragging) return;
      const clientY = e.touches ? e.touches[0].clientY : e.clientY;
      // Mouse down = clientY increases = height increases
      const delta = clientY - startY;
      const newHeight = Math.max(150, Math.min(startHeight + delta, window.innerHeight * 0.7));
      playerWrap.style.height = newHeight + 'px';
    }

    function onMouseUp() {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove('dragging');
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
      document.removeEventListener('touchmove', onMouseMove);
      document.removeEventListener('touchend', onMouseUp);
    }

    handle.addEventListener('mousedown', e => {
      e.preventDefault();
      dragging = true;
      startY = e.clientY;
      startHeight = playerWrap.offsetHeight;
      handle.classList.add('dragging');
      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp);
    });

    handle.addEventListener('touchstart', e => {
      e.preventDefault();
      dragging = true;
      startY = e.touches[0].clientY;
      startHeight = playerWrap.offsetHeight;
      handle.classList.add('dragging');
      document.addEventListener('touchmove', onMouseMove, { passive: false });
      document.addEventListener('touchend', onMouseUp);
    }, { passive: false });
  }

  // ============ Archive Tree View ============
  function renderArchiveView(meta, archiveData, downloadUrl) {
    var container = document.getElementById('previewContent');
    if (!container) container = document.getElementById('contentBody');
    if (!container) return;
    container.innerHTML = '';

    var archiveEntries = archiveData.entries || [];
    var encrypted = archiveData.encrypted;
    var error = archiveData.error;
    var totalFiles = archiveData.file_count || 0;
    var totalDirs = archiveData.dir_count || 0;
    var totalSize = archiveData.total_size || 0;
    var totalCount = archiveData.total || archiveEntries.length;

    // ── Info bar ──
    var infoBar = document.createElement('div');
    infoBar.className = 'archive-info-bar';
    var sizeStr = typeof formatSize === 'function' ? formatSize(totalSize) : (totalSize + ' B');
    infoBar.innerHTML =
      '<span class="archive-info-icon">📦</span>' +
      '<span class="archive-info-name">' + escHtml(meta.name || '') + '</span>' +
      '<span class="archive-info-stats">' + totalFiles + ' files, ' + totalDirs + ' dirs &middot; ' + escHtml(sizeStr) + '</span>' +
      '<span class="archive-info-actions">' +
        '<button class="archive-btn" id="archiveExpandAll">▼ Expand All</button>' +
        '<button class="archive-btn" id="archiveCollapseAll">▶ Collapse All</button>' +
        (downloadUrl ? '<a class="archive-btn archive-dl-btn" href="' + escHtml(downloadUrl) + '" download>⬇ Download</a>' : '') +
      '</span>';
    container.appendChild(infoBar);

    // ── Encrypted warning ──
    if (encrypted) {
      var warn = document.createElement('div');
      warn.className = 'archive-encrypted-warn';
      warn.innerHTML = '🔒 This archive is encrypted. Contents may be incomplete.';
      container.appendChild(warn);
    }

    // ── Error / unsupported ──
    if (error) {
      var err = document.createElement('div');
      err.className = 'archive-error';
      err.innerHTML =
        '<div class="archive-error-msg">' + escHtml(error) + '</div>' +
        (downloadUrl ? '<a class="preview-unsupported-download-btn" href="' + escHtml(downloadUrl) + '" download style="margin-top:16px;display:inline-flex;">⬇ Download</a>' : '');
      container.appendChild(err);
      return;
    }

    // ── Build tree from flat entries ──
    var treeRoot = { children: {}, dirs: {}, files: [] };

    archiveEntries.forEach(function(entry) {
      var parts = (entry.path || entry.name).split('/');
      var node = treeRoot;
      for (var i = 0; i < parts.length; i++) {
        var part = parts[i];
        if (!part) continue;
        var isLast = (i === parts.length - 1);
        if (!node.children[part]) {
          node.children[part] = { name: part, children: {}, dirs: {}, files: [], isDir: !isLast || entry.is_dir, entry: null };
        }
        if (isLast) {
          node.children[part].isDir = entry.is_dir;
          node.children[part].entry = entry;
        }
        node = node.children[part];
      }
    });

    // ── Render tree ──
    function buildTreeDom(node, depth) {
      depth = depth || 0;
      var names = Object.keys(node.children).sort(function(a, b) {
        var na = node.children[a];
        var nb = node.children[b];
        if (na.isDir !== nb.isDir) return na.isDir ? -1 : 1;
        return a.localeCompare(b);
      });
      var frag = document.createDocumentFragment();

      names.forEach(function(name) {
        var child = node.children[name];
        var row = document.createElement('div');
        row.className = 'archive-entry' + (child.isDir ? ' archive-dir' : ' archive-file');
        row.style.paddingLeft = (depth * 20 + 12) + 'px';

        // Indent guide
        if (depth > 0) {
          for (var d = 0; d < depth; d++) {
            var guide = document.createElement('span');
            guide.className = 'archive-indent-guide';
            guide.style.left = (d * 20 + 10) + 'px';
            row.appendChild(guide);
          }
        }

        var icon = document.createElement('span');
        icon.className = 'archive-icon';
        if (child.isDir) {
          icon.textContent = '▶';
          icon.style.cursor = 'pointer';
        } else {
          icon.innerHTML = '&nbsp;&nbsp;';
        }
        row.appendChild(icon);

        var nameSpan = document.createElement('span');
        nameSpan.className = 'archive-name';
        nameSpan.textContent = name + (child.isDir ? '/' : '');
        row.appendChild(nameSpan);

        if (!child.isDir && child.entry) {
          var s = child.entry.size;
          var sizeSpan = document.createElement('span');
          sizeSpan.className = 'archive-size';
          sizeSpan.textContent = typeof formatSize === 'function' ? formatSize(s) : (s + ' B');
          row.appendChild(sizeSpan);

          if (child.entry.mtime) {
            var mtimeSpan = document.createElement('span');
            mtimeSpan.className = 'archive-mtime';
            var d = new Date(child.entry.mtime * 1000);
            mtimeSpan.textContent = d.toISOString().slice(0, 10);
            row.appendChild(mtimeSpan);
          }
        }

        // Toggle children
        if (child.isDir && Object.keys(child.children).length > 0) {
          var childrenWrap = document.createElement('div');
          childrenWrap.className = 'archive-children';
          childrenWrap.style.display = 'none';
          var childDom = buildTreeDom(child, depth + 1);
          childrenWrap.appendChild(childDom);
          row.appendChild(childrenWrap);

          icon.addEventListener('click', function() {
            var isHidden = childrenWrap.style.display === 'none';
            childrenWrap.style.display = isHidden ? '' : 'none';
            icon.textContent = isHidden ? '▼' : '▶';
          });
        } else if (child.isDir) {
          // Empty directory
          icon.textContent = '▶';
          icon.style.opacity = '0.4';
        }

        frag.appendChild(row);
      });

      return frag;
    }

    var treeDom = buildTreeDom(treeRoot, 0);
    var treeWrap = document.createElement('div');
    treeWrap.className = 'archive-tree';
    treeWrap.appendChild(treeDom);
    container.appendChild(treeWrap);

    // ── Expand/collapse all buttons ──
    document.getElementById('archiveExpandAll').addEventListener('click', function() {
      treeWrap.querySelectorAll('.archive-children').forEach(function(c) { c.style.display = ''; });
      treeWrap.querySelectorAll('.archive-icon').forEach(function(ic) {
        if (ic.textContent === '▶') ic.textContent = '▼';
      });
    });
    document.getElementById('archiveCollapseAll').addEventListener('click', function() {
      treeWrap.querySelectorAll('.archive-children').forEach(function(c) { c.style.display = 'none'; });
      treeWrap.querySelectorAll('.archive-icon').forEach(function(ic) {
        if (ic.textContent === '▼') ic.textContent = '▶';
      });
    });
  }

  // ============ Media Feedback Panel ============
  function renderMediaFeedbackPanel() {
    const body = document.getElementById('feedbackBody');
    body.innerHTML = '';

    var topBar = document.createElement('div');
    topBar.className = 'fb-topbar';
    body.appendChild(topBar);

    var cardList = document.createElement('div');
    cardList.className = 'fb-card-list';
    body.appendChild(cardList);

    // Top row: Add feedback + Submit all


    const addBtn = document.createElement('button');
    addBtn.className = 'fb-btn-submit';
    addBtn.textContent = '+ 添加反馈';
    addBtn.addEventListener('click', () => {
      const currentTime = mediaEl ? formatTimestamp(mediaEl.currentTime) : '00:00:00';
      const item = { id: ++idCounter, text: '', startLine: 0, endLine: 0, note: '', type: 'media', position: 'Time ' + currentTime };
      mediaPendingItems.push(item);
      renderMediaFeedbackPanel();
      // Scroll to the newly added card
      const newCard = body.querySelector(`.fb-card[data-id="${item.id}"]`);
      if (newCard) newCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    topBar.appendChild(addBtn);

    const submitAllBtn = document.createElement('button');
    submitAllBtn.className = 'fb-btn-submit-all';
    const hasPending = mediaPendingItems.length > 0;
    submitAllBtn.style.cssText = `flex:1;padding:4px 8px;border-radius:6px;border:1px solid var(--border-color);background:var(--btn-bg);color:var(--btn-text);cursor:${hasPending ? 'pointer' : 'not-allowed'};font-size:13px;font-weight:600;opacity:${hasPending ? '1' : '0.5'};`;
    submitAllBtn.textContent = hasPending ? `✅ 全部提交（${mediaPendingItems.length} 条）` : '✅ 全部提交';
    submitAllBtn.disabled = !hasPending;
    if (hasPending) {
      submitAllBtn.addEventListener('click', () => {
        const missing = mediaPendingItems.filter(i => !i.note || !i.action);
        if (missing.length > 0) {
          showToast('请填写备注后再提交', 2000);
          return;
        }
        submitAllItems(submitAllBtn, {
          pendingArray: mediaPendingItems,
          onReload: loadMediaCompletedFeedback,
          itemType: 'media',
        });
      });
    }
    topBar.appendChild(submitAllBtn);

    // Empty state
    if (mediaPendingItems.length === 0 && mediaCompletedItems.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'fb-empty';
      empty.style.marginTop = '12px';
      empty.textContent = '点击「+ 添加反馈」开始';
      cardList.appendChild(empty);
      return;
    }

    // Pending items
    if (mediaPendingItems.length > 0) {
      [...mediaPendingItems].reverse().forEach(item => cardList.appendChild(createFeedbackCard(item)));
    }

    // Completed items — split pending/in_progress vs done/failed
    const pendingOrProgress = mediaCompletedItems.filter(i => i.status === 'pending' || i.status === 'in_progress');
    const doneOrFailed = mediaCompletedItems.filter(i => i.status === 'done' || i.status === 'failed');
    if (pendingOrProgress.length > 0) {
      const sep = document.createElement('div');
      sep.className = 'fb-section-sep';
      sep.innerHTML = '<span>⏳ 处理中</span>';
      cardList.appendChild(sep);
      pendingOrProgress.forEach(item => cardList.appendChild(renderCompletedFeedbackCard(item)));
    }
    if (doneOrFailed.length > 0) {
      const sep = document.createElement('div');
      sep.className = 'fb-section-sep';
      sep.innerHTML = '<span>✅ 已完成</span>';
      cardList.appendChild(sep);
      doneOrFailed.forEach(item => cardList.appendChild(renderCompletedFeedbackCard(item)));
    }
  }

  async function loadMediaCompletedFeedback() {
    // Render panel immediately to show topbar buttons, then populate data
    renderMediaFeedbackPanel();
    if (!rootId || !project || !filePath) return;
    const fn = filePath.split('/').pop();
    try {
      const res = await fetch(`/api/clawmate/feedback/list?root=${encodeURIComponent(rootId)}&project=${encodeURIComponent(project)}&file=${encodeURIComponent(fn)}`);
      if (!res.ok) return;
      const data = await res.json();
      mediaCompletedItems = (data.items || []).filter(i => i.status !== 'deleted').sort((a, b) => (b.updated || '').localeCompare(a.updated || ''));
      renderMediaFeedbackPanel();
    } catch (_) {}
  }

  // ============ Office / PDF Mode ============
  let officePdfCompletedItems = [];
  let officePdfCurrentMode = 'view'; // track which mode we're in

  function setupOfficePdfToolbar() {
    officePdfCurrentMode = onlyofficeMode;
    const dyn = document.getElementById('bottombarDynamic');
    dyn.innerHTML = '';
    // Office docs open in edit mode by default; no manual toggle needed
  }

  function reloadOfficeIframe() {
    const iframe = document.getElementById('officeIframe');
    if (!iframe) return;
          var ooTheme = document.documentElement.getAttribute('data-theme') || 'light';
      iframe.src = './onlyoffice.html?root=' + encodeURIComponent(rootId) + '&path=' + encodeURIComponent(filePath) + '&mode=' + encodeURIComponent(onlyofficeMode) + '&theme=' + ooTheme;
  }

  function renderOfficePdfFeedbackPanel() {
    const body = document.getElementById('feedbackBody');
    body.innerHTML = '';

    var topBar = document.createElement('div');
    topBar.className = 'fb-topbar';
    body.appendChild(topBar);

    var cardList = document.createElement('div');
    cardList.className = 'fb-card-list';
    body.appendChild(cardList);

    // Top row: Add feedback + Submit all


    const addBtn = document.createElement('button');
    addBtn.className = 'fb-btn-submit';
    addBtn.textContent = '+ 添加反馈';
    addBtn.addEventListener('click', () => {
      const EXCEL_EXTS = ['xlsx', 'xls'];
      const isExcelMode = EXCEL_EXTS.includes(ext);
      const defaultPos = isPdfMode ? 'Page 1' : (isExcelMode ? 'Range A1' : 'Page 1');
      const item = { id: ++idCounter, text: '', startLine: 0, endLine: 0, note: '', type: 'office', position: defaultPos };
      officePdfPendingItems.push(item);
      renderOfficePdfFeedbackPanel();
      const newCard = body.querySelector(`.fb-card[data-id="${item.id}"]`);
      if (newCard) newCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    topBar.appendChild(addBtn);

    const submitAllBtn = document.createElement('button');
    submitAllBtn.className = 'fb-btn-submit-all';
    const hasPending = officePdfPendingItems.length > 0;
    submitAllBtn.style.cssText = `flex:1;padding:4px 8px;border-radius:6px;border:1px solid var(--border-color);background:var(--btn-bg);color:var(--btn-text);cursor:${hasPending ? 'pointer' : 'not-allowed'};font-size:13px;font-weight:600;opacity:${hasPending ? '1' : '0.5'};`;
    submitAllBtn.textContent = hasPending ? `✅ 全部提交（${officePdfPendingItems.length} 条）` : '✅ 全部提交';
    submitAllBtn.disabled = !hasPending;
    if (hasPending) {
      submitAllBtn.addEventListener('click', () => {
        const missing = officePdfPendingItems.filter(i => !i.note || !i.action);
        if (missing.length > 0) {
          showToast('请填写备注后再提交', 2000);
          return;
        }
        submitAllItems(submitAllBtn, {
          pendingArray: officePdfPendingItems,
          onReload: loadOfficePdfCompletedFeedback,
          itemType: 'office',
        });
      });
    }
    topBar.appendChild(submitAllBtn);

    // Empty state
    if (officePdfPendingItems.length === 0 && officePdfCompletedItems.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'fb-empty';
      empty.style.marginTop = '12px';
      empty.textContent = '点击「+ 添加反馈」开始';
      cardList.appendChild(empty);
      return;
    }

    // Pending items
    if (officePdfPendingItems.length > 0) {
      [...officePdfPendingItems].reverse().forEach(item => cardList.appendChild(createFeedbackCard(item)));
    }


    // Completed items
    if (officePdfCompletedItems.length > 0) {
      const sep = document.createElement('div');
      sep.className = 'fb-section-sep';
      sep.innerHTML = '<span>✅ 已提交</span>';
      cardList.appendChild(sep);
      officePdfCompletedItems.forEach(item => cardList.appendChild(renderCompletedFeedbackCard(item)));
    }
  }

  async function loadOfficePdfCompletedFeedback() {
    // Render panel immediately to show topbar buttons, then populate data
    renderOfficePdfFeedbackPanel();
    if (!rootId || !project || !filePath) return;
    const fn = filePath.split('/').pop();
    try {
      const res = await fetch(`/api/clawmate/feedback/list?root=${encodeURIComponent(rootId)}&project=${encodeURIComponent(project)}&file=${encodeURIComponent(fn)}`);
      if (!res.ok) return;
      const data = await res.json();
      officePdfCompletedItems = (data.items || []).filter(i => i.status !== 'deleted').sort((a, b) => (b.updated || '').localeCompare(a.updated || ''));
      renderOfficePdfFeedbackPanel();
    } catch (_) {}
  }

  // ============ Bottom Bar Actions ============
  // Cached config for absolute path resolution
  let _cachedRootsConfig = null;
  async function getRootsConfig() {
    if (_cachedRootsConfig) return _cachedRootsConfig;
    const cached = sessionStorage.getItem('clawmate-roots-config');
    if (cached) { _cachedRootsConfig = JSON.parse(cached); return _cachedRootsConfig; }
    try {
      const res = await fetch('/api/clawmate/config');
      if (res.ok) {
        const data = await res.json();
        _cachedRootsConfig = data;
        if (data.task_templates) { _taskTemplates = data.task_templates; initPstTags(); }
        sessionStorage.setItem('clawmate-roots-config', JSON.stringify(data));
        return data;
      }
    } catch (_) {}
    return null;
  }

  function getRelativePath() {
    return filePath || null;
  }

  document.getElementById('btnPath').addEventListener('click', () => {
    const relPath = getRelativePath();
    if (relPath) {
      const parentDir = relPath.split('/').slice(0, -1).join('/');
      const root = rootId || '';
      window.location.href = `/clawmate/?root=${encodeURIComponent(root)}&dir=${encodeURIComponent(parentDir)}`;
    } else {
      showToast('无法获取路径', 2000);
    }
  });

  // Copy filename button next to docTitle
  var btnCopyFilename = document.getElementById('btnCopyFilename');
  if (btnCopyFilename) {
    btnCopyFilename.addEventListener('click', async function () {
      var name = fileName || '未命名';
      await copyText(name, '✅ 文件名已复制');
      btnCopyFilename.classList.add('copied');
      setTimeout(function () { btnCopyFilename.classList.remove('copied'); }, 1200);
    });
  }

  // Refresh content + outline button (skips feedback & agent panel)
  var btnRefreshContent = document.getElementById('btnRefreshContent');
  if (btnRefreshContent) {
    btnRefreshContent.addEventListener('click', async function () {
      btnRefreshContent.classList.add('spinning');
      _skipFeedbackLoad = true;
      try {
        await loadContent();
      } finally {
        _skipFeedbackLoad = false;
        btnRefreshContent.classList.remove('spinning');
      }
    });
  }

  /** Clear page title before print so browser header omits date/filename, restore after */
  function printWithoutHeaderFooter() {
    const origTitle = document.title;
    document.title = ' ';
    setTimeout(() => {
      window.print();
      // Restore title after print dialog closes (cannot detect exact close, but short delay is safe)
      setTimeout(() => { document.title = origTitle; }, 100);
    }, 50);
  }

  document.getElementById('btnPdf').addEventListener('click', () => {
    if (isPdfMode) {
      // PDF: open raw in new tab — browser's native PDF viewer handles multi-page print
      const rawUrl = `/api/clawmate/raw?root=${encodeURIComponent(rootId)}&path=${encodeURIComponent(filePath)}`;
      const pdfWindow = window.open(rawUrl, '_blank');
      if (pdfWindow) {
        showToast('PDF 已在新标签页打开，可使用浏览器打印所有页面', 3000);
      } else {
        // Popup blocked — fallback to window.print
        showToast('弹窗被拦截，请允许弹窗或手动下载后打印', 4000);
      }
    } else if (isOfficeMode) {
      // Office: try ONLYOFFICE API via postMessage
      const iframe = document.getElementById('officeIframe');
      if (iframe && iframe.contentWindow) {
        iframe.contentWindow.postMessage({ type: 'print-document' }, '*');
        showToast('已发送打印请求至 ONLYOFFICE', 2000);
      } else {
        showToast('ONLYOFFICE 未就绪，使用浏览器打印', 2000);
        printWithoutHeaderFooter();
      }
    } else {
      printWithoutHeaderFooter();
    }
  });

  document.getElementById('btnRename').addEventListener('click', async () => {
    const newName = prompt('输入新文件名：', fileName);
    if (!newName || newName === fileName) return;
    try {
      const res = await fetch('/api/clawmate/rename', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root: rootId, path: filePath, newName }),
      });
      const data = await res.json();
      if (data.ok) {
        const newUrl = `?root=${encodeURIComponent(rootId)}&file=${encodeURIComponent(data.newPath)}`;
        window.location.href = newUrl;
      } else {
        showToast('重命名失败: ' + (data.detail || '未知错误'), 3000);
      }
    } catch (e) {
      showToast('重命名失败: ' + e.message, 3000);
    }
  });

  // ============ Directory Picker (shared by Move and Extract) ============
  var dirPickerCallback = null;
  var dirPickerSelectedDir = '';
  var dirPickerMode = ''; // 'move' or 'extract'
  // Lazy-load tree state: cache of children per dir path, expanded/loading flags
  var dirPickerCache = {};
  var dirPickerExpanded = {};
  var dirPickerLoading = {};
  var dirPickerSkipped = 0;
  var DIR_PICKER_SKIP_PREFIXES = ['.', '__pycache__', 'node_modules'];

  function initDirPicker() {
    var closeBtn = document.getElementById('dirPickerClose');
    var cancelBtn = document.getElementById('dirPickerCancel');
    var confirmBtn = document.getElementById('dirPickerConfirm');
    var modal = document.getElementById('dirPickerModal');
    if (!closeBtn || !cancelBtn || !confirmBtn || !modal) return;

    closeBtn.addEventListener('click', closeDirPicker);
    cancelBtn.addEventListener('click', closeDirPicker);
    confirmBtn.addEventListener('click', confirmDirPicker);

    // Close on backdrop click
    modal.addEventListener('click', function(e) {
      if (e.target === this) closeDirPicker();
    });
  }

  function closeDirPicker() {
    var modal = document.getElementById('dirPickerModal');
    if (modal) modal.style.display = 'none';
    dirPickerCallback = null;
    dirPickerSelectedDir = '';
    dirPickerMode = '';
    // Reset lazy-load state
    dirPickerCache = {};
    dirPickerExpanded = {};
    dirPickerLoading = {};
    dirPickerSkipped = 0;
  }

  function confirmDirPicker() {
    if (dirPickerCallback) {
      dirPickerCallback(dirPickerSelectedDir);
    }
    closeDirPicker();
  }

  /** Filter API entries to directories only, skipping hidden/cache dirs. */
  function _filterDirsForPicker(entries) {
    var dirs = [];
    for (var i = 0; i < entries.length; i++) {
      if (!entries[i].is_dir) continue;
      var nm = entries[i].name;
      var skip = false;
      for (var s = 0; s < DIR_PICKER_SKIP_PREFIXES.length; s++) {
        if (nm.indexOf(DIR_PICKER_SKIP_PREFIXES[s]) === 0) { skip = true; break; }
      }
      if (skip) { dirPickerSkipped++; continue; }
      dirs.push({name: nm, path: entries[i].path});
    }
    return dirs;
  }

  async function openDirPicker(mode, title) {
    dirPickerMode = mode;
    dirPickerSelectedDir = parentDir || '';
    dirPickerCache = {};
    dirPickerExpanded = {};
    dirPickerLoading = {};
    dirPickerSkipped = 0;

    var titleEl = document.getElementById('dirPickerTitle');
    var modal = document.getElementById('dirPickerModal');
    var tree = document.getElementById('dirPickerTree');
    if (!titleEl || !modal || !tree) return;

    titleEl.textContent = title || '选择目标目录';
    modal.style.display = 'flex';

    tree.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:20px;">加载中...</div>';

    try {
      // Level 0: fetch root directory listing (directories only)
      var res = await fetch('/api/clawmate/list?root=' + encodeURIComponent(rootId) + '&dir=&limit=500&dirs_only=true');
      var data = await res.json();
      dirPickerCache[''] = _filterDirsForPicker(data.entries || []);

      // Pre-expand the path from root to the current directory so the user
      // sees context immediately without having to manually expand every level.
      if (dirPickerSelectedDir) {
        var parts = dirPickerSelectedDir.split('/');
        var accumulated = '';
        for (var i = 0; i < parts.length; i++) {
          accumulated = accumulated ? accumulated + '/' + parts[i] : parts[i];
          dirPickerExpanded[accumulated] = true;
          var childRes = await fetch('/api/clawmate/list?root=' + encodeURIComponent(rootId)
            + '&dir=' + encodeURIComponent(accumulated) + '&limit=500&dirs_only=true');
          if (childRes.ok) {
            var childData = await childRes.json();
            dirPickerCache[accumulated] = _filterDirsForPicker(childData.entries || []);
          }
        }
      }

      // Root node is always expanded
      dirPickerExpanded[''] = true;

      // Render the lazy tree
      renderDirTreeLazy(tree, data.name || rootId);

      if (dirPickerSkipped > 0) {
        var note = document.createElement('div');
        note.style.cssText = 'text-align:center;color:var(--text-muted);font-size:11px;padding:6px 0 2px;';
        note.textContent = '已跳过 ' + dirPickerSkipped + ' 个隐藏/缓存目录';
        tree.appendChild(note);
      }
    } catch (e) {
      tree.innerHTML = '<div style="text-align:center;color:var(--danger);padding:20px;">加载目录失败: ' + escHtml(e.message) + '</div>';
    }
  }

  /** Render the lazy directory tree using dirPickerCache / dirPickerExpanded. */
  function renderDirTreeLazy(container, rootName) {
    var folderSvg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;flex-shrink:0;"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>';
    var html = '';
    var rootLabel = rootName || rootId || '';

    // Root entry
    html += '<div class="dir-picker-item" data-dir="" style="display:flex;align-items:center;padding:4px 8px;cursor:pointer;border-radius:4px;margin:1px 0;' + (dirPickerSelectedDir === '' ? 'background:var(--accent);color:#fff;' : '') + '">';
    html += '<span style="width:16px;flex-shrink:0;text-align:center;margin-right:2px;user-select:none;">▼</span>';
    html += folderSvg;
    html += '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escHtml(rootLabel) + ' (根目录)</span>';
    html += '</div>';

    // Children of root
    html += renderDirChildrenHtml('', 1);

    container.innerHTML = html;

    // Click handler — event delegation for expand/collapse + selection
    container.onclick = function(e) {
      var arrow = e.target.closest('.dir-picker-arrow');
      var item = e.target.closest('.dir-picker-item');
      if (!item) return;

      var dir = item.getAttribute('data-dir');

      // Click on arrow: toggle expand/collapse (lazy-load if needed)
      if (arrow) {
        if (dirPickerExpanded[dir]) {
          // Collapse
          dirPickerExpanded[dir] = false;
          renderDirTreeLazy(container, rootName);
        } else if (!dirPickerLoading[dir]) {
          // Expand
          dirPickerExpanded[dir] = true;
          if (dirPickerCache[dir] === undefined) {
            // Not yet loaded — fetch children
            dirPickerLoading[dir] = true;
            renderDirTreeLazy(container, rootName); // show \u23f3 indicator
            fetch('/api/clawmate/list?root=' + encodeURIComponent(rootId)
              + '&dir=' + encodeURIComponent(dir) + '&limit=500&dirs_only=true')
              .then(function(r) { return r.ok ? r.json() : null; })
              .then(function(d) {
                dirPickerCache[dir] = d ? _filterDirsForPicker(d.entries || []) : [];
                dirPickerLoading[dir] = false;
                renderDirTreeLazy(container, rootName);
              })
              .catch(function() {
                dirPickerCache[dir] = [];
                dirPickerLoading[dir] = false;
                renderDirTreeLazy(container, rootName);
              });
          } else {
            // Already cached — just re-render
            renderDirTreeLazy(container, rootName);
          }
        }
        return;
      }

      // Click elsewhere on row: select the directory
      dirPickerSelectedDir = dir;
      var items = container.querySelectorAll('.dir-picker-item');
      for (var i = 0; i < items.length; i++) {
        items[i].style.background = '';
        items[i].style.color = '';
      }
      item.style.background = 'var(--accent)';
      item.style.color = '#fff';
      var selEl = document.getElementById('dirPickerSelected');
      if (selEl) selEl.textContent = dir || rootLabel + ' (根目录)';
    };
  }

  /** Recursively build HTML for children of a given parent directory. */
  function renderDirChildrenHtml(parentPath, depth) {
    var html = '';
    var children = dirPickerCache[parentPath];
    if (!children) return html;

    children.sort(function(a, b) { return a.name.localeCompare(b.name); });

    for (var i = 0; i < children.length; i++) {
      var child = children[i];
      var fullPath = child.path;
      var isExpanded = !!dirPickerExpanded[fullPath];
      var isCached = dirPickerCache[fullPath] !== undefined;
      var isLoading = !!dirPickerLoading[fullPath];
      var isSelected = dirPickerSelectedDir === fullPath;

      html += '<div class="dir-picker-item" data-dir="' + escHtml(fullPath) + '" style="display:flex;align-items:center;padding:4px 8px 4px ' + (8 + depth * 16) + 'px;cursor:pointer;border-radius:4px;margin:1px 0;' + (isSelected ? 'background:var(--accent);color:#fff;' : '') + '">';

      // Arrow / loading indicator / empty spacer
      if (isLoading) {
        html += '<span style="width:16px;flex-shrink:0;text-align:center;margin-right:2px;user-select:none;">\u23f3</span>';
      } else if (isCached && dirPickerCache[fullPath].length === 0) {
        // Known-empty directory — no arrow
        html += '<span style="width:16px;flex-shrink:0;display:inline-block;"></span>';
      } else {
        html += '<span class="dir-picker-arrow" style="width:16px;flex-shrink:0;text-align:center;cursor:pointer;margin-right:2px;user-select:none;">' + (isExpanded ? '\u25bc' : '\u25b6') + '</span>';
      }

      html += '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;flex-shrink:0;"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>';
      html += '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escHtml(child.name) + '</span>';
      html += '</div>';

      // Children (recursive — only render if expanded and has children)
      if (isExpanded && isCached && dirPickerCache[fullPath].length > 0) {
        html += renderDirChildrenHtml(fullPath, depth + 1);
      }
    }

    return html;
  }

  initDirPicker();


  // ============ Move Button ============
  document.getElementById('btnMove').addEventListener('click', function() {
    openDirPicker('move', '移动 "' + fileName + '" 到...');
    dirPickerCallback = async function(destDir) {
      if (destDir === parentDir) {
        showToast('文件已在目标目录中', 2000);
        return;
      }
      try {
        var res = await fetch('/api/clawmate/move', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ root: rootId, path: filePath, destDir: destDir }),
        });
        var data = await res.json();
        if (data.ok) {
          showToast('✅ 已移动到 ' + (destDir || '根目录'), 2000);
          var destForUrl = destDir ? destDir + '/' + data.newName : data.newName;
          var newUrl = 'preview.html?root=' + encodeURIComponent(rootId) + '&file=' + encodeURIComponent(destForUrl);
          setTimeout(function() { window.location.href = newUrl; }, 800);
        } else {
          showToast('❌ 移动失败: ' + (data.detail || '未知错误'), 3000);
        }
      } catch (e) {
        showToast('❌ 移动失败: ' + e.message, 3000);
      }
    };
  });

  // ============ Extract Button ============
  var btnExtract = document.getElementById('btnExtract');
  // Only show extract button for archive files
  if (isArchiveMode) {
    btnExtract.style.display = '';
  } else {
    btnExtract.style.display = 'none';
  }

  btnExtract.addEventListener('click', function() {
    openDirPicker('extract', '解压 "' + fileName + '" 到...');
    dirPickerCallback = async function(destDir) {
      try {
        var res = await fetch('/api/clawmate/extract', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ root: rootId, path: filePath, destDir: destDir }),
        });
        var data = await res.json();
        if (data.ok) {
          showToast('✅ 解压完成，共 ' + data.count + ' 个文件', 3000);
          // Redirect to the destination directory
          var backUrl = '/clawmate/?root=' + encodeURIComponent(rootId) + '&dir=' + encodeURIComponent(destDir);
          setTimeout(function() { window.location.href = backUrl; }, 800);
        } else {
          showToast('❌ 解压失败: ' + (data.detail || '未知错误'), 4000);
        }
      } catch (e) {
        showToast('❌ 解压失败: ' + e.message, 3000);
      }
    };
  });

  document.getElementById('btnDownload').addEventListener('click', () => {
    const link = document.createElement('a');
    link.href = buildDownloadLink(filePath);
    link.target = '_blank';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  });

  // ── Share state & toggle ───────────────────────────────────────────
  var _isShared = false;
  var _btnShareHtml = '';

  function updateShareButton() {
    var btn = document.getElementById('btnShare');
    if (!btn) return;
    if (_isShared) {
      btn.classList.add('active');
      btn.title = '点击取消分享';
    } else {
      btn.classList.remove('active');
      btn.title = '生成分享链接';
    }
  }

  async function checkShareStatus() {
    try {
      var res = await fetch('/api/clawmate/share/active');
      if (res.ok) {
        var data = await res.json();
        var shared = data.shared || {};
        var fileList = shared[rootId] || [];
        _isShared = fileList.indexOf(filePath) !== -1;
      }
    } catch (_) {
      _isShared = false;
    }
    updateShareButton();
  }

  document.getElementById('btnShare').addEventListener('click', async () => {
    var btn = document.getElementById('btnShare');
    // Cache original HTML on first click
    if (!_btnShareHtml) _btnShareHtml = btn.innerHTML;
    btn.disabled = true;

    try {
      if (_isShared) {
        // Already shared — expire it
        btn.textContent = '⏳';
        var res = await fetch('/api/clawmate/share/expire', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ root: rootId, path: filePath }),
        });
        if (res.ok) {
          _isShared = false;
          updateShareButton();
          showToast('已取消分享', 2000);
        } else {
          showToast('❌ 取消分享失败 (' + res.status + ')', 3000);
        }
      } else {
        // Not shared — create share link
        btn.textContent = '⏳';
        var res = await fetch('/api/clawmate/share/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ root: rootId, path: filePath }),
        });
        if (!res.ok) { showToast('❌ 分享链接生成失败 (' + res.status + ')', 3000); return; }
        var data = await res.json();
        await copyText(data.url, '✅ 分享链接已复制到剪贴板');
        showToast('🔗 已复制 · ' + (data.reused ? '有效期已刷新' : '24小时有效'), 3000);
        _isShared = true;
        updateShareButton();
      }
    } catch (e) {
      showToast('❌ ' + e.message, 3000);
    } finally {
      btn.innerHTML = _btnShareHtml;
      btn.disabled = false;
      // Re-sync visual state after restoring innerHTML (class list is preserved)
      updateShareButton();
    }
  });

  document.getElementById('btnDelete').addEventListener('click', async () => {
    if (!confirm(`确定要删除 "${fileName}" 吗？此操作不可恢复！`)) return;
    try {
      const res = await fetch(buildDeleteUrl(filePath), { method: 'DELETE' });
      if (res.ok) {
        window.location.href = backHref;
      } else {
        const err = await res.json().catch(() => ({}));
        showToast('删除失败: ' + (err.error || res.status), 3000);
      }
    } catch (e) {
      showToast('删除失败: ' + e.message, 3000);
    }
  });

  // ============ Version History (git) ============
  var _versionInfo = null;
  var _versionCommits = null;
  var _versionSelIdx = null;
  var _versionSelCommit = null;  // the commit being compared (from)

  async function fetchVersionInfo() {
    var pill = document.getElementById('versionPill');
    var pillHash = document.getElementById('versionPillHash');
    var pillDirty = document.getElementById('versionPillDirty');
    _versionInfo = null;
    if (pill) pill.classList.add('hidden');
    try {
      var res = await fetch('/api/clawmate/version/info?root=' + encodeURIComponent(rootId) + '&path=' + encodeURIComponent(filePath));
      if (!res.ok) return;
      var data = await res.json();
      if (!data.in_git) return;
      _versionInfo = data;
      // Show version pill in topbar
      if (pill && pillHash) {
        if (data.tracked) {
          pillHash.textContent = data.short_hash;
          if (pillDirty) {
            pillDirty.classList.toggle('hidden', !data.is_dirty);
          }
          pill.title = data.message + '\n' + data.author + ' · ' + (data.date ? data.date.substring(0, 10) : '');
        } else {
          pillHash.textContent = 'new';
          pillDirty.classList.add('hidden');
          pill.title = '文件尚未提交';
        }
        pill.classList.remove('hidden');
        pill.onclick = openVersionModal;
      }
      // Version info is shown in topbar pill — no separate button needed
    } catch (_) {}
  }

  async function commitAfterSave() {
    // Git commit after successful file save
    try {
      const res = await fetch('/api/clawmate/version/commit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root: rootId, path: filePath }),
      });
      const data = await res.json();
      if (data.ok) {
        if (data.note === 'no_changes') {
          // Nothing changed, just refresh pill
        } else if (data.short_hash) {
          showToast('✅ 已版本存储 ' + data.short_hash, 2000);
        } else {
          showToast('✅ 已版本存储', 2000);
        }
        // Refresh version pill in topbar
        fetchVersionInfo();
      } else if (data.detail) {
        // Don't show toast for "not in git" — too noisy for non-git files
        if (data.detail.includes('不在 Git')) return;
        showToast('⚠️ ' + data.detail, 3000);
      }
    } catch (_) {
      // Silently ignore commit errors — save succeeded, commit is optional
    }
  }

  function initVersionModal() {
    var modal = document.getElementById('versionModal');
    var closeBtn = document.getElementById('versionModalClose');
    if (!modal || !closeBtn) return;
    closeBtn.addEventListener('click', closeVersionModal);
    modal.addEventListener('click', function(e) {
      if (e.target === modal) closeVersionModal();
    });
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && modal.style.display !== 'none' && modal.style.display !== '') {
        closeVersionModal();
      }
    });
  }

  function closeVersionModal() {
    var modal = document.getElementById('versionModal');
    if (modal) modal.style.display = 'none';
    _versionSelIdx = null;
    _versionSelCommit = null;
  }

  async function openVersionModal() {
    var modal = document.getElementById('versionModal');
    var fnEl = document.getElementById('versionModalFileName');
    if (!modal) return;
    if (fnEl) fnEl.textContent = fileName;
    modal.style.display = 'flex';

    // Reset diff pane
    var dc = document.getElementById('versionDiffContent');
    var dh = document.getElementById('versionDiffHeader');
    if (dh) dh.textContent = '加载中...';
    if (dc) dc.innerHTML = '<div class="version-diff-placeholder">加载差异...</div>';

    // Latest info card
    var lc = document.getElementById('versionLatestCard');
    if (lc && _versionInfo) {
      if (_versionInfo.tracked) {
        var c = _versionInfo;
        var dirtyHtml = c.is_dirty ? ' <span style="color:#f59e0b;">(有未提交变更)</span>' : '';
        lc.innerHTML =
          '<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">' +
            '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>' +
            '<span style="font-weight:600;font-size:13px;color:var(--text-primary);">最新版本</span>' +
            '<span style="font-family:monospace;font-size:11px;color:var(--accent);">' + escHtml(c.short_hash) + '</span>' +
          '</div>' +
          '<div style="font-size:12px;color:var(--text-secondary);">' + escHtml(c.message) + '</div>' +
          '<div style="font-size:11px;color:var(--text-muted);margin-top:2px;">' +
            escHtml(c.author) + ' · ' + (c.date ? c.date.substring(0, 10) : '') + dirtyHtml +
          '</div>';
      } else {
        lc.innerHTML = '<div style="color:var(--text-muted);font-size:13px;text-align:center;padding:8px;">📄 新文件，尚未提交</div>';
      }
    }

    // Dirty warning
    var dw = document.getElementById('versionDirtyWarning');
    if (dw) dw.classList.toggle('hidden', !(_versionInfo && _versionInfo.tracked && _versionInfo.is_dirty));

    // Footer
    var footer = document.getElementById('versionModalFooter');
    if (footer && _versionInfo) {
      if (_versionInfo.tracked) {
        footer.textContent = '点击单个 commit 查看该版本引入的变更';
      } else {
        footer.textContent = '文件尚未提交到 Git 仓库';
      }
    }

    // Load commit list
    await loadVersionCommitList();
  }

  async function loadVersionCommitList() {
    var listEl = document.getElementById('versionCommitList');
    if (!listEl) return;
    listEl.innerHTML = '<div class="version-commit-empty">加载中...</div>';

    try {
      var res = await fetch('/api/clawmate/version/log?root=' + encodeURIComponent(rootId) + '&path=' + encodeURIComponent(filePath) + '&max_count=30');
      if (!res.ok) { listEl.innerHTML = '<div class="version-commit-empty">加载失败</div>'; return; }
      var data = await res.json();
      if (!data.in_git || !data.commits || data.commits.length === 0) {
        listEl.innerHTML = '<div class="version-commit-empty">' + (data.in_git ? '新文件，尚无提交历史' : '此文件不在 Git 仓库中') + '</div>';
        return;
      }
      _versionCommits = data.commits;

      var html = '';
      for (var i = 0; i < data.commits.length; i++) {
        var c = data.commits[i];
        var dateStr = c.date ? c.date.substring(0, 10) : '';
        html += '<div class="version-commit-item" data-idx="' + i + '">' +
          '<div class="version-commit-message">' + escHtml(c.message) + '</div>' +
          '<div class="version-commit-meta">' +
            '<span class="version-commit-hash">' + escHtml(c.short_hash) + '</span>' +
            '<span class="version-commit-author">' + escHtml(c.author) + '</span>' +
            '<span>' + dateStr + '</span>' +
          '</div>' +
        '</div>';
      }
      listEl.innerHTML = html;

      listEl.querySelectorAll('.version-commit-item').forEach(function(el) {
        el.addEventListener('click', function() {
          var idx = parseInt(this.dataset.idx);
          selectVersionCommit(idx);
        });
      });

      // Auto-select first commit (HEAD)
      _versionSelIdx = null;
      _versionSelCommit = null;
      selectVersionCommit(0);
    } catch (e) {
      listEl.innerHTML = '<div class="version-commit-empty">加载失败: ' + escHtml(e.message) + '</div>';
    }
  }

  async function selectVersionCommit(idx) {
    if (!_versionCommits || idx < 0 || idx >= _versionCommits.length) return;
    _versionSelIdx = idx;
    _versionSelCommit = _versionCommits[idx];

    // Highlight selected
    document.querySelectorAll('.version-commit-item').forEach(function(el, i) {
      el.classList.toggle('selected', i === idx);
    });

    var commit = _versionCommits[idx];

    // Determine diff range: show what THIS commit introduced (commit vs parent)
    var fromHash = commit.hash;
    var parentIdx = idx + 1;
    var url = '/api/clawmate/version/diff?root=' + encodeURIComponent(rootId) +
      '&path=' + encodeURIComponent(filePath) +
      '&from=' + encodeURIComponent(fromHash);

    if (parentIdx < _versionCommits.length) {
      url += '&to=' + encodeURIComponent(_versionCommits[parentIdx].hash);
    }

    // Update diff header
    var dh = document.getElementById('versionDiffHeader');
    if (dh) dh.textContent = commit.short_hash + ' — ' + commit.message;

    // Load diff
    await loadVersionDiff(url);
  }

  async function loadVersionDiff(url) {
    var dc = document.getElementById('versionDiffContent');
    if (!dc) return;
    dc.innerHTML = '<div class="version-diff-placeholder">加载差异...</div>';

    try {
      var res = await fetch(url);
      if (!res.ok) { dc.innerHTML = '<div class="version-diff-placeholder">加载差异失败</div>'; return; }
      var data = await res.json();
      if (!data.in_git) { dc.innerHTML = '<div class="version-diff-placeholder">无差异信息</div>'; return; }
      if (data.binary) { dc.innerHTML = '<div class="version-diff-placeholder">二进制文件，无法显示差异</div>'; return; }
      if (!data.diff || data.diff.trim() === '') { dc.innerHTML = '<div class="version-diff-placeholder">无变更内容</div>'; return; }

      dc.innerHTML = renderVersionDiff(data.diff);
    } catch (e) {
      dc.innerHTML = '<div class="version-diff-placeholder">加载失败: ' + escHtml(e.message) + '</div>';
    }
  }

  function renderVersionDiff(diffText) {
    var lines = diffText.split('\n');
    var html = '<pre class="version-diff-pre">';

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      // Skip file header lines (--- a/... and +++ b/...)
      if (line.startsWith('--- ') || line.startsWith('+++ ')) continue;

      var cls = 'version-diff-line';
      if (line.startsWith('@@')) {
        cls += ' version-diff-line-hunk';
      } else if (line.charAt(0) === '+') {
        cls += ' version-diff-line-add';
      } else if (line.charAt(0) === '-') {
        cls += ' version-diff-line-del';
      }

      html += '<div class="' + cls + '">' + escHtml(line) + '</div>';
    }

    html += '</pre>';
    return html;
  }

  // ============ Feedback Panel ============
  let pendingItems = [];  // { id, text, startLine, endLine, note, type }
  let completedItems = [];
  let idCounter = 0;
  let selectedPendingId = null;

  // Per-type pending items for media / office / image
  let mediaPendingItems = [];
  let officePdfPendingItems = [];
  let imagePendingItems = [];

  // ============ Feedback Card Factory ============
  // Unified factory for creating pending feedback cards.
  // Used by: tooltip "加入待办", panel "+ 添加反馈", and renderFeedbackPanel.
  function createFeedbackCard(item) {
    var card = document.createElement('div');
    var extraClass = (item.id === selectedPendingId ? ' selected' : '');
    if (item._isNew) { extraClass += ' fb-card-new'; }
    card.className = 'fb-card' + extraClass;
    card.dataset.id = item.id;
    if (item._isNew) {
      card.addEventListener('animationend', function () { card.classList.remove('fb-card-new'); });
      item._isNew = false;
    }

    // Determine item type (default to 'text' for line-number based positioning)
    const itemType = item.type || 'text';

    // Assign creation timestamp if not set
    if (!item.created) item.created = new Date().toISOString();

    // Header: position display + delete button (top-right corner)
    const headerRow = document.createElement('div');
    headerRow.style.cssText = 'display:flex;align-items:center;justify-content:space-between;';
    const locationEl = document.createElement('span');
    locationEl.style.cssText = 'font-size:11px;color:var(--text-muted);font-family:monospace;';
    const createdDate = item.created ? new Date(item.created) : new Date();
    const ts = `${String(createdDate.getMonth()+1).padStart(2,'0')}-${String(createdDate.getDate()).padStart(2,'0')} ${String(createdDate.getHours()).padStart(2,'0')}:${String(createdDate.getMinutes()).padStart(2,'0')}`;
    locationEl.textContent = ts;
    headerRow.appendChild(locationEl);
    const delBtn = document.createElement('button');
    delBtn.className = 'fb-btn-delete';
    delBtn.textContent = '✕';
    delBtn.addEventListener('click', e => {
      e.stopPropagation();
      if (isImageMode) {
        imagePendingItems = imagePendingItems.filter(i => i.id !== item.id);
      } else if (isMediaMode) {
        mediaPendingItems = mediaPendingItems.filter(i => i.id !== item.id);
      } else if (isOfficePdfMode) {
        officePdfPendingItems = officePdfPendingItems.filter(i => i.id !== item.id);
      } else {
        pendingItems = pendingItems.filter(i => i.id !== item.id);
      }
      if (selectedPendingId === item.id) selectedPendingId = null;
      clearHL();
      // Re-render the appropriate panel
      if (isImageMode) renderImageFeedbackPanel();
      else if (isMediaMode) renderMediaFeedbackPanel();
      else if (isOfficePdfMode) renderOfficePdfFeedbackPanel();
      else renderFeedbackPanel();
    });
    headerRow.appendChild(delBtn);
    card.appendChild(headerRow);

    // Position editable input — format depends on item type
    const posInput = document.createElement('input');
    posInput.type = 'text';
    posInput.className = 'fb-card-position-edit';
    // 优先用 item.position，回退到 startLine 组合
    var _posVal = item.position || '';
    if (!_posVal && item.startLine > 0) {
      _posVal = 'Line ' + item.startLine + '-' + item.endLine;
    }
    posInput.value = _posVal;
    if (itemType === 'text') {
      posInput.placeholder = 'Line {start}-{end} — 手动填写位置';
    } else if (itemType === 'markdown') {
      posInput.placeholder = 'Section {heading} / Line {start}-{end}';
    } else {
      posInput.placeholder = itemType === 'media' ? 'Time {HH:MM:SS} — 时间戳' :
                             itemType === 'office' ? 'Page {start}-{end} / Range {col}{row}-{col}{row}' :
                             itemType === 'image' ? 'Area [x,y]xR — 区域' : '位置';
    }
    posInput.title = '位置（可编辑）';
    posInput.addEventListener('input', () => {
      item.position = posInput.value;
      var m = posInput.value.match(/(\d+)(?:-(\d+))?/);
      if (m) {
        item.startLine = parseInt(m[1], 10);
        item.endLine = m[2] ? parseInt(m[2], 10) : item.startLine;
      }
    });
    posInput.addEventListener('click', e => e.stopPropagation());
    card.appendChild(posInput);

    // Selected content preview (editable textarea) — not shown for image
    if (itemType !== 'image') {
      const selInput = document.createElement('textarea');
      selInput.className = 'fb-note-input';
      selInput.value = item.text || '';
      selInput.placeholder = '<选填>粘贴针对的文中内容';
      selInput.rows = 2;
      selInput.style.cssText = 'font-size:11px;color:var(--text-muted);font-family:monospace;background:var(--bg-code);border-radius:4px;padding:6px 8px;white-space:pre-wrap;word-break:break-all;line-height:1.4;border:1px solid var(--border-color);width:100%;box-sizing:border-box;resize:vertical;';
      selInput.addEventListener('input', () => { item.text = selInput.value; });
      selInput.addEventListener('click', e => e.stopPropagation());
      card.appendChild(selInput);
    }

    // Note textarea — always present, always editable
    // Note textarea — always present, always editable
    const noteInput = document.createElement('textarea');
    noteInput.className = 'fb-note-input';
    noteInput.placeholder = '<必填>简要说明改动需求';
    noteInput.value = item.note || '';
    noteInput.rows = 3;
    noteInput.readOnly = false;
    noteInput.disabled = false;
    noteInput.addEventListener('input', () => { item.note = noteInput.value; });
    noteInput.addEventListener('click', e => e.stopPropagation());
    card.appendChild(noteInput);

    // Tag / action 选择按钮组（从 task_templates 动态加载）
    const tagRow = document.createElement('div');
    tagRow.style.cssText = 'display:flex;gap:4px;flex-wrap:wrap;margin-top:4px;';
    var _ext = (filePath || '').split('.').pop().toLowerCase();
    var _tagMap = _taskTemplates.length ? _taskTemplates.filter(function(t) {
      return t.source === 'selection' &&
        (t.match_ext.indexOf('*') >= 0 || t.match_ext.indexOf(_ext) >= 0);
    }) : [];
    // 当 _taskTemplates 为空时使用硬编码兜底（兼容旧部署）
    if (!_tagMap.length) {
      _tagMap = [
        { label: '🗑 删除', action: 'delete', scope: 'document' },
        { label: '🔧 修改', action: 'modify', scope: 'document' },
        { label: '📈 扩展', action: 'explain', scope: 'document' },
        { label: '📉 简化', action: 'simplify', scope: 'document' },
        { label: '⚡ 执行', action: 'execute', scope: 'project' },
      ];
    }
    _tagMap.forEach(function(t) {
      const btn = document.createElement('button');
      btn.textContent = t.label;
      const isActive = item.action === t.action;
      btn.style.cssText = `font-size:11px;padding:2px 6px;border-radius:4px;border:1px solid ${isActive ? 'var(--accent)' : 'var(--border-color)'};background:${isActive ? 'var(--accent)' : 'var(--bg-secondary)'};color:${isActive ? '#fff' : 'var(--text-primary)'};cursor:pointer;transition:all 0.15s;font-weight:${isActive ? '600' : '400'};`;
      btn.addEventListener('click', function(e) {
        e.stopPropagation();
        if (item.action === t.action) {
          delete item.action;
          delete item.scope;
        } else {
          item.action = t.action;
          item.scope = t.scope;
          if (t.action === 'execute' && typeof filePath !== 'undefined') {
            item.text = '读取文件' + filePath;
          }
        }
        if (isImageMode) renderImageFeedbackPanel();
        else if (isMediaMode) renderMediaFeedbackPanel();
        else if (isOfficePdfMode) renderOfficePdfFeedbackPanel();
        else renderFeedbackPanel();
      });
      tagRow.appendChild(btn);
    });
    card.appendChild(tagRow);

    // Execute button at bottom
    const actions = document.createElement('div');
    actions.className = 'fb-card-actions';
    actions.style.cssText = 'display:flex;gap:8px;margin-top:4px;';
    const submitBtn = document.createElement('button');
    submitBtn.className = 'fb-btn-submit';
    submitBtn.textContent = '立刻执行';
    submitBtn.addEventListener('click', e => {
      e.stopPropagation();
      if (submitBtn.disabled) return;
      submitBtn.disabled = true;
      submitBtn.textContent = '⏳ 执行中...';
      submitSingleItem(item).finally(() => {
        submitBtn.disabled = false;
        submitBtn.textContent = '立刻执行';
      });
    });
    actions.appendChild(submitBtn);
    card.appendChild(actions);

    // Click card to select/highlight (skip scrollToText for non-text types)
    card.addEventListener('click', (e) => {
      // Clicking input/button/textarea/select should not trigger card selection
      if (e.target.closest('input, textarea, button, select')) return;
      if (selectedPendingId === item.id) {
        selectedPendingId = null;
        clearHL();
      } else {
        selectedPendingId = item.id;
        // Only attempt scroll-to for text/markdown content
        if ((itemType === 'text' || itemType === 'markdown') && item.text) {
          scrollToText(item.text);
        }
      }
      // Re-render the appropriate panel
      if (isImageMode) renderImageFeedbackPanel();
      else if (isMediaMode) renderMediaFeedbackPanel();
      else if (isOfficePdfMode) renderOfficePdfFeedbackPanel();
      else renderFeedbackPanel();
    });

    return card;
  }

  function renderFeedbackPanel() {
    var body = document.getElementById('feedbackBody');
    body.innerHTML = '';

    // Fixed top row: buttons stay at top
    var topBar = document.createElement('div');
    topBar.className = 'fb-topbar';
    body.appendChild(topBar);

    // Scrollable card list
    var cardList = document.createElement('div');
    cardList.className = 'fb-card-list';
    body.appendChild(cardList);

    // === Unified top row: always show "+ 添加反馈" + "✅ 全部提交" ===


    const addBtn = document.createElement('button');
    addBtn.className = 'fb-btn-submit';
    addBtn.textContent = '+ 添加反馈';
    addBtn.addEventListener('click', () => {
      // Create a pending item and render it as a card in the pending section
      const item = { id: ++idCounter, text: '', startLine: 0, endLine: 0, note: '', type: 'text', _isNew: true };
      pendingItems.push(item);
      renderFeedbackPanel();
    });
    topBar.appendChild(addBtn);

    const submitAllBtn = document.createElement('button');
    submitAllBtn.className = 'fb-btn-submit-all';
    const hasPending = pendingItems.length > 0;
    submitAllBtn.style.cssText = `flex:1;padding:4px 8px;border-radius:6px;border:1px solid var(--border-color);background:var(--btn-bg);color:var(--btn-text);cursor:${hasPending ? 'pointer' : 'not-allowed'};font-size:13px;font-weight:600;opacity:${hasPending ? '1' : '0.5'};`;
    if (hasPending) {
      submitAllBtn.className = 'fb-btn-submit';
      submitAllBtn.textContent = '全部提交（' + pendingItems.length + '）';
      submitAllBtn.disabled = false;
      submitAllBtn.addEventListener('click', function () {
        var missing = pendingItems.filter(function (i) { return !i.action; });
        if (missing.length > 0) {
          missing.forEach(function (m) {
            var card = document.querySelector('.fb-card[data-id="' + (m.id || '') + '"]');
            if (card) {
              var existing = card.querySelector('.fb-card-error');
              if (existing) existing.remove();
              var err = document.createElement('div');
              err.className = 'fb-card-error';
              err.textContent = '请选择操作类型';
              card.appendChild(err);
              setTimeout(function () { if (err.parentNode) err.remove(); }, 5000);
            }
          });
          showToast('有 ' + missing.length + ' 条未选择操作类型', 3000);
          return;
        }
        submitAllItems(submitAllBtn, { itemType: 'text' });
      });
    } else {
      submitAllBtn.className = 'fb-btn-submit-all';
      submitAllBtn.textContent = '全部提交';
      submitAllBtn.disabled = true;
    }
    topBar.appendChild(submitAllBtn);

    // Empty state: only top row + hint
    if (pendingItems.length === 0 && completedItems.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'fb-empty';
      empty.style.marginTop = '12px';
      empty.textContent = '选中文本后点击「📋 加入待办」即可累积';
      cardList.appendChild(empty);
      return;
    }

    // Pending section
    if (pendingItems.length > 0) {
      [...pendingItems].reverse().forEach(function (item) {
        cardList.appendChild(createFeedbackCard(item));
      });
    }

    // Completed section
    if (completedItems.length > 0) {
      completedItems.forEach(function (item) {
        cardList.appendChild(renderCompletedFeedbackCard(item));
      });
    }
  }

  // ============ Unified Feedback Input Card (add-feedback popup) ============
  function showFeedbackInputCard(body, opts) {
    opts = opts || {};
    const {
      type = 'text',
      defaultPosition = '',
      positionPlaceholder = '',
      extraSelectionText = '',
      onSubmit = null,
    } = opts;

    // Remove any existing input card
    const existing = document.getElementById('fbInputCard');
    if (existing) existing.remove();

    const card = document.createElement('div');
    card.id = 'fbInputCard';
    card.className = 'fb-input-card';

    // All types use free-text input with type-specific placeholder
    positionHTML = `<input type="text" id="fbPosInput" class="fb-input-field position" value="${escHtml(defaultPosition)}" placeholder="${escHtml(positionPlaceholder)}" />`;

    card.innerHTML = `
      <div class="fb-input-card-header">📍 反馈位置</div>
      <div class="fb-input-row">
        <span class="fb-input-label">位置</span>
        ${positionHTML}
      </div>
      <textarea id="fbNoteInput" class="fb-input-field" placeholder="备注（必填）" rows="3"></textarea>
      <textarea id="fbSelInput" class="fb-input-field" placeholder="选区内容（可选）" rows="2" style="font-size:11px;color:var(--text-muted);">${escHtml(extraSelectionText)}</textarea>
      <div class="fb-input-actions">
        <button id="fbCancelBtn" class="fb-input-cancel">取消</button>
        <button id="fbSubmitBtn" class="fb-input-submit">提交</button>
      </div>
      <div id="fbStatusText" class="fb-input-status"></div>
    `;

    body.insertBefore(card, body.firstChild);
    body.scrollTop = 0;

    document.getElementById('fbCancelBtn').addEventListener('click', () => card.remove());
    document.getElementById('fbSubmitBtn').addEventListener('click', async () => {
      let position = document.getElementById('fbPosInput').value.trim();
      const note = document.getElementById('fbNoteInput').value.trim();
      const selection = document.getElementById('fbSelInput').value.trim();
      const statusEl = document.getElementById('fbStatusText');

      if (!note) {
        statusEl.textContent = '⚠️ 请填写备注';
        statusEl.className = 'fb-input-status error';
        document.getElementById('fbNoteInput').focus();
        return;
      }

      statusEl.textContent = '提交中...';
      statusEl.className = 'fb-input-status loading';

      try {
        const res = await fetch('/api/clawmate/task/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            root: rootId,
            file: filePath,
            selections: [{ task_id: 'review_modify', content: selection || note, note: note || '', position: position || note }],
          }),
        });
        const data = await res.json();
        if (data.ok) {
          statusEl.textContent = '✅ 已提交';
          statusEl.className = 'fb-input-status ok';
          // Immediately close the card and auto-open sidebar
          setTimeout(function() { card.remove(); }, 400);
          // Auto-open right sidebar
          if (rightSidebar.classList.contains('hidden')) {
            openRightSidebar();
            document.getElementById('btnToggleRight').classList.add('active');
          }
          // Start polling with returned IDs
          var ids = data.ids || [];
          _startDesktopPolling(ids, reloadCurrentFeedback);
          if (onSubmit) {
            setTimeout(function() { onSubmit(); }, 100);
          }
        } else {
          statusEl.textContent = '❌ ' + (data.detail || '提交失败');
          statusEl.className = 'fb-input-status error';
        }
      } catch (e) {
        statusEl.textContent = '❌ 网络错误';
        statusEl.className = 'fb-input-status error';
      }
    });
  }

  async function reloadCurrentFeedback() {
    if (isImageMode) await loadImageCompletedFeedback();
    else if (isMediaMode) await loadMediaCompletedFeedback();
    else if (isOfficePdfMode) await loadOfficePdfCompletedFeedback();
    else await loadCompletedFeedback();
    // Auto-start sidebar refresh timer if sidebar is visible
    if (!rightSidebar.classList.contains('hidden')) {
      _startSidebarRefresh();
    }
  }

  // ============ Unified Completed Feedback Card Renderer ============
  function renderCompletedFeedbackCard(item) {
    var statusLabel =
      item.status === 'done'       ? 'DONE' :
      item.status === 'in_progress' ? 'IN PROGRESS' :
      item.status === 'failed'     ? 'FAILED' : 'PENDING';
    var statusIcon = '<span class="fb-status-pill ' + (item.status || 'pending') + '">' + statusLabel + '</span>';

    // Truncate selection display at 80 chars
    const selText = item.selection_content || item.text || '';
    const selDisplay = selText.length > 80 ? selText.substring(0, 80) + '…' : selText;

    const card = document.createElement('div');
    card.className = 'fb-card fb-card-completed';

    // Build header with delete button
    const header = document.createElement('div');
    header.className = 'fb-card-header';
    header.style.cssText = 'display:flex;align-items:center;justify-content:space-between;';
    const left = document.createElement('div');
    left.style.cssText = 'display:flex;align-items:center;gap:6px;';
    left.innerHTML = `<span class="fb-card-status">${statusIcon}</span><span class="fb-card-id">${escHtml(item.id || '')}</span><span class="fb-card-time">${(item.updated || '').substring(5, 16)}</span>`;
    const delBtn = document.createElement('button');
    delBtn.className = 'fb-btn-delete';
    delBtn.textContent = '✕';
    delBtn.style.cssText = 'background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:12px;padding:2px 4px;';
    delBtn.title = '删除此反馈';
    delBtn.addEventListener('click', async e => {
      e.stopPropagation();
      if (!confirm('确定删除此反馈？')) return;
      try {
        const f = item.file || (filePath ? filePath.split('/').pop() : '');
        await fetch('/api/clawmate/feedback/update', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ root: rootId, project, path: filePath || '', id: item.id, status: 'deleted' }),
        });
        // Remove from appropriate completed array and re-render
        if (isImageMode) {
          imageCompletedItems = imageCompletedItems.filter(i => i.id !== item.id);
          renderImageFeedbackPanel();
        } else if (isMediaMode) {
          mediaCompletedItems = mediaCompletedItems.filter(i => i.id !== item.id);
          renderMediaFeedbackPanel();
        } else if (isOfficePdfMode) {
          officePdfCompletedItems = officePdfCompletedItems.filter(i => i.id !== item.id);
          renderOfficePdfFeedbackPanel();
        } else {
          completedItems = completedItems.filter(i => i.id !== item.id);
          renderFeedbackPanel();
        }
      } catch (_) {}
    });
    header.appendChild(left);
    header.appendChild(delBtn);
    card.appendChild(header);

    if (selDisplay) {
      const sel = document.createElement('div');
      sel.className = 'fb-card-selection';
      sel.textContent = selDisplay;
      card.appendChild(sel);
    }
    const note = document.createElement('div');
    note.className = 'fb-card-note';
    note.textContent = item.user_note || item.note || '（无备注）';
    card.appendChild(note);
    const pos = document.createElement('div');
    pos.className = 'fb-card-position';
    pos.textContent = item.position || item.location || '';
    card.appendChild(pos);

    // 处理结果: only show for done/failed items with result text
    const isDoneFailed = item.status === 'done' || item.status === 'failed';
    if (isDoneFailed && (item.result || item.processing_result)) {
      const resDiv = document.createElement('div');
      resDiv.className = 'fb-card-result';
      const txt = (item.result || item.processing_result || '');
      resDiv.textContent = '📋 ' + (txt.length > 100 ? txt.substring(0, 100) + '…' : txt);
      card.appendChild(resDiv);
    }

    // Click to show detail modal with full info
    card.addEventListener('click', e => {
      if (e.target.closest('button')) return; // skip button clicks
      showFeedbackDetailModal(item, statusIcon);
    });

    return card;
  }

  // ============ Feedback Detail Modal ============
  function showFeedbackDetailModal(item, statusIcon) {
    // Remove existing modal if any
    var existing = document.querySelector('.fb-detail-overlay');
    if (existing) existing.remove();

    var overlay = document.createElement('div');
    overlay.className = 'fb-detail-overlay';

    var modal = document.createElement('div');
    modal.className = 'fb-detail-modal';

    // Header
    var hdr = document.createElement('div');
    hdr.className = 'fb-detail-header';
    hdr.innerHTML = '<div class="fb-detail-header-left">' +
      '<span>' + (statusIcon || '📋') + '</span>' +
      '<span>' + escHtml(item.id || '') + '</span>' +
      '</div>';
    var closeBtn = document.createElement('button');
    closeBtn.className = 'fb-detail-close';
    closeBtn.textContent = '✕';
    closeBtn.addEventListener('click', function() { overlay.remove(); });
    hdr.appendChild(closeBtn);

    // Body
    var body = document.createElement('div');
    body.className = 'fb-detail-body';

    function addRow(label, value, cls) {
      if (!value) return;
      var row = document.createElement('div');
      row.className = 'fb-detail-row';
      row.innerHTML = '<div class="fb-detail-label">' + label + '</div>' +
        '<div class="fb-detail-value' + (cls ? ' ' + cls : '') + '">' + escHtml(value) + '</div>';
      body.appendChild(row);
    }

    addRow('文件', item.file || '');
    addRow('选中位置', item.position || item.location || '');
    addRow('选区内容', item.selection_content || item.text || item.content || '', 'selection');
    addRow('用户备注', item.user_note || item.note || '', 'selection');
    addRow('处理结果', item.result || item.processing_result || '', 'result');
    addRow('更新时间', item.updated || '');

    modal.appendChild(hdr);
    modal.appendChild(body);
    overlay.appendChild(modal);

    // Click overlay to close (but not modal itself)
    overlay.addEventListener('click', function(e) {
      if (e.target === overlay) overlay.remove();
    });
    // Escape key to close
    var escHandler = function(e) { if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', escHandler); } };
    document.addEventListener('keydown', escHandler);

    document.body.appendChild(overlay);
  }

  let imageCompletedItems = [];

  function renderImageFeedbackPanel() {
    const body = document.getElementById('feedbackBody');
    body.innerHTML = '';

    var topBar = document.createElement('div');
    topBar.className = 'fb-topbar';
    body.appendChild(topBar);

    var cardList = document.createElement('div');
    cardList.className = 'fb-card-list';
    body.appendChild(cardList);

    // Top row: Add feedback + Submit all


    const addBtn = document.createElement('button');
    addBtn.className = 'fb-btn-submit';
    addBtn.textContent = '+ 添加反馈';
    addBtn.addEventListener('click', () => {
      const item = { id: ++idCounter, text: '', startLine: 0, endLine: 0, note: '', type: 'image', position: '' };
      imagePendingItems.push(item);
      renderImageFeedbackPanel();
      const newCard = body.querySelector(`.fb-card[data-id="${item.id}"]`);
      if (newCard) newCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    topBar.appendChild(addBtn);

    const submitAllBtn = document.createElement('button');
    submitAllBtn.className = 'fb-btn-submit-all';
    const hasPending = imagePendingItems.length > 0;
    submitAllBtn.style.cssText = `flex:1;padding:4px 8px;border-radius:6px;border:1px solid var(--border-color);background:var(--btn-bg);color:var(--btn-text);cursor:${hasPending ? 'pointer' : 'not-allowed'};font-size:13px;font-weight:600;opacity:${hasPending ? '1' : '0.5'};`;
    submitAllBtn.textContent = hasPending ? `✅ 全部提交（${imagePendingItems.length} 条）` : '✅ 全部提交';
    submitAllBtn.disabled = !hasPending;
    if (hasPending) {
      submitAllBtn.addEventListener('click', () => {
        const missing = imagePendingItems.filter(i => !i.note || !i.position);
        if (missing.length > 0) {
          showToast('请填写备注和位置后再提交', 2000);
          return;
        }
        submitAllItems(submitAllBtn, {
          pendingArray: imagePendingItems,
          onReload: loadImageCompletedFeedback,
          itemType: 'image',
        });
      });
    }
    topBar.appendChild(submitAllBtn);

    // Empty state
    if (imagePendingItems.length === 0 && imageCompletedItems.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'fb-empty';
      empty.style.marginTop = '12px';
      empty.textContent = '点击「+ 添加反馈」开始';
      cardList.appendChild(empty);
      return;
    }

    // Pending items
    if (imagePendingItems.length > 0) {
      [...imagePendingItems].reverse().forEach(item => cardList.appendChild(createFeedbackCard(item)));
    }

    // Completed items
    if (imageCompletedItems.length > 0) {
      const sep = document.createElement('div');
      sep.className = 'fb-section-sep';
      sep.innerHTML = '<span>✅ 已提交</span>';
      cardList.appendChild(sep);
      imageCompletedItems.forEach(item => cardList.appendChild(renderCompletedFeedbackCard(item)));
    }
  }

  async function loadImageCompletedFeedback() {
    // Render panel immediately to show topbar buttons, then populate data
    renderImageFeedbackPanel();
    if (!rootId || !project || !filePath) return;
    const fn = filePath.split('/').pop();
    try {
      const res = await fetch(`/api/clawmate/feedback/list?root=${encodeURIComponent(rootId)}&project=${encodeURIComponent(project)}&file=${encodeURIComponent(fn)}`);
      if (!res.ok) return;
      const data = await res.json();
      imageCompletedItems = (data.items || []).filter(i => i.status !== 'deleted').sort((a, b) => (b.updated || '').localeCompare(a.updated || ''));
      renderImageFeedbackPanel();
    } catch (_) {}
  }

  async function loadCompletedFeedback() {
    if (isImageMode) {
      await loadImageCompletedFeedback();
      return;
    }
    if (isMediaMode) {
      await loadMediaCompletedFeedback();
      return;
    }
    // Render panel immediately to show topbar buttons, then populate data
    renderFeedbackPanel();
    if (!rootId || !project || !filePath) return;
    const fn = filePath.split('/').pop();
    try {
      const res = await fetch(`/api/clawmate/feedback/list?root=${encodeURIComponent(rootId)}&project=${encodeURIComponent(project)}&file=${encodeURIComponent(fn)}`);
      if (!res.ok) return;
      const data = await res.json();
      completedItems = (data.items || []).filter(i => i.status !== 'deleted').sort((a, b) => (b.updated || '').localeCompare(a.updated || ''));
      renderFeedbackPanel();
    } catch (_) {}
  }

  // ── Desktop polling: refresh completed items until all submitted IDs are done/failed ──
  var _desktopPollTimer = null;
  var _desktopPollIds = [];

  function _getCompletedItemsForMode() {
    if (isImageMode) return imageCompletedItems;
    if (isMediaMode) return mediaCompletedItems;
    if (isOfficePdfMode) return officePdfCompletedItems;
    return completedItems;
  }

  function _startDesktopPolling(ids, reloadFn) {
    if (_desktopPollTimer) { clearInterval(_desktopPollTimer); _desktopPollTimer = null; }
    _desktopPollIds = ids || [];
    // Do an immediate reload
    if (reloadFn) reloadFn();
    if (!_desktopPollIds.length) return; // no IDs to track, one-shot reload is enough

    var attempts = 0;
    var MAX_ATTEMPTS = 30; // ~4 minutes at 8s intervals
    var headerEl = document.querySelector('.preview-right-header span');
    var _origHeaderText = headerEl ? headerEl.textContent : '💬 反馈';

    _desktopPollTimer = setInterval(async function() {
      attempts++;
      if (attempts > MAX_ATTEMPTS) {
        clearInterval(_desktopPollTimer);
        _desktopPollTimer = null;
        if (reloadFn) await reloadFn();
        if (headerEl) headerEl.textContent = _origHeaderText;
        return;
      }
      if (reloadFn) await reloadFn();
      var allItems = _getCompletedItemsForMode();
      var tracked = allItems.filter(function(it) { return _desktopPollIds.indexOf(it.id) >= 0; });
      if (tracked.length === 0) {
        // Items not yet in the list (still being created), keep polling
        if (headerEl) headerEl.textContent = '⏳ 反馈';
        return;
      }
      var doneCount = tracked.filter(function(it) { return it.status === 'done'; }).length;
      var failCount = tracked.filter(function(it) { return it.status === 'failed'; }).length;
      var total = tracked.length;
      if (doneCount + failCount >= total) {
        // All items resolved
        clearInterval(_desktopPollTimer);
        _desktopPollTimer = null;
        if (headerEl) headerEl.textContent = _origHeaderText;
        if (reloadFn) await reloadFn();
        // Auto-open right sidebar if it was hidden
        if (rightSidebar.classList.contains('hidden')) {
          openRightSidebar();
        }
        _startSidebarRefresh();
      } else {
        if (headerEl) headerEl.textContent = '⏳ 反馈 (' + (doneCount + failCount) + '/' + total + ')';
      }
    }, 8000);
  }

  // Clean up desktop poll timer on page unload
  window.addEventListener('beforeunload', function() {
    if (_desktopPollTimer) { clearInterval(_desktopPollTimer); _desktopPollTimer = null; }
    if (_sidebarRefreshTimer) { clearInterval(_sidebarRefreshTimer); _sidebarRefreshTimer = null; }
  });

  // ── Sidebar auto-refresh: poll feedback list every 10s while right sidebar is visible ──
  var _sidebarRefreshTimer = null;

  function _startSidebarRefresh() {
    if (_sidebarRefreshTimer) return; // already running
    _sidebarRefreshTimer = setInterval(function() {
      if (rightSidebar.classList.contains('hidden')) {
        // Sidebar was closed externally — stop
        clearInterval(_sidebarRefreshTimer);
        _sidebarRefreshTimer = null;
        return;
      }
      reloadCurrentFeedback();
    }, 10000);
  }

  function _stopSidebarRefresh() {
    if (_sidebarRefreshTimer) {
      clearInterval(_sidebarRefreshTimer);
      _sidebarRefreshTimer = null;
    }
  }

  function buildTaskSelection(item) {
    // 将 feedback panel 的 item 转为 task/run 的 selection 格式
    const taskId = item.task_id || (item.action ? 'review_' + item.action : 'review_modify');
    return { task_id: taskId, content: item.text || item.content || '', note: item.note || '', position: item.position || '' };
  }

  async function submitSingleItem(item) {
    if (!item.action) {
      // Show inline error on the card (not a disappearing toast)
      var card = document.querySelector('.fb-card[data-id="' + (item.id || '') + '"]');
      if (card) {
        var existing = card.querySelector('.fb-card-error');
        if (existing) existing.remove();
        var err = document.createElement('div');
        err.className = 'fb-card-error';
        err.textContent = '请先选择操作类型（修改/删除/扩展/简化/执行）';
        card.appendChild(err);
        // Remove after card re-render or 5s
        setTimeout(function () { if (err.parentNode) err.remove(); }, 5000);
      }
      return;
    }
    try {
      const selPayload = { text: item.text, note: item.note || '' };
      if (item.action) selPayload.action = item.action;
      if (item.scope) selPayload.scope = item.scope;
      if (item.task_id) selPayload.task_id = item.task_id;
      if (item.type === 'text' || item.type === 'markdown') {
        if (item.startLine > 0) {
          selPayload.startLine = item.startLine;
          selPayload.endLine = item.endLine || item.startLine;
        }
        selPayload.position = item.position || '';
      } else {
        selPayload.position = item.position || '';
      }
      const res = await fetch('/api/clawmate/task/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          root: rootId,
          file: filePath,
          selections: [buildTaskSelection(selPayload)],
        }),
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        // Immediately remove from pending and close tooltip
        if (item.type === 'media') {
          mediaPendingItems = mediaPendingItems.filter(i => i.id !== item.id);
        } else if (item.type === 'office') {
          officePdfPendingItems = officePdfPendingItems.filter(i => i.id !== item.id);
        } else if (item.type === 'image') {
          imagePendingItems = imagePendingItems.filter(i => i.id !== item.id);
        } else {
          pendingItems = pendingItems.filter(i => i.id !== item.id);
        }
        if (selectedPendingId === item.id) selectedPendingId = null;
        clearHL();
        hideTooltip();
        // Auto-open right sidebar
        if (rightSidebar.classList.contains('hidden')) {
          openRightSidebar();
        }
        _startSidebarRefresh();
        renderFeedbackPanel();
        // Start polling with the returned IDs
        var ids = data.ids || [];
        var reloadFn;
        if (item.type === 'media') reloadFn = loadMediaCompletedFeedback;
        else if (item.type === 'office') reloadFn = loadOfficePdfCompletedFeedback;
        else if (item.type === 'image') reloadFn = loadImageCompletedFeedback;
        else reloadFn = loadCompletedFeedback;
        _startDesktopPolling(ids, reloadFn);
        showToast('✅ 已发送', 2000);
      } else {
        // Error: show inline in tooltip status
        const st = document.getElementById('pstStatus');
        if (st) {
          st.textContent = '❌ ' + (data.detail || '发送失败');
          st.className = 'pst-status pst-status-error';
        }
        showToast('❌ ' + (data.detail || '发送失败'), 3000);
      }
    } catch (e) {
      const st = document.getElementById('pstStatus');
      if (st) {
        st.textContent = '❌ 网络错误';
        st.className = 'pst-status pst-status-error';
      }
      showToast('❌ 网络错误', 3000);
    }
  }

  async function submitAllItems(btn, opts) {
    opts = opts || {};
    const pendingArray = opts.pendingArray || pendingItems;
    const onReload = opts.onReload || loadCompletedFeedback;
    const itemType = opts.itemType || '';

    if (!pendingArray.length) return;
    btn.disabled = true;
    btn.textContent = '提交中...';
    try {
      const res = await fetch('/api/clawmate/task/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          root: rootId,
          file: filePath,
          selections: pendingArray.map(it => {
            const p = { task_id: it.task_id || (it.action ? 'review_' + it.action : 'review_modify'), content: it.text || it.content || '', note: it.note || '', position: it.position || '' };
            if ((itemType === 'text' || itemType === 'markdown') && it.startLine > 0) {
              p.startLine = it.startLine;
              p.endLine = it.endLine || it.startLine;
            } else if (it.position) {
              p.position = it.position;
            }
            return p;
          }),
        }),
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        // Immediately clear pending items and close windows
        pendingArray.length = 0;  // Clear in-place
        selectedPendingId = null;
        clearHL();
        hideTooltip();
        // Auto-open right sidebar
        if (rightSidebar.classList.contains('hidden')) {
          openRightSidebar();
        }
        _startSidebarRefresh();
        renderFeedbackPanel();
        // Start polling with returned IDs
        var ids = data.ids || [];
        _startDesktopPolling(ids, onReload);
        btn.textContent = '✅ 已提交';
        setTimeout(function() {
          btn.disabled = false;
          btn.textContent = '✅ 全部提交';
        }, 2000);
      } else {
        // Error: show on the button itself
        btn.textContent = '❌ ' + (data.detail || '提交失败');
        btn.disabled = false;
        setTimeout(function() {
          btn.textContent = '✅ 全部提交（' + pendingArray.length + ' 条）';
        }, 3000);
        showToast('❌ ' + (data.detail || '提交失败'), 3000);
      }
    } catch (e) {
      btn.textContent = '❌ 网络错误';
      btn.disabled = false;
      setTimeout(function() {
        btn.textContent = '✅ 全部提交（' + pendingArray.length + ' 条）';
      }, 3000);
      showToast('❌ 网络错误', 3000);
    }
  }

  // ============ Highlight API (scroll-to + highlight) ============
  function clearHL() {
    try { CSS.highlights.delete('preview-hl'); } catch (_) {}
  }

  function scrollToText(targetText) {
    const mdBody = document.querySelector('.markdown-body');
    if (!mdBody || !targetText) return;

    // Take first 50 chars of selection to ensure unique match
    const searchText = targetText.substring(0, 50).trim();

    const walker = document.createTreeWalker(mdBody, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const idx = node.textContent.indexOf(searchText);
      if (idx !== -1) {
        const range = document.createRange();
        range.setStart(node, idx);
        // Compute end offset: length of searchText, but not beyond actual text end
        let endOffset = idx + targetText.length;
        if (endOffset > node.textContent.length) endOffset = node.textContent.length;
        range.setEnd(node, endOffset);

        // Scroll into view
        range.startContainer.parentElement?.scrollIntoView({ behavior: 'smooth', block: 'center' });

        // CSS Highlight API
        if (window.Highlight) {
          try {
            CSS.highlights.set('preview-hl', new Highlight(range));
          } catch (_) {}
        }

        return;
      }
    }
  }

  // ============ Selection Tooltip ============
  const tooltip = document.getElementById('selectionTooltip');
  let savedRange = null;

  // Global selection state — computed once in mouseup, reused by both buttons
  let currentStartLine = 0;
  let currentEndLine = 0;
  let currentSelText = '';

  function hideTooltip() {
    tooltip.style.display = 'none';
    savedRange = null;
    clearHL();
    document.querySelectorAll('.pst-tag').forEach(function(b) { b.classList.remove('active'); });
    document.getElementById('pstNote').value = '';
    _lastPstTag = '';
    if (window.getSelection) window.getSelection().removeAllRanges();
  }

  function findContentBody(node) {
    while (node && node !== document.body) {
      if (node.id === 'contentBody') return node;
      node = node.parentElement;
    }
    return null;
  }

  function buildSelectionPosition(range, selText) {
    if (!range || !selText) return '';

    if (isMarkdownMode && !isRawMode && !isPlainTextEditMode) {
      var heading = detectSectionFromDOM(range);
      return heading ? 'Section ' + heading : '';
    }

    if (isHtmlMode && !isRawMode) {
      return '';
    }

    var startLine = 0;
    var endLine = 0;
    var selLines = selText.split('\n').map(function(l) { return l.trim(); }).filter(function(l) { return l; });

    if (rawContent) {
      var idx = rawContent.indexOf(selText);
      if (idx !== -1) {
        var tb = rawContent.substring(0, idx);
        startLine = (tb.match(/\n/g) || []).length + 1;
        endLine = startLine + (selText.match(/\n/g) || []).length;
      }

      if (!startLine && selLines.length > 0) {
        var firstMatch = rawContent.indexOf(selLines[0]);
        if (firstMatch !== -1) {
          var tb2 = rawContent.substring(0, firstMatch);
          startLine = (tb2.match(/\n/g) || []).length + 1;
          var lastMatch = rawContent.indexOf(selLines[selLines.length - 1]);
          if (lastMatch !== -1) {
            var tbl = rawContent.substring(0, lastMatch);
            endLine = (tbl.match(/\n/g) || []).length + 1;
          } else {
            endLine = startLine + selLines.length - 1;
          }
        }
      }

      if (!startLine && selLines.length > 0) {
        for (var i = 0; i < rawContent.length - 10; i++) {
          if (rawContent.substring(i, i + selLines[0].length) === selLines[0]) {
            var tb3 = rawContent.substring(0, i);
            startLine = (tb3.match(/\n/g) || []).length + 1;
            endLine = startLine + selLines.length - 1;
            break;
          }
        }
      }

      if (!startLine) {
        var mdBody = document.querySelector('.markdown-body');
        if (mdBody) {
          var renderedText = mdBody.textContent;
          var ridx = renderedText.indexOf(selLines[0]);
          if (ridx !== -1) {
            var rtb = renderedText.substring(0, ridx);
            startLine = (rtb.match(/\n/g) || []).length + 1;
            endLine = startLine + selLines.length - 1;
          }
        }
      }
    }

    if (!startLine) return '';
    return getPosValue(ext, startLine, endLine);
  }

  function buildAgentInsertText(positionText, selectionText) {
    function quoteBlock(text) {
      return String(text || '')
        .split('\n')
        .map(function(line) { return '> ' + line; })
        .join('\n');
    }

    var parts = [];
    parts.push('---');
    parts.push('Location: ' + (positionText || ''));
    parts.push(quoteBlock(selectionText || ''));
    parts.push('---');
    return '\n' + parts.join('\n') + '\n';
  }

  let desktopSelText = '';
  let desktopSelPosition = '';
  let showDesktopSelBtn = null;
  let hideDesktopSelBtn = null;

  function isAgentSelectionMode() {
    return window.innerWidth >= 768 &&
      window.Agent &&
      typeof window.Agent.isOpen === 'function' &&
      window.Agent.isOpen();
  }

  function isSelectionInsideContentBody(sel, range) {
    var body = document.getElementById('contentBody');
    if (!body || !sel || !range) return false;

    function isInside(node) {
      if (!node) return false;
      var el = node.nodeType === 1 ? node : node.parentElement;
      return !!(el && (el === body || body.contains(el)));
    }

    return isInside(sel.anchorNode) &&
      isInside(sel.focusNode) &&
      isInside(range.commonAncestorContainer);
  }

  function syncAgentSelectionUI(range, selText) {
    if (!range || !selText) return;
    desktopSelText = selText;
    desktopSelPosition = buildSelectionPosition(range, selText);
    try { savedRange = range.cloneRange(); highlightSelection(); } catch (_) {}
    if (typeof showDesktopSelBtn === 'function') {
      showDesktopSelBtn(range);
    }
  }

  document.addEventListener('mouseup', function(e) {
    // Mobile: selection handling is done by touchend + mobileSelBtn flow;
    // skip desktop auto-copy + auto-highlight on small screens so users
    // can select text without immediately copying/highlighting it.
    if (window.innerWidth < 768) return;
    if (tooltip.contains(e.target)) return;
    setTimeout(() => {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || !sel.toString().trim()) {
        if (tooltip.style.display !== 'none' && !tooltip.contains(e.target)) {
          hideTooltip();
        }
        if (typeof hideDesktopSelBtn === 'function') hideDesktopSelBtn(true);
        return;
      }
      let range = null;
      try { range = sel.getRangeAt(0); } catch (_) {}
      if (!isSelectionInsideContentBody(sel, range)) {
        if (tooltip.style.display !== 'none') hideTooltip();
        if (typeof hideDesktopSelBtn === 'function') hideDesktopSelBtn(true);
        return;
      }

      const selText = sel.toString().trim();
      if (!selText) { hideTooltip(); return; }

      if (isAgentSelectionMode()) {
        syncAgentSelectionUI(range, selText);
        tooltip.style.display = 'none';
        return;
      }

      if (typeof hideDesktopSelBtn === 'function') hideDesktopSelBtn(true);

      // 桌面端选中文本时自动复制到剪贴板（仅新选中时触发，tooltip 已显示时不重复复制）
      if (tooltip.style.display === 'none') copyText(selText, '已复制到剪贴板');

      // 重置"立刻执行"按钮状态（上次成功提交后 hideTooltip 不会恢复按钮状态，
      // 导致新选中时按钮仍然显示为 disabled "⏳ ...")
      const sendBtn = document.getElementById('pstBtnSend');
      if (sendBtn) {
        sendBtn.disabled = false;
        sendBtn.textContent = '⚡ 立刻执行';
      }

      // ── Rendered Markdown mode: detect section heading ──
      if ((isMarkdownMode) && !isRawMode && !isPlainTextEditMode) {
        currentStartLine = null;
        currentEndLine = null;
        currentSelText = selText;
        try { savedRange = range.cloneRange(); highlightSelection(); } catch (_) {}

        const heading = detectSectionFromDOM(range);
        const posValue = heading ? 'Section ' + heading : '';
        const posEl = document.getElementById('pstLocationInput');
        posEl.classList.remove('hidden');
        posEl.placeholder = 'Section {heading} — 自动检测章节';
        posEl.value = posValue;
        document.getElementById('pstNote').value = '';
        document.getElementById('pstStatus').textContent = '';
        document.getElementById('pstStatus').className = 'pst-status';

        const rect = range.getBoundingClientRect();
        let top = rect.bottom + 8;
        let left = rect.left + rect.width / 2;
        tooltip.style.maxWidth = Math.min(400, window.innerWidth - 20) + 'px';
        tooltip.style.display = 'flex';
        requestAnimationFrame(() => {
          const h = tooltip.offsetHeight;
          const w = tooltip.offsetWidth;
          if (top + h > window.innerHeight - 10) top = rect.top - h - 8;
          if (top < 10) top = 10;
          left = Math.max(10 + w / 2, Math.min(window.innerWidth - 10 - w / 2, left));
          tooltip.style.top = top + 'px';
          tooltip.style.left = left + 'px';
          tooltip.style.transform = 'translateX(-50%)';
        });
        return;
      }

      // ── HTML rendered mode (iframe): no auto position ──
      if (isHtmlMode && !isRawMode) {
        currentStartLine = null;
        currentEndLine = null;
        currentSelText = selText;
        try { savedRange = range.cloneRange(); highlightSelection(); } catch (_) {}
        document.getElementById('pstLocationInput').value = '';
        document.getElementById('pstLocationInput').classList.add('hidden');
        document.getElementById('pstLocationInput').placeholder = '位置：无（渲染模式）';
        document.getElementById('pstNote').value = '';
        document.getElementById('pstStatus').textContent = '';
        document.getElementById('pstStatus').className = 'pst-status';
        const rect = range.getBoundingClientRect();
        let top = rect.bottom + 8;
        let left = rect.left + rect.width / 2;
        tooltip.style.maxWidth = Math.min(400, window.innerWidth - 20) + 'px';
        tooltip.style.display = 'flex';
        requestAnimationFrame(() => {
          const h = tooltip.offsetHeight;
          const w = tooltip.offsetWidth;
          if (top + h > window.innerHeight - 10) top = rect.top - h - 8;
          if (top < 10) top = 10;
          left = Math.max(10 + w / 2, Math.min(window.innerWidth - 10 - w / 2, left));
          tooltip.style.top = top + 'px';
          tooltip.style.left = left + 'px';
          tooltip.style.transform = 'translateX(-50%)';
        });
        return;
      }

      const text = selText;
      if (!text) { hideTooltip(); return; }

      // Calculate line numbers — 5-level fallback matching
      let startLine = 0, endLine = 0;
      const selLines = text.split('\n').map(l => l.trim()).filter(l => l);

      // Level 1: Exact match in rawContent
      if (rawContent) {
        let idx = rawContent.indexOf(text);
        if (idx !== -1) {
          const tb = rawContent.substring(0, idx);
          startLine = (tb.match(/\n/g) || []).length + 1;
          endLine = startLine + (text.match(/\n/g) || []).length;
        }

        // Level 2: Per-line exact match in rawContent (solves table | stripped | matching)
        if (!startLine && selLines.length > 0) {
          const firstMatch = rawContent.indexOf(selLines[0]);
          if (firstMatch !== -1) {
            const tb = rawContent.substring(0, firstMatch);
            startLine = (tb.match(/\n/g) || []).length + 1;
            const lastMatch = rawContent.indexOf(selLines[selLines.length - 1]);
            if (lastMatch !== -1) {
              const tbl = rawContent.substring(0, lastMatch);
              endLine = (tbl.match(/\n/g) || []).length + 1;
            } else {
              endLine = startLine + selLines.length - 1;
            }
          }
        }

        // Level 3: Per-line substring match (handles whitespace differences)
        if (!startLine && selLines.length > 0) {
          for (let i = 0; i < rawContent.length - 10; i++) {
            if (rawContent.substring(i, i + selLines[0].length) === selLines[0]) {
              const tb = rawContent.substring(0, i);
              startLine = (tb.match(/\n/g) || []).length + 1;
              endLine = startLine + selLines.length - 1;
              break;
            }
          }
        }

        // Level 4: Fallback to rendered DOM textContent
        if (!startLine) {
          const mdBody = document.querySelector('.markdown-body');
          if (mdBody) {
            const renderedText = mdBody.textContent;
            const ridx = renderedText.indexOf(selLines[0]);
            if (ridx !== -1) {
              const rtb = renderedText.substring(0, ridx);
              startLine = (rtb.match(/\n/g) || []).length + 1;
              endLine = startLine + selLines.length - 1;
            }
          }
        }
      }

      // Level 5: Complete failure — null it out (shows "?" in UI)
      if (!startLine) {
        currentStartLine = null;
        currentEndLine = null;
      } else {
        currentStartLine = startLine;
        currentEndLine = endLine;
      }
      currentSelText = text;

      try { savedRange = range.cloneRange(); highlightSelection(); } catch (_) {}

      const posEl = document.getElementById('pstLocationInput');
      posEl.classList.remove('hidden');
      posEl.placeholder = getPosPlaceholder(ext);
      posEl.value = startLine ? getPosValue(ext, startLine, endLine) : '';
      document.getElementById('pstNote').value = '';
      document.getElementById('pstStatus').textContent = '';
      document.getElementById('pstStatus').className = 'pst-status';

      const rect = range.getBoundingClientRect();
      let top = rect.bottom + 8;
      let left = rect.left + rect.width / 2;
      tooltip.style.maxWidth = Math.min(400, window.innerWidth - 20) + 'px';
      tooltip.style.display = 'flex';

      requestAnimationFrame(() => {
        const h = tooltip.offsetHeight;
        const w = tooltip.offsetWidth;
        if (top + h > window.innerHeight - 10) top = rect.top - h - 8;
        if (top < 10) top = 10;
        left = Math.max(10 + w / 2, Math.min(window.innerWidth - 10 - w / 2, left));
        tooltip.style.top = top + 'px';
        tooltip.style.left = left + 'px';
        tooltip.style.transform = 'translateX(-50%)';
      });
    }, 10);
  });

  document.addEventListener('click', function(e) {
    if (tooltip.style.display !== 'none' && !tooltip.contains(e.target)) {
      // Don't hide if user just selected text (avoid race with mouseup's setTimeout)
      var sel = window.getSelection();
      if (sel && !sel.isCollapsed && sel.toString().trim()) {
        return;
      }
      hideTooltip();
    }
  });

  // Prevent tooltip clicks from propagating to document (which would hide tooltip prematurely)
  tooltip.addEventListener('click', function(e) {
    e.stopPropagation();
  });

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') hideTooltip();
    // Ctrl+S / Cmd+S: save in edit mode
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      if (isPlainTextEditMode && sourceDirty) {
        if (isMarkdownMode || isHtmlMode) saveSourceEdit();
        else savePlainTextContent();
      }
    }
  });

  // ── Position 标准化格式：根据文件扩展名返回前缀/值 ──
  function getPosPlaceholder(ext) {
    if (!ext) return 'Line {start}-{end}';
    var e = ext.toLowerCase();
    // raw/source mode: markdown also uses Line format
    var rawFormats = ['txt','py','js','ts','jsx','tsx','html','css','scss','less','json','xml','yaml','yml','toml','ini','cfg','conf','sh','bash','zsh','fish','bat','ps1','c','cpp','h','hpp','java','go','rs','rb','php','sql','r','lua','pl','swift','kt','dart','scala','vue','svelte','astro','ejs','hbs','srt','vtt','ass','ssa','sub'];
    if (rawFormats.includes(e)) return 'Line {start}-{end}';
    if (['md','rmd','mdx'].includes(e)) return 'Line {start}-{end}';  // source mode
    if (['docx','doc','pptx','ppt','pdf','odt','odp'].includes(e)) return 'Page {start}-{end}';
    if (['xlsx','xls','csv','tsv'].includes(e)) return 'Range {col}{row}-{col}{row}';
    if (['mp3','mp4','wav','webm','ogg','flac','aac','m4a','mov','avi','mkv','wmv','flv'].includes(e)) return 'Time {HH:MM:SS}';
    if (['png','jpg','jpeg','gif','bmp','webp','svg','ico'].includes(e)) return 'Area [x,y]xR';
    return 'Line {start}-{end}';
  }
  // getPosValue / detectSectionFromDOM: defined in preview-common.js

  function highlightSelection() {
    if (!savedRange) return;
    // CSS Highlight API
    if (window.Highlight) {
      try {
        const h = new Highlight(savedRange);
        CSS.highlights.set('preview-hl', h);
      } catch (_) {}
    }
    // CSS ::selection fallback
    try {
      const sel = window.getSelection();
      if (sel) {
        sel.removeAllRanges();
        sel.addRange(savedRange);
      }
    } catch (_) {}
  }

  // Add to panel
  // Quick tags: 从 /api/config 动态加载 task_templates，按文件扩展名过滤
  var _lastPstTag = '';
  var _taskTemplates = [];

  function initPstTags() {
    var ext = (filePath || '').split('.').pop().toLowerCase();
    var container = document.getElementById('pstTags');
    if (!container) return;
    container.innerHTML = '';
    var filtered = _taskTemplates.filter(function(t) {
      return t.source === 'selection' && (t.match_ext.indexOf('*') >= 0 || t.match_ext.indexOf(ext) >= 0);
    });
    if (!filtered.length) return;
    filtered.forEach(function(t) {
      var btn = document.createElement('button');
      btn.className = 'pst-tag';
      btn.textContent = t.label;
      btn.setAttribute('data-tag', t.agent_prompt);
      btn.setAttribute('data-action', t.action);
      btn.setAttribute('data-scope', t.scope);
      btn.addEventListener('click', function() {
        var tag = this.getAttribute('data-tag');
        _lastPstTag = tag;
        document.querySelectorAll('.pst-tag').forEach(function(b) { b.classList.remove('active'); });
        this.classList.add('active');
        var noteEl = document.getElementById('pstNote');
        noteEl.placeholder = '例如：' + tag;
        noteEl.focus();
      });
      container.appendChild(btn);
    });
  }

  // 更新 "加入待办" 的 action 解析 — 从按钮的 data属性 读取
  function _resolvePstAction(note) {
    for (var i = 0; i < _taskTemplates.length; i++) {
      var t = _taskTemplates[i];
      if (note && note.indexOf(t.agent_prompt) === 0) return { action: t.action, scope: t.scope, task_id: t.id };
    }
    return null;
  }

  document.getElementById('pstBtnAdd').addEventListener('click', function() {
    const note = document.getElementById('pstNote').value.trim();
    const st = document.getElementById('pstStatus');
    if (!_lastPstTag) {
      st.textContent = '⚠️ 请选择操作类型（删除/修改/扩展等）';
      st.className = 'pst-status pst-status-warn';
      return;
    }
    if (!currentSelText) return;

    const posInput = document.getElementById('pstLocationInput');
    const hasPos = !posInput.classList.contains('hidden');
    let startLine = 0, endLine = 0;
    let rawPosition = '';
    if (hasPos) {
      const posVal = posInput.value.trim();
      const m = posVal.match(/(\d+)(?:-(\d+))?/);
      if (m) {
        startLine = parseInt(m[1], 10);
        endLine = m[2] ? parseInt(m[2], 10) : startLine;
      }
      rawPosition = posVal;
    }

    var _itemAction = 'other', _itemScope = 'document';
    var _mapEntry = _resolvePstAction(_lastPstTag) || _resolvePstAction(note);
    if (_mapEntry) {
      _itemAction = _mapEntry.action;
      _itemScope = _mapEntry.scope;
    }
    // execute 作用域为 project，content 记录文件引用
    var _itemText = currentSelText;
    if (_itemAction === 'execute' && filePath) {
      _itemText = '读取文件' + filePath;
    }
    var _itemType = 'text';
    if (isMarkdownMode && !isRawMode && !isPlainTextEditMode) _itemType = 'markdown';
    var _itemTaskId = _mapEntry ? (_mapEntry.task_id || '') : '';
    const item = { id: ++idCounter, text: _itemText, startLine, endLine, position: rawPosition, note, action: _itemAction, scope: _itemScope, task_id: _itemTaskId, type: _itemType };
    pendingItems.push(item);

    st.textContent = `✅ 已加入面板（共 ${pendingItems.length} 条）`;
    st.className = 'pst-status pst-status-ok';
    document.getElementById('pstNote').value = '';
    document.getElementById('pstNote').rows = 1;

    // Open right sidebar if not already
    if (rightSidebar.classList.contains('hidden')) {
      openRightSidebar();
    }

    renderFeedbackPanel();
    setTimeout(hideTooltip, 800);
  });

  // Send immediately
  document.getElementById('pstBtnSend').addEventListener('click', async function() {
    var btn = this;
    if (btn.disabled) return;
    const note = document.getElementById('pstNote').value.trim();
    const st = document.getElementById('pstStatus');
    if (!_lastPstTag) {
      st.textContent = '⚠️ 请选择操作类型（删除/修改/扩展等）';
      st.className = 'pst-status pst-status-warn';
      return;
    }
    if (!currentSelText) return;

    btn.disabled = true;
    btn.textContent = '⏳ ...';
    st.textContent = '发送中...';
    st.className = 'pst-status pst-status-loading';

    // Open right sidebar if not already
    if (rightSidebar.classList.contains('hidden')) {
      openRightSidebar();
    }
    document.getElementById('pstNote').value = '';

    const posInput = document.getElementById('pstLocationInput');
    const hasPos = !posInput.classList.contains('hidden');
    let startLine = null, endLine = null;
    let rawPosition = '';
    if (hasPos) {
      const posVal = posInput.value.trim();
      const m = posVal.match(/(\d+)(?:-(\d+))?/);
      if (m) {
        startLine = parseInt(m[1], 10);
        endLine = m[2] ? parseInt(m[2], 10) : startLine;
      }
      rawPosition = posVal;
    }

    var _sendAction = 'other', _sendScope = 'document';
    var _sendEntry = _resolvePstAction(_lastPstTag);
    if (_sendEntry) { _sendAction = _sendEntry.action; _sendScope = _sendEntry.scope; }
    var _sendTaskId = _sendEntry ? (_sendEntry.task_id || '') : '';
    const selPayload = { text: currentSelText, note, action: _sendAction, scope: _sendScope, task_id: _sendTaskId };
    if (hasPos && startLine !== null) {
      selPayload.startLine = startLine;
      selPayload.endLine = endLine;
    }
    selPayload.position = rawPosition;

    try {
      const res = await fetch('/api/clawmate/task/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          root: rootId,
          file: filePath,
          selections: [buildTaskSelection(selPayload)],
        }),
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        // 恢复按钮状态（hideTooltip 不会重置按钮，避免新选中时仍显示 disabled "⏳ ...")
        btn.disabled = false;
        btn.textContent = '⚡ 立刻执行';
        // Immediately close tooltip and auto-open sidebar
        st.textContent = '✅ 已发送';
        st.className = 'pst-status pst-status-ok';
        hideTooltip();
        // Auto-open right sidebar
        if (rightSidebar.classList.contains('hidden')) {
          openRightSidebar();
        }
        // Start polling with returned IDs
        var ids = data.ids || [];
        _startDesktopPolling(ids, loadCompletedFeedback);
      } else {
        const err = data;
        st.textContent = '❌ ' + (err.detail || '发送失败');
        st.className = 'pst-status pst-status-error';
        btn.disabled = false;
        btn.textContent = '⚡ 立刻执行';
      }
    } catch (e) {
      st.textContent = '❌ 网络错误';
      st.className = 'pst-status pst-status-error';
      btn.disabled = false;
      btn.textContent = '⚡ 立刻执行';
    }
  });

  // ============ postMessage: ONLYOFFICE error → PDF fallback to pdf.js ============
  window.addEventListener('message', function(e) {
    if (!isPdfMode) return;
    if (e.data && e.data.type === 'onlyoffice-error' && e.data.isPdf) {
      switchToPdfJsViewer();
    }
  });

  function switchToPdfJsViewer() {
    // Replace ONLYOFFICE iframe with pdf.js viewer
    const wrap = document.getElementById('officeIframeWrap');
    if (!wrap) return;
    wrap.innerHTML = '';

    const iframe = document.createElement('iframe');
    const pdfJsUrl = `/clawmate/pdfjs/viewer.html?file=${encodeURIComponent(window.location.origin + `/api/clawmate/raw?root=${encodeURIComponent(rootId)}&path=${encodeURIComponent(filePath)}`)}`;
    iframe.src = pdfJsUrl;
    iframe.style.cssText = 'width:100%;height:100%;border:none;overflow:hidden;';
    wrap.appendChild(iframe);

    // Hide view/edit toggle since pdf.js doesn't support edit mode
    const dyn = document.getElementById('bottombarDynamic');
    const toggleBtn = document.getElementById('btnOfficeEditToggle');
    if (toggleBtn) toggleBtn.style.display = 'none';

    showToast('PDF.js 渲染模式（编辑模式不可用）', 3000);
  }

  // ── Line param / hash handler ──────────────────────────────────
  var _lineScrollHandled = false;

  function _handleLineScroll() {
    if (_lineScrollHandled) return;
    _lineScrollHandled = true;

    var lineNum = null;

    // 1) ?line=N query parameter
    var lineParam = params.get('line');
    if (lineParam) {
      lineNum = parseInt(lineParam, 10);
      if (isNaN(lineNum) || lineNum < 1) lineNum = null;
    }

    // 2) #LN or #L{N} hash fragment
    if (!lineNum) {
      var hash = window.location.hash;
      var m = hash && hash.match(/^#L(\d+)$/);
      if (m) lineNum = parseInt(m[1], 10);
    }

    if (lineNum) {
      setTimeout(function() { scrollToCodeLine(lineNum); }, 300);
    }
  }

  // ── Listen for hash changes ─────────────────────────────────────
  window.addEventListener('hashchange', function() {
    _lineScrollHandled = false;
    _handleLineScroll();
  });

  // ── Init ────────────────────────────────────────────────────────
  loadContent();
  checkShareStatus();
  // Version info (git) — load after a short delay to not compete with content
  setTimeout(fetchVersionInfo, 300);
  setTimeout(initVersionModal, 500);
  // 加载 task_templates 到 _taskTemplates 并初始化标签按钮
  getRootsConfig().then(function(cfg) {
    if (cfg && cfg.task_templates) { _taskTemplates = cfg.task_templates; initPstTags(); }
  }).catch(function() {});

  // Warn on pending items before unload
  window.addEventListener('beforeunload', e => {
    if (pendingItems.length > 0) {
      e.preventDefault();
      e.returnValue = '';
    }
  });

  // ============ Mobile: Mermaid Pinch Zoom ============
  (function augmentMermaidZoom() {
    // Overlay touch support on existing desktop zoom setup
    var origSetup = window.setupMermaidZoomDesktop || setupMermaidZoomDesktop;
    if (typeof origSetup !== 'function') return;

    // Wrap to add touch handlers after desktop setup
    var _origSetupMermaid = setupMermaidZoomDesktop;
    setupMermaidZoomDesktop = function(svg) {
      _origSetupMermaid(svg);
      var container = svg.parentElement;
      if (!container || container._touchZoom) return;
      container._touchZoom = true;

      var scale = 1, lastDist = 0, lastTap = 0;

      container.addEventListener('touchstart', function(e) {
        if (e.touches.length === 2) {
          lastDist = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
        }
        var now = Date.now();
        if (e.touches.length === 1 && now - lastTap < 300) {
          // Double tap: toggle zoom
          scale = scale >= 2 ? 1 : Math.min(3, scale + 1);
          svg.style.transform = 'scale(' + scale + ')';
          svg.style.transformOrigin = 'center top';
          container.classList.toggle('mermaid-zoomed', scale !== 1);
        }
        lastTap = now;
      }, { passive: true });

      container.addEventListener('touchmove', function(e) {
        if (e.touches.length === 2) {
          e.preventDefault();
          var dist = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
          var delta = dist / lastDist;
          scale = Math.max(0.5, Math.min(3, scale * delta));
          svg.style.transform = 'scale(' + scale + ')';
          svg.style.transformOrigin = 'center top';
          container.classList.toggle('mermaid-zoomed', scale !== 1);
          lastDist = dist;
        }
      }, { passive: false });
    };
  })();

  // ============ Mobile: Selection Floating Button + Bottom Feedback Panel ============
  (function initMobileFeedback() {
    var selBtn = document.getElementById('mobileSelBtn');
    if (!selBtn) return;

    var pendingText = '', pendingRange = null, pendingStart = 0, pendingEnd = 0;
    var _savedText = '';  // persists across panel open/close to prevent data loss
    var mobileSelTaskId = '';
    var _pollTimer = null;
    var _submittedIds = [];

    // Bottom panel elements
    var overlay = document.getElementById('mobileFbOverlay');
    var panel = document.getElementById('mobileFbPanel');
    var fbSel = document.getElementById('mobileFbSelection');
    var fbNote = document.getElementById('mobileFbNote');
    var fbTags = document.getElementById('mobileFbTags');
    var fbSubmit = document.getElementById('mobileFbSubmit');
    var fbStatus = document.getElementById('mobileFbStatus');
    var fbClose = document.getElementById('mobileFbClose');

    function hideSelBtn() {
      selBtn.style.display = 'none';
    }

    function clearMobileSelection() {
      pendingText = ''; pendingRange = null;
      _savedText = '';
      hideSelBtn();
      try { CSS.highlights.delete('preview-hl'); } catch (_) {}
    }

    function showSelBtn(range) {
      if (window.innerWidth >= 768) return;
      var rect = range.getBoundingClientRect();
      var top = rect.top - 42;
      if (top < 8) top = rect.bottom + 8;
      var left = Math.max(8, Math.min(window.innerWidth - 100, rect.left + rect.width / 2 - 40));
      selBtn.style.top = top + 'px';
      selBtn.style.left = left + 'px';
      selBtn.style.display = 'block';
    }

    function showPanel() {
      if (!overlay || !panel) return;
      overlay.classList.add('visible');
      panel.classList.add('visible');
      document.body.style.overflow = 'hidden';
    }

    function hidePanel(preserveText) {
      if (!overlay || !panel) return;
      overlay.classList.remove('visible');
      panel.classList.remove('visible');
      document.body.style.overflow = '';
      if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
      if (!preserveText) {
        _savedText = '';
      }
      // Always clear highlight + browser selection when panel is dismissed
      try { CSS.highlights.delete('preview-hl'); } catch (_) {}
      if (window.getSelection) window.getSelection().removeAllRanges();
      hideSelBtn();
    }

    // ── Unified selection check (called by both selectionchange + touchend) ──
    function _checkMobileSelection() {
      if (window.innerWidth >= 768) return;
      var sel = window.getSelection();
      if (!sel || sel.isCollapsed || !sel.toString().trim()) { hideSelBtn(); return; }
      var text = sel.toString().trim();
      if (text.length < 2) { hideSelBtn(); return; }
      pendingText = text;
      pendingRange = sel.getRangeAt(0).cloneRange();
      // Save text to survive panel open/close cycles
      _savedText = text;
      var startLine = 0, endLine = 0;
      if (rawContent) {
        var idx = rawContent.indexOf(text);
        if (idx !== -1) {
          startLine = (rawContent.substring(0, idx).match(/\n/g) || []).length + 1;
          endLine = startLine + (text.match(/\n/g) || []).length;
        }
      }
      pendingStart = startLine; pendingEnd = endLine;
      showSelBtn(sel.getRangeAt(0));
    }

    // Selection detection — selectionchange + touchend for reliable mobile coverage
    document.addEventListener('selectionchange', function() {
      clearTimeout(selBtn._timer);
      selBtn._timer = setTimeout(_checkMobileSelection, 150);
    });

    // touchend fallback: some mobile browsers don't fire selectionchange reliably
    document.addEventListener('touchend', function(e) {
      // Only check if touch ended inside content area
      var ct = document.getElementById('contentBody');
      if (ct && ct.contains(e.target)) {
        clearTimeout(selBtn._touchendTimer);
        selBtn._touchendTimer = setTimeout(_checkMobileSelection, 200);
      }
    });

    document.addEventListener('scroll', function() {
      if (panel && panel.classList.contains('visible')) return;
      hideSelBtn();
    }, { passive: true });

    // Open bottom panel
    selBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      // Restore from saved text if pendingText was cleared (e.g., panel was hidden)
      if (!pendingText && _savedText) {
        pendingText = _savedText;
        // Re-derive line numbers from rawContent
        if (rawContent) {
          var idx2 = rawContent.indexOf(pendingText);
          if (idx2 !== -1) {
            pendingStart = (rawContent.substring(0, idx2).match(/\n/g) || []).length + 1;
            pendingEnd = pendingStart + (pendingText.match(/\n/g) || []).length;
          }
        }
      }
      if (!pendingText) return;
      copyText(pendingText, '已复制到剪贴板');
      // Highlight selection
      try {
        if (pendingRange && window.Highlight) {
          CSS.highlights.set('preview-hl', new Highlight(pendingRange));
        }
      } catch (_) {}
      // Populate panel
      if (fbSel) fbSel.textContent = pendingText.substring(0, 300);
      if (fbNote) { fbNote.value = ''; fbNote.placeholder = '简要说明需要的改动'; }
      if (fbStatus) fbStatus.textContent = '';
      // Render tags from task templates
      if (fbTags) {
        fbTags.innerHTML = '';
        var ex = (filePath || '').split('.').pop().toLowerCase();
        var filtered = _taskTemplates.filter(function(t) {
          return t.source === 'selection' && (t.match_ext.indexOf('*') >= 0 || t.match_ext.indexOf(ex) >= 0);
        });
        if (!filtered.length) {
          filtered = [
            { id: 'review_modify', label: '🔧 修改', action: 'modify', scope: 'document', agent_prompt: '修改' },
            { id: 'review_delete', label: '🗑 删除', action: 'delete', scope: 'document', agent_prompt: '删除' },
            { id: 'review_explain', label: '📈 扩展', action: 'explain', scope: 'document', agent_prompt: '扩展说明' },
          ];
        }
        mobileSelTaskId = '';
        filtered.forEach(function(t) {
          var tag = document.createElement('button');
          tag.className = 'mobile-fb-tag';
          tag.textContent = t.label;
          tag.addEventListener('click', function() {
            fbTags.querySelectorAll('.mobile-fb-tag').forEach(function(b) { b.classList.remove('active'); });
            tag.classList.add('active');
            mobileSelTaskId = t.id;
            if (fbNote) fbNote.placeholder = '例如：' + (t.agent_prompt || '');
            fbNote.focus();
          });
          fbTags.appendChild(tag);
        });
        // Default select first
        var first = fbTags.querySelector('.mobile-fb-tag');
        if (first) { first.classList.add('active'); mobileSelTaskId = filtered[0].id; }
      }
      showPanel();
    });

    // Close handlers
    // Close button: full clear (user deliberately dismissed)
    if (fbClose) fbClose.addEventListener('click', function() {
      clearMobileSelection();
      hidePanel(false);
    });
    // Overlay tap: hide panel but preserve text (user may re-open)
    if (overlay) overlay.addEventListener('click', function() { hidePanel(true); });

    // ── Desktop "添加到会话" selection handler ──
    // Independent from the mobile selection flow; only activates on desktop with agent panel open.
    (function() {
      var agentBtn = document.getElementById('selAddToAgent');
      if (!agentBtn) return;
      var desktopSelTimer = null;

      hideDesktopSelBtn = function(clearState) {
        agentBtn.style.display = 'none';
        if (clearState) {
          desktopSelText = '';
          desktopSelPosition = '';
        }
      };

      showDesktopSelBtn = function(range) {
        var rect = range.getBoundingClientRect();
        var top = rect.top - 42;
        if (top < 8) top = rect.bottom + 8;
        // Avoid overlapping the feedback tooltip if visible
        var fbTooltip = document.getElementById('selectionTooltip');
        if (fbTooltip && fbTooltip.style.display !== 'none' && fbTooltip.style.display !== '') {
          var fbRect = fbTooltip.getBoundingClientRect();
          var gap = 6;
          if (top < fbRect.bottom + gap) {
            top = fbRect.bottom + gap;
          }
        }
        var left = Math.max(8, Math.min(window.innerWidth - 140, rect.left + rect.width / 2 - 60));
        agentBtn.style.top = top + 'px';
        agentBtn.style.left = left + 'px';
        agentBtn.style.display = 'flex';
      };

      function checkDesktopSelection() {
        // Desktop only, and only when agent panel is open
        if (window.innerWidth < 768) return;
        var agentOpen = false;
        try { agentOpen = window.Agent && typeof window.Agent.isOpen === 'function' && window.Agent.isOpen(); } catch (_) {}
        if (!agentOpen) {
          hideDesktopSelBtn(true);
          return;
        }
        var sel = window.getSelection();
        if (!sel || sel.isCollapsed || !sel.toString().trim()) {
          hideDesktopSelBtn(true);
          return;
        }
        var text = sel.toString().trim();
        if (text.length < 2) { hideDesktopSelBtn(true); return; }
        var range = null;
        try { range = sel.getRangeAt(0); } catch (_) {}
        if (!isSelectionInsideContentBody(sel, range)) {
          hideDesktopSelBtn(true);
          return;
        }
        try {
          if (range) syncAgentSelectionUI(range, text);
          else hideDesktopSelBtn(true);
        } catch (_) { hideDesktopSelBtn(true); }
      }

      // Desktop selection detection
      document.addEventListener('selectionchange', function() {
        clearTimeout(desktopSelTimer);
        desktopSelTimer = setTimeout(checkDesktopSelection, 200);
      });

      // Hide on scroll
      document.addEventListener('scroll', function() { hideDesktopSelBtn(); }, { passive: true });

      // Hide when clicking outside the button
      document.addEventListener('mousedown', function(e) {
        if (agentBtn.style.display !== 'none' && !agentBtn.contains(e.target)) {
          hideDesktopSelBtn(true);
          savedRange = null;
          clearHL();
          try { window.getSelection().removeAllRanges(); } catch (_) {}
        }
      });

      // Click handler: send selected text to agent
      agentBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        var text = desktopSelText;
        if (!text) return;
        if (window.Agent && typeof window.Agent.insertText === 'function') {
          window.Agent.insertText(buildAgentInsertText(desktopSelPosition, text));
        }
        savedRange = null;
        clearHL();
        hideDesktopSelBtn(true);
        // Clear selection
        try { window.getSelection().removeAllRanges(); } catch (_) {}
      });
    })();

    // ── 轮询提交的任务状态 ──
    function _startPolling() {
      if (_pollTimer) clearInterval(_pollTimer);
      var attempts = 0;
      var MAX_ATTEMPTS = 30; // 最多 5 分钟
      _pollTimer = setInterval(async function() {
        attempts++;
        if (attempts > MAX_ATTEMPTS) {
          clearInterval(_pollTimer);
          _pollTimer = null;
          if (fbStatus) { fbStatus.textContent = '⏰ 超时，请手动刷新'; fbStatus.style.color = 'var(--warning)'; }
          return;
        }
        try {
          var fn = (filePath || '').split('/').pop();
          var proj = filePath && filePath.includes('/') ? filePath.split('/')[0] : (rootId || '');
          var res = await fetch('/api/clawmate/feedback/list?root=' + encodeURIComponent(rootId) +
            '&project=' + encodeURIComponent(proj) +
            '&file=' + encodeURIComponent(fn));
          if (!res.ok) return;
          var data = await res.json();
          var items = data.items || [];
          var mine = items.filter(function(it) { return _submittedIds.indexOf(it.id) >= 0; });
          if (mine.length === 0) return; // 尚未入库，等下一轮
          var allDone = mine.every(function(it) { return it.status === 'done' || it.status === 'failed'; });
          if (allDone) {
            clearInterval(_pollTimer);
            _pollTimer = null;
            var doneCount = mine.filter(function(it) { return it.status === 'done'; }).length;
            var failCount = mine.filter(function(it) { return it.status === 'failed'; }).length;
            if (fbStatus) {
              fbStatus.textContent = '✅ 完成 ' + doneCount + ' 项' + (failCount > 0 ? '，❌ ' + failCount + ' 项失败' : '');
              fbStatus.style.color = failCount > 0 ? 'var(--warning)' : 'var(--success)';
            }
            // Also refresh the desktop completed items list (right sidebar)
            if (typeof reloadCurrentFeedback === 'function') {
              try { reloadCurrentFeedback(); } catch (_) {}
            }
            setTimeout(function() { hidePanel(false); }, 2000);
          } else {
            var progressCount = mine.filter(function(it) { return it.status === 'done' || it.status === 'failed'; }).length;
            if (fbStatus) { fbStatus.textContent = '⏳ 处理中... (' + progressCount + '/' + mine.length + ')'; }
          }
        } catch (_) {}
      }, 10000);
    }

    // Submit
    if (fbSubmit) {
      fbSubmit.addEventListener('click', async function() {
        var note = fbNote ? fbNote.value.trim() : '';
        if (!pendingText) {
          if (fbStatus) { fbStatus.textContent = '⚠️ 请先选中文本'; fbStatus.style.color = 'var(--warning)'; }
          return;
        }
        fbSubmit.disabled = true;
        fbSubmit.textContent = '提交中...';
        if (fbStatus) { fbStatus.textContent = '⏳ 提交中'; fbStatus.style.color = 'var(--text-muted)'; }
        try {
          var pos = '';
          if (isMarkdownMode && pendingRange) {
            var heading = detectSectionFromDOM(pendingRange);
            if (heading) pos = 'Section ' + heading;
          }
          if (!pos && pendingStart) pos = getPosValue(ext, pendingStart, pendingEnd);
          var res = await fetch('/api/clawmate/task/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              root: rootId, file: filePath,
              selections: [{ task_id: mobileSelTaskId || 'review_modify', content: pendingText.substring(0, 1000), note: note, position: pos }],
            }),
          });
          var data = await res.json();
          if (data.ok) {
            _submittedIds = data.ids || [];
            if (fbStatus) { fbStatus.textContent = '✅ 已提交'; fbStatus.style.color = 'var(--success)'; }
            clearMobileSelection();
            // Close bottom panel after brief success feedback
            setTimeout(function() { hidePanel(false); }, 600);
            // Auto-open right sidebar so user can track feedback status
            if (rightSidebar.classList.contains('hidden')) {
              openRightSidebar();
            }
            // Start sidebar auto-refresh + immediate load
            reloadCurrentFeedback();
          } else {
            if (fbStatus) { fbStatus.textContent = '❌ ' + (data.detail || '提交失败'); fbStatus.style.color = 'var(--danger)'; }
            fbSubmit.disabled = false;
            fbSubmit.textContent = '提交反馈';
          }
        } catch (e) {
          if (fbStatus) { fbStatus.textContent = '❌ 网络错误'; fbStatus.style.color = 'var(--danger)'; }
          fbSubmit.disabled = false;
          fbSubmit.textContent = '提交反馈';
        }
      });
    }
  })();

  // ============ Agent Overlay (preview page) ============
  var _agentLibsLoaded = false;
  var _agentLibsLoading = false;
  var _agentConfig = { backend: 'claude', wsUrl: '', agentId: '' };

  /** Fetch agent config from getRootsConfig cached data */
  async function _fetchAgentConfig() {
    try {
      var cfg = await getRootsConfig();
      if (cfg && cfg.agent) {
        _agentConfig.backend = cfg.agent.backend || 'claude';
        _agentConfig.wsUrl = cfg.agent.ws_url || '';
      }
      if (cfg && cfg.roots) {
        for (var i = 0; i < cfg.roots.length; i++) {
          if (cfg.roots[i].id === rootId) {
            _agentConfig.agentId = cfg.roots[i].agent_id || '';
            break;
          }
        }
      }
    } catch (_) {}
  }

  // xterm.js version — keep in sync with agent.js XTERM_VERSION + index.html <link>/<script>
  var XTERM_CDN = 'https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0';

  /** Lazy-load xterm.js + addons + agent.js (only on first agent open) */
  function _loadAgentLibs() {
    return new Promise(function(resolve, reject) {
      if (_agentLibsLoaded) { resolve(); return; }
      if (_agentLibsLoading) {
        var check = setInterval(function() {
          if (_agentLibsLoaded) { clearInterval(check); resolve(); }
        }, 100);
        return;
      }
      _agentLibsLoading = true;

      // xterm CSS
      var cssLink = document.createElement('link');
      cssLink.rel = 'stylesheet';
      cssLink.href = XTERM_CDN + '/css/xterm.min.css';
      document.head.appendChild(cssLink);

      // agent.js is now loaded via <script defer> in preview.html
      var scripts = [
        XTERM_CDN + '/lib/xterm.min.js',
        './vendor/addon-fit.min.js?v=20260622',
      ];

      function loadNext(idx) {
        if (idx >= scripts.length) {
          _agentLibsLoaded = true;
          _agentLibsLoading = false;
          resolve();
          return;
        }
        var script = document.createElement('script');
        script.src = scripts[idx];
        script.onload = function() { loadNext(idx + 1); };
        script.onerror = function() {
          _agentLibsLoading = false;  // reset so retry works
          reject(new Error('Failed to load: ' + scripts[idx]));
        };
        document.head.appendChild(script);
      }
      loadNext(0);
    });
  }

  // Agent toggle button
  var btnToggleAgent = document.getElementById('btnToggleAgent');
  if (btnToggleAgent) {
    btnToggleAgent.addEventListener('click', function() {
      if (!agentPanel) return;

      var isOpen = !agentPanel.classList.contains('hidden');

      if (!isOpen) {
        // Mutual exclusion: close left sidebar only on narrow screens
        if (window.innerWidth <= 1500 && leftSidebar && !leftSidebar.classList.contains('hidden')) {
          closeLeftSidebar();
        }
        // Snap feedback panel closed instantly (no transition) to avoid overlap flicker
        if (rightSidebar && !rightSidebar.classList.contains('hidden')) {
          rightSidebar.style.transition = 'none';
          if (_desktopPollTimer) { clearInterval(_desktopPollTimer); _desktopPollTimer = null; }
          _stopSidebarRefresh();
          closeRightSidebar();
          rightSidebar.offsetHeight; // force reflow
          rightSidebar.style.transition = '';
          rightSidebar.style.display = ''; // let CSS display:none take effect now (inline flex from closeRightSidebar is no longer needed)
        }
        // Opening — lazy-load libs then init Agent
        _fetchAgentConfig().then(function() {
          return _loadAgentLibs();
        }).then(function() {
          agentPanel.style.display = 'flex';     // override any stale display:none from previous close
          agentPanel.classList.remove('hidden');
          agentPanel.style.display = '';         // let CSS take over
          btnToggleAgent.classList.add('active');
          updateGridColumns();
          _syncPanelOpenClass();

          if (window.Agent) {
            // Use the directory of the previewed file as the agent working dir
            var agentDir = filePath.includes('/') ? filePath.split('/').slice(0, -1).join('/') : '';
            window.Agent.init({
              domPrefix: 'preview',  // use #previewXtermContainer etc.
              backend: _agentConfig.backend,
              wsUrl: _agentConfig.wsUrl,
              rootId: rootId,
              dir: agentDir,
              agentId: _agentConfig.agentId,
            });
            // Wrap Agent.close to sync preview grid columns
            var _origClose = window.Agent.close;
            window.Agent.close = function () {
              _origClose.apply(this, arguments);
              if (agentPanel) { agentPanel.classList.add('hidden'); agentPanel.style.display = 'none'; }
              if (btnToggleAgent) btnToggleAgent.classList.remove('active');
              updateGridColumns();
              _syncPanelOpenClass();
            };
            // Pass path only; quote/content insertion is handled explicitly by selection.
            var fileCtx = filePath ? { path: filePath } : null;
            window.Agent.open(rootId, agentDir, fileCtx);
            if (window.Agent.focus) window.Agent.focus();
          }
        }).catch(function(err) {
          console.error('[agent-panel] Failed to load:', err);
          showToast && showToast('Agent 加载失败', 3000);
        });
      } else {
        // Closing
        if (typeof hideDesktopSelBtn === 'function') hideDesktopSelBtn(true);
        agentPanel.classList.add('hidden');
        btnToggleAgent.classList.remove('active');
        updateGridColumns();
        _syncPanelOpenClass();
        if (window.Agent) {
          window.Agent.close();
        }
      }
    });
  }

  // Close button inside agent panel (also handled by agent.js closeBtn handler after init)
  var btnClosePreviewAgent = document.getElementById('previewBtnCloseAgent');
  if (btnClosePreviewAgent) {
    btnClosePreviewAgent.addEventListener('click', function() {
      if (typeof hideDesktopSelBtn === 'function') hideDesktopSelBtn(true);
      if (agentPanel) { agentPanel.classList.add('hidden'); agentPanel.style.display = 'none'; }
      if (btnToggleAgent) btnToggleAgent.classList.remove('active');
      updateGridColumns();
      _syncPanelOpenClass();
      if (_desktopPollTimer) { clearInterval(_desktopPollTimer); _desktopPollTimer = null; }
      if (window.Agent) {
        window.Agent.close();
      }
    });
  }

})();
