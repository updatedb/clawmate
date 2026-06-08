# ClawMate UI 优化 + 移动端方案

> 评审稿 · 2026-06-06

---

## 一、Markdown 渲染优化

### 目标

保持 `highlight.js` + `KaTeX` + `mermaid v11` 不变，在 CSS 层面达到最佳视觉效果。

### 方案：替换为 GitHub Markdown CSS 变体 + 暗色主题

当前用的是 `github-markdown-light.min.css` + `github.min.css`（代码高亮），但暗色模式下是强行覆盖 light CSS，导致：

```
@media (prefers-color-scheme: dark) {
  .markdown-body { background-color: #0d1117 !important; }
  .markdown-body code { color: #1f2328 !important; }  /* light 颜色强制覆盖 */
}
```

**推荐方案**：用 `sindresorhus/github-markdown-css` 的暗色变体

| 当前 | 替换为 |
|------|--------|
| `github-markdown-light.min.css` | `github-markdown-dark.min.css`（暗色模式时）+ `github-markdown-light.min.css`（亮色时） |
| `highlight.js github.min.css` | `highlight.js github-dark.min.css`（暗色时）+ `github.min.css`（亮色时） |

**CSS 引入逻辑**（动态切换，现有 `<link>` 已用 id 标记可行）：

```javascript
// 在现有的 dark mode 切换逻辑中增加 markdown 主题切换
function setMarkdownTheme(dark) {
  const mdLink = document.getElementById('github-markdown-css');
  mdLink.href = dark ? './vendor/github-markdown-dark.min.css' : './vendor/github-markdown-light.min.css';
  
  const hlLink = document.getElementById('highlight-theme-css');
  hlLink.href = dark ? 
    'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css' :
    'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css';
}
```

**效果**：
- 标题、表格、引用块、警告块都跟随 GitHub 官方暗色配色
- 代码高亮自动匹配暗色背景（不再有 `color: #1f2328 !important` 的强行覆盖）
- 支持亮色/暗色/跟随系统三种模式

### 其他渲染优化（轻量、低风险）

| 优化项 | 实现 | 效果 |
|--------|------|------|
| 代码块折叠（长代码） | < details> 包裹 >20 行代码块 | 防止长代码撑满屏幕，移动端友好 |
| 表格横向滚动 | `.markdown-body table { display: block; overflow-x: auto }` | 防止宽表格破坏布局 |
| 图片最大宽度适配 | `img { max-width: 100%; height: auto }` | 图片不溢出容器 |
| KaTeX 字号 | 略增大（1.05em → 1.15em） | 移动端公式可读性 |
| Mermaid 缩放 | `.mermaid svg { max-width: 100% }` | 防止大图溢出 |

---

## 二、移动端方案

### 总体策略

建立独立页面目录 `static/m/`，**不**修改现有 `index.html` / `preview.html`。

```
static/
├── index.html           # 桌面版（不动）
├── preview.html         # 桌面版（不动）
├── m/
│   ├── index.html       # 移动端目录浏览（新增）
│   ├── preview.html     # 移动端内容阅读（新增）
│   └── style.css        # 移动端独立样式（新增）
```

**路由**：检测 UA 或通过 query 参数 `?mobile=1` 切换到 `/m/` 路径。

### 使用零新接口

移动端完全复用现有后端 API：

| 页面 | 调用 API | 方式 |
|------|---------|------|
| m/index.html | `GET /api/clawmate/list?root=X&dir=Y` | 现有，参数不变 |
| m/index.html | `GET /api/clawmate/config` | 获取 roots 列表 |
| m/preview.html | `GET /api/clawmate/preview/load?root=X&file=Y` | 现有，参数不变 |
| m/preview.html | `GET /api/clawmate/preview/outline?root=X&file=Y` | 现有，参数不变 |
| m/preview.html | `GET /api/clawmate/feedback/list?root=X&project=Y&file=Z` | 现有，参数不变 |
| m/preview.html | `POST /api/clawmate/feedback` | 提交反馈，现有 |
| m/preview.html | `POST /api/clawmate/feedback/update` | 更新反馈，现有 |
| m/preview.html | `POST /api/clawmate/feedback/cron-tick` | 兜底扫描，现有 |

### m/index.html 布局

```
┌─────────────────────────────┐
│ ← Roots    🔍 搜索文件名    │  ← 顶栏（44px）
├─────────────────────────────┤
│ 📁 htdocs    文档  · 3个    │  ← 过滤标签行（内边距 8px）
│ 📋 markdown  · 全部        │  
│ 🎵 audio     · 全部        │  
├─────────────────────────────┤
│ 按: 时间↓  类型  文件名     │  ← 排序/视图行（紧凑）
├─────────────────────────────┤
│ 📄 design.md        2.3k   │  ← 文件列表（每行 48px）
│ 📄 todo.md          1.1k   │  
│ 📄 README.md        3.2k   │  
│ 📁 src/               —    │  
│ 📁 assets/            —    │  
│ 📄 api-spec.md       4.1k  │  
│ ...                       │  
└─────────────────────────────┘
```

**关键交互**：
- 顶部左侧：当前 root 名称，点击弹出 root 切换面板（底部半屏，复用 `GET /api/clawmate/config` 的 roots 列表）
- 搜索框：输入即过滤（前端过滤，无需后端，现有逻辑）
- 过滤标签：一行横滑，选中即按类型过滤（现有 `guess_category` 映射 + `file.category`）
- 排序：横向 Toggle Btn（时间↓ / 类型 / 文件名↑），比下拉选择器更直观
- 每行：文件图标 + 文件名 + 后缀标签 + 大小/时间 + 箭头 →
- 点击文件 → 跳转 `m/preview.html?root=X&file=Y`

### m/preview.html 布局

```
┌─────────────────────────────┐
│ ← 返回  文件名.md    📑 💬  │  ← 顶栏（44px）
├─────────────────────────────┤
│                             │
│       Markdown 正文         │  ← 正文区（全宽，上下滑动）
│                             │
│                             │
│                             │
│                             │
│                             │
├─────────────────────────────┤
│  大纲  ·   反馈 (3条待处理) │  ← 底栏（tap 唤起 panel）
└─────────────────────────────┘
```

**关键交互**：

**大纲面板**（底部弹出）：
```
┌─────────────────────────────┐
│ 📑 大纲              ✕ 关闭 │
├─────────────────────────────┤
│ # 设计方案（当前）          │
│   ## 1.1 背景               │
│   ## 1.2 目标               │
│ # 实施计划                   │
│   ## 2.1 阶段一              │
│   ## 2.2 阶段二              │
│ # 附录                      │
│                             │
│         ──────────          │  ← 拖动手柄
└─────────────────────────────┘
```
- 从底部升起（不是侧边栏），占据 60% 屏幕高度 + 可拖动
- 点击条目 → 滚动正文到对应位置 → 大纲收起
- 复用现有大纲 API：`GET /api/clawmate/preview/outline?root=X&file=Y`

**反馈面板**（底部弹出）：
```
┌─────────────────────────────┐
│ 💬 反馈 (3条待处理)   ✕ 关闭│
├─────────────────────────────┤
│ [选择文本后在此出现提示]     │  ← 选中文本后出现浮动条
│                             │
│ FD-0001 pending              │  ← 反馈列表
│   "修改这个段落"           │  
│   🗑 🔧 📈 📉 ⚡  [+ 添加] │  ← 快速操作标签
│ ───────────────────────────  │
│                             │
│ [添加新反馈]                │  ← 浮动按钮 / 底部按钮
│                             │
│         ──────────          │  ← 拖动手柄
└─────────────────────────────┘
```

选中文本后的浮动工具条（类似桌面版的 selection tooltip，但适配触屏）：
```
  ┌────────────────────────┐
  │ 📝 添加备注  🗑 🔧 📈  │  ← 选中文本后出现在选区上方
  └────────────────────────┘
```
点击"添加备注" → 弹出输入框 + 快捷标签 → 确认后 `POST /api/clawmate/feedback`

### 移动端样式集约定

```css
/* m/style.css */

:root {
  --safe-top: env(safe-area-inset-top, 0px);
  --safe-bottom: env(safe-area-inset-bottom, 0px);
  --topbar-height: 44px;
  --bottombar: 48px;
  --font-md: 16px;  /* 防止 iOS 自动缩放 */
}
```

- 所有交互元素最小 44px 触控目标
- `-webkit-overflow-scrolling: touch`
- 状态栏适配：`viewport-fit=cover` + safe area env vars
- 全宽容器，无边距/阴影等桌面装饰

### 响应式切换

```javascript
// 在现有 index.html 顶部加入：
if (window.innerWidth < 768) {
  const params = new URLSearchParams(location.search);
  params.set('mobile', '1');
  location.href = '/clawmate/m/index.html?' + params.toString();
}
```

移动端页面内链接触手屏打开（不另起新 tab）：

```javascript
document.addEventListener('click', (e) => {
  const link = e.target.closest('a[href]');
  if (link && link.href.startsWith(location.origin)) {
    e.preventDefault();
    history.pushState({}, '', link.href);
    loadContent(); // SPA 式加载或页面跳转
  }
});
```

---

## 三、排序问题修复

### 问题

1. `<select id="sortKey">` 默认选中第一项 `名称`，但 JS 默认状态是 `sortKey: "mtime"`——选择器与状态不同步
2. 排序方向按钮只显示"降序"，对时间而言意义模糊（最新=降序？最旧=降序？）

### 修复方案

**HTML 修正** — select 与 JS 默认值对齐：

```html
<select id="sortKey">
  <option value="time">时间</option>
  <option value="name">名称</option>
  <option value="size">大小</option>
</select>
<button id="sortDir">↓ 最新优先</button>
```

**排序方向按钮行为**（语义化）：

| 排序键 | 降序 | 升序 |
|--------|------|------|
| 时间 | ↓ 最新优先 | ↑ 最早优先 |
| 名称 | ↓ Z→A | ↑ A→Z |
| 大小 | ↓ 最大优先 | ↑ 最小优先 |

```javascript
// state 初始化
sortKey: "time",     // 别名 mtime，显示用 "时间"
sortDir: "desc",

// 方向按钮文字动态更新
function updateSortLabel() {
  const labels = {
    time: { desc: "↓ 最新优先", asc: "↑ 最早优先" },
    name: { desc: "↓ Z → A", asc: "↑ A → Z" },
    size: { desc: "↓ 最大优先", asc: "↑ 最小优先" },
  };
  els.sortDir.textContent = labels[state.sortKey][state.sortDir];
}
```

**select 同步**（页面加载时）：

```javascript
// 在 init() 中加入
els.sortKey.value = state.sortKey === "mtime" ? "time" : state.sortKey;
```

---

## 四、UI 框架参考方案

### 桌面 Preveiw 两栏布局优化

**当前问题**：大纲是固定侧边栏，反馈是固定右侧面板，占据大量屏幕、不可收起。

**参考方案**（Obsidian / VS Code / Notion 模式）：

```
┌────┬──────────────────────┬─────┐
│    │                      │     │
│ 大 │    Markdown 正文     │ 反  │
│ 纲 │    （全高度）        │ 馈  │
│    │                      │ 列  │
│    │                      │ 表  │
│    ├──────────────────────┤     │
│    │  底栏：大纲·反馈图标  │     │
├────┴──────────────────────┴─────┤
│  状态栏：文件名 · 字数 · 行数   │
└──────────────────────────────────┘
```

**关键改进**：

| 当前 | 改为 |
|------|------|
| 大纲侧边栏始终显示 | **大纲：左侧图标按钮**，点击后弹出/收起 |
| 反馈面板始终占右侧 | **反馈：右侧图标按钮**，点击后弹出/收起 |
| 无状态栏 | **底栏**：文件名 + 字数 + 行统计 |
| feedback 表单在固定区域内 | feedback 输入在**底部浮层/模态框**中（类似桌面版 selection tooltip 增强） |

**大纲收起状态**：
```
未展开：左边缘仅一个 📑 图标（18px 宽）
展开后：350px 宽的侧边栏，覆盖在正文上方
```

**反馈面板收起状态**：
```
未展开：右边缘仅一个 💬 图标
展开后：400px 宽的侧边栏
```

**选中文本后**（桌面 + 移动统一使用浮层，而非固定面板）：

```
                 ┌──────────────────────┐
                 │ 📝 备注  🗑 🔧 📈 📉 ⚡│  ← 浮动在选中文本上方
                 └──────────────────────┘
点击备注 → 弹出输入框叠加层（非侧边栏）
```

### 行业参考对比

| 参考 | 可借鉴的点 | ClawMate 适配 |
|------|-----------|-------------|
| **VS Code Markdown Preview** | 两栏：编辑/预览，代码块主题跟随系统 | 我们的 preview.html 本身就是纯预览，可参考它的代码块折叠 |
| **Obsidian** | 侧边栏收起/展开、底部 panel、标签页式反馈 | 大纲+反馈用图标收起，不占屏幕 |
| **GitHub Markdown** | 渲染风格、表格/代码块样式（标准） | 换 GitHub Markdown CSS |
| **Bear (iOS)** | 极简工具栏、浮层编辑器、触屏交互 | 移动端参考，只有最必要按钮 |
| **Files (iOS 文件 App)** | 目录列表扁平、过滤标签、排序开关 | 移动端 index.html 参考 |

---

## 五、变更清单

| 变更 | 文件 | 说明 |
|------|------|------|
| 新增 | `dev/static/m/style.css` | 移动端独立 CSS |
| 新增 | `dev/static/m/index.html` | 移动端目录浏览（~200 行） |
| 新增 | `dev/static/m/preview.html` | 移动端阅读+反馈（~400 行） |
| 修改 | `dev/static/index.html` | 排序 select 默认值 + 方向按钮语义化 |
| 修改 | `dev/static/js/app.js` | 排序标签更新逻辑 + select 同步 |
| 修改 | `dev/static/preview.html` | 大纲/反馈面板可收起 + 浮层 feedback 表单 |
| 替换 | `dev/static/css/style.css` | 新增暗色模式下 GitHub Markdown CSS 动态切换 |
| 引用 | `vendor/github-markdown-dark.min.css` | 新增 vendor 文件或 CDN 引用 |

### 不做的事

- ❌ 不新增后端 API 接口
- ❌ 不改 `feedback.json` 格式
- ❌ 不改现有桌面版的核心功能（只改样式/布局）
- ❌ 不引入前端框架（保持 Vanilla JS）
