# ClawMate UI 优化 + 移动端方案（v2）

> 评审稿 · 2026-06-06

---

## 一、Markdown 渲染优化

### 1.1 markdown-it vs marked：收益分析

| 对比维度 | marked (当前) | markdown-it (待迁移) |
|----------|--------------|---------------------|
| 体积 | ~20KB | ~40KB (UMD) + 插件 |
| 每周下载 | ~4600 万 | ~2400 万 |
| CDN 可用 | v12.x (vendor 本地) | jsdelivr + cdnjs 13.0.2 |
| CommonMark 支持 | ✅ | ✅ |
| **容器块** `:::note` | ❌ 需自定义 | ✅ 官方插件 `markdown-it-container` |
| **任务列表** `- [ ]` | ❌ | ✅ 官方插件 `markdown-it-task-lists` |
| **脚注** | ❌ | ✅ 官方插件 `markdown-it-footnote` |
| **Emoji**:+1: | ❌ | ✅ 官方插件 `markdown-it-emoji` |
| **可配置规则** | 有限 | 高度可定制 |
| **插件生态** | 小而少 | 丰富活跃 |
| highlight.js 集成 | ✅ 后处理 | ✅ 后处理（不变） |
| KaTeX 集成 | ✅ 后处理 | ✅ 后处理（不变） |
| Mermaid 集成 | ✅ 互不干扰 | ✅ 互不干扰 |

#### 对 ClawMate 用户的实际收益

**收益 1：容器块 — 更丰富的排版**

当前用户写：
```markdown
> **Note:** 这是一个注意事项
```

用 markdown-it-container 后可写：
```markdown
:::note
这是一个注意事项
:::

:::warning
⚠️ 这是一个警告
:::

:::tip
💡 一个小提示
:::
```
渲染自动生成带有颜色标识的 block，无需手动加 emoji 和粗体。

**收益 2：任务列表**

当前不支持 `- [x]` 语法，渲染为普通列表项。迁移后自适应渲染带 checkbox 的任务列表。

**收益 3：脚注**

```markdown
这是一个说法[^1]。

[^1]: 详细的脚注说明
```
适合技术文档场景。

#### 迁移成本

| 项 | 成本 |
|------|------|
| CDN 引用 | 替换 1 行 vendor 引用 → jsdelivr UMD |
| 渲染调用 | `marked.parse(text)` → `md.render(text)` |
| 高亮集成 | 不变（仍然是 `hljs.highlightElement` 后处理） |
| KaTeX 集成 | 不变（仍然是 `renderMathInElement` 后处理） |
| Mermaid | 不受影响 |
| 测试 | 需验证所有现有 markdown 渲染一致性 |

**结论**：收益明确（容器/任务列表/脚注），迁移成本低（~2 处代码改 + 1 个 CDN 引用替换 + 测试）。建议实施。

### 1.2 GitHub Markdown CSS 主题

当前问题：
- 暗色模式用 `github-markdown-light.min.css` + `!important` 覆盖 → 颜色不准、维护困难
- ![当前的覆盖方式](https://via.placeholder.com/1x1)

**方案**：替换为 `sindresorhus/github-markdown-css` 暗色变体

```javascript
// 在现有的暗色模式切换逻辑中
function setMarkdownTheme(dark) {
  document.getElementById('github-markdown-css').href = dark
    ? 'https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.7.0/github-markdown-dark.min.css'
    : 'https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.7.0/github-markdown.min.css';

  document.getElementById('highlight-theme-css').href = dark
    ? 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css'
    : 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css';
}
```

**收益**：
- 暗色下文本、表格、引用块、代码块全部跟随 GitHub 官方配色
- 消除 ~30 行 `!important` 覆盖
- 亮色/暗色/跟随系统三种模式都正确定义

---

## 二、移动端方案

### 2.1 策略

独立页面目录 `static/m/`，**不修改**现有桌面版。

```
static/
├── index.html           # 桌面版（不动）
├── preview.html         # 桌面版（不动）
├── m/
│   ├── index.html       # 移动端目录浏览（新增）
│   ├── preview.html     # 移动端内容+大纲+反馈（新增）
│   └── style.css        # 移动端独立样式（新增）
```

### 2.2 使用零新接口

全部复用现有后端 API：

| 移动端页面 | 调用 API | 桌面版同样调用 |
|-----------|---------|-------------|
| m/index.html | `GET /api/clawmate/list?root=X&dir=Y` | 同 |
| m/index.html | `GET /api/clawmate/config` | 同 |
| m/preview.html | `GET /api/clawmate/preview/load?root=X&file=Y` | 同 |
| m/preview.html | `GET /api/clawmate/preview/outline?root=X&file=Y` | 同 |
| m/preview.html | `GET /api/clawmate/feedback/list?root=X&project=Y&file=Z` | 同 |
| m/preview.html | `POST /api/clawmate/feedback` | 同 |
| m/preview.html | `POST /api/clawmate/feedback/update` | 同 |

### 2.3 m/index.html 布局

```
┌─────────────────────────────┐
│ My Projects          ▽ 切换 │  ← 顶栏 44px，点击弹出 root 选择
├─────────────────────────────┤
│ 🔍 搜索文件名...            │  ← 搜索框，输入即前端过滤
├─────────────────────────────┤
│ 全部 · 📁文档 · 📋代码 · 📊数据 │  ← 横滑类型过滤标签
├────┬────────────────────────┤
│ 排 │ ↓ 最新  ↑ 名称 · · · │  ← 排序行：时间/名称/大小 切换
├────┴────────────────────────┤
│ 📄 design.md      2.3k   › │  ← 文件列表，每行 48px
│ 📄 README.md      3.2k   › │
│ 📁 src/              —    › │
│ 📁 assets/           —    › │
│ 📄 api-spec.md     4.1k  › │
│                           │
└─────────────────────────────┘
```

**交互**：
- 顶部 root 名称 → 点击弹出底部面板，显示所有可选 root → 切换即重新加载目录
- 搜索 → 实时过滤（前端 `filter()`，不调后端）
- 类型过滤标签 → 横滑，选中高亮
- 排序 → 横向分段控件（时间↓ / 名称↑ / 大小↓），点击切换排序键+方向
- 每行 → 文件图标 + 名称 + 大小/后缀 + 箭头 → 点击进 `m/preview.html`

### 2.4 m/preview.html 布局

```
┌─────────────────────────────┐
│ ←     文件名.md    📑 💬   │  ← 顶栏 44px
├─────────────────────────────┤
│                             │
│       Markdown 正文         │  ← 全宽、滑动阅读
│       （KaTeX/Mermaid       │
│        /highlight.js）      │
│                             │
│                             │
├─────────────────────────────┤
│   📑 大纲 · 💬 反馈 (3)    │  ← 底栏 40px，点击弹 panel
└─────────────────────────────┘
```

**大纲 panel**（底部升起，60% 高度，可拖动）：

```
┌─────────────────────────────┐
│ 📑 大纲              ✕ 关闭 │
├─────────────────────────────┤
│ # 设计方案（当前阅读位置）  │
│   ## 1.1 背景               │
│   ## 1.2 目标               │
│ # 实施计划                   │
│   ## 2.1 阶段一              │
│   ## 2.2 阶段二              │
│                             │
│         ═══ 拖动手柄 ═══    │
└─────────────────────────────┘
```

- 点击条目 → 滚动正文到对应 heading → 收起 panel
- 复用现有 `GET /api/clawmate/preview/outline`

**反馈 panel**（底部升起，50% 高度，可拖动）：

```
┌─────────────────────────────┐
│ 💬 反馈 (3条待处理)  ✕ 关闭 │
├─────────────────────────────┤
│                             │
│ FD-0001  "修改此段落"   done│  ← 反馈列表
│ FD-0002  "删除这个"       ✓ │
│                             │
│ ─────────────────────────── │
│                             │
│ [选择文本后出现浮动按钮]    │  ← 选中文本后触发
│                             │
│         ═══ 拖动手柄 ═══    │
└─────────────────────────────┘
```

**选中文本后的反馈输入流程**：

```
用户选中“一段文字”
       ↓
浮动按钮出现在选区上方：[📝 备注] [🗑 删除] [🔧 修改] [...]
       ↓ 点击备注
底部升起输入面板：
┌─────────────────────────────┐
│ 添加反馈           ✕ 取消   │
├─────────────────────────────┤
│ 选中内容:                   │
│ "一段文字"                 │
│                             │
│ 你的意见:                   │
│ [________________________] │
│                             │
│ 快捷标签: 🗑🔧📈📉⚡      │  ← 点击填入意见框
│                             │
│       [提交反馈]             │
│         ═══ ═══             │
└─────────────────────────────┘
      ↓ 提交
POST /api/clawmate/feedback → 写入反馈 → 回到列表
```

### 2.5 移动端样式约定

```css
/* m/style.css */
:root {
  --safe-top: env(safe-area-inset-top, 0px);
  --safe-bottom: env(safe-area-inset-bottom, 0px);
  --topbar: 44px;
  --bottombar: 40px;
  --font-size: 16px;       /* 防止 iOS 缩放 */
  --touch-target: 44px;    /* 最小触控目标 */
}
```

- 所有按钮/链接最小 44px 触控目标
- 无阴影、无 border-radius 装饰
- `-webkit-overflow-scrolling: touch`
- 状态栏适配：`<meta viewport-fit=cover>` + safe area env vars
- 全宽布局，不留边距空隙

### 2.6 响应式切换

在桌面版 `index.html` / `preview.html` 顶部加入：

```javascript
if (window.innerWidth < 768 && !sessionStorage.getItem('desktop')) {
  const params = new URLSearchParams(location.search);
  location.href = '/clawmate/m/' + (location.pathname.includes('preview') ? 'preview.html' : 'index.html') + '?' + params.toString();
}
```
用户手动切换到桌面版（通过底栏"桌面版"链接）后设 `sessionStorage.desktop = 1`。

---

## 三、排序 bug 修复

### 问题

1. `<select id="sortKey">` 第一个选项是 `名称`，但 JS 默认是 `sortKey: "mtime"` → 显示与状态不同步
2. 排序按钮显示"降序"，对时间而言"最新=降序"不直观

### 修复

```html
<!-- 改为与 JS 默认值一致 -->
<select id="sortKey">
  <option value="time">时间</option>
  <option value="name">名称</option>
  <option value="size">大小</option>
</select>
<button id="sortDir">↓ 最新优先</button>
```

方向按钮动态文字：

```javascript
function updateSortLabel() {
  const labels = {
    time: { desc: "↓ 最新优先", asc: "↑ 最早优先" },
    name: { desc: "↓ Z→A", asc: "↑ A→Z" },
    size: { desc: "↓ 最大优先", asc: "↑ 最小优先" },
  };
  els.sortDir.textContent = labels[state.sortKey][state.sortDir];
}
```

页面加载时同步 select：

```javascript
els.sortKey.value = state.sortKey === "mtime" ? "time" : state.sortKey;
```

---

## 四、实施计划

### 阶段一：排序修复 + Markdown 主题 CSS（约 2h）

| 编号 | 文件 | 变更 |
|------|------|------|
| S1.1 | `index.html` | 排序 select 默认值修复 + 方向按钮语义化 |
| S1.2 | `app.js` | 排序标签文字动态更新逻辑 + select 同步 |
| S1.3 | `preview.html` | GitHub Markdown CSS 暗色/亮色动态切换 |
| S1.4 | `style.css`（已存在） | 删除〜30 行 !important 覆盖（暗色 markdown-body） |

### 阶段二：markdown-it 迁移（约 3h）

| 编号 | 文件 | 变更 |
|------|------|------|
| S2.1 | `preview.html` | CDN 引用：`marked.min.js` → `markdown-it.min.js` + 插件 |
| S2.2 | `app.js` | `marked.parse()` → `md.render()`，注册插件 |
| S2.3 | `core/markdown.js`（可选） | 如渲染逻辑复杂，抽离为独立渲染模块 |
| S2.4 | 测试 | 验证所有现有 markdown 渲染一致 + task list/container 新功能 |

**CDN 引用**：

```html
<!-- 替换 vendor/marked.min.js -->
<script src="https://cdn.jsdelivr.net/npm/markdown-it/dist/markdown-it.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/markdown-it-container/dist/markdown-it-container.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/markdown-it-emoji/dist/markdown-it-emoji.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/markdown-it-footnote/dist/markdown-it-footnote.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/markdown-it-task-lists/dist/markdown-it-task-lists.min.js"></script>
```

### 阶段三：移动端 m/index.html（约 4h）

| 编号 | 文件 | 变更 |
|------|------|------|
| S3.1 | `m/style.css` | 移动端全局样式 |
| S3.2 | `m/index.html` | 目录浏览：文件列表、搜索、类型过滤、排序 |

### 阶段四：移动端 m/preview.html（约 6h）

| 编号 | 文件 | 变更 |
|------|------|------|
| S4.1 | `m/preview.html` | 内容阅读：markdown 渲染、大纲 panel、反馈 panel、选中文本提交反馈 |

### 不做的事（本次计划排除）

- ❌ 桌面版预览 UI 重构（大纲/反馈面板可收起）— 后续版本
- ❌ 桌面版 feedback 浮层改造 — 后续版本
- ❌ 桌面版状态栏 — 后续版本
- ❌ 不新增后端 API

---

## 五、实施路径建议

```
阶段一（排序+CSS） → 阶段二（markdown-it） → 阶段三（m/index） → 阶段四（m/preview）
    ~2h                  ~3h                   ~4h                  ~6h
```

各阶段可独立发布。建议按顺序，因为阶段一/二的风险低、收益快，做完了再投入移动端。
