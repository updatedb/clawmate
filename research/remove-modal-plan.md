# 移除 Modal Window 方案

> 状态：待审查 | 日期：2026-06-02

## 1. 背景

ClawMate 当前有**两条文件预览路径**：

```
index.html 点击文件
  ├── PDF / Office 文件 → window.open preview.html（直接跳转）
  └── 其他文件（md/image/audio/video/text）→ Modal 弹窗预览
       └── Modal 内有 🔗 按钮 → window.open preview.html（二次跳转）
```

维护两套预览渲染逻辑（Modal JS + preview.html），功能也不对等（Modal 无大纲/反馈面板）。PDF 和 Office 已经直接跳 preview.html，Modal 是历史遗留。

## 2. 目标

- **preview.html 成为唯一预览入口**
- 点击 index.html 中的文件 → 直接在新 tab/window 打开 preview.html
- 删除所有 Modal 相关代码（HTML + CSS + JS）
- 保持 index.html 文件浏览体验不变

## 3. 变更范围

### 3.1 index.html — 删除

```html
<!-- 删除整个 Modal div（第 98-105 行） -->
<div id="previewModal" class="modal hidden">
  <div class="modal-content">
    <div class="modal-topbar">
      <button id="openInPreview" ...>🔗</button>
      <button id="toggleMaximize" ...>⛶</button>
      <button id="closePreview" class="close">×</button>
    </div>
    <div id="previewBody" class="preview-body"></div>
  </div>
</div>
```

### 3.2 style.css — 删除

| 行号范围 | 内容 | 行数 |
|----------|------|------|
| CSS Variables | `--bg-modal`, `--modal-overlay`（light + dark 两份） | 4 |
| 324-326 | `@media (max-width: 768px)` 中 `.modal-content` 全屏覆盖 | 3 |
| 345-347 | `.modal`, `.modal.hidden`, `.modal-content` | 3 |
| 348-351 | `.modal-topbar` 系列 | 4 |
| 355-358 | `.modal-footer` 系列 | 4 |
| 361-362 | `.preview-link-btn` | 2 |
| 363-364 | `.maximize-btn` | 2 |
| 365-371 | `.modal.maximized` 系列 | 7 |
| 372-384 | `.preview-body` 内模态子元素系列 | ~13 |
| 386-395 | `.preview-footer` 系列 | ~10 |
| 434 | `.preview-body img` 规则（如有 modal 专用） | 1 |
| **合计** | | **约 60 行** |

保留不动：`showFeedbackDetailModal` 相关 CSS（fb-detail-overlay/ fb-detail-modal）— 这是反馈卡片详情弹窗，不是文件预览 Modal。

### 3.3 app.js — 删除

#### DOM 元素引用（6 个）

```javascript
// els 对象中删除：
previewModal: document.getElementById("previewModal"),
previewBody: document.getElementById("previewBody"),
modalContent: document.querySelector("#previewModal .modal-content"),
closePreview: document.getElementById("closePreview"),
toggleMaximize: document.getElementById("toggleMaximize"),
openInPreview: document.getElementById("openInPreview"),
```

#### 函数（8 个）

| 函数名 | 行号 | 描述 |
|--------|------|------|
| `showPreviewSkeleton()` | ~1386 | 骨架屏加载动画 |
| `openEntryPreview()` | ~1544 | 入口分发（PDF→preview / Office→preview / 其他→modal） |
| `openPdfPreview()` | ~1561 | pdf.js 降级预览（Modal 内 iframe） |
| `buildPreviewHeader()` | ~1596 | 构建 Modal 内预览标题 |
| `buildPreviewFooter()` | ~1632 | 构建 Modal 内底部工具栏 |
| `openPreview()` | ~1728 | Modal 预览主逻辑（md/image/audio/video/text） |
| `closePreviewModal()` | ~2144 | 关闭 Modal 并清理 |
| `findPreviewContainer()` | ~2365 | 查找 Modal 所在的 preview 容器 |
| `scrollModalToLine()` | ~617 | 代码大纲点击跳转行号 |
| `renderCodeOutlineModal()` | ~623 | 代码大纲渲染 |

#### 事件绑定

```javascript
// 需要清理的事件（在 init 或其他位置）：
els.closePreview.addEventListener(...)
els.toggleMaximize.addEventListener(...)
els.openInPreview.addEventListener(...)
// 键盘 Escape 关闭 modal 监听
// document click 关闭 modal 监听
```

#### 代码引用（约 70 处）

所有引用 `els.previewBody` / `els.previewModal` / `els.modalContent` 的地方都要清理。

#### 保留不动

- `showFeedbackDetailModal()` — 反馈卡片详情弹窗，不是文件预览 Modal
- `buildRawLink()` / `toAbsoluteUrl()` — 仍用于下载链接
- PDF/Office 的 `window.open(previewUrl, ...)` — 已正确跳 preview.html

### 3.4 新增：统一跳转逻辑

```javascript
// 删除 openEntryPreview() + openPreview()，替换为：
function openEntryPreview(entry) {
  if (!entry || entry.is_dir) return;
  const previewUrl = `/clawmate/preview.html?root=${encodeURIComponent(state.rootId)}&file=${encodeURIComponent(entry.relPath)}`;
  window.open(previewUrl, "_blank", "noopener");
}
```

所有文件类型统一走 `window.open` → `preview.html`，不再区分文件类型。

### 3.5 兼容性影响

| 场景 | 影响 | 处理 |
|------|------|------|
| 桌面端点击文件 | 原来 Modal 弹窗 → 现在新 tab | 用户体验变化，需确认可接受 |
| 手机端点击文件 | 原来 Modal 全屏 → 现在新 tab | 行为趋同，几乎无差异 |
| 目录浏览 | 无影响 | `handleEntryClick` → `loadDir` |
| 搜索 | 无影响 | 搜索结果点击同样走新逻辑 |
| 反馈功能 | 从 Modal feedbackPanel → 仅 preview.html 反馈 | 简化，preview.html 功能更完整 |
| 返回文件列表 | 之前关 Modal 即可 → 现在关 tab | 用户需适应 |
| 打印/导出 PDF | 之前 Modal 顶部有按钮 → 现在 preview.html 底部有 | 迁移到 preview.html |

### 3.6 体验优化（可选，独立于本次）

- preview.html 底部「← 返回」按钮跳回 index.html
- index.html URL 参数记录当前 root+目录，preview.html 知道从哪里来

## 4. 任务列表

| # | 任务 | 描述 | 文件 |
|---|------|------|------|
| M1 | 替换入口函数 | `openEntryPreview` 改为统一 `window.open preview.html`，删除 `openPreview` 等 8 个函数 | `app.js` |
| M2 | 清理 DOM 引用 | 删除 `els` 中 6 个 modal 引用 | `app.js` |
| M3 | 清理函数体 | 删除所有引用 modal 的代码路径（~70 处） | `app.js` |
| M4 | 删除 Modal HTML | 删除 `#previewModal` div | `index.html` |
| M5 | 删除 Modal CSS | 删除 60 行 modal 样式 | `style.css` |
| M6 | 清理事件绑定 | 删除 modal 相关的 addEventListener | `app.js` |
| M7 | 回归验证 | 点击各类文件 → 正确跳转 preview.html；目录浏览正常；搜索正常 | 手动测试 |
| M8 | 手机端适配 | `.modal-content` 全屏覆盖规则移除后确认无影响 | `style.css` |

## 5. 风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| `els.previewBody` 引用被其他模块（feedback tooltip）依赖 | 中 | 逐行审查，feedback tooltip 在 preview.html 有自己的 context |
| 用户习惯改变（Modal → 新 tab） | 低 | 桌面端 `window.open` 默认新 tab，用户可拖回同一窗口 |
| 代码清理遗漏导致运行时错误 | 中 | 全局搜索 `previewBody`/`previewModal`/`modal` 残留并验证 |
| style.css 删除范围过大影响其他元素 | 低 | 仅删除 `.modal*` `.preview-link*` `.maximize*` 命名空间规则 |

## 6. 不处理项

- preview.html 本身的任何功能改动
- 反馈面板（feedbackPanel）逻辑 — 仅在 preview.html 运行，不受影响
- 文件下载/重命名/删除 — 通过右键或独立 API 调用，不在本次范围
- 音频/视频/字幕面板 — 已在 preview.html 中完整实现
