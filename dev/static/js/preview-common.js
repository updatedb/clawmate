/**
 * ClawMate Preview Common — 桌面端与移动端共享的工具函数。
 * 在 preview.html / m/preview.html 中于 vendor scripts 之后、专属脚本之前加载。
 *
 * 暴露为全局函数，不依赖 IIFE 闭包。
 */
(function(global) {
  'use strict';

  // ── 文件类型常量 ──────────────────────────────────────────────
  global.AUDIO_EXTS = ['mp3','ogg','wav','flac','m4a','aac','wma'];
  global.VIDEO_EXTS = ['mp4','webm','mov','avi','mkv','wmv','flv','m4v'];
  global.PLAIN_TEXT_EXTS = ['txt','csv','yaml','yml','py','js','ts','tsx','css','sh','bash','sql','toml','ini','conf','cfg','env','xml','gpx','kml','srt','log','json'];
  global.MARKDOWN_EXTS = ['md','markdown','rmd','mdx'];
  global.HTML_EXTS = ['html','htm'];
  global.OFFICE_EXTS = ['doc','docx','xls','xlsx','ppt','pptx','odt','ods','odp'];
  global.PDF_EXT = 'pdf';
  global.CODE_EXTS = ['py','js','ts','tsx','jsx','html','css','scss','less','sh','bash','zsh','fish','bat','ps1','sql','go','rs','rb','php','c','cpp','h','hpp','java','swift','kt','dart','scala','vue','svelte','astro','ejs','hbs','r','lua','pl','pm','hs'];

  // ── HTML 工具 ──────────────────────────────────────────────────
  global.escHtml = function(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  };

  // ── 文件大小格式化 ────────────────────────────────────────────
  global.formatSize = function(bytes) {
    if (!bytes) return '-';
    var units = ['B', 'KB', 'MB', 'GB'];
    var i = 0, num = bytes;
    while (num >= 1024 && i < units.length - 1) { num /= 1024; i++; }
    return num.toFixed(1) + ' ' + units[i];
  };

  // ── Toast 通知 ─────────────────────────────────────────────────
  global.showToast = function(msg, duration) {
    var el = document.getElementById('toast');
    if (!el) return;
    el.textContent = msg;
    el.style.display = 'block';
    el.style.opacity = '1';
    clearTimeout(el._timer);
    el._timer = setTimeout(function() {
      el.style.opacity = '0';
      setTimeout(function() { el.style.display = 'none'; }, 300);
    }, duration || 2000);
  };

  // ── 剪贴板复制 ─────────────────────────────────────────────────
  global.copyText = async function(text, msg) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        global.showToast(msg || '已复制');
        return;
      }
    } catch (_) {}
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;left:-9999px;top:-9999px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    global.showToast(msg || '已复制');
  };

  // ── Position 生成 ──────────────────────────────────────────────
  global.getPosValue = function(ext, startLine, endLine) {
    if (!startLine) return '';
    var e = ext ? ext.toLowerCase() : '';
    var rawFormats = ['txt','py','js','ts','tsx','jsx','html','css','scss','less','json','xml','yaml','yml','toml','ini','cfg','conf','sh','bash','zsh','fish','bat','ps1','c','cpp','h','hpp','java','go','rs','rb','php','sql','r','lua','pl','pm','hs','swift','kt','dart','scala','vue','svelte','astro','ejs','hbs','srt','vtt','ass','ssa','sub','md','rmd','mdx','log'];
    if (rawFormats.includes(e)) return 'Line ' + startLine + '-' + endLine;
    if (['docx','doc','pptx','ppt','pdf','odt','odp'].includes(e)) return 'Page ' + startLine + '-' + endLine;
    if (['xlsx','xls','csv','tsv'].includes(e)) return 'Range A' + startLine;
    return 'Line ' + startLine + '-' + endLine;
  };

  // ── Section 检测 ───────────────────────────────────────────────
  global.detectSectionFromDOM = function(range) {
    if (!range) return '';
    var mdBody = document.querySelector('.markdown-body');
    if (!mdBody) return '';
    var node = range.startContainer;
    // Walk up to find a heading in the ancestor chain
    for (var n = node; n && n !== mdBody; n = n.parentNode) {
      if (/^H[1-6]$/i.test(n.tagName)) {
        return n.textContent.trim().replace(/\s+/g, ' ').slice(0, 80);
      }
    }
    // Walk backward through siblings to find nearest heading
    var prev = node;
    while (prev) {
      if (prev.previousSibling) {
        prev = prev.previousSibling;
        if (prev.querySelectorAll) {
          var headings = prev.querySelectorAll('h1,h2,h3,h4,h5,h6');
          if (headings.length > 0) {
            var h = headings[headings.length - 1];
            return h.textContent.trim().replace(/\s+/g, ' ').slice(0, 80);
          }
        }
        if (/^H[1-6]$/i.test(prev.tagName)) {
          return prev.textContent.trim().replace(/\s+/g, ' ').slice(0, 80);
        }
      } else {
        prev = prev.parentNode;
      }
      if (prev === mdBody) break;
    }
    return '';
  };

  // SRT 解析/序列化函数因桌面端与后端格式有差异，保留在各端专属脚本中。

  // ── 行号计算（从文本偏移量）─────────────────────────────────────
  global.getLineNumbersFromRange = function(text, startOffset, endOffset) {
    if (!text) return { startLine: 1, endLine: 1 };
    const lines = text.split('\n');
    let charCount = 0;
    let startLine = 1, endLine = 1;
    for (let i = 0; i < lines.length; i++) {
      const lineLen = lines[i].length + 1; // +1 for newline
      if (startOffset >= charCount && startOffset < charCount + lineLen) {
        startLine = i + 1;
      }
      if (endOffset >= charCount && endOffset < charCount + lineLen) {
        endLine = i + 1;
        break;
      }
      charCount += lineLen;
    }
    return { startLine, endLine };
  };

  // ── 代码大纲解析（函数/类定义索引）──────────────────────────────
  global.parseCodeOutline = function(content, ext) {
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
      html: [
        [/^\s*<h([1-6])\b[^>]*>(.*?)<\/h\1>/, function(m) { return m[2].replace(/<[^>]*>/g,''); }, 'skip'],
      ],
    };
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
    var langPatterns = patterns[ext] || [];
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
  };

  // ── 从渲染后的 Markdown DOM 提取标题大纲 ──────────────────────────
  global.buildHeadingTOC = function(container) {
    var headings = container.querySelectorAll('h1, h2, h3, h4');
    var items = [];
    headings.forEach(function(h, i) {
      if (!h.id) h.id = 'heading-' + i;
      var level = parseInt(h.tagName[1]);
      items.push({ id: h.id, text: h.textContent, level: level, element: h });
    });
    return items;
  };

  // ── 为代码块添加复制按钮 ──────────────────────────────────────
  global.addCopyButtons = function(container) {
    container.querySelectorAll('pre').forEach(function(pre) {
      if (pre.querySelector('.code-copy-btn')) return;
      var btn = document.createElement('button');
      btn.className = 'code-copy-btn';
      btn.textContent = '复制';
      btn.addEventListener('click', function() {
        var code = pre.querySelector('code');
        var text = code ? code.textContent : pre.textContent;
        global.copyText(text, '代码已复制');
        btn.textContent = '已复制';
        btn.classList.add('copied');
        setTimeout(function() { btn.textContent = '复制'; btn.classList.remove('copied'); }, 1500);
      });
      pre.style.position = 'relative';
      pre.appendChild(btn);
    });
  };

  // ── 为渲染后的链接添加 target=_blank ────────────────────────────
  global.openLinksInNewTab = function(container) {
    container.querySelectorAll('a').forEach(function(a) {
      var href = a.getAttribute('href') || '';
      // Internal ClawMate preview links + hash anchors: stay in same tab
      if (href.indexOf('preview.html?root=') !== -1 || href.startsWith('#')) {
        a.setAttribute('target', '_self');
        return;
      }
      a.setAttribute('target', '_blank');
      a.setAttribute('rel', 'noopener noreferrer');
    });
  };

})(window);
