// Configure highlight.js to allow unescaped HTML in code blocks
// (internal docs may contain raw HTML in JS snippets)
if (window.hljs) {
  hljs.configure({ ignoreUnescapedHTML: true });
}

// HTML escape utility
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// ── Auth error handler ─────────────────────────────────────────────
function handleAuthError(res) {
  if (res.status === 401 || res.status === 302) {
    const redirectTo = '/clawmate/login.html?redirect=' + encodeURIComponent(window.location.pathname + window.location.search);
    window.location.href = redirectTo;
    return true;
  }
  return false;
}

async function authFetch(url, options = {}) {
  const res = await fetch(url, options);
  if (handleAuthError(res)) {
    throw new Error('auth_redirect');
  }
  return res;
}

const state = {
  roots: [],
  defaultRootId: "",
  rootId: "",
  rootLabel: "",
  dir: "",
  entries: [],
  searchResults: null,
  searchQuery: "",
  view: "grid",
  filterType: "all",
  sortKey: "time",
  sortDir: "desc",
  page: 1,
  pageSize: 60,
  total: 0,
  hasMore: false,
  loadingMore: false,
  pageLimit: 200,  // 每页从服务器请求的最大条目数
  selectedPaths: new Set(),
  multiSelectEnabled: false,
  onlyofficeAvailable: null, // null=unknown, true=available, false=unavailable
};

// Sidebar state — shows parent directory's children (siblings of current dir)
let sidebarParentDir = "";
let sidebarEntries = [];

const els = {
  breadcrumb: document.getElementById("breadcrumb"),
  dirList: document.getElementById("dirList"),
  hamburgerBtn: document.getElementById("hamburgerBtn"),
  sidebarOverlay: document.getElementById("sidebarOverlay"),
  sidebar: document.getElementById("sidebar"),

  currentPath: document.getElementById("currentPath"),
  gallery: document.getElementById("gallery"),
  list: document.getElementById("list"),
  status: document.getElementById("status"),
  searchInput: document.getElementById("searchInput"),
  searchBtn: document.getElementById("searchBtn"),
  clearSearchBtn: document.getElementById("clearSearchBtn"),
  viewGrid: document.getElementById("viewGrid"),
  viewList: document.getElementById("viewList"),
  filterType: document.getElementById("filterType"),
  sortTime: document.getElementById("sortTime"),
  sortName: document.getElementById("sortName"),
  sortSize: document.getElementById("sortSize"),
  prevPage: document.getElementById("prevPage"),
  nextPage: document.getElementById("nextPage"),
  pageInfo: document.getElementById("pageInfo"),
  loadMoreBtn: document.getElementById("loadMoreBtn"),
  rootSelect: document.getElementById("rootSelect"),
  batchDownloadBtn: document.getElementById("batchDownloadBtn"),
  // Multi-select
  multiSelectToggle: document.getElementById("multiSelectToggle"),
  btnMkdir: document.getElementById("btnMkdir"),
  batchBar: document.getElementById("batchBar"),
  batchCount: document.getElementById("batchCount"),
  batchSelectAllBtn: document.getElementById("batchSelectAllBtn"),
  batchDeleteBtn: document.getElementById("batchDeleteBtn"),
  batchDownloadBtn2: document.getElementById("batchDownloadBtn2"),
  batchClearBtn: document.getElementById("batchClearBtn"),
};

function getResolvedTheme() {
  return window._topbarResolvedTheme ? window._topbarResolvedTheme() : 'light';
}

function getMermaidTheme() {
  return getResolvedTheme() === 'dark' ? 'dark' : 'default';
}

// Initialize theme on load
// 排序标签更新函数
function updateSortPills() {
  const pills = [
    { el: els.sortTime, key: "time", desc: "↓ 最新", asc: "↑ 最早" },
    { el: els.sortName, key: "name", desc: "↓ Z→A", asc: "↑ A→Z" },
    { el: els.sortSize, key: "size", desc: "↓ 最大", asc: "↑ 最小" },
  ];
  pills.forEach(p => {
    if (!p.el) return;
    const active = state.sortKey === p.key;
    p.el.classList.toggle("active", active);
    if (active) {
      const isDesc = state.sortDir === "desc";
      p.el.textContent = isDesc ? p.desc : p.asc;
      p.el.dataset.dir = state.sortDir;
    }
  });
}

// ===== Utilities =====
function formatSize(bytes) {
  if (bytes === 0 || bytes == null) return "-";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let num = bytes;
  while (num >= 1024 && i < units.length - 1) {
    num /= 1024;
    i++;
  }
  return `${num.toFixed(1)} ${units[i]}`;
}

function formatMtime(ts) {
  if (!ts) return "-";
  var dt = new Date(ts * 1000);
  if (isNaN(dt.getTime())) return "-";
  var mo = dt.getMonth() + 1, d = dt.getDate(), h = dt.getHours(), mi = dt.getMinutes();
  return mo + '/' + d + ' ' + String(h).padStart(2,'0') + ':' + String(mi).padStart(2,'0');
}

function getFileTypeLabel(entry) {
  if (entry.category && entry.category !== "other") return entry.category;
  const name = entry.name || "";
  const ext = name.includes(".") ? name.split(".").pop() : "";
  if (ext) return ext.toLowerCase();
  return entry.category || "文件";
}

function setStatus(text) {
  els.status.textContent = text || "";
}

function sanitizeDir(raw) {
  if (!raw) return "";
  let dir = String(raw).trim();
  if (!dir) return "";
  dir = dir.replace(/^\.\/+/, "").replace(/\/+$/, "");
  if (!dir) return "";
  if (dir.startsWith("/")) return "";
  if (dir.includes("\\")) return "";
  const parts = dir.split("/");
  if (parts.some((part) => part === ".." || part === "")) return "";
  return dir;
}

function mapEntry(entry) {
  return {
    ...entry,
    relPath: entry.path || "",
  };
}

function updateUrl() {
  const url = new URL(window.location.href);
  if (state.rootId) {
    url.searchParams.set("root", state.rootId);
  } else {
    url.searchParams.delete("root");
  }
  if (state.dir) {
    url.searchParams.set("dir", state.dir);
  } else {
    url.searchParams.delete("dir");
  }
  history.replaceState(null, "", url);
}

function getRootById(rootId) {
  return state.roots.find((root) => root.id === rootId);
}

function selectRoot(rootId) {
  const root = getRootById(rootId);
  if (!root) return false;
  state.rootId = root.id;
  state.rootLabel = root.label || root.id;
  if (els.rootSelect) {
    els.rootSelect.value = root.id;
  }
  // Close agent panel on root switch (session is root-specific)
  if (window.Agent) {
    window.Agent.close();
  }
  return true;
}

function populateRootSelect() {
  if (!els.rootSelect) return;
  els.rootSelect.innerHTML = "";
  state.roots.forEach((root) => {
    const option = document.createElement("option");
    option.value = root.id;
    option.textContent = root.label || root.id;
    els.rootSelect.appendChild(option);
  });
}

function getInitialLocation() {
  const params = new URLSearchParams(window.location.search);
  const rootParam = params.get("root");
  const dirParam = sanitizeDir(params.get("dir") || "");

  if (rootParam && getRootById(rootParam)) {
    return { rootId: rootParam, subdir: dirParam };
  }

  return { rootId: "", subdir: "" };
}

function buildBreadcrumbItems() {
  const parts = state.dir ? state.dir.split("/") : [];
  const items = [];
  items.push({ label: state.rootLabel || "media", dir: "" });
  let current = "";
  parts.forEach((part) => {
    current = current ? `${current}/${part}` : part;
    items.push({ label: part, dir: current });
  });
  return items;
}

function getDirHref(dir) {
  if (!state.rootId) return "#";
  const base = "/clawmate/";
  const rootParam = `?root=${encodeURIComponent(state.rootId)}`;
  const dirParam = `&dir=${encodeURIComponent(dir || "")}`;
  return `${base}${rootParam}${dirParam}`;
}

function buildDownloadLink(path) {
  if (!state.rootId) return "#";
  return `/api/clawmate/download?root=${encodeURIComponent(state.rootId)}&path=${encodeURIComponent(path || "")}`;
}

function buildRawLink(path) {
  if (!state.rootId) return "#";
  return `/api/clawmate/raw?root=${encodeURIComponent(state.rootId)}&path=${encodeURIComponent(path || "")}`;
}

function buildBatchDownloadLink(path) {
  if (!state.rootId) return "#";
  return `/api/clawmate/batch-download?root=${encodeURIComponent(state.rootId)}&path=${encodeURIComponent(path || "")}`;
}

function buildOnlyOfficeLink(path) {
  if (!state.rootId) return "#";
  return `/clawmate/onlyoffice.html?root=${encodeURIComponent(state.rootId)}&path=${encodeURIComponent(path || "")}`;
}

function buildDeleteUrl(path) {
  if (!state.rootId) return "#";
  return `/api/clawmate/delete?root=${encodeURIComponent(state.rootId)}&path=${encodeURIComponent(path || "")}`;
}

function buildDirDeleteUrl(path) {
  if (!state.rootId) return "#";
  return `/api/clawmate/delete-dir?root=${encodeURIComponent(state.rootId)}&path=${encodeURIComponent(path || "")}`;
}

async function deleteEntry(entry) {
  if (!entry) return;
  const isDir = !!entry.is_dir;
  const confirmed = window.confirm(
    `确定要删除${isDir ? "目录" : "文件"} "${entry.name}" 吗？\n此操作不可恢复！`
  );
  if (!confirmed) return;

  setStatus("删除中...");
  try {
    const url = isDir ? buildDirDeleteUrl(entry.relPath) : buildDeleteUrl(entry.relPath);
    const res = await authFetch(url, { method: "DELETE" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: "删除失败" }));
      setStatus(err.error || "删除失败");
      return;
    }
    setStatus("删除成功");
    invalidateDirCache();
    await loadDir(state.dir);
  } catch (e) {
    setStatus("删除失败: " + e.message);
  }
}

function getEntryExt(entry) {
  const name = entry?.name || "";
  return name.includes(".") ? name.split(".").pop().toLowerCase() : "";
}

function isOfficeFile(entry) {
  if (!entry || entry.is_dir) return false;
  const ext = getEntryExt(entry);
  return ["doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "pdf"].includes(ext);
}

const TEXT_EXTS = new Set(["md", "markdown", "txt", "log", "json", "yaml", "yml", "csv", "tsv", "xml", "gpx", "kml", "ini", "conf", "cfg", "html", "htm", "py", "js", "ts", "css", "sh", "bash", "sql", "toml", "java", "c", "cpp", "go", "rs", "rb", "php", "srt"]);

function isTextFile(entry) {
  if (!entry || entry.is_dir) return false;
  if (entry.category === "text") return true;
  const ext = getEntryExt(entry);
  return TEXT_EXTS.has(ext);
}

function isMarkdownEntry(entry) {
  if (!entry || entry.is_dir) return false;
  const ext = getEntryExt(entry);
  return ext === "md" || ext === "markdown";
}

// Group entries into markdown files, folders, and other files (entries already sorted by applyFilterSort)
function groupEntries(entries) {
  const markdownEntries = entries.filter(isMarkdownEntry);
  const folderEntries = entries.filter((e) => e.is_dir);
  const otherEntries = entries.filter((e) => !isMarkdownEntry(e) && !e.is_dir);

  return { markdownEntries, folderEntries, otherEntries };
}

// ===== File Type Icons =====
// Uses SVG icons from icons.js (loaded before app.js)
function getFileIcon(entry) {
  // fileThumbSVG is defined in icons.js — returns inline SVG wrapped in 32x32 container
  if (typeof fileThumbSVG === 'function') return fileThumbSVG(entry);
  // Fallback if icons.js not loaded
  if (!entry || !entry.is_dir && !entry.category) return '<span style="display:inline-flex;align-items:center;justify-content:center;width:56px;height:56px;font-size:48px;flex-shrink:0;">📄</span>';
  if (entry.is_dir) return '<span style="display:inline-flex;align-items:center;justify-content:center;width:56px;height:56px;font-size:48px;flex-shrink:0;">' + (entry.marker ? '🦞' : '📁') + '</span>';
  return '<span style="display:inline-flex;align-items:center;justify-content:center;width:56px;height:56px;font-size:48px;flex-shrink:0;">📄</span>';
}

function toAbsoluteUrl(url) {
  return new URL(url, window.location.origin).href;
}

async function copyText(text, successMessage) {
  // Try modern Clipboard API first
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      setStatus(successMessage || "已复制到剪贴板");
      return true;
    }
  } catch (_) {}

  // Fallback: execCommand for HTTP/non-secure contexts
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    ta.style.top = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, 99999);
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    if (ok) {
      setStatus(successMessage || "已复制到剪贴板");
      return true;
    }
  } catch (_) {}

  window.prompt("复制失败，请手动复制：", text);
  setStatus("已提供复制内容");
  return false;
}

function triggerDownload(url) {
  const link = document.createElement("a");
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

function triggerBatchDownload(url, folderName) {
  setStatus(`正在打包下载 ${folderName || state.dir || "当前目录"} ...`);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${(folderName || "download").replace(/[/\\:*?"<>|]/g, "-")}.zip`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  setTimeout(() => setStatus(""), 3000);
}

// ===== TOC Generation =====
function buildTOC(div) {
  const headings = div.querySelectorAll('h1, h2, h3');
  if (headings.length < 2) return; // Only show TOC if 2+ headings

  // Ensure headings have IDs
  headings.forEach((h, i) => {
    if (!h.id) h.id = `heading-${i}`;
  });

  const toc = document.createElement('nav');
  toc.className = 'markdown-toc';

  const header = document.createElement('div');
  header.className = 'markdown-toc-header';
  header.innerHTML = '<span>目录</span><span class="markdown-toc-toggle">▾</span>';
  header.addEventListener('click', () => toc.classList.toggle('collapsed'));

  const list = document.createElement('ul');
  list.className = 'markdown-toc-list';

  headings.forEach((h) => {
    const li = document.createElement('li');
    const level = parseInt(h.tagName[1]);
    li.className = level === 2 ? 'toc-h2' : 'toc-h3';
    const a = document.createElement('a');
    a.href = `#${h.id}`;
    a.textContent = h.textContent;
    a.addEventListener('click', (e) => {
      e.preventDefault();
      h.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    li.appendChild(a);
    list.appendChild(li);
  });

  toc.appendChild(header);
  toc.appendChild(list);
  div.insertBefore(toc, div.firstChild);
}

// ===== Code Copy Buttons =====
function addCopyButtons(div) {
  const pres = div.querySelectorAll('pre');
  pres.forEach(pre => {
    const btn = document.createElement('button');
    btn.className = 'code-copy-btn';
    btn.textContent = '复制';
    btn.addEventListener('click', async () => {
      const code = pre.querySelector('code');
      const text = code ? code.textContent : pre.textContent;
      const ok = await copyText(text, '代码已复制');
      if (ok) {
        btn.textContent = '已复制';
        btn.classList.add('copied');
        setTimeout(() => {
          btn.textContent = '复制';
          btn.classList.remove('copied');
        }, 1500);
      }
    });
    pre.style.position = 'relative';
    pre.appendChild(btn);
  });
}

// ===== Code Outline Parser =====
function parseCodeOutline(content, ext) {
  const lines = content.split('\n');
  const items = [];
  const patterns = {
    py: [
      [/^\s*def\s+(\w+)\s*\(/, m => 'def ' + m[1] + '(...)'],
      [/^\s*class\s+(\w+)/, m => 'class ' + m[1]],
      [/^\s*async\s+def\s+(\w+)\s*\(/, m => 'async def ' + m[1] + '(...)'],
    ],
    js: [
      [/^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)/, m => 'function ' + m[1] + '()'],
      [/^\s*(?:export\s+)?class\s+(\w+)/, m => 'class ' + m[1]],
      [/^\s*(?:static\s+)?(?:async\s+)?(\w+)\s*\([^)]*\)\s*\{/, m => m[1] + '()', true],
      [/^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(/, m => 'const ' + m[1] + ' = (...) =>'],
      [/^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function/, m => 'const ' + m[1] + ' = function'],
    ],
    ts: [
      [/^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)/, m => 'function ' + m[1] + '()'],
      [/^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)/, m => 'class ' + m[1]],
      [/^\s*(?:export\s+)?interface\s+(\w+)/, m => 'interface ' + m[1]],
      [/^\s*(?:async\s+)?(\w+)\s*\([^)]*\)\s*(?::\s*\w+)?\s*\{/, m => m[1] + '()', true],
      [/^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*:\s*(?:.*=>|[\w<>]+)\s*=/, m => 'const ' + m[1]],
    ],
    tsx: [
      [/^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)/, m => 'function ' + m[1] + '()'],
      [/^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)/, m => 'class ' + m[1]],
      [/^\s*(?:export\s+)?interface\s+(\w+)/, m => 'interface ' + m[1]],
      [/^\s*(?:async\s+)?(\w+)\s*\([^)]*\)\s*(?::\s*\w+)?\s*\{/, m => m[1] + '()', true],
    ],
    go: [
      [/^\s*func\s+\((\w+)\s+(\*?\w+)\)\s+(\w+)\s*\(/, m => 'func (' + m[1] + ' ' + m[2] + ') ' + m[3] + '(...)'],
      [/^\s*func\s+(\w+)\s*\(/, m => 'func ' + m[1] + '(...)'],
      [/^\s*type\s+(\w+)\s+(?:struct|interface)/, m => 'type ' + m[1]],
    ],
    java: [
      [/^\s*(?:public|private|protected)?\s*(?:static|final|abstract)?\s*(?:class|interface)\s+(\w+)/, m => m[0].trim().split(/\s+/)[0] + ' ' + m[1]],
      [/^\s*(?:public|private|protected)?\s*(?:static|final|abstract|\s)+[\w<>\[\],\s]+\s+(\w+)\s*\(/, m => m[1] + '()'],
    ],
    rs: [
      [/^\s*(?:pub\s+)?fn\s+(\w+)/, m => 'fn ' + m[1] + '()'],
      [/^\s*(?:pub\s+)?struct\s+(\w+)/, m => 'struct ' + m[1]],
      [/^\s*(?:pub\s+)?trait\s+(\w+)/, m => 'trait ' + m[1]],
      [/^\s*(?:pub\s+)?impl\s+(\w+)/, m => 'impl ' + m[1]],
      [/^\s*(?:pub\s+)?enum\s+(\w+)/, m => 'enum ' + m[1]],
    ],
    c: [
      [/^\s*(?:static\s+)?(?:inline\s+)?(?:\w+[\s*]+)+(\w+)\s*\([^)]*\)\s*\{/, m => m[1] + '()'],
    ],
    cpp: [
      [/^\s*(?:static\s+)?(?:inline\s+)?(?:virtual\s+)?(?:\w+(?:::)?)+[\s*&]+(\w+)\s*\([^)]*\)\s*(?:const\s*)?\{/, m => m[1] + '()'],
      [/^\s*(?:template\s*<[^>]*>\s*)?class\s+(\w+)/, m => 'class ' + m[1]],
    ],
    h: [
      [/^\s*(?:static\s+)?(?:inline\s+)?(?:\w+[\s*]+)+(\w+)\s*\([^)]*\)\s*(?:const\s*)?;/, m => m[1] + '()'],
      [/^\s*(?:template\s*<[^>]*>\s*)?class\s+(\w+)/, m => 'class ' + m[1]],
    ],
    sh: [
      [/^\s*(\w+)\s*\(\)\s*\{/, m => m[1] + '()'],
      [/^\s*function\s+(\w+)/, m => 'function ' + m[1] + '()'],
    ],
    bash: [
      [/^\s*(\w+)\s*\(\)\s*\{/, m => m[1] + '()'],
      [/^\s*function\s+(\w+)/, m => 'function ' + m[1] + '()'],
    ],
  };
  const langPatterns = patterns[ext] || [];
  const JS_KEYWORDS = new Set([
    'if','else','for','while','switch','case','break','continue','return',
    'throw','try','catch','finally','do','with','new','delete','typeof',
    'instanceof','void','in','of','await','debugger','export','import',
    'yield','super','this','async','true','false','null','undefined',
    'let','var','const','function','class','extends','implements','static',
    'get','set','enum','interface','type','namespace','module','require',
    'from','as','default','public','private','protected','readonly'
  ]);
  if (!langPatterns.length) return items;
  for (let i = 0; i < lines.length; i++) {
    for (const entry of langPatterns) {
      const regex = entry[0], formatter = entry[1], skipKeywords = entry[2];
      const m = lines[i].match(regex);
      if (m) {
        if (skipKeywords && JS_KEYWORDS.has(m[1])) break;
        items.push({ text: formatter(m).trim(), line: i + 1 }); break;
      }
    }
  }
  return items;
}
function openLinksInNewTab(div) {
  div.querySelectorAll('a').forEach(a => {
    a.setAttribute('target', '_blank');
    a.setAttribute('rel', 'noopener noreferrer');
  });
}

// ===== Dynamic vendor loading (Mermaid/KaTeX) =====
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
  var css = document.createElement('link');
  css.rel = 'stylesheet'; css.href = './vendor/katex.min.css';
  document.head.appendChild(css);
  await loadScript('./vendor/katex.min.js');
  await loadScript('./vendor/auto-render.min.js');
  _katexLoaded = true;
}

// ===== Mermaid Error Visualization =====
async function renderMermaid(div, mermaidStore) {
  const mermaidBlocks = div.querySelectorAll('.mermaid');
  if (mermaidBlocks.length === 0) return;

  // Give the container a unique class for scoped querySelector
  const scopeClass = 'mermaid-scope-' + Date.now();
  div.classList.add(scopeClass);

  if (!window.mermaid) {
    console.warn('Mermaid not loaded');
    for (const block of mermaidBlocks) {
      block.classList.add('mermaid-error');
      block.innerHTML = (typeof iconSVG === 'function' ? iconSVG('x', 14) + ' ' : '') + 'Mermaid 未加载，请刷新页面重试。';
    }
    return;
  }

  try {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      fontFamily: 'ui-monospace, SF Mono, Cascadia Code, Consolas, monospace',
      maxWidth: 800,
      theme: getMermaidTheme()
    });

    // Restore stored code into each .mermaid block before calling mermaid.run()
    for (const block of mermaidBlocks) {
      const id = block.getAttribute('data-mermaid-id');
      if (id == null || !mermaidStore[id]) {
        block.classList.add('mermaid-error');
        block.innerHTML = (typeof iconSVG === 'function' ? iconSVG('x', 14) + ' ' : '') + '图表数据丢失';
        continue;
      }
      block.textContent = mermaidStore[id];
    }

    await mermaid.run({ querySelector: '.' + scopeClass + ' .mermaid' });
    // Fix quadrantChart NaN% colors (Mermaid bug)
    for (const block of mermaidBlocks) {
      block.querySelectorAll('[fill*="NaN%"], [stroke*="NaN%"]').forEach(el => {
        const fill = el.getAttribute('fill') || '';
        const stroke = el.getAttribute('stroke') || '';
        if (fill.includes('NaN%')) el.setAttribute('fill', fill.replace(/hsl\([^)]*NaN%[^)]*\)/g, getResolvedTheme() === 'dark' ? '#58a6ff' : '#4f46e5'));
        if (stroke.includes('NaN%')) el.setAttribute('stroke', stroke.replace(/hsl\([^)]*NaN%[^)]*\)/g, getResolvedTheme() === 'dark' ? '#58a6ff' : '#4f46e5'));
      });
    }
  } catch (err) {
    console.warn('Mermaid error:', err);
    for (const block of mermaidBlocks) {
      block.classList.add('mermaid-error');
      block.innerHTML = (typeof iconSVG === 'function' ? iconSVG('x', 14) + ' ' : '') + '图表渲染失败，请检查 Mermaid 语法。';
    }
  } finally {
    div.classList.remove(scopeClass);
  }
}

// ── Mermaid resize handles ──
function setupMermaidResizeHandles(container) {
  const blocks = container.querySelectorAll('.mermaid');
  blocks.forEach(block => {
    if (block.querySelector('.mermaid-resize-handle')) return;

    // Wrap existing content in an inner scrollable div so the resize
    // handle (a sibling) never scrolls with the content.
    const inner = document.createElement('div');
    inner.className = 'mermaid-inner';
    while (block.firstChild) {
      inner.appendChild(block.firstChild);
    }
    block.appendChild(inner);

    // Clear outer container constraints — .mermaid-inner handles scrolling now.
    block.style.overflow = 'visible';
    block.style.maxHeight = 'none';

    // Pull zoom controls back to the outer container so they stay visible.
    const zoomControls = inner.querySelector('.mermaid-zoom-controls');
    if (zoomControls) block.appendChild(zoomControls);

    const handle = document.createElement('div');
    handle.className = 'mermaid-resize-handle';
    handle.style.touchAction = 'none';
    block.appendChild(handle);

    let dragging = false, startY, startHeight, pointerId;

    const onPointerDown = (e) => {
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
    };

    const onPointerMove = (e) => {
      if (!dragging) return;
      const delta = e.clientY - startY;
      const newH = Math.max(100, Math.min(window.innerHeight * 0.9, startHeight + delta));
      inner.style.maxHeight = 'none';
      inner.style.height = newH + 'px';
      inner.style.overflow = 'auto';
    };

    const onPointerUp = (e) => {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove('dragging');
      handle.releasePointerCapture(pointerId);
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
    };

    handle.addEventListener('pointerdown', onPointerDown);
    handle.addEventListener('pointermove', onPointerMove);
    handle.addEventListener('pointerup', onPointerUp);
    handle.addEventListener('pointercancel', onPointerUp);
  });
}

// ===== Render Markdown =====
function createMarkdownRenderer(entryRelPath, mermaidStore) {
  let mermaidIdx = 0;

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
    // If href is not absolute URL or /-prefixed, treat as relative
    if (!/^https?:\/\//i.test(href) && !href.startsWith('/')) {
      const dir = entryRelPath.split('/').slice(0, -1).join('/');
      const fullPath = dir ? dir + '/' + href : href;
      href = `/api/clawmate/preview?root=${encodeURIComponent(state.rootId)}&path=${encodeURIComponent(fullPath)}`;
    }
    return `<img src="${href}" alt="${escHtml(text)}"${title ? ` title="${escHtml(title)}"` : ''}>`;
  };

  // Handle fenced code blocks (mermaid + syntax highlighting)
  md.renderer.rules.fence = function(tokens, idx, options, env, slf) {
    const token = tokens[idx];
    const language = token.info.trim();
    const raw = token.content;
    const className = language ? `language-${language}` : '';

    // Mermaid diagram — store code in memory array, output placeholder
    if (language === 'mermaid') {
      const id = mermaidIdx++;
      mermaidStore[id] = raw;
      return `<div class="mermaid" data-mermaid-id="${id}"></div>`;
    }

    // Highlight with hljs
    if (language && window.hljs) {
      try {
        // Normalize common language aliases
        const langMap = {
          'yml': 'yaml', 'node': 'javascript', 'node.js': 'javascript',
          'py': 'python', 'sh': 'bash', 'markdown': 'md', 'text': 'plaintext'
        };
        const normalizedLang = langMap[language.toLowerCase()] || language;
        const plain = raw.replace(/<[^>]*>/g, '');
        const highlighted = hljs.highlight(plain, { language: normalizedLang, ignoreIllegals: true }).value;
        return `<pre class="hljs" data-highlighted="yes"><code class="${className}">${highlighted}</code></pre>`;
      } catch (_) {}
    }

    // No highlighting — escape HTML safely
    return `<pre><code class="${className}">${escHtml(raw)}</code></pre>`;
  };

  return md;
}

function renderBreadcrumbContainer(container) {
  if (!container) return;
  container.innerHTML = "";
  const items = buildBreadcrumbItems();
  items.forEach((item, idx) => {
    if (idx > 0) {
      const sep = document.createElement("span");
      sep.className = "breadcrumb-sep";
      sep.textContent = " / ";
      container.appendChild(sep);
    }
    const link = document.createElement("a");
    link.className = "breadcrumb-link";
    link.href = getDirHref(item.dir);
    link.textContent = item.label;
    link.addEventListener("click", (e) => {
      e.preventDefault();
      loadDir(item.dir);
    });
    container.appendChild(link);
  });
}

function renderBreadcrumbs() {
  renderBreadcrumbContainer(els.breadcrumb);
  if (els.currentPath) {
    els.currentPath.classList.add("breadcrumb");
    renderBreadcrumbContainer(els.currentPath);
  }
  // Add action buttons after breadcrumb
  var container = els.currentPath || els.breadcrumb;
  if (!container) return;
  // Remove existing action buttons
  var existing = container.querySelectorAll('.breadcrumb-copy,.breadcrumb-refresh');
  for (var i = 0; i < existing.length; i++) existing[i].remove();
  // Copy directory button
  var copyBtn = document.createElement('button');
  copyBtn.className = 'breadcrumb-copy';
  copyBtn.title = '复制目录';
  copyBtn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
  copyBtn.addEventListener('click', function (e) {
    e.preventDefault();
    var root = getRootById(state.rootId);
    var absPath = root ? (root.dir + (state.dir ? '/' + state.dir : '')) : (state.dir || '');
    copyText(absPath || state.rootLabel || '');
    copyBtn.classList.add('copied');
    setTimeout(function () { copyBtn.classList.remove('copied'); }, 1200);
  });
  container.appendChild(copyBtn);
  // Refresh directory button
  var refreshBtn = document.createElement('button');
  refreshBtn.className = 'breadcrumb-copy breadcrumb-refresh';
  refreshBtn.title = '刷新当前目录';
  refreshBtn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M3 21v-5h5"/></svg>';
  refreshBtn.addEventListener('click', function (e) {
    e.preventDefault();
    invalidateDirCache();
    if (state.rootId) loadDir(state.dir);
    else loadConfig();
  });
  container.appendChild(refreshBtn);
}

// Compute parent directory path from a given dir
function getParentDir(dir) {
  if (!dir) return "";
  const parts = dir.split("/");
  parts.pop();
  return parts.join("/");
}

// Load parent directory entries for sidebar
async function loadSidebarParent(dir) {
  if (!state.rootId) return;
  // At root level: load root's own directory listing (not parent, which doesn't exist)
  // At subdirectory: load parent directory listing to show sibling dirs
  const fetchDir = (dir === "") ? "" : getParentDir(dir);
  try {
    const res = await authFetch(`/api/clawmate/list?root=${encodeURIComponent(state.rootId)}&dir=${encodeURIComponent(fetchDir)}`);
    if (!res.ok) {
      sidebarParentDir = fetchDir;
      sidebarEntries = [];
      return;
    }
    const data = await res.json();
    sidebarParentDir = fetchDir;
    sidebarEntries = (data.entries || [])
      .filter(e => e.is_dir && !e.name.startsWith("."))
      .map(e => ({
        ...e,
        relPath: e.path || ""
      }))
      .sort((a, b) => a.name.localeCompare(b.name));
  } catch (_) {
    sidebarParentDir = fetchDir;
    sidebarEntries = [];
  }
}

function renderSidebarTree() {
  els.dirList.innerHTML = "";
  // v1.24-b 防御性：过滤 name 为空白字符的目录项（避免 CSS ellipsis 截断导致"空名"假象）
  sidebarEntries = sidebarEntries.filter(e => !(e.is_dir && e.name.trim() === ""));
  if (!sidebarEntries.length) {
    const li = document.createElement("li");
    li.textContent = "（无子目录）";
    li.style.paddingLeft = "8px";
    li.style.color = "var(--text-muted, #999)";
    els.dirList.appendChild(li);
    return;
  }
  sidebarEntries.forEach((entry) => {
    const li = document.createElement("li");
    li.style.display = "flex";
    li.style.alignItems = "center";
    li.style.gap = "4px";
    li.style.paddingLeft = "8px";
    li.style.cursor = "pointer";
    li.style.borderRadius = "4px";

    const icon = document.createElement("span");
    var icoName = entry.relPath === state.dir ? 'folder-open' : (entry.marker ? 'folder-project' : 'folder');
    icon.innerHTML = typeof iconSVG === 'function' ? iconSVG(icoName, 14) : (entry.relPath === state.dir ? '📂' : (entry.marker ? '🦞' : '📁'));
    icon.style.flexShrink = "0";

    const label = document.createElement("span");
    label.textContent = entry.name;
    label.style.flex = "1";
    label.style.overflow = "hidden";
    label.style.textOverflow = "ellipsis";
    label.style.whiteSpace = "nowrap";

    li.addEventListener("click", () => {
      if (entry.relPath !== state.dir) loadDir(entry.relPath);
      if (window.innerWidth < 768) {
        els.sidebar.classList.add('hidden');
        btnToggleSidebar.classList.remove('active');
        if (els.sidebarOverlay) els.sidebarOverlay.style.display = 'none';
      }
    });
    if (entry.relPath === state.dir) {
      li.style.fontWeight = "bold";
      li.style.color = "var(--accent, #4a9eff)";
    }

    li.appendChild(icon);
    li.appendChild(label);
    els.dirList.appendChild(li);
  });
}

// Backward-compatible alias (kept so other code that might call renderDirs still works)
const renderDirs = renderSidebarTree;

// ===== Multi-Select & Batch Operations =====
function toggleSelect(relPath, checked) {
  if (checked) {
    state.selectedPaths.add(relPath);
  } else {
    state.selectedPaths.delete(relPath);
  }
  // Lightweight: toggle CSS class on existing cards, don't rebuild
  var sel = checked ? 'add' : 'remove';
  document.querySelectorAll('[data-path="' + CSS.escape(relPath) + '"]').forEach(function (el) {
    el.classList[sel]('selected');
  });
  updateBatchBar();
}

function toggleMultiSelect() {
  state.multiSelectEnabled = !state.multiSelectEnabled;
  if (els.multiSelectToggle) {
    if (typeof iconSVG === 'function') {
      els.multiSelectToggle.innerHTML = (state.multiSelectEnabled ? iconSVG('check-square', 14) : iconSVG('check-square', 14)) + ' 多选';
    } else {
      els.multiSelectToggle.textContent = state.multiSelectEnabled ? "☑ 多选" : "☐ 多选";
    }
    if (state.multiSelectEnabled) {
      els.multiSelectToggle.classList.add("active");
      document.body.classList.add("multiselect");
    } else {
      els.multiSelectToggle.classList.remove("active");
      document.body.classList.remove("multiselect");
      state.selectedPaths.clear();
      deselectAll();
    }
  }
}

function selectAll() {
  const entries = state.searchResults || state.entries;
  const { filtered } = applyFilterSort(entries);
  const allGrouped = [...filtered.filter(isMarkdownEntry), ...filtered.filter(e => e.is_dir), ...filtered.filter(e => !isMarkdownEntry(e) && !e.is_dir)];
  const { paged } = paginate(allGrouped);
  paged.forEach(function (entry) { state.selectedPaths.add(entry.relPath); });
  // Lightweight: just toggle classes on all visible cards
  document.querySelectorAll('.card, .list-item').forEach(function (el) {
    if (state.selectedPaths.has(el.dataset.path)) {
      el.classList.add('selected');
      var cb = el.querySelector('.card-check, .list-check');
      if (cb) cb.checked = true;
    }
  });
  updateBatchBar();
}

function deselectAll() {
  state.selectedPaths.clear();
  // Lightweight: just remove selected class from all cards
  document.querySelectorAll('.card.selected, .list-item.selected').forEach(function (el) {
    el.classList.remove('selected');
    var cb = el.querySelector('.card-check, .list-check');
    if (cb) cb.checked = false;
  });
  document.querySelectorAll('.card .card-check:checked, .list-item .list-check:checked').forEach(function (cb) {
    cb.checked = false;
  });
  updateBatchBar();
}

function updateBatchBar() {
  if (!els.batchBar) return;
  const count = state.selectedPaths.size;
  if (count === 0) {
    els.batchBar.classList.add("hidden");
  } else {
    els.batchBar.classList.remove("hidden");
    if (els.batchCount) els.batchCount.textContent = `已选 ${count} 个文件`;
  }
}

async function batchDelete() {
  const paths = Array.from(state.selectedPaths);
  if (paths.length === 0) return;

  const confirmed = window.confirm(
    `确定要批量删除 ${paths.length} 个文件吗？\n此操作不可恢复！\n\n文件列表:\n${paths.join("\n")}`
  );
  if (!confirmed) return;

  setStatus(`正在删除 ${paths.length} 个文件...`);
  let deleted = 0;
  let failed = 0;
  const errors = [];

  for (const path of paths) {
    try {
      // Check if path is a directory from current entries
      const entry = (state.searchResults || state.entries).find(e => e.relPath === path);
      const isDir = entry ? entry.is_dir : false;
      const url = isDir ? buildDirDeleteUrl(path) : buildDeleteUrl(path);
      const res = await authFetch(url, { method: "DELETE" });
      if (res.ok) {
        deleted++;
        state.selectedPaths.delete(path);
      } else {
        failed++;
        const err = await res.json().catch(() => ({ error: "删除失败" }));
        errors.push(`${path}: ${err.error || "删除失败"}`);
      }
    } catch (e) {
      failed++;
      errors.push(`${path}: ${e.message}`);
    }
  }

  if (errors.length > 0) {
    setStatus(`删除完成: ${deleted} 成功, ${failed} 失败。${errors.slice(0, 3).join("; ")}`);
  } else {
    setStatus(`成功删除 ${deleted} 个文件`);
  }

  // Reload current directory
  await loadDir(state.dir);
}

function batchDownloadSelected() {
  const paths = Array.from(state.selectedPaths);
  if (paths.length === 0) return;
  if (!state.rootId) { setStatus("请先选择根目录"); return; }

  // Try batch-download API with comma-separated paths
  const pathsParam = paths.map(encodeURIComponent).join(",");
  const url = `/api/clawmate/batch-download?root=${encodeURIComponent(state.rootId)}&paths=${pathsParam}`;
  setStatus(`正在打包下载 ${paths.length} 个文件...`);
  const link = document.createElement("a");
  link.href = url;
  link.download = `batch-${paths.length}-files.zip`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  setTimeout(() => setStatus(""), 3000);
}

function batchClear() {
  state.selectedPaths.clear();
  deselectAll();
}


function applyFilterSort(entries) {
  let filtered = entries;
  // Hide dotfiles
  filtered = filtered.filter((e) => !e.name.startsWith("."));
  if (state.filterType !== "all") {
    filtered = filtered.filter((entry) => {
      if (state.filterType === "dir") return entry.is_dir;
      if (entry.is_dir) return false;
      return entry.category === state.filterType;
    });
  }

  // Sort using state.sortKey and state.sortDir
  const { sortKey, sortDir } = state;
  const dir = sortDir === "desc" ? -1 : 1;
  filtered.sort((a, b) => {
    if (sortKey === "name") {
      return dir * a.name.localeCompare(b.name);
    } else if (sortKey === "size") {
      return dir * ((a.size || 0) - (b.size || 0));
    } else {
      // Default: mtime desc
      return dir * ((a.mtime || 0) - (b.mtime || 0));
    }
  });

  const { markdownEntries, folderEntries, otherEntries } = groupEntries(filtered);

  return { filtered, markdownEntries, folderEntries, otherEntries };
}

function paginate(entries) {
  const totalPages = Math.max(1, Math.ceil(entries.length / state.pageSize));
  state.page = Math.min(Math.max(state.page, 1), totalPages);
  const start = (state.page - 1) * state.pageSize;
  return {
    paged: entries.slice(start, start + state.pageSize),
    totalPages,
  };
}

function updatePagination(totalPages) {
  if (!els.pageInfo) return;
  els.pageInfo.textContent = `第 ${state.page} / ${totalPages} 页`;
  els.prevPage.disabled = state.page <= 1;
  els.nextPage.disabled = state.page >= totalPages;
}

function appendGalleryGroupHeader(container, label) {
  const header = document.createElement("div");
  header.className = "entry-group-header";
  header.innerHTML = label;
  container.appendChild(header);
}

function renderGallery(markdownEntries, folderEntries, otherEntries) {
  els.gallery.innerHTML = "";

  const renderGroup = (entries, label) => {
    if (!entries.length) return;
    var frag = document.createDocumentFragment();
    appendGalleryGroupHeader(frag, label);
    entries.forEach((entry) => {
      const card = document.createElement("div");
      card.className = "card";
      card.dataset.path = entry.relPath;
      const isSelected = state.selectedPaths.has(entry.relPath);
      if (isSelected) card.classList.add("selected");

      // Checkbox always present, visibility via CSS .multiselect
      const check = document.createElement("input");
      check.type = "checkbox";
      check.className = "card-check";
      check.checked = isSelected;
      check.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleSelect(entry.relPath, check.checked);
      });

      const thumb = document.createElement("div");
      thumb.className = "thumb";
      if (entry.category === "image") {
        const img = document.createElement("img");
        img.src = `/api/clawmate/preview?root=${encodeURIComponent(state.rootId)}&path=${encodeURIComponent(entry.relPath)}`;
        img.loading = "lazy";
        img.decoding = "async";
        thumb.appendChild(img);
      } else {
        thumb.innerHTML = getFileIcon(entry);
      }
      // Append checkbox inside thumb
      thumb.appendChild(check);

      const title = document.createElement("div");
      title.className = "title";
      title.textContent = entry.name;

      const meta = document.createElement("div");
      meta.className = "meta";
      meta.innerHTML = `<span>${formatMtime(entry.mtime)}</span><span>${entry.is_dir ? "-" : formatSize(entry.size)}</span>`;

      card.appendChild(thumb);
      card.appendChild(title);
      card.appendChild(meta);

      // ── ⋯ Menu button (overlaid on thumb) ──
      var menuBtn = document.createElement("button");
      menuBtn.className = "card-menu-btn";
      menuBtn.innerHTML = iconSVG('menu', 15);
      menuBtn.title = "操作";
      menuBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        // Toggle: if this menu is already open, close it
        if (menuBtn._dropdown) {
          menuBtn._dropdown.remove();
          menuBtn._dropdown = null;
          return;
        }
        // Close any other open menu first
        var existing = document.querySelector('.card-menu-dropdown');
        if (existing) existing.remove();
        // Build dropdown
        var dropdown = document.createElement("div");
        dropdown.className = "card-menu-dropdown";
        menuBtn._dropdown = dropdown;
        function addItem(iconName, label, onClick) {
          var item = document.createElement("div");
          item.className = "card-menu-item";
          item.innerHTML = iconSVG(iconName, 13) + '<span>' + label + '</span>';
          item.addEventListener("click", function (ev) {
            ev.stopPropagation();
            dropdown.remove();
            menuBtn._dropdown = null;
            onClick();
          });
          dropdown.appendChild(item);
        }
        addItem('copy', '复制文件名', function () {
          copyText(entry.name, "已复制文件名");
        });
        addItem('move', '移动到...', function () {
          openDirPicker('选择目标目录 — ' + entry.name);
          dirPickerCallback = function (destDir) {
            authFetch('/api/clawmate/move', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ root: state.rootId, path: entry.relPath, dest: destDir })
            })
              .then(function (r) { return r.json(); })
              .then(function (data) {
                if (data.ok) { state.page = 1; state.searchResults = null; invalidateDirCache(); if (state.rootId) loadDir(state.dir); else loadConfig(); }
                else { alert('移动失败：' + (data.detail || data.error || '未知错误')); }
              })
              .catch(function () { alert('移动失败'); });
          };
        });
        if (entry.is_dir) {
          addItem('download', '下载', function () {
            triggerBatchDownload(buildBatchDownloadLink(entry.relPath), entry.name);
          });
        } else {
          addItem('download', '下载', function () {
            triggerDownload(buildDownloadLink(entry.relPath));
          });
        }
        addItem('pencil', '重命名', function () {
          var newName = prompt("请输入新名称：", entry.name);
          if (newName && newName !== entry.name) {
            authFetch('/api/clawmate/rename?root=' + encodeURIComponent(state.rootId) + '&path=' + encodeURIComponent(entry.relPath) + '&new_name=' + encodeURIComponent(newName), { method: 'POST' })
              .then(function (r) { return r.json(); })
              .then(function (data) { if (data.ok) { state.page = 1; state.searchResults = null; invalidateDirCache(); if (state.rootId) loadDir(state.dir); else loadConfig(); } else { alert('重命名失败：' + (data.detail || data.error || '未知错误')); } })
              .catch(function () { alert('重命名失败'); });
          }
        });
        addItem('trash-2', '删除', function () { deleteEntry(entry); });
        // Position dropdown relative to the menu button (viewport-relative)
        // so it floats above all cards, never clipped.
        var btnRect = menuBtn.getBoundingClientRect();
        dropdown.style.position = 'fixed';
        dropdown.style.top = (btnRect.bottom + 4) + 'px';
        dropdown.style.left = (btnRect.right - 140) + 'px';
        dropdown.style.zIndex = '9999';
        document.body.appendChild(dropdown);
      });
      thumb.appendChild(menuBtn);

      card.onclick = () => handleEntryClick(entry);
      frag.appendChild(card);
    });
    // Batch insert this group
    els.gallery.appendChild(frag);
  };

  renderGroup(markdownEntries, (typeof iconSVG === 'function' ? iconSVG('file-text', 12) + ' ' : '') + 'Markdown');
  renderGroup(folderEntries, (typeof iconSVG === 'function' ? iconSVG('folder', 12) + ' ' : '') + '文件夹');
  renderGroup(otherEntries, (typeof iconSVG === 'function' ? iconSVG('file', 12) + ' ' : '') + '文件');

  // Staggered reveal animation
  animateCards();
}

function animateCards() {
  // Simultaneous fade-in — no stagger, all cards appear together
  var cards = document.querySelectorAll('#gallery .card');
  requestAnimationFrame(function () {
    cards.forEach(function (card) {
      card.style.animation = 'cardFadeIn 0.3s cubic-bezier(0.16,1,0.3,1) both';
    });
  });
}

function renderList(markdownEntries, folderEntries, otherEntries) {
  els.list.innerHTML = "";

  const renderGroup = (entries, label) => {
    if (!entries.length) return;
    const header = document.createElement("div");
    header.className = "entry-group-header";
    header.innerHTML = label;
    els.list.appendChild(header);
    entries.forEach((entry) => {
      const row = document.createElement("div");
      row.className = "list-item";
      row.dataset.path = entry.relPath;
      const isSelected = state.selectedPaths.has(entry.relPath);
      if (isSelected) row.classList.add("selected");

      // Checkbox always present, visibility via CSS .multiselect
      const check = document.createElement("input");
      check.type = "checkbox";
      check.className = "list-check";
      check.checked = isSelected;
      check.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleSelect(entry.relPath, check.checked);
      });
      row.appendChild(check);

      const icon = document.createElement("span");
      icon.innerHTML = typeof fileIconSVG === 'function' ? fileIconSVG(entry, 22) : getFileIcon(entry);
      icon.style.marginRight = "6px";
      icon.style.flexShrink = "0";
      const name = document.createElement("span");
      name.style.display = "flex";
      name.style.alignItems = "center";
      name.style.minWidth = "0";
      name.appendChild(icon);
      name.appendChild(document.createTextNode(entry.name));
      // Copy filename button — always visible, after filename
      const copyBtn = document.createElement("button");
      copyBtn.className = "list-copy-btn";
      copyBtn.innerHTML = iconSVG('copy', 12);
      copyBtn.title = "复制文件名";
      copyBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        copyText(entry.name, "已复制文件名");
        copyBtn.classList.add("copied");
        setTimeout(function () { copyBtn.classList.remove("copied"); }, 1200);
      });
      name.appendChild(copyBtn);
      const type = document.createElement("span");
      type.textContent = entry.is_dir ? "目录" : entry.category;
      const size = document.createElement("span");
      size.textContent = entry.is_dir ? "-" : formatSize(entry.size);
      const mtime = document.createElement("span");
      const dt = new Date(entry.mtime * 1000);
      var mo = dt.getMonth() + 1, d = dt.getDate(), h = dt.getHours(), mi = dt.getMinutes();
      mtime.textContent = isNaN(dt.getTime()) ? "-" : (mo + '/' + d + ' ' + String(h).padStart(2,'0') + ':' + String(mi).padStart(2,'0'));

      row.appendChild(name);
      row.appendChild(type);
      row.appendChild(size);
      row.appendChild(mtime);
      row.onclick = () => handleEntryClick(entry);
      els.list.appendChild(row);
    });
  };

  renderGroup(markdownEntries, (typeof iconSVG === 'function' ? iconSVG('file-text', 12) + ' ' : '') + 'Markdown');
  renderGroup(folderEntries, (typeof iconSVG === 'function' ? iconSVG('folder', 12) + ' ' : '') + '文件夹');
  renderGroup(otherEntries, (typeof iconSVG === 'function' ? iconSVG('file', 12) + ' ' : '') + '文件');
}

// Cache breadcrumb/sidebar between renders (only rebuild on dir change)
var _lastRenderedDir = null;
function render() {
  var currentKey = state.rootId + ':' + state.dir;
  var dirChanged = _lastRenderedDir !== currentKey;
  if (dirChanged) {
    _lastRenderedDir = currentKey;
    renderBreadcrumbs();
    renderDirs();
  }

  const entries = state.searchResults || state.entries;
  const { filtered, markdownEntries, folderEntries, otherEntries } = applyFilterSort(entries);

  // Paginate over the combined group order (markdown → folder → other)
  const allGrouped = [...markdownEntries, ...folderEntries, ...otherEntries];
  const { paged, totalPages } = paginate(allGrouped);

  // Re-split paged results back into groups for rendering
  const pagedMarkdown = paged.filter((e) => markdownEntries.includes(e));
  const pagedFolder = paged.filter((e) => folderEntries.includes(e));
  const pagedOther = paged.filter((e) => otherEntries.includes(e));

  // Only render current view (the other is hidden — skip wasted DOM work)
  if (state.view === 'grid') {
    renderGallery(pagedMarkdown, pagedFolder, pagedOther);
  } else {
    renderList(pagedMarkdown, pagedFolder, pagedOther);
  }
  updatePagination(totalPages);
  updateLoadMoreBtn();
  updateBatchBar();

  // Empty state toggling
  var emptyStateEl = document.getElementById('emptyState');
  var emptySearchEl = document.getElementById('emptySearch');
  if (emptyStateEl) emptyStateEl.classList.add('hidden');
  if (emptySearchEl) emptySearchEl.classList.add('hidden');

  var baseCount = entries.length;
  var filteredCount = filtered.length;
  var isSearch = !!state.searchResults;
  if (isSearch && baseCount === 0) {
    if (emptySearchEl) emptySearchEl.classList.remove('hidden');
  } else if (baseCount === 0) {
    if (emptyStateEl) emptyStateEl.classList.remove('hidden');
  }
  if (!state.searchResults && baseCount === 0) {
    setStatus("目录为空");
  } else {
    const searchPrefix = state.searchResults ? `搜索 "${state.searchQuery}"，找到 ${baseCount} 项` : `${baseCount} 项`;
    const filterInfo = filteredCount !== baseCount ? `，筛选后 ${filteredCount} 项` : "";
    setStatus(`${searchPrefix}${filterInfo} · 第 ${state.page}/${totalPages} 页`);
  }
}

// ===== Skeleton Screen Helpers =====
function showGallerySkeleton() {
  const count = 12;
  els.gallery.innerHTML = '';
  for (let i = 0; i < count; i++) {
    const card = document.createElement('div');
    card.className = 'skeleton-card';
    card.style.animationDelay = `${(i % 4) * 0.1}s`;
    card.innerHTML = `
      <div class="skeleton-thumb"></div>
      <div class="skeleton-line medium"></div>
      <div class="skeleton-line short"></div>
    `;
    els.gallery.appendChild(card);
  }
}

function showListSkeleton() {
  els.list.innerHTML = '';
  const wrap = document.createElement('div');
  wrap.className = 'list-table-wrap';
  const table = document.createElement('table');
  const count = 8;
  for (let i = 0; i < count; i++) {
    const tr = document.createElement('tr');
    tr.style.animationDelay = `${(i % 4) * 0.1}s`;
    tr.innerHTML = `
      <td style="width:32px"></td>
      <td><div class="skeleton-line" style="width:${50 + (i % 3) * 15}%"></div></td>
      <td><div class="skeleton-line" style="width:60%"></div></td>
      <td><div class="skeleton-line" style="width:50%"></div></td>
      <td><div class="skeleton-line" style="width:65%"></div></td>
    `;
    table.appendChild(tr);
  }
  wrap.appendChild(table);
  els.list.appendChild(wrap);
}


// ===== Drag-and-Drop Upload =====
async function checkOnlyofficeAvailable() {
  if (state.onlyofficeAvailable !== null) return state.onlyofficeAvailable;
  try {
    const res = await fetch('/api/clawmate/onlyoffice/script-url');
    const data = await res.json();
    state.onlyofficeAvailable = !!(data.url && data.url.trim() !== '');
  } catch (_) {
    state.onlyofficeAvailable = false;
  }
  return state.onlyofficeAvailable;
}

function setupDragDrop() {
  const mainEl = document.querySelector('.main');
  if (!mainEl) return;

  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(evt => {
    mainEl.addEventListener(evt, e => {
      e.preventDefault();
      e.stopPropagation();
    });
  });

  ['dragenter', 'dragover'].forEach(evt => {
    mainEl.addEventListener(evt, () => {
      if (state.rootId) mainEl.classList.add('drag-over');
    });
  });

  ['dragleave', 'drop'].forEach(evt => {
    mainEl.addEventListener(evt, () => {
      mainEl.classList.remove('drag-over');
    });
  });

  mainEl.addEventListener('drop', async e => {
    if (!state.rootId) { setStatus('请先选择根目录'); return; }
    const files = Array.from(e.dataTransfer.files);
    if (!files.length) return;
    setStatus(`正在上传 ${files.length} 个文件...`);
    let uploaded = 0, failed = 0;
    for (const file of files) {
      try {
        const formData = new FormData();
        formData.append('file', file);
        const res = await authFetch(
          `/api/clawmate/upload?root=${encodeURIComponent(state.rootId)}&dir=${encodeURIComponent(state.dir)}`,
          { method: 'POST', body: formData }
        );
        if (res.ok) uploaded++;
        else failed++;
      } catch (_) {
        failed++;
      }
    }
    setStatus(`上传完成: ${uploaded} 成功${failed ? ', ' + failed + ' 失败' : ''}`);
    if (uploaded > 0) loadDir(state.dir);
  });

  // ── Clipboard paste: paste image from clipboard and upload ──
  document.addEventListener('paste', async e => {
    // Ignore paste in input/textarea/contenteditable
    var tag = e.target && e.target.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || (e.target && e.target.isContentEditable)) return;
    if (!state.rootId) { setStatus('请先选择根目录'); return; }
    var files = e.clipboardData.files;
    var items = e.clipboardData.items;
    var imageFile = null;

    // Try files first
    if (files.length) {
      for (var i = 0; i < files.length; i++) {
        if (files[i].type && files[i].type.startsWith('image/')) {
          imageFile = files[i];
          break;
        }
      }
    }

    // Fallback: check items for image data (e.g. Snipping Tool, screenshot)
    if (!imageFile && items) {
      for (var i = 0; i < items.length; i++) {
        if (items[i].type && items[i].type.startsWith('image/')) {
          imageFile = items[i].getAsFile();
          if (imageFile) break;
        }
      }
    }

    if (!imageFile) return; // no image in clipboard, nothing to do
    e.preventDefault();

    // Generate a filename with timestamp
    var now = new Date();
    var ts = now.getFullYear()
      + String(now.getMonth()+1).padStart(2,'0')
      + String(now.getDate()).padStart(2,'0') + '-'
      + String(now.getHours()).padStart(2,'0')
      + String(now.getMinutes()).padStart(2,'0')
      + String(now.getSeconds()).padStart(2,'0');
    var ext = 'png';
    if (imageFile.name && imageFile.name.includes('.')) {
      ext = imageFile.name.split('.').pop();
    }
    var filename = 'paste-' + ts + '.' + ext;

    setStatus('正在上传剪切板图片...');
    try {
      var formData = new FormData();
      formData.append('file', imageFile, filename);
      var res = await authFetch(
        '/api/clawmate/upload?root=' + encodeURIComponent(state.rootId) + '&dir=' + encodeURIComponent(state.dir),
        { method: 'POST', body: formData }
      );
      if (res.ok) {
        var data = await res.json();
        setStatus('剪切板图片已上传: ' + (data.filename || filename));
        loadDir(state.dir);
      } else {
        setStatus('上传失败: ' + res.status);
      }
    } catch (err) {
      setStatus('上传出错: ' + (err.message || err));
    }
  });
}

// ── Directory list cache (30s TTL, keyed by root:dir) ──
const _dirCache = {};
const _DIR_CACHE_TTL = 30000; // 30 seconds

function _getCachedDir(key) {
  const entry = _dirCache[key];
  if (entry && Date.now() - entry.ts < _DIR_CACHE_TTL) return entry.data;
  return null;
}
function _setCachedDir(key, data) {
  _dirCache[key] = { data: data, ts: Date.now() };
}
// Invalidate cache on mutations (delete/rename/upload/save)
function invalidateDirCache() {
  for (var k in _dirCache) delete _dirCache[k];
}

async function loadDir(dir) {
  if (!state.rootId) {
    setStatus("请先选择根目录");
    return;
  }
  // Mobile: auto-close directory panel after navigation
  if (window.innerWidth < 768) {
    var sidebar = els.sidebar;
    if (sidebar && !sidebar.classList.contains('hidden')) {
      sidebar.classList.add('hidden');
      if (btnToggleSidebar) btnToggleSidebar.classList.remove('active');
      if (els.sidebarOverlay) els.sidebarOverlay.style.display = 'none';
    }
  }
  const safeDir = sanitizeDir(dir);
  if (dir && safeDir !== dir) {
    setStatus("非法目录，已回退到根目录");
  }
  state.searchResults = null;
  state.searchQuery = "";
  state.page = 1;
  state.loadingMore = false;

  const cacheKey = state.rootId + ':' + (safeDir || '');
  const cached = _getCachedDir(cacheKey);
  if (cached) {
    state.dir = cached.dir;
    state.entries = cached.entries;
    state.total = cached.total;
    state.hasMore = cached.hasMore;
    updateUrl();
    await loadSidebarParent(state.dir);
    render();
    if (window.Agent) window.Agent.updateRoot(state.rootId, state.dir);
    return;
  }

  setStatus("加载中...");
  // Show skeleton while loading
  if (state.view === 'grid') { showGallerySkeleton(); } else { showListSkeleton(); }  const res = await authFetch(`/api/clawmate/list?root=${encodeURIComponent(state.rootId)}&dir=${encodeURIComponent(safeDir)}&limit=${state.pageLimit}`);
  if (!res.ok) {
    if (res.status === 404) {
      setStatus("目录不存在");
    } else if (res.status === 403) {
      setStatus("没有权限访问该目录");
    } else {
      setStatus("无法加载目录");
    }
    return;
  }
  const data = await res.json();  state.dir = data.path || "";
  if (window.Agent) window.Agent.updateRoot(state.rootId, state.dir);
  state.entries = (data.entries || []).map(mapEntry);
  state.total = data.total || 0;
  state.hasMore = state.entries.length < state.total;
  _setCachedDir(cacheKey, {
    dir: state.dir, entries: state.entries, total: state.total, hasMore: state.hasMore
  });
  updateUrl();
  // Also load parent dir for sidebar
  await loadSidebarParent(state.dir);
  render();
}

async function loadMore() {
  if (state.loadingMore || !state.hasMore || state.searchResults) return;
  state.loadingMore = true;
  const btn = els.loadMoreBtn;
  if (btn) { btn.textContent = "加载中..."; btn.disabled = true; }

  const offset = state.entries.length;
  const safeDir = state.dir || "";  try {
    const res = await authFetch(`/api/clawmate/list?root=${encodeURIComponent(state.rootId)}&dir=${encodeURIComponent(safeDir)}&offset=${offset}&limit=${state.pageLimit}`);
    if (!res.ok) { state.loadingMore = false; updateLoadMoreBtn(); return; }
    const data = await res.json();
    const newEntries = (data.entries || []).map(mapEntry);
    state.entries = state.entries.concat(newEntries);
    state.total = data.total || 0;
    state.hasMore = state.entries.length < state.total;
  } catch (e) {
    console.error("loadMore error:", e);
  }
  state.loadingMore = false;
  updateLoadMoreBtn();
  render();
}

function updateLoadMoreBtn() {
  const btn = els.loadMoreBtn;
  if (!btn) return;
  if (state.searchResults) { btn.style.display = 'none'; return; }
  if (state.loadingMore) { btn.textContent = "加载中..."; btn.disabled = true; btn.style.display = ''; return; }
  if (state.hasMore) {
    const remaining = state.total - state.entries.length;
    btn.textContent = `加载更多 (剩余 ${remaining} 项)`;
    btn.disabled = false;
    btn.style.display = '';
  } else {
    btn.style.display = 'none';
  }
}

// ── Infinite scroll via IntersectionObserver ─────────────────────────
let _scrollObserver = null;

function setupInfiniteScroll() {
  teardownInfiniteScroll();
  const sentinel = document.getElementById('scrollSentinel');
  if (!sentinel) return;
  _scrollObserver = new IntersectionObserver(function (entries) {
    if (entries[0] && entries[0].isIntersecting && state.hasMore && !state.loadingMore && !state.searchResults) {
      loadMore();
    }
  }, { rootMargin: '200px' });
  _scrollObserver.observe(sentinel);
}

function teardownInfiniteScroll() {
  if (_scrollObserver) { _scrollObserver.disconnect(); _scrollObserver = null; }
}

async function search() {
  if (!state.rootId) {
    setStatus("请先选择根目录");
    return;
  }
  const q = els.searchInput.value.trim();
  if (!q) return;
  setStatus("搜索中...");
  const recursive = "true";
  const res = await authFetch(
    `/api/clawmate/search?root=${encodeURIComponent(state.rootId)}&q=${encodeURIComponent(q)}&dir=${encodeURIComponent(state.dir)}&recursive=${recursive}`
  );
  if (!res.ok) {
    setStatus("搜索失败");
    return;
  }
  const data = await res.json();
  state.searchResults = (data.results || []).map(mapEntry);
  state.searchQuery = q;
  state.page = 1;
  render();
}

function clearSearch() {
  state.searchResults = null;
  state.searchQuery = "";
  state.page = 1;
  els.searchInput.value = "";
  render();
}

function handleEntryClick(entry) {
  if (entry.is_dir) {
    loadDir(entry.relPath);
  } else {
    openEntryPreview(entry);
  }
}

function openEntryPreview(entry) {
  if (!entry || entry.is_dir) return;
  const previewUrl = `/clawmate/preview.html?root=${encodeURIComponent(state.rootId)}&file=${encodeURIComponent(entry.relPath)}`;
  window.open(previewUrl, '_blank');
}


function setView(view) {
  state.view = view;
  if (view === "grid") {
    els.gallery.classList.remove("hidden");
    els.list.classList.add("hidden");
    els.viewGrid.classList.add("active");
    els.viewList.classList.remove("active");
  } else {
    els.gallery.classList.add("hidden");
    els.list.classList.remove("hidden");
    els.viewGrid.classList.remove("active");
    els.viewList.classList.add("active");
  }
  render();
}

function setFilterType(value) {
  state.filterType = value;
  state.page = 1;
  // toggle accent when filtering
  if (value !== "all") {
    els.filterType.classList.add("filtering");
  } else {
    els.filterType.classList.remove("filtering");
  }
  render();
}

function handleSortPill(btn) {
  const key = btn.dataset.key;
  if (state.sortKey === key) {
    // Same key: toggle direction
    state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
  } else {
    // Different key: switch sort key, keep current direction
    state.sortKey = key;
  }
  state.page = 1;
  updateSortPills();
  render();
}

async function loadConfig() {
  try {
    const res = await fetch("/api/clawmate/config");
    if (!res.ok) throw new Error("config not found");
    const data = await res.json();
    state.roots = Array.isArray(data.roots) ? data.roots : [];
    state.defaultRootId = data.defaultRootId || "";
    if (!state.roots.length) {
      state.roots = [{ id: "media", label: "媒体", dir: "" }];
    }
    // Store agent config for later init (after root selection)
    state.agentConfig = data.agent || null;
  } catch (err) {
    state.roots = [{ id: "media", label: "媒体", dir: "" }];
    state.defaultRootId = "";
  }
  populateRootSelect();
}

// ===== Event Listeners =====
els.searchBtn.addEventListener("click", search);
els.clearSearchBtn.addEventListener("click", clearSearch);
els.searchInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") search();
});
if (els.rootSelect) {
  els.rootSelect.addEventListener("change", (e) => {
    if (!selectRoot(e.target.value)) {
      setStatus("根目录无效");
      return;
    }
    _initAgent();
    // Reset multi-select state on root change
    if (state.multiSelectEnabled) {
      state.multiSelectEnabled = false;
      state.selectedPaths.clear();
      if (els.multiSelectToggle) {
        els.multiSelectToggle.textContent = "☐ 多选";
        els.multiSelectToggle.classList.remove("active");
      }
      updateBatchBar();
      if (els.batchBar) els.batchBar.classList.add("hidden");
    }
    state.dir = "";
    state.page = 1;
    loadDir("");
  });
}
els.viewGrid.addEventListener("click", () => setView("grid"));
els.viewList.addEventListener("click", () => setView("list"));

// Hamburger menu (mobile)
els.hamburgerBtn && els.hamburgerBtn.addEventListener("click", () => {
  if (!els.sidebar) return;
  const isHidden = els.sidebar.classList.contains('hidden');
  if (isHidden) {
    els.sidebar.classList.remove('hidden');
  } else {
    els.sidebar.classList.add('hidden');
  }
  if (els.sidebarOverlay) {
    els.sidebarOverlay.style.display = isHidden ? 'block' : 'none';
  }
  // Sync sidebar toggle button state
  const btn = document.getElementById('btnToggleSidebar');
  if (btn) btn.classList.toggle('active', isHidden);
});
els.sidebarOverlay && els.sidebarOverlay.addEventListener("click", () => {
  els.sidebar && els.sidebar.classList.add('hidden');
  if (els.sidebarOverlay) els.sidebarOverlay.style.display = "none";
  // Sync sidebar toggle button state
  const btn = document.getElementById("btnToggleSidebar");
  if (btn) btn.classList.remove("active");
});
els.filterType.addEventListener("change", (e) => setFilterType(e.target.value));
els.sortTime && els.sortTime.addEventListener("click", () => handleSortPill(els.sortTime));
els.sortName && els.sortName.addEventListener("click", () => handleSortPill(els.sortName));
els.sortSize && els.sortSize.addEventListener("click", () => handleSortPill(els.sortSize));
els.prevPage.addEventListener("click", () => {
  if (state.page > 1) {
    state.page -= 1;
    render();
  }
});
els.nextPage.addEventListener("click", () => {
  state.page += 1;
  render();
});
els.loadMoreBtn && els.loadMoreBtn.addEventListener("click", loadMore);

// Sidebar toggle
const btnToggleSidebar = document.getElementById("btnToggleSidebar");
if (btnToggleSidebar) {
  // Set initial active state
  if (window.innerWidth >= 768) {
    btnToggleSidebar.classList.add("active");
  }
  btnToggleSidebar.addEventListener("click", function () {
    const sidebar = els.sidebar;
    if (!sidebar) return;
    if (window.innerWidth < 768) {
      // Mobile: close agent overlay first if showing (mutual exclusion)
      const agentPanel = document.getElementById("agentPanel");
      if (agentPanel && !agentPanel.classList.contains('hidden')) {
        if (window.Agent) window.Agent.close();
      }
      // Toggle overlay — uses .hidden class consistent with preview panels
      const isHidden = sidebar.classList.contains('hidden');
      if (isHidden) {
        sidebar.classList.remove('hidden');
        btnToggleSidebar.classList.add('active');
      } else {
        sidebar.classList.add('hidden');
        btnToggleSidebar.classList.remove('active');
      }
      // Toggle overlay
      if (els.sidebarOverlay) {
        els.sidebarOverlay.style.display = isHidden ? 'block' : 'none';
      }
    } else {
      // Desktop: if CSS auto-hides sidebar (agent-open + narrow), close agent first
      const agentPanel = document.getElementById("agentPanel");
      const cssHidden = agentPanel && !agentPanel.classList.contains("hidden") && window.innerWidth <= 1500 && document.body.classList.contains("agent-open");
      if (cssHidden && sidebar.classList.contains("hidden")) {
        if (window.Agent) window.Agent.close();
      }
      // Toggle with slide animation
      const isHidden = sidebar.classList.contains("hidden");
      if (isHidden) {
        // ── Open: slide from left ──
        sidebar.style.display = 'flex';           // override global .hidden display:none
        // Expand grid column directly while sidebar is still "hidden"
        // (bypass _updateContentGrid which would keep column at 0px)
        var _contentEl = document.querySelector('.content');
        var gridParts = (_contentEl.style.gridTemplateColumns || '240px 1fr 0px 0px').split(' ');
        gridParts[0] = '240px';
        _contentEl.style.gridTemplateColumns = gridParts.join(' ');
        sidebar.offsetHeight;                     // force reflow: w=240, translateX(-240px)
        sidebar.classList.remove('hidden');       // slide-in: translateX(-240px) → 0
        sidebar.style.display = '';               // let CSS .sidebar handle display
        btnToggleSidebar.classList.add('active');
      } else {
        // ── Close: slide to left ──
        sidebar.style.display = 'flex';           // override global .hidden display:none
        sidebar.classList.add('hidden');          // slide-out: translateX(0) → translateX(-100%)
        btnToggleSidebar.classList.remove('active');
        // Grid stays expanded during slide-out; collapse after animation
        setTimeout(function () {
          sidebar.style.display = '';             // let global .hidden handle display
          _updateContentGrid();                   // grid column → 0px
        }, 300);
      }
    }
    syncSidebarBtn();
  });
}

// Update content grid columns when sidebar/agent panel change
function _updateContentGrid() {
  // Delegate to agent.js for consistent grid management
  if (window.Agent && window.Agent.updateGrid) {
    window.Agent.updateGrid();
  }
}

// Theme toggle
els.themeToggle && els.themeToggle.addEventListener("click", cycleTheme);

// Agent panel toggle
const btnToggleAgent = document.getElementById("btnToggleAgent");
btnToggleAgent && btnToggleAgent.addEventListener("click", function () {
  if (window.Agent) {
    // If opening agent, close sidebar first (mutual exclusion)
    if (!window.Agent.isOpen()) {
      if (window.innerWidth < 768) {
        // Mobile: close sidebar overlay
        if (els.sidebar && !els.sidebar.classList.contains('hidden')) {
          els.sidebar.classList.add('hidden');
          syncSidebarBtn();
          if (els.sidebarOverlay) els.sidebarOverlay.style.display = 'none';
        }
      } else if (window.innerWidth <= 1500) {
        // Desktop narrow: hide sidebar
        if (els.sidebar && !els.sidebar.classList.contains('hidden')) {
          els.sidebar.classList.add('hidden');
          syncSidebarBtn();
          _updateContentGrid();
        }
      }
    }
    window.Agent.toggle();
    if (window.Agent.isOpen()) {
      btnToggleAgent.classList.add("active");
      window.Agent.focus();
    } else {
      btnToggleAgent.classList.remove("active");
    }
  }
});

// Logout
const btnLogoutMain = document.getElementById("btnLogout");
btnLogoutMain && btnLogoutMain.addEventListener("click", async function() {
  if (!confirm("确定要退出登录吗？")) return;
  try { await fetch("/api/clawmate/auth/logout", { method: "POST" }); } catch (_) {}
  window.location.href = "/clawmate/login.html";
});

// Create directory
async function mkdirCurrent() {
  if (!state.rootId) { setStatus("请先选择根目录"); return; }
  var name = prompt("请输入新目录名：");
  if (!name) return;
  name = name.trim();
  if (!name) return;
  try {
    var res = await authFetch("/api/clawmate/mkdir", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ root: state.rootId, dir: state.dir, name: name }),
    });
    if (res.ok) {
      setStatus("目录已创建: " + name);
      invalidateDirCache();
      loadDir(state.dir);
    } else {
      var detail = "";
      try { var err = await res.json(); detail = err.detail || ""; } catch (_) {}
      setStatus("创建失败: " + (detail || res.status));
    }
  } catch (e) {
    setStatus("创建出错: " + (e.message || e));
  }
}

// Multi-select
els.multiSelectToggle && els.multiSelectToggle.addEventListener("click", toggleMultiSelect);
els.btnMkdir && els.btnMkdir.addEventListener("click", mkdirCurrent);
els.batchSelectAllBtn && els.batchSelectAllBtn.addEventListener("click", selectAll);

// Batch operations
els.batchDeleteBtn && els.batchDeleteBtn.addEventListener("click", batchDelete);
els.batchDownloadBtn2 && els.batchDownloadBtn2.addEventListener("click", batchDownloadSelected);
els.batchClearBtn && els.batchClearBtn.addEventListener("click", batchClear);


// Batch download button (pagination bar)
els.batchDownloadBtn && els.batchDownloadBtn.addEventListener("click", () => {
  if (!state.rootId) { setStatus("请先选择根目录"); return; }
  triggerBatchDownload(buildBatchDownloadLink(state.dir), state.dir || "root");
});

// ===== Feedback Detail Modal =====
function showFeedbackDetailModal(item, statusIcon) {
  // Remove existing
  var existing = document.querySelector('.fb-detail-overlay');
  if (existing) existing.remove();

  var overlay = document.createElement('div');
  overlay.className = 'fb-detail-overlay';
  var modal = document.createElement('div');
  modal.className = 'fb-detail-modal';

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

  overlay.addEventListener('click', function(e) {
    if (e.target === overlay) overlay.remove();
  });
  var escHandler = function(e) {
    if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', escHandler); }
  };
  document.addEventListener('keydown', escHandler);
  document.body.appendChild(overlay);
}

// ===== Per-Preview Feedback Panel =====
let _activeFeedbackPanel = null;

function createFeedbackPanel(container, context) {
  // context: { root, project, path, rawContent, isStandalone }
  let items = [];

  // Stub functions referenced by feedback panel UI
  function clearHighlight() { /* no-op: main page has no highlight region */ }
  function highlightLinesInContainer(c, start, end) { /* no-op */ }
  async function _batchSendItems(api, items) {
    throw new Error('batchSendItems not implemented for main page feedback panel');
  }
  let completedItems = [];
  let idCounter = 0;
  let visible = false;
  let selectedItemId = null;

  const panel = document.createElement('div');
  // Default: hidden
  panel.classList.add('hidden');
  panel.className = 'preview-feedback-panel';

  const header = document.createElement('div');
  header.className = 'preview-feedback-panel-header';
  header.innerHTML = (typeof iconSVG === 'function' ? iconSVG('message-square', 14) + ' ' : '') + '反馈';
  panel.appendChild(header);

  const body = document.createElement('div');
  body.className = 'preview-feedback-panel-body';
  var copyIcon = typeof iconSVG === 'function' ? iconSVG('copy', 12) : '';
  body.innerHTML = '<div class="feedback-empty">选中文本后点击「' + copyIcon + ' 加入面板」即可累积</div>';
  panel.appendChild(body);

  // Helper: scroll container to make a given line range visible
  function _scrollToLines(container, startLine, endLine) {
    const text = container.textContent || '';
    const lines = text.split('\n');
    if (startLine > lines.length) return;
    // Calculate character offset for the start line
    let startOffset = 0;
    for (let i = 0; i < startLine - 1; i++) {
      startOffset += (lines[i] || '').length + 1;
    }
    // Walk text nodes to find the DOM element containing this offset
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null, false);
    let charCount = 0;
    let node;
    while ((node = walker.nextNode())) {
      const nodeLen = node.textContent.length;
      if (charCount + nodeLen > startOffset) {
        // Found the text node — scroll its parent into view
        let el = node.parentElement;
        // Walk up to a scrollable ancestor or the container itself
        while (el && el !== container && getComputedStyle(el).overflowY === 'visible') {
          el = el.parentElement;
        }
        if (!el) el = container;
        // Use the actual DOM node to scroll into view
        if (node.parentElement) {
          node.parentElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
        break;
      }
      charCount += nodeLen;
    }
  }

  function renderBody() {
    body.innerHTML = '';

    // Empty state: no pending and no completed items
    if (items.length === 0 && completedItems.length === 0) {
      var copyIcon = typeof iconSVG === 'function' ? iconSVG('copy', 12) : '';
  body.innerHTML = '<div class="feedback-empty">选中文本后点击「' + copyIcon + ' 加入面板」即可累积</div>';
      return;
    }

    // Section: pending items (interactive)
    if (items.length > 0) {
      if (completedItems.length > 0) {
        const pendingLabel = document.createElement('div');
        pendingLabel.className = 'feedback-section-label';
        pendingLabel.textContent = '📝 待提交';
        body.appendChild(pendingLabel);
      }

      items.forEach(item => {
        const card = document.createElement('div');
        card.className = 'preview-feedback-card';
        if (item.id === selectedItemId) card.classList.add('selected');

        const location = document.createElement('div');
        location.className = 'preview-feedback-card-location';
        location.textContent = `📄 ${item.path} L${item.startLine}-L${item.endLine}`;
        card.appendChild(location);

        const text = document.createElement('div');
        text.className = 'preview-feedback-card-text';
        text.textContent = item.text;
        card.appendChild(text);

        const noteInput = document.createElement('textarea');
        noteInput.className = 'preview-feedback-card-note';
        noteInput.placeholder = '备注（必填）';
        noteInput.value = item.note || '';
        noteInput.addEventListener('input', () => {
          item.note = noteInput.value;
        });
        card.appendChild(noteInput);

        const actions = document.createElement('div');
        actions.className = 'preview-feedback-card-actions';

        const delBtn = document.createElement('button');
        delBtn.className = 'fb-btn-delete';
        delBtn.textContent = '🗑 删除';
        delBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          if (confirm('确认删除此反馈？')) {
            items = items.filter(i => i.id !== item.id);
            if (selectedItemId === item.id) selectedItemId = null;
            clearHighlight();
            renderBody();
            _updateToggleBadge();
            // Auto-hide if no items remain
            if (items.length === 0) {
              api.hide();
            }
          }
        });
        actions.appendChild(delBtn);

        card.appendChild(actions);

        // Card click → highlight in preview
        card.addEventListener('click', () => {
          if (selectedItemId === item.id) {
            // Deselect
            selectedItemId = null;
            clearHighlight();
          } else {
            selectedItemId = item.id;
            // Scroll to the highlighted region before applying highlight
            _scrollToLines(container, item.startLine, item.endLine);
            highlightLinesInContainer(container, item.startLine, item.endLine);
          }
          renderBody();
        });

        body.appendChild(card);
      });

      // Submit all button
      const submitAllDiv = document.createElement('div');
      submitAllDiv.className = 'preview-feedback-submit-all';
      const submitAllBtn = document.createElement('button');
      submitAllBtn.className = 'fb-btn-submit-all';
      submitAllBtn.textContent = `✅ 提交全部（${items.length} 条）`;
      submitAllBtn.addEventListener('click', async () => {
        if (!items.length) return;
        submitAllBtn.disabled = true;
        submitAllBtn.textContent = '提交中...';
        try {
          await _batchSendItems(api, items);
          submitAllBtn.textContent = '✅ 已提交';
        } catch (err) {
          submitAllBtn.disabled = false;
          submitAllBtn.textContent = `❌ 提交失败（${err.message || '重试'})`;
          setTimeout(() => {
            submitAllBtn.disabled = false;
            submitAllBtn.textContent = `✅ 提交全部（${items.length} 条）`;
          }, 2500);
        }
      });
      submitAllDiv.appendChild(submitAllBtn);
      body.appendChild(submitAllDiv);
    }

    // Section: completed items (read-only, from API)
    if (completedItems.length > 0) {
      if (items.length > 0) {
        const sep = document.createElement('div');
        sep.className = 'feedback-section-sep';
        sep.innerHTML = '<span>✅ 已完成</span>';
        body.appendChild(sep);
      } else {
        const completedLabel = document.createElement('div');
        completedLabel.className = 'feedback-section-label';
        completedLabel.textContent = '✅ 已完成';
        body.appendChild(completedLabel);
      }

      completedItems.forEach(item => {
        const card = document.createElement('div');
        card.className = 'completed-feedback-card';
        const statusIcon = item.status === 'done' ? '✅' :
                           item.status === 'in_progress' ? '🔄' :
                           item.status === 'failed' ? '❌' : '⏳';
        const isDoneFailed = item.status === 'done' || item.status === 'failed';
        const resultText = (item.result || item.processing_result || '');
        const resultHtml = (isDoneFailed && resultText)
          ? '<div class="sfb-result">📋 ' + escHtml(resultText.length > 100 ? resultText.substring(0, 100) + '…' : resultText) + '</div>'
          : '';
        card.innerHTML = `
          <div class="sfb-header">
            <span class="sfb-status">${statusIcon}</span>
            <span class="sfb-id">${escHtml(item.id || '')}</span>
            <span class="sfb-time">${escHtml(item.updated || '').substring(5, 16)}</span>
          </div>
          <div class="sfb-note">${escHtml(item.user_note || item.note || '（无备注）')}</div>
          <div class="sfb-location">${escHtml(item.location || item.file || '')}</div>
          ${resultHtml}
        `;
        // Click to show detail modal
        card.style.cursor = 'pointer';
        card.addEventListener('click', () => {
          showFeedbackDetailModal(item, statusIcon);
        });
        body.appendChild(card);
      });
    }
  }

  async function _sendCardItem(item) {
    if (!item.note || !item.note.trim()) {
      _showToast('请填写备注');
      return;
    }
    try {
      const res = await authFetch('/api/clawmate/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode: 'send',
          root: context.root,
          project: context.project,
          path: item.path,
          selections: [{
            text: item.text,
            startLine: item.startLine,
            endLine: item.endLine,
            note: item.note,
          }],
        }),
      });
      if (res.ok) {
        items = items.filter(i => i.id !== item.id);
        if (selectedItemId === item.id) selectedItemId = null;
        clearHighlight();
        renderBody();
        _updateToggleBadge();
        // Auto-hide if no items remain
        if (items.length === 0) {
          api.hide();
        }
        _showToast('✅ 已发送');
      } else {
        const err = await res.json().catch(() => ({}));
        _showToast('❌ ' + (err.detail || '发送失败'));
      }
    } catch (e) {
      _showToast('❌ 网络错误');
    }
  }

  function _showToast(msg) {
    setStatus(msg);
    setTimeout(() => {
      if (els.status && els.status.textContent === msg) setStatus('');
    }, 2000);
  }

  function _updateToggleBadge() {
    const toggleBtn = container.querySelector('.feedback-toggle-btn');
    if (toggleBtn) {
      if (items.length > 0) {
        toggleBtn.classList.add('has-items');
      } else {
        toggleBtn.classList.remove('has-items');
      }
    }
  }

  const api = {
    el: panel,
    addItem(item) {
      const id = ++idCounter;
      items.push({ id, ...item, note: item.note || '' });
      renderBody();
      _updateToggleBadge();
      // Auto-show on first item
      if (items.length === 1) {
        api.show();
      }
      return id;
    },
    getPendingCount() { return items.length; },
    getPendingItems() { return items.slice(); },
    clearItems() {
      items = [];
      selectedItemId = null;
      clearHighlight();
      renderBody();
      _updateToggleBadge();
      if (items.length === 0) api.hide();
    },
    show() {
      visible = true;
      panel.classList.remove('hidden');
    },
    hide() {
      visible = false;
      panel.classList.add('hidden');
      clearHighlight();
      selectedItemId = null;
      renderBody();
    },
    destroy() {
      document.removeEventListener('click', _handleOutsideClick);
      if (_activeFeedbackPanel === api) _activeFeedbackPanel = null;
      clearHighlight();
      panel.remove();
    },
    toggle(show) {
      if (typeof show === 'boolean') {
        if (show) api.show();
        else api.hide();
      } else {
        if (visible) api.hide();
        else api.show();
      }
    },
    isVisible() { return visible; },
    loadCompletedItems(newItems) {
      completedItems = newItems || [];
      renderBody();
    },
    reloadCompletedItems() {
      // Fetch completed items from API and update the completedItems list
      const filePath = context.path;
      const project = context.project;
      const rootId = context.root;
      if (!rootId || !project || !filePath) return Promise.resolve([]);
      const fileName = filePath.split('/').pop();
      return fetch(`/api/clawmate/feedback/list?root=${encodeURIComponent(rootId)}&project=${encodeURIComponent(project)}&file=${encodeURIComponent(fileName)}`)
        .then(res => {
          if (!res.ok) return [];
          return res.json();
        })
        .then(data => {
          completedItems = data.items || [];
          renderBody();
          return completedItems;
        })
        .catch(() => {
          completedItems = [];
          renderBody();
          return [];
        });
    },
  };

  if (!context.isStandalone) {
    _activeFeedbackPanel = api;
  }

  // Click outside to collapse
  function _handleOutsideClick(e) {
    if (!visible) return;
    if (panel.contains(e.target)) return;
    if (e.target.closest('.feedback-toggle-btn')) return;
    if (feedbackTooltipEl && feedbackTooltipEl.contains(e.target)) return;
    api.hide();
  }
  document.addEventListener('click', _handleOutsideClick);

  // Also store on container for feedback panel lookup
  container._feedbackPanel = api;

  return api;
}

function getActiveFeedbackPanel() {
  return _activeFeedbackPanel;
}

function clearActiveFeedbackPanel() {
  if (_activeFeedbackPanel) {
    _activeFeedbackPanel.destroy();
    _activeFeedbackPanel = null;
  }
}


async function init() {
  await loadConfig();
  // Sync sort select with state default
  updateSortPills();
  setupDragDrop(); // Activate drag-and-drop upload
  initDirPicker(); // Directory picker (for move operations)
  setupInfiniteScroll(); // IntersectionObserver for auto-loading more items
  // Pre-check ONLYOFFICE availability in background
  checkOnlyofficeAvailable();

  const params = new URLSearchParams(window.location.search);
  const rootParam = params.get("root");
  const dirRaw = params.get("dir");
  const hasDirParam = dirRaw != null && dirRaw !== "";
  const dirParam = sanitizeDir(dirRaw || "");

  if (!rootParam) {
    if (hasDirParam) {
      setStatus("请在 URL 中指定 root，例如 ?root=<id>");
      return;
    }
    const fallbackRootId = state.defaultRootId || (state.roots[0] && state.roots[0].id) || "";
    if (!fallbackRootId) {
      setStatus("没有可用根目录");
      return;
    }
    if (!selectRoot(fallbackRootId)) {
      setStatus("root 不在白名单内");
      return;
    }
    updateUrl();
    await loadDir("");
    _initAgent();
    return;
  }

  if (!selectRoot(rootParam)) {
    setStatus("root 不在白名单内");
    return;
  }
  await loadDir(dirParam || "");
  _initAgent();
}

function _initAgent() {
  if (state.agentConfig && window.Agent) {
    var curRoot = getRootById(state.rootId) || state.roots[0] || {};
    window.Agent.init({
      backend: state.agentConfig.backend || "claude",
      wsUrl: state.agentConfig.ws_url || "",
      rootId: state.rootId || "",
      dir: state.dir || "",
      agentId: curRoot.agent_id || "",
    });
  }
}

// ── Responsive: auto-switch to list on small screens ──
const RESPONSIVE_BREAKPOINT = 768;
let _responsiveViewActive = false;

function applyResponsiveView() {
  const small = window.innerWidth < RESPONSIVE_BREAKPOINT;
  if (small && !_responsiveViewActive) {
    _responsiveViewActive = true;
    if (state.view === "grid") setView("list");
  } else if (!small && _responsiveViewActive) {
    _responsiveViewActive = false;
  }
  // Sync sidebar button with actual sidebar visibility
  syncSidebarBtn();
}

function syncSidebarBtn() {
  const btn = document.getElementById("btnToggleSidebar");
  const sidebar = els.sidebar;
  if (!btn || !sidebar) return;
  // Desktop: check actual visibility (CSS may have auto-hidden it)
  const visible = getComputedStyle(sidebar).display !== 'none' && !sidebar.classList.contains('hidden');
  if (window.innerWidth < 768) {
    btn.classList.toggle("active", !sidebar.classList.contains("hidden"));
  } else {
    btn.classList.toggle("active", visible);
  }
}

// Watch for CSS-driven sidebar auto-hide (agent-open mode)
if (window.matchMedia) {
  window.matchMedia('(max-width: 1500px)').addEventListener('change', function () {
    if (document.body.classList.contains('agent-open')) syncSidebarBtn();
  });
}

// Run on load and on resize (debounced)
applyResponsiveView();
let _resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(_resizeTimer);
  _resizeTimer = setTimeout(applyResponsiveView, 250);
});

// ── Directory Picker (for move operations) ─────────────────────────────

var dirPickerCallback = null;
var dirPickerSelectedDir = '';
var dirPickerMode = ''; // 'move'

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
}

function confirmDirPicker() {
  if (dirPickerCallback) {
    dirPickerCallback(dirPickerSelectedDir);
  }
  closeDirPicker();
}

function openDirPicker(title) {
  dirPickerMode = 'move';
  dirPickerSelectedDir = state.dir || '';
  var titleEl = document.getElementById('dirPickerTitle');
  var modal = document.getElementById('dirPickerModal');
  var tree = document.getElementById('dirPickerTree');
  var selLabel = document.getElementById('dirPickerSelected');
  if (!titleEl || !modal || !tree) return;

  titleEl.textContent = title || '选择目标目录';
  if (selLabel) selLabel.textContent = dirPickerSelectedDir || '(根目录)';
  modal.style.display = 'flex';

  // Load directory tree (mirrors preview.js logic)
  tree.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:20px;">加载中...</div>';

  (async function () {
    try {
      var MAX_DEPTH = 10;
      var SKIP_PREFIXES = ['.', '__pycache__', 'node_modules'];
      var allDirs = [];
      var rootDirName = state.rootId;
      var skippedCount = 0;

      function filterDirs(entries) {
        var dirs = [];
        for (var i = 0; i < entries.length; i++) {
          if (!entries[i].is_dir) continue;
          var nm = entries[i].name;
          var skip = false;
          for (var s = 0; s < SKIP_PREFIXES.length; s++) {
            if (nm.indexOf(SKIP_PREFIXES[s]) === 0) { skip = true; break; }
          }
          if (skip) { skippedCount++; continue; }
          dirs.push(entries[i].path);
        }
        return dirs;
      }

      // Level 0: root
      var res = await authFetch('/api/clawmate/list?root=' + encodeURIComponent(state.rootId) + '&dir=&limit=1000');
      var data = await res.json();
      if (data.name) rootDirName = data.name;
      var currentLevel = filterDirs(data.entries || []);
      allDirs = allDirs.concat(currentLevel);

      // Level 1..MAX_DEPTH: parallel fetches per level
      for (var depth = 1; depth < MAX_DEPTH && currentLevel.length > 0; depth++) {
        var results = await Promise.all(currentLevel.map(function(dir) {
          return authFetch('/api/clawmate/list?root=' + encodeURIComponent(state.rootId) + '&dir=' + encodeURIComponent(dir) + '&limit=1000')
            .then(function(r) { return r.ok ? r.json() : null; })
            .catch(function() { return null; });
        }));
        var nextLevel = [];
        for (var j = 0; j < results.length; j++) {
          if (!results[j]) continue;
          var subDirs = filterDirs(results[j].entries || []);
          allDirs = allDirs.concat(subDirs);
          nextLevel = nextLevel.concat(subDirs);
        }
        currentLevel = nextLevel;
      }

      // Render tree
      _renderDirPickerTree(tree, allDirs, rootDirName);
      if (skippedCount > 0) {
        var note = document.createElement('div');
        note.style.cssText = 'text-align:center;color:var(--text-muted);font-size:11px;padding:6px 0 2px;';
        note.textContent = '已跳过 ' + skippedCount + ' 个隐藏/缓存目录';
        tree.appendChild(note);
      }
    } catch (e) {
      tree.innerHTML = '<div style="text-align:center;color:var(--danger);padding:20px;">加载目录失败: ' + escHtml(e.message) + '</div>';
    }
  })();
}

function _renderDirPickerTree(container, dirs, rootDirName) {
  if (dirs.length === 0) {
    container.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:20px;">没有可用的子目录</div>';
    return;
  }

  // Sort dirs by depth, then alphabetically
  dirs.sort(function(a, b) {
    var depthA = (a.match(/\//g) || []).length;
    var depthB = (b.match(/\//g) || []).length;
    if (depthA !== depthB) return depthA - depthB;
    return a.localeCompare(b);
  });

  // Build tree structure
  var treeData = {};
  for (var i = 0; i < dirs.length; i++) {
    var parts = dirs[i].split('/');
    var current = treeData;
    for (var j = 0; j < parts.length; j++) {
      if (!current[parts[j]]) current[parts[j]] = {};
      current = current[parts[j]];
    }
  }

  var html = '';
  var folderSvg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;flex-shrink:0;"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>';

  var rootLabel = rootDirName || state.rootId || '';
  // Root entry
  html += '<div class="dir-picker-item" data-dir="" style="display:flex;align-items:center;padding:4px 8px;cursor:pointer;border-radius:4px;margin:1px 0;' + (dirPickerSelectedDir === '' ? 'background:var(--accent);color:#fff;' : '') + '">';
  html += folderSvg;
  html += '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escHtml(rootLabel) + ' (根目录)</span>';
  html += '</div>';

  function renderTreeLevel(obj, prefix, depth) {
    var keys = Object.keys(obj).sort();
    for (var k = 0; k < keys.length; k++) {
      var fullPath = prefix ? prefix + '/' + keys[k] : keys[k];
      var isSelected = dirPickerSelectedDir === fullPath;
      html += '<div class="dir-picker-item" data-dir="' + escHtml(fullPath) + '" style="display:flex;align-items:center;padding:4px 8px 4px ' + (8 + depth * 16) + 'px;cursor:pointer;border-radius:4px;margin:1px 0;' + (isSelected ? 'background:var(--accent);color:#fff;' : '') + '">';
      html += folderSvg;
      html += '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escHtml(keys[k]) + '</span>';
      html += '</div>';
      if (obj[keys[k]]) {
        renderTreeLevel(obj[keys[k]], fullPath, depth + 1);
      }
    }
  }

  renderTreeLevel(treeData, '', 1);
  container.innerHTML = html;

  // Click handler: update selection
  container.onclick = function(e) {
    var item = e.target.closest('.dir-picker-item');
    if (!item) return;
    var dir = item.getAttribute('data-dir');
    dirPickerSelectedDir = dir;
    var items = container.querySelectorAll('.dir-picker-item');
    for (var i = 0; i < items.length; i++) {
      items[i].style.background = '';
      items[i].style.color = '';
    }
    item.style.background = 'var(--accent)';
    item.style.color = '#fff';
    var selLabel = document.getElementById('dirPickerSelected');
    if (selLabel) selLabel.textContent = dir || rootLabel + ' (根目录)';
  };
}

// Close any open card menu dropdown when clicking outside
document.addEventListener('click', function (e) {
  var open = document.querySelector('.card-menu-dropdown');
  if (open && !e.target.closest('.card-menu-btn') && !e.target.closest('.card-menu-dropdown')) {
    // Clear reference on the owning button
    var allBtns = document.querySelectorAll('.card-menu-btn');
    for (var i = 0; i < allBtns.length; i++) {
      if (allBtns[i]._dropdown === open) {
        allBtns[i]._dropdown = null;
        break;
      }
    }
    open.remove();
  }
});

init();
