/**
 * ClawMate Preview Common — 桌面端与移动端共享的工具函数。
 * 在 preview.html / m/preview.html 中于 vendor scripts 之后、专属脚本之前加载。
 *
 * 暴露为全局函数，不依赖 IIFE 闭包。
 */
(function(global) {
  'use strict';

  var hasDocument = typeof document !== 'undefined';

  // A preview/share-like document can use the registry without putting panel
  // setup into its heavy feature script.
  if (hasDocument && document.head && !global.ClawMatePanels && !document.querySelector('script[data-clawmate-panels]')) {
    var panelsScript = document.createElement('script');
    panelsScript.src = './js/clawmate-panels.js';
    panelsScript.dataset.clawmatePanels = '1';
    document.head.appendChild(panelsScript);
  }

  // Project panel is shared with the directory surface but loaded separately
  // so preview's heavy features remain lazy.  It binds before preview.js.
  if (hasDocument && document.head && !global.ClawMateProjectPanel && !document.querySelector('script[data-clawmate-project-panel]')) {
    var projectPanelScript = document.createElement('script');
    projectPanelScript.src = './js/project-panel.js';
    projectPanelScript.dataset.clawmateProjectPanel = '1';
    document.head.appendChild(projectPanelScript);
  }
  // Shared card factory is loaded independently of preview.js so lightweight
  // share and heavy preview surfaces retain the same feedback DOM contract.
  if (hasDocument && document.head && !global.ClawMateFeedbackPanel && !document.querySelector('script[data-clawmate-feedback-panel]')) {
    var feedbackPanelScript = document.createElement('script');
    feedbackPanelScript.src = './js/feedback-panel.js';
    feedbackPanelScript.dataset.clawmateFeedbackPanel = '1';
    document.head.appendChild(feedbackPanelScript);
  }

  // The Agent facade remains lazy in preview.js; this tiny adapter only
  // registers the already-present DOM as the preview surface's reusable panel.
  function mountPreviewAgentPanel() {
    if (!global.ClawMatePanels) {
      var registryScript = document.querySelector('script[data-clawmate-panels]');
      if (registryScript && !registryScript.dataset.clawmateAgentWaiting) {
        registryScript.dataset.clawmateAgentWaiting = '1';
        registryScript.addEventListener('load', mountPreviewAgentPanel, {once:true});
      }
      return;
    }
    if (!global.ClawMateAgentPanel) return;
    global.ClawMateAgentPanel.mount({surface:'preview', panelId:'previewAgentPanel', buttonId:'btnToggleAgent', hideDisplay:true});
  }
  if (hasDocument && document.head) {
    if (!global.ClawMateAgentPanel && !document.querySelector('script[data-clawmate-agent-panel]')) {
      var agentPanelScript = document.createElement('script');
      agentPanelScript.src = './js/agent-panel.js';
      agentPanelScript.dataset.clawmateAgentPanel = '1';
      agentPanelScript.addEventListener('load', mountPreviewAgentPanel, {once:true});
      document.head.appendChild(agentPanelScript);
    } else mountPreviewAgentPanel();
  }

  // ── 文件类型常量 ──────────────────────────────────────────────
  global.AUDIO_EXTS = ['mp3','ogg','wav','flac','m4a','aac','wma'];
  global.VIDEO_EXTS = ['mp4','webm','mov','avi','mkv','wmv','flv','m4v'];
  global.PLAIN_TEXT_EXTS = ['txt','csv','yaml','yml','py','js','ts','tsx','css','sh','bash','sql','toml','ini','conf','cfg','env','xml','bpmn','gpx','kml','srt','log','json'];
  global.MARKDOWN_EXTS = ['md','markdown','rmd','mdx'];
  global.HTML_EXTS = ['html','htm'];
  global.OFFICE_EXTS = ['doc','docx','xls','xlsx','ppt','pptx','odt','ods','odp'];
  global.PDF_EXT = 'pdf';
  global.CODE_EXTS = ['py','js','ts','tsx','jsx','html','css','scss','less','sh','bash','zsh','fish','bat','ps1','sql','go','rs','rb','php','c','cpp','h','hpp','java','swift','kt','dart','scala','vue','svelte','astro','ejs','hbs','r','lua','pl','pm','hs'];
  global.ARCHIVE_EXTS = ['zip','rar','tar','gz','tgz','bz2','tbz2','xz','txz','7z'];

  // Single source of truth for actions offered for a selected file. Both the
  // review page and public share page receive templates from /config (where
  // extensions are exposed as match_ext); accepting match.ext too keeps this
  // helper usable with the on-disk template shape in deterministic tests.
  global.getSelectionActionTemplates = function(templates, fileOrExt) {
    var list = Array.isArray(templates) ? templates : [];
    var ext = String(fileOrExt || '').split('.').pop().toLowerCase();
    var allowed = list.filter(function(template) {
      if (!template || template.source !== 'selection') return false;
      if (!template.frontend || !(template.frontend.tooltip || template.frontend.panel)) return false;
      var matchExt = Array.isArray(template.match_ext) ? template.match_ext :
        (template.match && Array.isArray(template.match.ext) ? template.match.ext : []);
      return matchExt.indexOf('*') >= 0 || matchExt.indexOf(ext) >= 0;
    });
    // Only an unavailable/empty API response gets a fallback. A configured
    // template that simply does not match this extension must yield no action.
    if (list.length) return allowed;
    return [{ id: 'review_replace', label: '📈 替换', action: 'replace', scope: 'document' }];
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

  // The single selection-to-feedback locator used by review and share. The
  // calculated line numbers only produce the existing position string; they
  // are never part of the persisted feedback contract.
  global.getFeedbackSelectionPosition = function(options) {
    options = options || {};
    var ext = String(options.ext || '').toLowerCase();
    var text = String(options.text || '');
    var raw = String(options.rawContent || '');
    var range = options.range;
    if (!text) return { position: '' };
    if (options.markdownRendered && range) {
      var heading = global.detectSectionFromDOM(range);
      if (heading) return { position: 'Section ' + heading };
    }
    if (options.htmlRendered) return { position: '' };
    var start = 0, end = 0;
    var lines = text.split('\n').map(function(line) { return line.trim(); }).filter(Boolean);
    function lineAt(index) { return (raw.slice(0, index).match(/\n/g) || []).length + 1; }
    var index = raw.indexOf(text);
    if (index >= 0) { start = lineAt(index); end = start + (text.match(/\n/g) || []).length; }
    if (!start && lines.length) {
      index = raw.indexOf(lines[0]);
      if (index >= 0) {
        start = lineAt(index);
        var last = raw.indexOf(lines[lines.length - 1]);
        end = last >= 0 ? lineAt(last) : start + lines.length - 1;
      }
    }
    if (!start && lines.length) {
      for (var i = 0; i < raw.length - 10; i++) {
        if (raw.substring(i, i + lines[0].length) === lines[0]) {
          start = lineAt(i); end = start + lines.length - 1; break;
        }
      }
    }
    if (!start && options.renderedRoot && lines.length) {
      var rendered = options.renderedRoot.textContent || '';
      index = rendered.indexOf(lines[0]);
      if (index >= 0) { start = (rendered.slice(0, index).match(/\n/g) || []).length + 1; end = start + lines.length - 1; }
    }
    return { position: start ? global.getPosValue(ext, start, end) : '' };
  };

  global.getFeedbackPositionPlaceholder = function(ext) {
    var e = String(ext || '').toLowerCase();
    if (['docx','doc','pptx','ppt','pdf','odt','odp'].includes(e)) return 'Page {start}-{end}';
    if (['xlsx','xls','csv','tsv'].includes(e)) return 'Range {col}{row}-{col}{row}';
    if (global.AUDIO_EXTS.includes(e) || global.VIDEO_EXTS.includes(e)) return 'Time {HH:MM:SS}';
    if (['png','jpg','jpeg','gif','bmp','webp','svg','ico'].includes(e)) return 'Area [x,y]xR';
    return 'Line {start}-{end}';
  };

  global.formatFeedbackTime = function(seconds) {
    seconds = Number(seconds) || 0;
    var h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = Math.floor(seconds % 60);
    return [h, m, s].map(function(v) { return String(v).padStart(2, '0'); }).join(':');
  };

  // ── Section 检测 ───────────────────────────────────────────────
  global.detectSectionFromDOM = function(range) {
    if (!hasDocument || !range) return '';
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
  function copyCodeBlock(text) {
    var writer = typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText
      ? function(value) { return navigator.clipboard.writeText(value); }
      : null;
    if (global.utils && global.utils.copyText && writer) {
      global.utils.copyText(text, writer).catch(function() { copyWithSelection(text); });
      return;
    }
    copyWithSelection(text);
  }

  function copyWithSelection(text) {
    if (!hasDocument || !document.body) return;
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;left:-9999px;top:-9999px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }

  global.addCopyButtons = function(container) {
    if (!hasDocument || !container) return;
    container.querySelectorAll('pre').forEach(function(pre) {
      if (pre.querySelector('.code-copy-btn')) return;
      var btn = document.createElement('button');
      btn.className = 'code-copy-btn';
      btn.textContent = '复制';
      btn.addEventListener('click', function() {
        var code = pre.querySelector('code');
        var text = code ? code.textContent : pre.textContent;
        copyCodeBlock(text);
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

})(typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : {}));
