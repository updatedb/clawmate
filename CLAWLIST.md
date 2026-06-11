# CLAWLIST — ClawMate

> 🏛️ 仅记录各版本最终决策与结果。过程信息已清理。

## v0.1 MVP ✅
文件管理+Markdown/代码/图片/音视频预览、ONLYOFFICE/PDF预览、拖拽上传、批量操作

## v0.2 Standalone 预览 + Skill ✅
Standalone 预览、Slash Commands（preview/list/todo/do）

## v0.3 反馈闭环 Phase 1 ✅
选中文本→浮层→提交→FEEDBACK.md 托管→Agent 处理→状态更新

## v0.4 批量反馈 + Daemon ✅
批量累积+一键提交、Systemd Daemon（user-level + Linger 开机自启）

## v1.0 UI 增强 + 完善 ✅
画廊卡片样式、CSS 变量颜色体系、侧边栏/面包屑、骨架屏、PDF ONLYOFFICE 降级

## v1.1 Slash Commands 增强 ✅
新增 preview-link/feedback/list API、5 个有效 Slash Command、Feedback Push Wake

## v1.2 Feedback 重构 + Standalone 三栏布局 ✅
Feedback JSON 格式迁移（FEEDBACK.md→feedback.json）、Standalone 三栏布局

## v1.3 preview.html 统一 + ONLYOFFICE 编辑 + 双模式渲染 ✅
- preview.html 全类型预览统一（图片/音视频/Office/PDF/代码/Markdown）
- ONLYOFFICE 编辑模式+JWT 安全集成
- Markdown/Mermaid/KaTeX/highlight.js 渲染引擎
- 反馈面板、底部工具栏

## v1.4 反馈增强 + 代码大纲 + 质量提升 ✅
- 无后缀文件文本检测（嗅探文件头 8KB）
- 代码文件大纲索引（12 种语言函数/类）
- 反馈处理结果字段、详情弹窗
- 反馈浮窗快捷标签（🗑 🔧 📈 📉）
- 防重复提交、多行内容完整保存
- 配置文件单用户认证方案
- 字幕提取（faster-whisper local）
- Feedback JSON 格式升级（ID 四位零填充、root/project 提至顶层）
- Modal Window 删除（所有文件直接 window.open preview.html）
- project=root 场景支持

## v1.5 Feedback JSON 全链路回归验证 ✅
36 项测试通过率 93.3%（2 项已知偏差已确认）

## v1.6 架构重构 + Auth 增强 + Cron 修复 ✅
- Feedback 路由独立至 feedback_api.py
- Cron 管理独立至 cron_manager.py，命名 clawmate-fb-{agent}
- Auth: localhost bypass、登录跳转保留 query string
- Cron name 对齐前缀匹配

## v1.7 图片导航 + 反馈标签配置化 ✅
- 图片预览上/下一张 + 计数器
- Feedback 标签从 config.json 配置化（feedback.tags）

## v1.7.1 图片导航计数器 1/N 格式 ✅
计数器从 "🖼 filename · 共 N 张" 改为 "N / M"

## v1.8 反馈系统 + 缓存 + 清理修复 ✅
- _wake_agent_for_root 异常改为结构化日志
- _load_config TTL 缓存（60s 过期重载）
- feedback.json 归档（90 天 done 项归档到 feedback.archive.json）

## v1.9 删除操作鉴权强化 + 审计日志 ✅
- DELETE 操作写 audit log（JSONL 格式到 dev/audit.json）
- 字段：timestamp/username/client_ip/operation/root_id/path/result/error
- 本机 bypass 保留（cron 任务需要），但记录 caller=local-bypass

## v1.10 移动端 P0 4 项修复 ✅
反馈 Sheet 弹出、侧栏遮罩+内容缩窄、safe-area 适配、Bootstrap 断点统一

## v1.11 移动 P1 5 项 + P2 4 项 + 漏项 2 项 ✅
P1: Mermaid 缩放、键盘遮挡 Sheet、虚拟键盘布局、44px 触摸目标、横向溢出
P2: 阅读模式沉浸、惯性滚动（IntersectionObserver）、飞书 WebView cookie、移动端上传
漏项: SPA iframe 预览、弱网提示、UIState 状态机

## v1.12 CLAWMATE_PUBLIC_BASE_URL 启动检查 ✅
启动时检查环境变量，未设则 print WARNING（不阻塞启动）

## v1.13 preview-mask 桌面 bug + SPAPreview × 按钮冗余 ✅
- preview-mask 桌面 display:none（768px+）
- SPAPreview 移除冗余 × 按钮（ESC+后退键已够）

## v1.14 topbar/bottombar 风格统一 + 状态机 bug ✅
- preview-bottombar padding/gap 与 topbar 对齐
- btnToggleRight/btnOutline 改为直接 toggle（不走 UIState）

## v1.15 topbar/bottombar 元素垂直居中 ✅
- .brand/.preview-topbar-title 统一 34px + flex 居中
- .preview-bottom-divider 高度改为 36px（与 btn 对齐）

## v1.16 index 移动端 button 28px + 上传 fixed bottom bar ✅
移动端：button 统一 28px、上传按钮改 fixed bottom bar（48px full-width）

## v1.17 preview.html mobile UX 4 项 ✅
SPAPreview label 删除、mobile 隐藏 4 个按钮、默认显示大纲不显示反馈、隐藏后内容正常展示

## v1.18 preview-mask 遮挡 topbar/bottombar ✅
preview-mask inset 改为 top:48px/bottom:48px（让出顶底栏）

## v1.19 mobile 全面回退到 desktop-only ✅
- 移除 ~1903 行 mobile 代码（6 文件），保留 desktop 友好修复
- 移动端不再维护，页面不崩但仅 desktop 体验
- commit: `0bac2da` + manual clean

## v1.20 README/PRD mobile 废弃标注 ✅
README 顶部加 desktop-only 提示、PRD 加平台支持字段

## v1.21 FD-SRT-0007 根因排查 ✅
- _wake_agent_for_root 添加 waking/wake success INFO 日志
- ?status=all 字面过滤 bug 修复（跳过 status=all 不过滤）

## v1.22 systemd unit PATH 修复 ✅
- systemd unit 加 Environment=PATH（含 ~/.npm-global/bin）
- wake 失败根因排除（之前 openclaw CLI 不在 PATH）
- service md5 新基线: disk 视图 `27c84dba886179a403f07c41f2bf12c7`

## v1.24-a feedback API 5 端点审计补全 ✅
5 端点（list/create/status/update/cleanup）加 logger.info 审计（双轨：journalctl + disk audit）

## v1.24-b UI 层防御：空白名字目录不渲染 ✅
renderSidebarTree 入口加前端 filter（仅过滤 name 为空白字符的目录项）

## v1.24-c 移除 disk audit，只保留 journalctl INFO ✅
disk audit 完全移除（强哥决策），journalctl 保留 5 端点全字段审计

## v1.25 ClawMate webhook wake 重构 ✅
- webhook 配置从 env 文件移至 config.json（openclaw 节）
- 删除独立 webhook_wake.py，功能并入 feedback_api
- 删除 audit logs、env 文件、hooks.mappings 旧条目
- cron_manager 精简（只保留 add_cron/run_cron）

## v1.26 config.py + store.py + cron-tick + 清理 ✅
- 新增 config.py（类型化 ConfigLoader + TTL 缓存）
- 新增 store.py（纯函数 FeedbackStore）
- feedback_api 重写（store.* 替代散装 json 读写）
- cron_template 重写、subtitle.py 死代码清理

## v1.27 排序修复 + GitHub Markdown CSS + markdown-it 迁移 ✅
- 排序 select/button 与 state 同步（默认 time 降序）
- GitHub Markdown CSS CDN 动态切换暗色/亮色
- marked → markdown-it（含 4 插件：container/emoji/footnote/task-lists）

## v1.28 移动端独立页面 m/index.html + m/preview.html ❌
- 标记为已完成但实际未创建，已被 v1.19 全面回退覆盖
- 移动端页面实际位于 dev/static/m/

## v1.29 Task Template 统一体系 ✅
- 创建 task_templates.json（6 个模板）
- task_runner.py 独立路由、subtitle 路由迁移
- Wake message data-driven（agent 零额外 API 调用）
- 前端按钮从 /api/config 动态渲染
- 老数据兼容（note 前缀匹配降级）
- commit: `051675f`

## v1.30 Position 格式标准化 + Task 体系加固 ✅
Position: Section/Line/Time/Range 格式统一
Task: schema 补全 action/scope/task_id 字段、note 优先保留不因模板丢失、前端 task_id 透传

## v1.31 窄屏布局清理 + Wake 通知改进 ✅
- 移除所有窄屏 @media 和抽屉覆盖，始终 3 列网格
- 移除 batch-process 端点
- Wake 全链路去重/冲突检测、HTTP 标记 in_progress、actions→task_id

## v1.32 Store 清理 + 文档工程化 ✅ (HEAD: e84b916)
- 移除死代码（_detect_position_prefix 等）、内存泄漏修复
- CLAWLIST/CHANGELOG/计划/笔记 移除 git 跟踪（本地管理）
- README 同步、Skill 更新（{base_url} 统一）

## v1.34 分享链接（新增功能）✅ (HEAD: d52ed2e)
- 后端：POST /api/clawmate/share/create 生成 24h 短链
- 分享页：/clawmate/share-view.html?token=*** 免登录只读预览
- 支持 Markdown/Mermaid/KaTeX/代码高亮/图片/音视频/Office
- 同一文件复用 token（仅更新有效期）
- token 存 share_links.json（与 config.json 同目录）
- 移动端底栏新增 ↗️ 分享按钮，弹出面板与大纲/反馈风格一致
- 分享页标题取自文件内容（Markdown 取 # heading）
- Auth 白名单：share-view.html + share API 免登录
- 桌面版不变

## v1.33 统一 task/run 入口 + 安全加固 + Mobile 同步 ✅ (HEAD: 5c18a91)
- task/run 统一唯一入口（selections 数组），删除 feedback_create
- wake_agent_for_root + cron-tick 迁至 task_runner
- store: _get_feedback_path 不自动创建目录
- 安全: 删除操作防根目录 + scope 约束提醒
- subtitle.py 合并至 subtitle_routes.py
- Mobile: 与 desktop API 对齐（/task/run、position 格式、tags 动态加载）
- Mobile: 100dvh 视图适配、当前窗口打开文件
