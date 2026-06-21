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
  const fileName = filePath.split('/').pop() || '未命名';
  const ext = fileName.includes('.') ? fileName.split('.').pop().toLowerCase() : '';
  // isMarkdown defined above
  const AUDIO_EXTS = window.AUDIO_EXTS;
  const VIDEO_EXTS = window.VIDEO_EXTS;
  const PLAIN_TEXT_EXTS = window.PLAIN_TEXT_EXTS;
  const MARKDOWN_EXTS = window.MARKDOWN_EXTS;
  const HTML_EXTS = window.HTML_EXTS;
  const OFFICE_EXTS = window.OFFICE_EXTS;
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
  // OnlyOffice mode: view or edit (for iframe src)
  // Non-PDF Office documents default to edit mode; PDF stays in view mode
  const isEditableOffice = OFFICE_EXTS.includes(ext) && ext !== 'pdf';
  let onlyofficeMode = isEditableOffice ? 'edit' : 'view';
  const project = filePath.includes('/') ? filePath.split('/')[0] : (rootId || '');

  // Update page title
  document.title = `${fileName} — ClawMate`;
  document.getElementById('docTitle').textContent = fileName;

  // Back button
  const parentDir = filePath.split('/').slice(0, -1).join('/');
  const backHref = `/clawmate/?root=${encodeURIComponent(rootId)}&dir=${encodeURIComponent(parentDir)}`;
  document.getElementById('btnBack').href = backHref;
  const btnBackMobile = document.getElementById('btnBackMobile');
  if (btnBackMobile) btnBackMobile.href = backHref;

  // ============ Theme ============
  let currentTheme = localStorage.getItem('clawmate-theme') || 'auto';

  function getResolvedTheme() {
    if (currentTheme === 'auto') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    return currentTheme;
  }

  function switchThemeCSS(resolved) {
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
  }

  function applyTheme() {
    const resolved = getResolvedTheme();
    if (resolved === 'dark') {
      document.documentElement.setAttribute('data-theme', 'dark');
      document.body.classList.add('dark');
    } else {
      document.documentElement.setAttribute('data-theme', 'light');
      document.body.classList.remove('dark');
    }
    switchThemeCSS(resolved);
    const btn = document.getElementById('themeToggle');
    if (btn) {
      var iconName = currentTheme === 'auto' ? 'sun-moon' : currentTheme === 'light' ? 'sun' : 'moon';
      btn.title = '主题: ' + (currentTheme === 'auto' ? '自动' : currentTheme === 'light' ? '浅色' : '深色');
      if (typeof iconSVG === 'function') btn.innerHTML = iconSVG(iconName, 16);
    }
  }

  function cycleTheme() {
    if (currentTheme === 'auto') currentTheme = 'light';
    else if (currentTheme === 'light') currentTheme = 'dark';
    else currentTheme = 'auto';
    localStorage.setItem('clawmate-theme', currentTheme);
    applyTheme();
  }

  document.getElementById('themeToggle').addEventListener('click', cycleTheme);
  applyTheme();

  // Logout
  document.getElementById('btnLogout').addEventListener('click', async () => {
    if (!confirm('确定要退出登录吗？')) return;
    try {
      await fetch('/api/clawmate/auth/logout', { method: 'POST' });
    } catch (_) {}
    window.location.href = '/clawmate/login.html';
  });

  // escHtml / formatSize / copyText / showToast: defined in preview-common.js

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
    console.log('[ClawMate] renderMermaid: found ' + blocks.length + ' mermaid block(s), store size=' + mermaidStore.length);

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
      var resolvedTheme = getResolvedTheme();
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

      console.log('[ClawMate] Calling mermaid.run() with scope=' + scopeClass + ', store has ' + mermaidStore.length + ' entries');
      await window.mermaid.run({ querySelector: '.' + scopeClass + ' .mermaid' });
      console.log('[ClawMate] mermaid.run() completed successfully');

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
    controls.innerHTML = '<button class="mermaid-zoom-btn" data-zoom="out">−</button><button class="mermaid-zoom-btn" data-zoom="reset">⊙</button><button class="mermaid-zoom-btn" data-zoom="in">+</button>';
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
      if (btn.dataset.zoom === 'in') { scale = Math.min(5, scale + 0.5); }
      else if (btn.dataset.zoom === 'out') { scale = Math.max(0.3, scale - 0.5); }
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

  function buildTOC(div) {
    const headings = div.querySelectorAll('h1, h2, h3, h4');
    if (headings.length < 2) {
      // No meaningful TOC — collapse left sidebar
      leftSidebar.classList.add('hidden');
      btnToggleLeft.classList.remove('active');
      updateGridColumns();
      return;
    }
    // Show sidebar and build TOC (on mobile: keep hidden, user opens via topbar)
    if (window.innerWidth >= 768) {
      leftSidebar.classList.remove('hidden');
      btnToggleLeft.classList.add('active');
      updateGridColumns();
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
        } else if (srcPre && isRawMode && (isMarkdownMode || isHtmlMode)) {
          // Source view (pre) mode: scroll contentBody to the heading line + select heading text
          if (foundLine) {
            var lh2 = parseFloat(getComputedStyle(srcPre).lineHeight) || 22;
            var container = document.getElementById('contentBody');
            var preTop = srcPre.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop;
            container.scrollTo({ top: preTop + (foundLine - 3) * lh2, behavior: 'smooth' });
            // Highlight by selecting the heading text in the pre
            var codeEl = srcPre.querySelector('code');
            var textNode = codeEl || srcPre;
            var fullText = textNode.textContent || '';
            var idx = fullText.indexOf(headingText);
            if (idx >= 0 && document.createRange) {
              try {
                var range = document.createRange();
                // Walk to find the text node containing the heading
                var walker = document.createTreeWalker(textNode, NodeFilter.SHOW_TEXT);
                var node, offset = 0;
                while (node = walker.nextNode()) {
                  var ni = node.textContent.indexOf(headingText);
                  if (ni >= 0) {
                    range.setStart(node, ni);
                    range.setEnd(node, ni + headingText.length);
                    var sel = window.getSelection();
                    sel.removeAllRanges();
                    sel.addRange(range);
                    break;
                  }
                }
              } catch(_) {}
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
    // Check textarea (edit mode) first, then pre (view mode)
    var ta = document.getElementById('plainTextEditor');
    if (ta) {
      var lineHeight = parseFloat(getComputedStyle(ta).lineHeight) || 22;
      ta.scrollTop = Math.max(0, (lineNum - 4) * lineHeight);
      // Move cursor + briefly highlight the line
      var lines = ta.value.split('\n');
      var pos = 0;
      for (var i = 0; i < Math.min(lineNum - 1, lines.length); i++) pos += lines[i].length + 1;
      ta.setSelectionRange(pos, pos + (lines[lineNum - 1] || '').length);
      ta.focus();
      return;
    }
    var pre = contentBody.querySelector('pre');
    if (!pre) return;
    var lineHeight = parseFloat(getComputedStyle(pre).lineHeight) || 22;
    var scrollTarget = Math.max(0, (lineNum - 4) * lineHeight);
    pre.parentElement.scrollTop = scrollTarget;
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
        scrollToCodeLine(item.line);
      });
      li.appendChild(a);
      list.appendChild(li);
    });
    tocBody.innerHTML = '';
    tocBody.appendChild(list);
    return true;
  }

  // ============ Source Edit Mode (Markdown / HTML raw) ============
  let isPlainTextEditMode = false;
  let sourceDirty = false;

  function _updateSourcePre(pre, content) {
    if (!pre) return;
    var code = pre.querySelector('code');
    if (code) {
      code.innerHTML = content;
    } else {
      pre.textContent = content;
    }
  }

  function enterSourceEditMode() {
    const srcPre = document.getElementById('sourceRawPre');
    if (!srcPre) return;
    isPlainTextEditMode = true;
    sourceDirty = false;
    srcPre.style.display = 'none';
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
    // Insert after the banner (or as first child if no banner)
    const banner = document.getElementById('sourceEditBanner');
    if (banner) {
      banner.style.display = '';
      srcPre.parentNode.insertBefore(ta, banner.nextSibling);
    } else {
      srcPre.parentNode.insertBefore(ta, srcPre);
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
    if (srcPre) {
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
        if (srcPre) {
          srcPre.style.display = '';
          // Refresh source content in case it was edited
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
    if (isRawMode) {
      if (mdDiv) mdDiv.style.display = 'none';
      if (htmlIframe) htmlIframe.style.display = 'none';
      if (srcPre) {
        srcPre.style.display = '';
        _updateSourcePre(srcPre, rawContent);
      }
    } else {
      if (mdDiv) mdDiv.style.display = '';
      if (htmlIframe) htmlIframe.style.display = '';
      if (srcPre) srcPre.style.display = 'none';
    }
  }

  // Toggle right (feedback) panel
  document.getElementById('btnToggleRight').addEventListener('click', () => {
    const wasHidden = rightSidebar.classList.contains('hidden');
    rightSidebar.classList.toggle('hidden');
    updateGridColumns();
    document.getElementById('btnToggleRight').classList.toggle('active', !rightSidebar.classList.contains('hidden'));
    if (!wasHidden) {
      // Closing sidebar
      clearHL(); hideTooltip();
      _stopSidebarRefresh();
    } else {
      // Opening sidebar — start auto-refresh and do an immediate load
      _startSidebarRefresh();
      reloadCurrentFeedback();
    }
  });

  // Close buttons on panel headers
  document.getElementById('btnCloseLeft').addEventListener('click', () => {
    leftSidebar.classList.add('hidden');
    updateGridColumns();
    btnToggleLeft.classList.remove('active');
  });
  document.getElementById('btnCloseRight').addEventListener('click', () => {
    clearHL();
    hideTooltip();
    rightSidebar.classList.add('hidden');
    updateGridColumns();
    document.getElementById('btnToggleRight').classList.remove('active');
    _stopSidebarRefresh();
  });

  // ============ Raw Markdown Content (for accurate line number calculation) ============
  let rawContent = '';

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

        // Fetch directory listing for prev/next
        const parentDir = filePath.split('/').slice(0, -1).join('/');
        const nav = { prev: null, next: null, idx: 0, total: 0 };
        (async () => {
          try {
            const listRes = await fetch(`/api/clawmate/list?root=${encodeURIComponent(rootId)}&dir=${encodeURIComponent(parentDir)}`);
            const listData = await listRes.json();
            const allEntries = listData.entries || [];
            const images = allEntries.filter(e => ['png','jpg','jpeg','svg','webp','gif','bmp','ico'].includes((e.name.split('.').pop() || '').toLowerCase()));
            nav.total = images.length;
            const curIdx = images.findIndex(e => (e.path || e.relPath || e.name) === filePath);
            if (curIdx >= 0) {
              nav.idx = curIdx + 1;
              if (curIdx > 0) nav.prev = images[curIdx - 1];
              if (curIdx < images.length - 1) nav.next = images[curIdx + 1];
            }
          } catch (_) {}
          renderImgNav();
        })();

        // Image and counter wrapper
        const wrap = document.createElement('div');
        wrap.style.cssText = 'display:flex;flex-direction:column;align-items:center;position:relative;';

        const imgWrap = document.createElement('div');
        imgWrap.style.cssText = 'display:flex;align-items:center;justify-content:center;position:relative;width:100%;';

        const img = document.createElement('img');
        img.id = 'previewImage';
        img.src = `/api/clawmate/preview?root=${encodeURIComponent(rootId)}&path=${encodeURIComponent(filePath)}`;
        img.style.cssText = 'max-width:100%;max-height:70vh;object-fit:contain;border-radius:8px;';
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
        renderImageFeedbackPanel();
        loadCompletedFeedback();

        function renderImgNav() {
          const hasPrev = nav.prev;
          const hasNext = nav.next;

          // Create prev if needed
          if (hasPrev && !document.getElementById('imgNavPrev')) {
            const prevBtn = document.createElement('button');
            prevBtn.id = 'imgNavPrev';
            prevBtn.innerHTML = '‹';
            prevBtn.className = 'img-nav-btn';
            prevBtn.style.left = '4px';
            prevBtn.title = '上一张';
            const p = nav.prev.path || nav.prev.relPath || nav.prev.name;
            prevBtn.addEventListener('click', () => { window.location.href = 'preview.html?root=' + encodeURIComponent(rootId) + '&file=' + encodeURIComponent(p); });
            imgWrap.appendChild(prevBtn);
          }

          // Create next if needed
          if (hasNext && !document.getElementById('imgNavNext')) {
            const nextBtn = document.createElement('button');
            nextBtn.id = 'imgNavNext';
            nextBtn.innerHTML = '›';
            nextBtn.className = 'img-nav-btn';
            nextBtn.style.right = '4px';
            nextBtn.title = '下一张';
            const n = nav.next.path || nav.next.relPath || nav.next.name;
            nextBtn.addEventListener('click', () => { window.location.href = 'preview.html?root=' + encodeURIComponent(rootId) + '&file=' + encodeURIComponent(n); });
            imgWrap.appendChild(nextBtn);
          }

          // Update counter
          const infoEl = document.getElementById('imgNavInfo');
          if (infoEl && nav.total > 0) {
            infoEl.textContent = fileName + ' (' + nav.idx + '/' + nav.total + ')';
          }
        }
        return;
      }

      if (isVideoMode) {
        setupMediaMode('video');
        removeLoading();
        loadCompletedFeedback();
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
          loadCompletedFeedback();
          return;
        }
        if (ct.startsWith('audio/') || isAudioMode) {
          setupMediaMode('audio');
          removeLoading();
          loadCompletedFeedback();
          return;
        }
        // Fallback for unknown binary
        contentBody.innerHTML = `<div class="preview-error">无法预览此文件类型</div>`;
        removeLoading();
        return;
      }

      const data = await res.json();
      const content = data.content || '';

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
        loadOfficePdfCompletedFeedback();
        return;
      }

      // ======== Office (ONLYOFFICE) ========
      if (isOfficeMode) {
        const wrap = document.createElement('div');
        wrap.className = 'office-iframe-wrap';
        wrap.id = 'officeIframeWrap';

        const iframe = document.createElement('iframe');
        iframe.id = 'officeIframe';
        iframe.src = `./onlyoffice.html?root=${encodeURIComponent(rootId)}&path=${encodeURIComponent(filePath)}&mode=${encodeURIComponent(onlyofficeMode)}`;
        iframe.style.cssText = 'width:100%;height:100%;border:none;overflow:hidden;';
        wrap.appendChild(iframe);

        contentBody.style.cssText = 'display:flex;flex-direction:column;flex:1;min-height:0;padding:0;';
        contentBody.appendChild(wrap);
        removeLoading();

        setupOfficePdfToolbar();
        loadOfficePdfCompletedFeedback();
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

        // Create source view (raw pre, hidden by default unless isRawMode)
        const srcPre = document.createElement('pre');
        srcPre.id = 'sourceRawPre';
        srcPre.textContent = content;
        if (window.hljs) {
          try {
            const highlighted = window.hljs.highlight(content, { language: 'markdown', ignoreIllegals: true }).value;
            const code = document.createElement('code');
            code.className = 'language-markdown';
            code.innerHTML = highlighted;
            srcPre.appendChild(code);
            srcPre.className = 'code-highlighted';
          } catch (_) {
            srcPre.className = 'raw-text';
          }
        } else {
          srcPre.className = 'raw-text';
        }
        srcPre.style.display = isRawMode ? '' : 'none';
        contentBody.appendChild(srcPre);

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
          srcPre.style.display = '';
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

        console.log('[ClawMate] About to call renderMermaid, mermaidStore has ' + mermaidStore.length + ' entries');
        try { await renderMermaid(mdDiv, mermaidStore); } catch (e) { console.error('[ClawMate] renderMermaid threw:', e); }
        removeLoading();
        updateMarkdownDynamicButtons();
        loadCompletedFeedback();
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

        // Source view (highlighted pre, hidden by default unless isRawMode)
        const srcPre = document.createElement('pre');
        srcPre.id = 'sourceRawPre';
        srcPre.className = 'code-highlighted';
        srcPre.style.display = isRawMode ? '' : 'none';
        srcPre.style.flex = '1';
        srcPre.style.overflow = 'auto';
        srcPre.style.margin = '0';
        srcPre.style.borderRadius = '0';
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

        removeLoading();
        updateMarkdownDynamicButtons();
        loadCompletedFeedback();
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
          // Display mode: syntax-highlighted pre
          const pre = document.createElement('pre');
          pre.className = 'code-highlighted';
          const langMap = { json: 'json', xml: 'xml', yaml: 'yaml', yml: 'yaml', py: 'python', js: 'javascript', ts: 'typescript', tsx: 'typescript', sql: 'sql', sh: 'bash', bash: 'bash', css: 'css', log: 'plaintext', txt: 'plaintext', csv: 'plaintext', kml: 'xml', gpx: 'xml', srt: 'plaintext', toml: 'ini', ini: 'ini', conf: 'plaintext', cfg: 'ini', env: 'bash', yaml: 'yaml' };
          const lang = langMap[ext] || 'plaintext';
          if (lang !== 'plaintext' && window.hljs) {
            try {
              const highlighted = window.hljs.highlight(rawContent, { language: lang, ignoreIllegals: true }).value;
              const code = document.createElement('code');
              code.className = `language-${lang}`;
              code.innerHTML = highlighted;
              pre.appendChild(code);
            } catch (_) { pre.textContent = rawContent; }
          } else {
            pre.textContent = rawContent;
          }
          contentBody.appendChild(pre);
          removeLoading();
          // Render outline sidebar for code (display mode: auto-open on desktop only)
          if (codeOutlineItems.length >= 2) {
            renderCodeOutline(codeOutlineItems);
            if (window.innerWidth >= 768) {
              leftSidebar.classList.remove('hidden');
              btnToggleLeft.classList.add('active');
              updateGridColumns();
            }
          }
          updatePlainTextDynamicButtons();
        }

      // Load completed feedback items from API
      loadCompletedFeedback();

    } catch (e) {
      const loadingEl3 = document.querySelector('.preview-loading');
      if (loadingEl3) loadingEl3.remove();
      contentBody.innerHTML = `<div class="preview-error">加载失败: ${escHtml(e.message)}</div>`;
    }
  }

  // ============ Sidebar Toggle (Grid Adaptive) ============
  const leftSidebar = document.getElementById('leftSidebar');
  const rightSidebar = document.getElementById('rightSidebar');
  const threeCol = document.querySelector('.preview-three-col');

  // Topbar outline toggle button (must be after sidebar declarations)
  const btnToggleLeft = document.getElementById('btnToggleLeft');
  btnToggleLeft.addEventListener('click', () => {
    leftSidebar.classList.toggle('hidden');
    updateGridColumns();
    btnToggleLeft.classList.toggle('active', !leftSidebar.classList.contains('hidden'));
    if (isMarkdownMode) updateMarkdownDynamicButtons();
    if (isPlainTextMode && codeOutlineItems.length >= 2) updatePlainTextDynamicButtons();
  });
  // Initialize active state based on current sidebar visibility
  btnToggleLeft.classList.toggle('active', !leftSidebar.classList.contains('hidden'));

  function updateGridColumns() {
    const lHidden = leftSidebar.classList.contains('hidden');
    const rHidden = rightSidebar.classList.contains('hidden');
    const lW = lHidden ? '0px' : '240px';
    const rW = rHidden ? '0px' : '300px';
    threeCol.style.gridTemplateColumns = `${lW} 1fr ${rW}`;
  }

  // Left sidebar: markdown shows it (via buildTOC), non-markdown hides it
  // On mobile: always start hidden, user toggles via topbar
  const isMobileViewport = window.innerWidth < 768;
  if (isMobileViewport || !isMarkdownMode) {
    leftSidebar.classList.add('hidden');
    btnToggleLeft.classList.remove('active');
  } else {
    leftSidebar.classList.remove('hidden');
    btnToggleLeft.classList.add('active');
  }
  // Right sidebar: hidden by default, auto-opens when feedback is added
  rightSidebar.classList.add('hidden');
  updateGridColumns();

  // ============ Image Mode Detection ============
  const isImageMode = ['png', 'jpg', 'jpeg', 'svg'].includes(ext);

  // ============ Image / Media Mode Toolbar Setup ============
  function setupMediaToolbar() {
    // Hide left sidebar in media mode (no TOC for media)
    leftSidebar.classList.add('hidden');
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
    loadMediaCompletedFeedback();

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

  // ============ Media Feedback Panel ============
  function renderMediaFeedbackPanel() {
    const body = document.getElementById('feedbackBody');
    body.innerHTML = '';

    // Top row: Add feedback + Submit all
    const topRow = document.createElement('div');
    topRow.style.cssText = 'display:flex;gap:6px;margin-bottom:8px;';

    const addBtn = document.createElement('button');
    addBtn.className = 'fb-btn-submit';
    addBtn.style.cssText = 'flex:1;padding:4px 8px;border-radius:6px;border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer;font-size:13px;font-weight:600;';
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
    topRow.appendChild(addBtn);

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
    topRow.appendChild(submitAllBtn);
    body.appendChild(topRow);

    // Empty state
    if (mediaPendingItems.length === 0 && mediaCompletedItems.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'fb-empty';
      empty.style.marginTop = '12px';
      empty.textContent = '点击「+ 添加反馈」开始';
      body.appendChild(empty);
      return;
    }

    // Pending items
    if (mediaPendingItems.length > 0) {
      [...mediaPendingItems].reverse().forEach(item => body.appendChild(createFeedbackCard(item)));
    }

    // Completed items — split pending/in_progress vs done/failed
    const pendingOrProgress = mediaCompletedItems.filter(i => i.status === 'pending' || i.status === 'in_progress');
    const doneOrFailed = mediaCompletedItems.filter(i => i.status === 'done' || i.status === 'failed');
    if (pendingOrProgress.length > 0) {
      const sep = document.createElement('div');
      sep.className = 'fb-section-sep';
      sep.innerHTML = '<span>⏳ 处理中</span>';
      body.appendChild(sep);
      pendingOrProgress.forEach(item => body.appendChild(renderCompletedFeedbackCard(item)));
    }
    if (doneOrFailed.length > 0) {
      const sep = document.createElement('div');
      sep.className = 'fb-section-sep';
      sep.innerHTML = '<span>✅ 已完成</span>';
      body.appendChild(sep);
      doneOrFailed.forEach(item => body.appendChild(renderCompletedFeedbackCard(item)));
    }
  }

  async function loadMediaCompletedFeedback() {
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
    iframe.src = `./onlyoffice.html?root=${encodeURIComponent(rootId)}&path=${encodeURIComponent(filePath)}&mode=${encodeURIComponent(onlyofficeMode)}`;
  }

  function renderOfficePdfFeedbackPanel() {
    const body = document.getElementById('feedbackBody');
    body.innerHTML = '';

    // Top row: Add feedback + Submit all
    const topRow = document.createElement('div');
    topRow.style.cssText = 'display:flex;gap:6px;margin-bottom:8px;';

    const addBtn = document.createElement('button');
    addBtn.className = 'fb-btn-submit';
    addBtn.style.cssText = 'flex:1;padding:4px 8px;border-radius:6px;border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer;font-size:13px;font-weight:600;';
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
    topRow.appendChild(addBtn);

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
    topRow.appendChild(submitAllBtn);
    body.appendChild(topRow);

    // Empty state
    if (officePdfPendingItems.length === 0 && officePdfCompletedItems.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'fb-empty';
      empty.style.marginTop = '12px';
      empty.textContent = '点击「+ 添加反馈」开始';
      body.appendChild(empty);
      return;
    }

    // Pending items
    if (officePdfPendingItems.length > 0) {
      [...officePdfPendingItems].reverse().forEach(item => body.appendChild(createFeedbackCard(item)));
    }


    // Completed items
    if (officePdfCompletedItems.length > 0) {
      const sep = document.createElement('div');
      sep.className = 'fb-section-sep';
      sep.innerHTML = '<span>✅ 已提交</span>';
      body.appendChild(sep);
      officePdfCompletedItems.forEach(item => body.appendChild(renderCompletedFeedbackCard(item)));
    }
  }

  async function loadOfficePdfCompletedFeedback() {
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

  async function getAbsolutePath() {
    const cfg = await getRootsConfig();
    if (!cfg || !cfg.roots) return null;
    const root = cfg.roots.find(r => r.id === rootId);
    if (!root || !root.dir) return null;
    return root.dir.replace(/\/+$/, '') + '/' + filePath;
  }

  document.getElementById('btnPath').addEventListener('click', async () => {
    const absPath = await getAbsolutePath();
    if (absPath) {
      await copyText(absPath, '✅ 路径已复制');
    } else {
      showToast('无法获取路径', 2000);
    }
  });

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

  document.getElementById('btnDownload').addEventListener('click', () => {
    const link = document.createElement('a');
    link.href = buildDownloadLink(filePath);
    link.target = '_blank';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  });

  document.getElementById('btnShare').addEventListener('click', async () => {
    const btn = document.getElementById('btnShare');
    btn.textContent = '⏳';
    btn.disabled = true;
    try {
      const res = await fetch('/api/clawmate/share/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root: rootId, path: filePath }),
      });
      if (!res.ok) { showToast('❌ 分享链接生成失败 (' + res.status + ')', 3000); return; }
      const data = await res.json();
      await copyText(data.url, '✅ 分享链接已复制到剪贴板');
      showToast('🔗 已复制 · ' + (data.reused ? '有效期已刷新' : '24小时有效'), 3000);
    } catch (e) {
      showToast('❌ ' + e.message, 3000);
    } finally {
      btn.textContent = '↗️ 分享';
      btn.disabled = false;
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
    const card = document.createElement('div');
    card.className = 'fb-card' + (item.id === selectedPendingId ? ' selected' : '');
    card.dataset.id = item.id;

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
        renderFeedbackPanel();
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
    const body = document.getElementById('feedbackBody');
    body.innerHTML = '';

    // === Unified top row: always show "+ 添加反馈" + "✅ 全部提交" ===
    const topRow = document.createElement('div');
    topRow.style.cssText = 'display:flex;gap:6px;margin-bottom:8px;';

    const addBtn = document.createElement('button');
    addBtn.className = 'fb-btn-submit';
    addBtn.style.cssText = 'flex:1;padding:4px 8px;border-radius:6px;border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer;font-size:13px;font-weight:600;';
    addBtn.textContent = '+ 添加反馈';
    addBtn.addEventListener('click', () => {
      // Create a pending item and render it as a card in the pending section
      const item = { id: ++idCounter, text: '', startLine: 0, endLine: 0, note: '', type: 'text' };
      pendingItems.push(item);
      renderFeedbackPanel();
      // Scroll to the newly added card
      const newCard = document.querySelector(`.fb-card[data-id="${item.id}"]`);
      if (newCard) newCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    topRow.appendChild(addBtn);

    const submitAllBtn = document.createElement('button');
    submitAllBtn.className = 'fb-btn-submit-all';
    const hasPending = pendingItems.length > 0;
    submitAllBtn.style.cssText = `flex:1;padding:4px 8px;border-radius:6px;border:1px solid var(--border-color);background:var(--btn-bg);color:var(--btn-text);cursor:${hasPending ? 'pointer' : 'not-allowed'};font-size:13px;font-weight:600;opacity:${hasPending ? '1' : '0.5'};`;
    submitAllBtn.textContent = hasPending ? `✅ 全部提交（${pendingItems.length} 条）` : '✅ 全部提交';
    submitAllBtn.disabled = !hasPending;
    if (hasPending) {
      submitAllBtn.addEventListener('click', () => {
        // Validate: each pending item must have a note
        const missing = pendingItems.filter(i => !i.action);
        if (missing.length > 0) {
          showToast('请选择操作类型后再提交', 2000);
          return;
        }
        submitAllItems(submitAllBtn, { itemType: 'text' });
      });
    }
    topRow.appendChild(submitAllBtn);
    body.appendChild(topRow);

    // Empty state: only top row + hint
    if (pendingItems.length === 0 && completedItems.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'fb-empty';
      empty.style.marginTop = '12px';
      empty.textContent = '选中文本后点击「📋 加入待办」即可累积';
      body.appendChild(empty);
      return;
    }

    // Pending section
    if (pendingItems.length > 0) {
      [...pendingItems].reverse().forEach(item => {
        body.appendChild(createFeedbackCard(item));
      });
    }

    // Completed section
    if (completedItems.length > 0) {
      const sep = document.createElement('div');
      sep.className = 'fb-section-sep';
      sep.innerHTML = '<span>✅ 已提交</span>';
      body.appendChild(sep);

      completedItems.forEach(item => {
        const c = renderCompletedFeedbackCard(item);
        body.appendChild(c);
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
            rightSidebar.classList.remove('hidden');
            updateGridColumns();
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
    const statusIcon =
      item.status === 'done' ? '✅' :
      item.status === 'in_progress' ? '🔄' :
      item.status === 'failed' ? '❌' : '⏳';

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

    // Top row: Add feedback + Submit all
    const topRow = document.createElement('div');
    topRow.style.cssText = 'display:flex;gap:6px;margin-bottom:8px;';

    const addBtn = document.createElement('button');
    addBtn.className = 'fb-btn-submit';
    addBtn.style.cssText = 'flex:1;padding:4px 8px;border-radius:6px;border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer;font-size:13px;font-weight:600;';
    addBtn.textContent = '+ 添加反馈';
    addBtn.addEventListener('click', () => {
      const item = { id: ++idCounter, text: '', startLine: 0, endLine: 0, note: '', type: 'image', position: '' };
      imagePendingItems.push(item);
      renderImageFeedbackPanel();
      const newCard = body.querySelector(`.fb-card[data-id="${item.id}"]`);
      if (newCard) newCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    topRow.appendChild(addBtn);

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
    topRow.appendChild(submitAllBtn);
    body.appendChild(topRow);

    // Empty state
    if (imagePendingItems.length === 0 && imageCompletedItems.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'fb-empty';
      empty.style.marginTop = '12px';
      empty.textContent = '点击「+ 添加反馈」开始';
      body.appendChild(empty);
      return;
    }

    // Pending items
    if (imagePendingItems.length > 0) {
      [...imagePendingItems].reverse().forEach(item => body.appendChild(createFeedbackCard(item)));
    }

    // Completed items
    if (imageCompletedItems.length > 0) {
      const sep = document.createElement('div');
      sep.className = 'fb-section-sep';
      sep.innerHTML = '<span>✅ 已提交</span>';
      body.appendChild(sep);
      imageCompletedItems.forEach(item => body.appendChild(renderCompletedFeedbackCard(item)));
    }
  }

  async function loadImageCompletedFeedback() {
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
    if (!rootId || !project || !filePath) return;
    if (isImageMode) {
      await loadImageCompletedFeedback();
      return;
    }
    if (isMediaMode) {
      await loadMediaCompletedFeedback();
      return;
    }
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
          rightSidebar.classList.remove('hidden');
          updateGridColumns();
          document.getElementById('btnToggleRight').classList.add('active');
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
      showToast('请选择操作类型', 2000);
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
          rightSidebar.classList.remove('hidden');
          updateGridColumns();
          document.getElementById('btnToggleRight').classList.add('active');
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
          rightSidebar.classList.remove('hidden');
          updateGridColumns();
          document.getElementById('btnToggleRight').classList.add('active');
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

  document.addEventListener('mouseup', function(e) {
    // Mobile: selection handling is done by touchend + mobileSelBtn flow;
    // skip desktop auto-copy + auto-highlight on small screens so users
    // can select text without immediately copying/highlighting it.
    if (window.innerWidth < 768) return;
    setTimeout(() => {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || !sel.toString().trim()) {
        if (tooltip.style.display !== 'none' && !tooltip.contains(e.target)) {
          hideTooltip();
        }
        return;
      }
      const container = findContentBody(sel.anchorNode);
      if (!container || container.id !== 'contentBody') {
        if (tooltip.style.display !== 'none') hideTooltip();
        return;
      }

      const selText = sel.toString().trim();
      if (!selText) { hideTooltip(); return; }

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
        const range = sel.getRangeAt(0);
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
        const range = sel.getRangeAt(0);
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

      const range = sel.getRangeAt(0);
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
    const wasRightHidden = rightSidebar.classList.contains('hidden');
    rightSidebar.classList.remove('hidden');
    if (wasRightHidden) {
      updateGridColumns();
      document.getElementById('btnToggleRight').classList.add('active');
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
    const wasRightHidden2 = rightSidebar.classList.contains('hidden');
    rightSidebar.classList.remove('hidden');
    if (wasRightHidden2) {
      updateGridColumns();
      document.getElementById('btnToggleRight').classList.add('active');
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
          rightSidebar.classList.remove('hidden');
          updateGridColumns();
          document.getElementById('btnToggleRight').classList.add('active');
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

  // ============ Init ============
  loadContent();
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
              rightSidebar.classList.remove('hidden');
              updateGridColumns();
              document.getElementById('btnToggleRight').classList.add('active');
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

})();
