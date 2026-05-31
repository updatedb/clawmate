# ClawMate 测试用例 — v0.1–v1.2

---

## v0.1 文件管理

### TC-001 目录浏览
**测试项**：切换目录，文件列表正确加载
**步骤**：`GET /api/clawmate/list?root=Openclaw&dir=outbound`
**预期**：返回 JSON 含 `entries` 数组，`path=outbound`，条目含 name/category/size

### TC-002 Root 切换
**测试项**：不同 root 返回各自的目录结构
**步骤**：`GET /api/clawmate/list?root=webprojects&dir=clawmate`
**预期**：返回 clawmate 项目目录内容

### TC-003 画廊/列表视图（代码审查）
**测试项**：前端支持 gallery/list 切换
**方法**：JS 代码审查 `app.js` 中 `showGallery()` / `showList()` 函数，gallery 有卡片 CSS `border-radius: var(--radius-lg)`，list 有表格行 CSS

### TC-004 类型过滤
**测试项**：按 category 过滤
**步骤**：`GET /api/clawmate/list?root=Openclaw&dir=browser`
**预期**：只返回 image 类型条目

### TC-005 递归搜索
**测试项**：跨子目录搜索
**步骤**：`GET /api/clawmate/search?q=png&root=Openclaw&recursive=true`
**预期**：返回多个目录中的 png 文件（results >= 1）

### TC-006 搜索清除
**测试项**：空搜索词返回空结果
**步骤**：`GET /api/clawmate/search?q=&root=Openclaw`
**预期**：`results=[]`

### TC-007 分页
**测试项**：大目录分页返回
**方法**：代码审查 `app.js` 中 `loadDir()` 有分页逻辑（每页 60 条）

### TC-008 单文件下载
**测试项**：download 端点返回文件
**步骤**：`GET /api/clawmate/download?root=Openclaw&path=browser/2455ac37-7818-4f46-a592-e3339c78fe63.png`
**预期**：HTTP 200

### TC-009 批量下载
**测试项**：多文件打包 zip
**步骤**：`GET /api/clawmate/batch-download?root=Openclaw&paths=browser/2455ac37-7818-4f46-a592-e3339c78fe63.png`
**预期**：HTTP 200，ZIP 文件

### TC-010 删除文件（二次确认 API 行为）
**测试项**：删除已存在文件
**步骤**：`POST /api/clawmate/upload` → `DELETE /api/clawmate/delete`
**预期**：上传成功，删除返回 `{"success":true}`

### TC-011 批量多选（代码审查）
**测试项**：前端支持复选框批量选择
**方法**：JS 代码审查 `app.js` 中 `selectedFiles` Set 结构和 `batchActions()` 函数

### TC-012 复制路径
**测试项**：复制文件绝对路径
**方法**：代码审查 `app.js` 中 `copyPath()` 函数调用 `navigator.clipboard.writeText()`

---

## v0.2 Standalone 预览

### TC-013 Standalone URL 模式
**测试项**：`?mode=standalone` 触发独立预览
**方法**：代码审查 `app.js` 检测 URL 参数 `mode=standalone` → `showStandalonePreview()`

### TC-014 Standalone 去侧边栏
**测试项**：standalone 模式隐藏 sidebar 和 toolbar
**方法**：CSS 代码审查 `.standalone-mode .sidebar { display:none }` 和 JS `document.body.classList.add('standalone-mode')`

### TC-015 Standalone 底部返回链接
**测试项**：standalone 底部有返回链接
**方法**：HTML 代码审查 `static/index.html` 中 standalone 模板含 `<a href="/clawmate/">← 返回</a>`

### TC-016 预览链接生成
**测试项**：`/api/clawmate/preview-link` 返回完整 URL
**步骤**：`GET /api/clawmate/preview-link?root=Openclaw&file=test.md`
**预期**：返回 `{url: "https://.../clawmate/?root=Openclaw&file=test.md&mode=standalone"}`

---

## v0.3 Feedback 闭环

### TC-017 选中文本浮层
**测试项**：预览区选中文本弹出操作浮层
**方法**：代码审查 `app.js` 中 `setupSelectionFeedback()` 注册 `selectionchange` 事件监听

### TC-018 备注输入 + 面板累积
**测试项**：输入备注后加入列表，面板累积多条
**方法**：代码审查 `createFeedbackPanel()` 工厂函数，`feedbackPanelList` 数组累积

### TC-019 Feedback 提交写入文件
**测试项**：POST /api/clawmate/feedback 写入 FEEDBACK.md
**步骤**：POST feedback → GET /api/clawmate/feedback/status 验证 `exists=True`
**预期**：`counts.pending >= 1`

### TC-020 Push Wake
**测试项**：feedback 创建后触发 wake
**方法**：代码审查 `routes.py` 中 `subprocess.run([openclaw_bin, "system", "event", ...])` 调用

---

## v0.4 批量操作 + Daemon

### TC-021 批量删除
**测试项**：多选后批量删除
**方法**：代码审查 `app.js` 中 `batchDelete()` 调用 `DELETE /api/clawmate/delete`

### TC-022 拖拽上传
**测试项**：drag-drop 区域接收文件并上传
**方法**：代码审查 `app.js` 中 `setupDragDrop()` 注册 `dragover/drop` 事件

### TC-023 install.sh 语法
**测试项**：install.sh 无语法错误
**步骤**：`bash -n ~/webprojects/clawmate/install.sh`
**预期**：无输出（语法正确）

---

## v1.0 UI + PDF 降级

### TC-024 卡片圆角阴影
**测试项**：gallery 卡片有圆角和阴影
**方法**：CSS 代码审查 `.gallery-card { border-radius: var(--radius-lg); box-shadow: var(--card-shadow) }`

### TC-025 颜色/主题变量
**测试项**：CSS 变量定义完整（light + dark）
**方法**：CSS 代码审查 `static/css/` 中 CSS 变量定义（`--bg-light`, `--bg-dark`, `--accent` 等）

### TC-026 移动端响应式
**测试项**：<768px 汉堡菜单
**方法**：CSS 代码审查 `@media (max-width: 768px)` 含 `.hamburger` 显示逻辑

### TC-027 骨架屏动画
**测试项**：骨架屏有 pulse 动画
**方法**：JS 代码审查 `showGallerySkeleton()` / `showListSkeleton()` 含 `@keyframes skeleton-pulse`

### TC-028 PDF 降级（ONLYOFFICE 不可用时）
**测试项**：ONLYOFFICE 不可达时降级到 pdf.js
**方法**：代码审查 `checkOnlyofficeAvailable()` 失败时调用 `openPdfPreview()` 渲染 pdf.js iframe

### TC-029 PDF 降级（ONLYOFFICE 可用时）
**测试项**：ONLYOFFICE 可用时正常调用
**方法**：代码审查 `window.open(onlyOfficeUrl)` 调用链

---

## v1.1 Slash Commands

### TC-030 /clawmate preview 命令
**测试项**：搜索文件并生成可点击预览链接
**方法**：SKILL.md 代码审查 `clawmate_preview()` 函数逻辑

### TC-031 /clawmate list 命令
**测试项**：列出今天所有 feedback
**方法**：SKILL.md 代码审查 `/clawmate list` 分支调用 `GET /api/clawmate/feedback/list?since=today`

### TC-032 /clawmate list pending
**测试项**：只列出待处理 feedback
**步骤**：`GET /api/clawmate/feedback/list?root=Openclaw&project=testproject&status=pending&since=today`
**预期**：`total=0`（上例中只有 done 项）

### TC-033 /clawmate list 黄昏（文件过滤）
**测试项**：文件名模糊匹配
**步骤**：`GET /api/clawmate/feedback/list?root=Openclaw&project=testproject&file=test&since=today`
**预期**：`total=1`

### TC-034 Feedback 创建 wake
**测试项**：创建 feedback 后立即 push wake
**方法**：代码审查 routes.py POST /feedback 中 `subprocess.run([openclaw_bin, "system", "event", ...])`

---

## v1.2 Feedback 重构 + 三栏

### TC-035 Feedback 无 type 字段
**测试项**：API 响应不包含 type 字段
**步骤**：`GET /api/clawmate/feedback/list?...`
**预期**：响应 JSON 中每个 item 无 `type` 键

### TC-036 /feedback/list 三参数过滤
**测试项**：status/file/since 三个参数同时过滤
**方法**：代码审查 `routes.py` 中 `clawmate_feedback_list()` 的三个过滤分支

### TC-037 默认 today 过滤
**测试项**：不传 since 时默认 today
**步骤**：`GET /api/clawmate/feedback/list?root=Openclaw&project=testproject`
**预期**：默认 `since=today`

### TC-038 Standalone 三栏布局
**测试项**：standalone 模式三栏布局
**方法**：HTML/CSS 代码审查 `index.html` 中 standalone 模板含三栏 `.standalone-left/.standalone-content/.standalone-right`

### TC-039 底部工具栏
**测试项**：standalone 底部工具栏存在
**方法**：HTML 代码审查 standalone 模板含 `.standalone-toolbar` 含复制/导出/下载/删除/返回按钮

### TC-040 移动端侧栏默认隐藏
**测试项**：<900px 侧栏默认隐藏
**方法**：CSS 代码审查 `@media (max-width: 900px)` 中 `.standalone-left, .standalone-right { transform: translateX(...) }`

---

## API 端点测试（18个）

### TC-API-01 GET /api/clawmate/config
**步骤**：`GET /api/clawmate/config`
**预期**：HTTP 200，JSON 含 `roots` 数组和 `defaultRootId`

### TC-API-02 GET /api/clawmate/list
**步骤**：`GET /api/clawmate/list?root=Openclaw&dir=outbound`
**预期**：HTTP 200，JSON 含 `path`/`entries`

### TC-API-03 GET /api/clawmate/search
**步骤**：`GET /api/clawmate/search?q=png&root=Openclaw`
**预期**：HTTP 200，`results` 数组含 png 文件

### TC-API-04 GET /api/clawmate/preview
**步骤**：`GET /api/clawmate/preview?root=Openclaw&path=browser/2455ac37-7818-4f46-a592-e3339c78fe63.png`
**预期**：HTTP 200，图片文件返回原始内容

### TC-API-05 GET /api/clawmate/download
**步骤**：`GET /api/clawmate/download?root=Openclaw&path=browser/2455ac37-7818-4f46-a592-e3339c78fe63.png`
**预期**：HTTP 200，Content-Disposition attachment

### TC-API-06 GET /api/clawmate/raw
**步骤**：`GET /api/clawmate/raw?root=Openclaw&path=browser/2455ac37-7818-4f46-a592-e3339c78fe63.png`
**预期**：HTTP 200，inline Content-Type

### TC-API-07 GET /api/clawmate/batch-download
**步骤**：`GET /api/clawmate/batch-download?root=Openclaw&paths=browser/2455ac37.png`
**预期**：HTTP 200，ZIP 文件

### TC-API-08 POST /api/clawmate/upload
**步骤**：`POST /api/clawmate/upload` with multipart file
**预期**：`{"success": true, "filename": "...", "path": "..."}`

### TC-API-09 DELETE /api/clawmate/delete
**步骤**：`DELETE /api/clawmate/delete?root=Openclaw&path=outbound/test_upload.txt`
**预期**：`{"success": true}`

### TC-API-10 DELETE /api/clawmate/delete-dir
**步骤**：`DELETE /api/clawmate/delete-dir?root=Openclaw&path=nonexistent`
**预期**：404 `{"detail": "Directory not found"}`

### TC-API-11 GET /api/clawmate/preview-link
**步骤**：`GET /api/clawmate/preview-link?root=Openclaw&file=test.md`
**预期**：HTTP 200，`{url: "...", root: "...", file: "..."}`

### TC-API-12 GET /api/clawmate/onlyoffice/script-url
**步骤**：`GET /api/clawmate/onlyoffice/script-url`
**预期**：HTTP 200，`{url: "https://..."}`

### TC-API-13 GET /api/clawmate/onlyoffice/config
**步骤**：`GET /api/clawmate/onlyoffice/config?root=Openclaw&path=test.png`
**预期**：HTTP 200，含 JWT config

### TC-API-14 POST /api/clawmate/feedback
**步骤**：`POST /api/clawmate/feedback` with selections
**预期**：`{ok: true, ids: ["FD-..."], ...}`

### TC-API-15 GET /api/clawmate/feedback/list
**步骤**：`GET /api/clawmate/feedback/list?root=Openclaw&project=testproject&since=today`
**预期**：HTTP 200，`{total: N, items: [...]}`

### TC-API-16 POST /api/clawmate/feedback/update
**步骤**：`POST /api/clawmate/feedback/update` 更新状态
**预期**：`{ok: true, id: "FD-...", newStatus: "done"}`

### TC-API-17 GET /api/clawmate/feedback/status
**步骤**：`GET /api/clawmate/feedback/status?root=Openclaw&project=testproject`
**预期**：HTTP 200，`{exists: true/false, counts: {...}, items: [...]}`

### TC-API-18 错误处理：缺少必填参数
**测试项**：缺少 root/project 时正确报错
**步骤**：`GET /api/clawmate/feedback/status`（无参数）
**预期**：422 `{"detail": "Missing root or project"}`
