# Changelog

## v1.5.1 (2026-06-06)

### 桌面端
- 图片导航：‹ › 上一页/下一页 + (1/N) 计数
- Mermaid 缩放：Ctrl+滚轮/按钮/拖拽平移/双击重置
- 底部栏分组重构：preview-btn-group 统一组内 4px 间距
- btnSrcEdit/btnSrcSave 独立分组展示

### 移动端
- 代码大纲 (buildCodeOutline)：支持 py/js/ts/go/rs/html 函数/类定义导航
- Mermaid 渲染修复：mermaidStore 缺值导致 "No diagram type detected"
- 选中自定义高亮 (CSS Highlight API)：黄底+橙色下划线

### 清理
- 删除 feedback_api.py.bak、marked.min.js（被 markdown-it 替代）
- feedback.json 取消 git 追踪
- config.example.json 真实 URL 替换为占位符

### 后端
- _wake_agent_for_root 新增 project/file 可选参数，缩小 agent 查询范围
- cron list 匹配改用 --json，消除 UUID 前缀截断 bug
- config.py 新增 env 覆写：CLAWMATE_HOOK_TOKEN / GATEWAY_URL 等
- faster-whisper 改为可选依赖 (CLAWMATE_ENABLE_SUBTITLE=1)

## v1.5 (2026-06-06)

### 移动端首页 (m/index.html)
- 搜索框：输入即搜，✕ 清除按钮可控
- root 切换面板：整条 topbar 可点击 + 选中高亮 + 品牌 ClawMate
- 文件列表显示更新时间（取代文件大小）

### 移动端预览 (m/preview.html)
- 代码高亮 (CODE_EXTS + hljs)，JSON 格式化
- 图片预览 + ‹ › 导航
- Office/PDF ONLYOFFICE 嵌入预览
- 文本选中反馈：浮动 ✏️ 按钮 → 面板弹出
- 反馈提交链路完整

### 后端
- routes.py: 修复 onlyoffice_config UnboundLocalError
- _get_onlyoffice_secret 增加 config.json 回退

### 其他
- 桌面端图片导航
- 项目清理 + Dockerfile/docker-compose 规范化
- CLAWLIST 追加 v1.5 章节

## v1.28 (2026-06-06)

- 移动端独立页面 m/index.html（目录浏览）+ m/preview.html（阅读+反馈）

## v1.27 (2026-06-06)

- 排序修复 + GitHub Markdown CSS + markdown-it 迁移

## v1.26 (2026-06-06)

- config.py + store.py + cron-tick + 清理

## v1.0 — v1.25

- 详见 CLAWLIST.md

## v0.1 — MVP

- 初始版本
