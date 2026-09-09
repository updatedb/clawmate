# Command Palette — 项目优先 + MRU + 搜索 chip — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐个任务实现。步骤用 `- [ ]` 复选框追踪。

**Goal:** 把命令面板（Ctrl/Cmd+K）改成项目优先：默认只显示项目卡片、按最近使用降序、输入即过滤；文件/内容搜索作为输入框下固定的 chip 行；并把 index/preview 顶栏标题 wrap 内容水平居中。

**Architecture:** 纯前端（方案 A）。不改后端。打开面板时用现有 `/api/clawmate/list?marker_filter=true` 拉各 root 项目（已含 `mtime`），结合 localStorage 的"最近使用"记录做 MRU 排序；本地按名称过滤；渲染为平铺卡片网格。

**Tech Stack:** 原生 JS + CSS（无构建步骤，沿用 `dev/static/js/command-palette.js`、`command-palette.css`、`index.html`、`app.js`、`style.css`、`preview.css` 现有风格）。测试用 pytest 契约测试（读静态文件断言）+ 浏览器实测。

## Global Constraints

- 不改任何 Python 后端；mtime 直接用 `/api/clawmate/list` 返回的 `entry.mtime`。
- 复用现有 `fileSearch(query)`、`contentSearch(query)`、`switchProject`、`selectRoot`、`loadDir`。
- 面板仍由 `command-palette.js` IIFE 管理，保持其 `var` + `function` 写法。
- localStorage key 固定为 `clawmate.recentProjects`（index 与面板共同使用）。
- 项目卡片**按 root 平铺，不做 root 分组/折叠**；每张卡标注所属 root。
- MRU 排序：有 localStorage 记录按记录时间降序；无记录的项目按 `mtime` 降序排在后。
- 契约测试新增 `tests/test_command_palette_contract.py`。
- 对用户的所有说明/汇报用中文。

---

### Task 1: 顶栏标题 wrap 水平居中（companion tweak）

**Files:**
- Modify: `dev/static/css/style.css`（`.path-title-wrap` 规则，约 257 行）
- Modify: `dev/static/css/preview.css`（`.preview-topbar-title-wrap` 规则，约 1128 行）
- Test: `tests/test_command_palette_contract.py`（新建）

**Interfaces:**
- Consumes: 无
- Produces: `.path-title-wrap`、`.preview-topbar-title-wrap` 两者 `justify-content: center`（供 Task 5 浏览器验证依赖）

- [ ] **Step 1: 写失败契约测试**

```python
# tests/test_command_palette_contract.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")

def test_center_title_wraps():
    style = _read("dev/static/css/style.css")
    i = style.index(".path-title-wrap {")
    assert "justify-content: center" in style[i:i + 220]

    preview = _read("dev/static/css/preview.css")
    j = preview.index(".preview-topbar-title-wrap {")
    assert "justify-content: center" in preview[j:j + 240]
```

- [ ] **Step 2: 运行验证失败**

Run: `dev/.venv/bin/python -m pytest tests/test_command_palette_contract.py::test_center_title_wraps -q`
Expected: FAIL（`AssertionError` / 断言不成立）

- [ ] **Step 3: 实现 — 两个 wrap 加 `justify-content: center`**

`style.css` 的 `.path-title-wrap`（在 `height: 34px;` 后追加）：
```css
.path-title-wrap { flex: 1; min-width: 0; display: inline-flex; align-items: center; justify-content: center; gap: 4px; height: 34px; }
```

`preview.css` 的 `.preview-topbar-title-wrap`（在 `height: 34px;` 后追加）：
```css
.preview-topbar-title-wrap {
  flex: 1;
  min-width: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
  height: 34px;
}
```

- [ ] **Step 4: 运行验证通过**

Run: `dev/.venv/bin/python -m pytest tests/test_command_palette_contract.py -q`
Expected: PASS（1 passed）

- [ ] **Step 5: 提交**

```bash
git add dev/static/css/style.css dev/static/css/preview.css tests/test_command_palette_contract.py
git commit -m "style(topbar): center path/title wraps horizontally"
```

---

### Task 2: MRU 记录/读取共享函数（app.js 全局）

**Files:**
- Modify: `dev/static/js/app.js`（文件末尾附近，加全局函数）
- Test: `tests/test_command_palette_contract.py`

**Interfaces:**
- Consumes: 无
- Produces: 全局 `recordProjectUse(rootId, name)`、`projectUseAt(rootId, name)` —— Task 4 的 command-palette.js 会调用（guarded，`typeof recordProjectUse === "function"`）。

- [ ] **Step 1: 写失败契约测试**

```python
def test_mru_helpers_in_app_js():
    src = _read("dev/static/js/app.js")
    assert "function recordProjectUse(rootId, name)" in src
    assert "function projectUseAt(rootId, name)" in src
    assert "clawmate.recentProjects" in src
```

- [ ] **Step 2: 运行验证失败**

Run: `dev/.venv/bin/python -m pytest tests/test_command_palette_contract.py::test_mru_helpers_in_app_js -q`
Expected: FAIL

- [ ] **Step 3: 实现 — 在 app.js 顶层（共享全局作用域）加 MRU 函数**

```js
// ── Recent-projects MRU (shared with the command palette) ──
const CP_MRU_KEY = "clawmate.recentProjects";
function recordProjectUse(rootId, name) {
  if (!rootId || !name) return;
  let map = {};
  try { map = JSON.parse(localStorage.getItem(CP_MRU_KEY)) || {}; } catch (_) {}
  map[rootId + "/" + name] = Date.now();
  try { localStorage.setItem(CP_MRU_KEY, JSON.stringify(map)); } catch (_) {}
}
function projectUseAt(rootId, name) {
  try {
    const v = JSON.parse(localStorage.getItem(CP_MRU_KEY))?.[rootId + "/" + name];
    return typeof v === "number" ? v : -1;
  } catch (_) { return -1; }
}
```

（放在 app.js 顶层即可——它是 classic script，顶层 `function` 进入共享全局域，command-palette.js 可按裸名引用。）

- [ ] **Step 4: 运行验证通过**

Run: `dev/.venv/bin/python -m pytest tests/test_command_palette_contract.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add dev/static/js/app.js
git commit -m "feat(app): add recent-project MRU helpers shared with command palette"
```

---

### Task 3: 面板结构 — 搜索 chip 行 + 项目卡片网格（HTML + CSS）

**Files:**
- Modify: `dev/static/index.html`（`#clawmateCommandPalette` 内，`#cpList` 上方加 `.cp-chips`）
- Modify: `dev/static/css/command-palette.css`（加 `.cp-chips`/`.cp-chip`、`.cp-card*`，改 `.cp-list` 为网格）
- Test: `tests/test_command_palette_contract.py`

**Interfaces:**
- Consumes: 无
- Produces: `.cp-chips`（含 `.cp-chip[data-cp-search]`）、`.cp-card`、`.cp-list` 网格 —— Task 4 的 JS 依赖这些类选择器。

- [ ] **Step 1: 写失败契约测试**

```python
def test_palette_search_chips_and_cards():
    html = _read("dev/static/index.html")
    css = _read("dev/static/css/command-palette.css")
    assert "cp-chips" in html
    assert "data-cp-search" in html
    assert "文件搜索" in html
    assert "内容搜索" in html
    assert ".cp-chips" in css
    assert ".cp-chip" in css
    assert ".cp-card" in css
    assert "grid-template-columns: repeat(auto-fill" in css
```

- [ ] **Step 2: 运行验证失败**

Run: `dev/.venv/bin/python -m pytest tests/test_command_palette_contract.py::test_palette_search_chips_and_cards -q`
Expected: FAIL

- [ ] **Step 3: 实现 — index.html 加 `.cp-chips` 行**

在 `#cpInput` 的 `.cp-input-wrap` 之后、`#cpList` 之前插入：
```html
      <div class="cp-chips" id="cpChips" role="group" aria-label="搜索">
        <button class="cp-chip" type="button" data-cp-search="filename">文件搜索</button>
        <button class="cp-chip" type="button" data-cp-search="content">内容搜索</button>
      </div>
```

- [ ] **Step 4: 实现 — command-palette.css 加 chip + card 样式，`.cp-list` 改网格**

在 `.cp-list` 规则后追加/替换：
```css
.cp-chips {
  flex-shrink: 0;
  display: flex; align-items: center; gap: 8px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--border-color);
}
.cp-chip {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  padding: 5px 12px;
  font: 500 12px/1 var(--font-ui);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out), border-color var(--duration-fast) var(--ease-out);
}
.cp-chip:hover, .cp-chip:focus-visible { border-color: var(--accent); color: var(--accent); outline: none; }

.cp-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 10px 12px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 10px;
  align-content: start;
}
.cp-card {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-secondary);
  cursor: pointer;
  color: var(--text-primary);
}
.cp-card.active { background: var(--accent); border-color: var(--accent); color: #fff; }
.cp-card:hover:not(.active) { background: var(--bg-tertiary); }
.cp-card-ico { flex-shrink: 0; color: var(--text-muted); display: inline-flex; }
.cp-card.active .cp-card-ico, .cp-card.active .cp-card-root, .cp-card.active .cp-card-when { color: rgba(255,255,255,0.85); }
.cp-card-body { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.cp-card-name { font-size: var(--font-size-sm); font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cp-card-root { font-size: var(--font-size-xs, 11px); color: var(--text-muted); }
.cp-card-when { font-size: var(--font-size-xs, 11px); color: var(--text-muted); }
```

- [ ] **Step 5: 运行验证通过**

Run: `dev/.venv/bin/python -m pytest tests/test_command_palette_contract.py -q`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add dev/static/index.html dev/static/css/command-palette.css
git commit -m "feat(palette): add search-chips row and project-card grid styles"
```

---

### Task 4: command-palette.js 逻辑改造（项目卡片、MRU 排序、过滤、chip 点击、switchProject 记录）

**Files:**
- Modify: `dev/static/js/command-palette.js`（重写 `populateHints`/`loadProjectsForLayout`/`render`/`setActive`/`activateCurrent`，新增 `switchProject` 记录、chip 绑定，删除 `_pushSearchActions`）
- Test: `tests/test_command_palette_contract.py`

**Interfaces:**
- Consumes: 全局 `recordProjectUse`/`projectUseAt`（Task 2）；`.cp-chip[data-cp-search]`、`.cp-card`（Task 3）；现有 `fileSearch`/`contentSearch`/`selectRoot`/`loadDir`。
- Produces: 面板开合、卡片渲染、搜索 chip 行为、MRU 写入。

- [ ] **Step 1: 写失败契约测试**

```python
def test_palette_projects_only_and_mru():
    src = _read("dev/static/js/command-palette.js")
    assert "projectUseAt" in src
    assert "recordProjectUse" in src
    assert "data-cp-search" in src          # 绑定 chip 点击
    assert ".cp-card" in src                # 卡片渲染
    assert "_pushSearchActions" not in src  # 搜索项不再是列表 item
```

- [ ] **Step 2: 运行验证失败**

Run: `dev/.venv/bin/python -m pytest tests/test_command_palette_contract.py::test_palette_projects_only_and_mru -q`
Expected: FAIL

- [ ] **Step 3: 实现 — 改造 command-palette.js**

替换以下片段（整文件用下面关键改动覆盖对应函数）：

- 删除 `_pushSearchActions()`（及其在 `populateHints` 里的调用），`populateHints` 只调用 `loadProjectsForLayout()`。
- `loadProjectsForLayout()`：拉取各 root 项目 → 组装 items `{type:'project', root, name, label, mtime, mruAt, icon, activate}` → 用 `projectUseAt` 读 MRU → 排序 → `render`。
- 排序：`items.sort(projSort)`，`projSort` 优先 `mruAt>=0`（按 `mruAt` 降序），否则 `mtime` 降序。
- `render(query)`：按名称过滤后渲染 `.cp-card`（不再渲染 `.cp-item` / group-label）。
- `setActive`/`activateCurrent`：改用 `.cp-card` 选择器。
- 新增 chip 绑定：`.cp-chip` 点击 → 读输入值 → `fileSearch(v)`/`contentSearch(v)` → `close()`。
- `switchProject(name, rootId)`：调用 `mruRecord(name, rootId)`（guarded）再切 root + `loadDir`。
- 新增 `relTime(ms)`（简单相对时间，供 `cp-card-when` 展示）。

```js
// (command-palette.js 关键改动 —— 其余 iife/事件/icon/escape 保持不变)

var items = [];   // { type:'project', root, name, label, mtime, mruAt, icon, activate }
var activeIndex = 0;

function mruRecord(name, rootId) { if (typeof recordProjectUse === "function") recordProjectUse(rootId, name); }

function relTime(ms) {
  if (typeof ms !== "number" || ms <= 0) return "—";
  var diff = Date.now() - ms;
  if (diff < 60000) return "刚刚";
  if (diff < 3600000) return Math.floor(diff / 60000) + " 分钟前";
  if (diff < 86400000) return Math.floor(diff / 3600000) + " 小时前";
  return Math.floor(diff / 86400000) + " 天前";
}

function projSort(a, b) {
  var am = a.mruAt >= 0 ? 0 : 1, bm = b.mruAt >= 0 ? 0 : 1;
  if (am !== bm) return am - bm;                       // 用过的排前
  var at = (am === 0 ? a.mruAt : a.mtime) - (bm === 0 ? b.mruAt : b.mtime);
  if (at !== 0) return at > 0 ? -1 : 1;                // 时间新→旧
  return a.name.localeCompare(b.name);
}

function populateHints() { items = []; activeIndex = 0; loadProjectsForLayout(); }

function loadProjectsForLayout() {
  getRoots().forEach(function (r) {
    safeAuthFetch("/api/clawmate/list?root=" + encodeURIComponent(r.id) + "&dir=&marker_filter=true")
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (data) {
        if (!data || !Array.isArray(data.entries)) return;
        data.entries.filter(function (e) { return e && e.is_dir && e.name && e.name.charAt(0) !== "."; })
          .forEach(function (e) {
            var mruAt = typeof projectUseAt === "function" ? projectUseAt(r.id, e.name) : -1;
            items.push({
              type: "project", root: r.id, name: e.name,
              label: e.name, mtime: e.mtime || 0, mruAt: mruAt, icon: "folder",
              activate: function () { switchProject(e.name, r.id); close(); },
            });
          });
        items.sort(projSort);
        render(inputEl() ? inputEl().value : "");
      }).catch(function () { /* ignore network errors */ });
  });
}

function render(query) {
  var list = listEl();
  if (!list) return;
  var q = (query || "").trim().toLowerCase();
  var shown = items.filter(function (it) { return it.label.toLowerCase().indexOf(q) !== -1; });
  if (activeIndex >= shown.length) activeIndex = Math.max(0, shown.length - 1);
  if (!shown.length) { list.innerHTML = '<div class="cp-empty">没有匹配项目</div>'; return; }
  var html = shown.map(function (it, idx) {
    var when = relTime(it.mruAt >= 0 ? it.mruAt : it.mtime);
    return '<div class="cp-card' + (idx === activeIndex ? " active" : "") +
      '" data-index="' + idx + '" role="option" aria-selected="' + (idx === activeIndex) + '">' +
      '<span class="cp-card-ico">' + iconFor(it.icon) + "</span>" +
      '<span class="cp-card-body">' +
      '<span class="cp-card-name">' + escapeHtml(it.label) + "</span>" +
      '<span class="cp-card-root">' + escapeHtml(it.root) + "</span>" +
      '<span class="cp-card-when">最近使用 · ' + when + "</span>" +
      "</span></div>";
  }).join("");
  list.innerHTML = html;
}

function setActive(index) {
  var list = listEl(); if (!list) return;
  var shown = list.querySelectorAll(".cp-card");
  if (index < 0 || index >= shown.length) return;
  activeIndex = index;
  shown.forEach(function (n, i) {
    n.classList.toggle("active", i === activeIndex);
    n.setAttribute("aria-selected", i === activeIndex ? "true" : "false");
  });
  if (shown[activeIndex].scrollIntoView) shown[activeIndex].scrollIntoView({ block: "nearest" });
}

function activateCurrent() {
  var query = inputEl() ? inputEl().value : "";
  var shown = items.filter(function (it) { return it.label.toLowerCase().indexOf(query.trim().toLowerCase()) !== -1; });
  var it = shown[activeIndex];
  if (it && typeof it.activate === "function") it.activate();
}

function switchProject(name, rootId) {
  if (rootId && rootId !== currentRoot()) safeSelectRoot(rootId);
  safeLoadDir(name);
  mruRecord(name, rootId);
}

// chip 绑定（在 bindEvents 里加）
function bindSearchChips() {
  var chips = document.querySelectorAll("#cpChips .cp-chip");
  Array.prototype.forEach.call(chips, function (chip) {
    chip.addEventListener("click", function () {
      var q = inputEl() ? inputEl().value : "";
      var kind = chip.getAttribute("data-cp-search");
      if (kind === "content" && typeof contentSearch === "function") contentSearch(q);
      else if (typeof fileSearch === "function") fileSearch(q);
      close();
    });
  });
}
// 在 init() 中调用 bindSearchChips(); 并在 keydown 的 Enter 分支保持 activateCurrent()。
```

> 注：`_pushSearchActions` 及其调用一并删除；`bindEvents` 保持原有输入过滤/键盘逻辑；`bindSearchChips()` 在 `init()` 调用。

- [ ] **Step 4: 运行验证通过**

Run: `dev/.venv/bin/python -m pytest tests/test_command_palette_contract.py -q`
Expected: PASS（含 `_pushSearchActions` not in src）

- [ ] **Step 5: 提交**

```bash
git add dev/static/js/command-palette.js
git commit -m "feat(palette): projects-only cards with MRU sort, live filter, search chips"
```

---

### Task 5: app.js 面板打开时记录 MRU + 全量验证

**Files:**
- Modify: `dev/static/js/app.js`（`_setProjectPanelOpen(true)` 或 `_updateProjectPanelBtn` 内调用 `recordProjectUse`）
- Test: `tests/test_command_palette_contract.py`

**Interfaces:**
- Consumes: `recordProjectUse`（Task 2）
- Produces: 打开项目面板也计入"最近使用"，让 MRU 排序准确。

- [ ] **Step 1: 写失败契约测试**

```python
def test_project_panel_open_records_mru():
    src = _read("dev/static/js/app.js")
    # 在项目面板打开/激活路径里必须调用 recordProjectUse
    assert "recordProjectUse(state.rootId, state.project)" in src
```

- [ ] **Step 2: 运行验证失败**

Run: `dev/.venv/bin/python -m pytest tests/test_command_palette_contract.py::test_project_panel_open_records_mru -q`
Expected: FAIL

- [ ] **Step 3: 实现 — 在 `_updateProjectPanelBtn` 激活分支调用**

`app.js` 的 `_updateProjectPanelBtn()` 中，`const active = Boolean(state.project && state.rootId);` 之后、`if (btnProjectPanel) ...` 一带，在 `active` 为真时写入 MRU（幂等）：
```js
  const active = Boolean(state.project && state.rootId);
  if (active) recordProjectUse(state.rootId, state.project);
  if (btnProjectPanel) btnProjectPanel.style.display = active ? '' : 'none';
```

- [ ] **Step 4: 运行验证通过 + 全量回归**

Run: `dev/.venv/bin/python -m pytest -q`
Expected: 全量通过（含新增契约测试；本任务只改动前端，不影响既有后端行为）

- [ ] **Step 5: 浏览器验证（手动）**

在浏览器打开 `http://127.0.0.1:5533/clawmate/?root=webprojects`：
1. `Ctrl+K` 打开 → 只显示项目卡片，未用过的按名称/出现顺序；用过某项目后再打开，该项目置顶。
2. 输入关键词 → 卡片按名称实时过滤。
3. 点某个卡 → 跳到该项目目录并关闭面板；再开 `Ctrl+K` 该项目在最前。
4. 点"文件搜索"/"内容搜索" chip → 面板关闭，index 显示搜索结果。
5. 顶栏 index 面包屑、preview 文档标题内容水平居中（对比 desktop/mobile）。

- [ ] **Step 6: 提交**

```bash
git add dev/static/js/app.js
git commit -m "feat(app): record recent-project use on project panel open"
```

---

## Self-Review

- **Spec 覆盖**：TODo1（只显示项目 + MRU 排序）→Task 4；TODO2（平铺卡片、无 root 分组）→Task 3/4；TODO3（名称过滤）→Task 4 `render`；TODO4（chip 放在输入框后 + 点击关闭并在 index 显示）→Task 3/4；companion 居中 →Task 1。无遗漏。
- **占位符**：无 TBD/TODO。
- **类型一致性**：`recordProjectUse(rootId, name)` / `projectUseAt(rootId, name)` 签名在 Task 2 定义，Task 4/5 一致使用；`selectRoot`/`loadDir`/`fileSearch`/`contentSearch` 均沿用现有全局名；选择器 `.cp-chip`/`.cp-card`/`.cp-list` 在三处一致。
- **测试方式说明**：本项目无前端 JS 单元测试运行器（仅 contract/快照），故 JS 行为靠契约测试断言 + 浏览器实测，计划已如实标注。
