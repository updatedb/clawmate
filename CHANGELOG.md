# Changelog

## v1.37 (2026-06-19)
### 反馈存储性能优化
- 内存读缓存：基于 mtime_ns 校验，分离 cache_lock 避免读写互斥，LRU 淘汰(256条上限)
- 过期清理：done/failed/deleted 超过 cleanup_done_after_days(默认30天)自动删除
- pending/in_progress 条目永不清理；threshold=0 禁用清理

### 工具栏样式统一
- .tb-left label/select/button 统一 padding:0 左缘对齐
- select/button bordered 元素 padding:0 14px 呼吸空间
- 全部 active 状态去辉光 box-shadow，统一 accent填充+白字
- outline:none 消除 focus ring 与 active 视觉冲突
- hover:not(.active) 避免 active 状态下 hover 变色无法阅读

## v1.36 (2026-06-19)
### 反馈系统全面修复
- **移动端**：新增 touchend 事件监听解决 selectionchange 不可靠；选中文本跨面板开启/关闭保留
- **移动端**：提交成功自动关闭底部面板并打开右侧反馈栏，状态轮询移至侧边栏(10s间隔)
- **桌面端**：提交成功立即关闭 tooltip/输入卡，右侧反馈栏自动弹出；错误内联显示
- **侧边栏轮询**：打开时每10秒自动刷新 pending/in_progress 条目状态
- **桌面端轮询**：提交后8秒间隔跟踪新提交ID直至完成(进度显示 ⏳ 反馈 X/Y)

### KaTeX 渲染修复
- 移除 \\(\\)/\\[\\] 分隔符 — JS字符串 \\( 经KaTeX regex处理后错误匹配了所有普通()
- 导致文档中所有括号内容被当作数学公式用KaTeX字体渲染

### 中英文混排字体
- .markdown-body 字体栈加入 Noto Sans SC，消除括号内中日韩+ASCII字符的字体割裂

## v1.35 (2026-06-18)
### 响应式统一 — 桌面/移动端合并
- 删除 m/ 目录（m/index.html, m/preview.html, m/style.css），main.py 移除 UA 重定向
- index.html：移动端自动切列表视图、隐藏多选、隐藏分类过滤、列表卡片布局
- preview.html：三列网格 → 移动端单列+侧栏浮层、底栏精简、选区浮动按钮+底部反馈面板
- share-view.html：重构为与 preview 一致的三列布局 + 顶栏📑/🌓 + asset 端点

### 顶栏 & 底栏
- 大纲按钮移至顶栏（📑 💬 🌓 🚪），与反馈/主题/登出并列
- 顶栏按钮 active 态紫色 accent 高亮 + 外发光，CSS 顺序修正 hover/active
- 移动端底栏隐藏路径/导出/下载/重命名/删除，保留返回/分享/动态按钮
- 移动端顶栏 brand 替换为 ← 返回按钮

### 编辑模式增强
- 大纲点击跳转支持编辑 textarea、源码 pre、渲染视图三种模式
- Ctrl/Cmd+S 快捷键保存
- 编辑窗口高度填满视口
- Banner 美化（圆角 badge + 快捷键提示）

### 排序 & 列表
- 排序从下拉框改为 pill 按钮（↓最新 / ↑名称 / ↓大小）
- 列表日期右对齐，移动端 icon 缩进对齐
- 搜索框高度与排序行统一（30/28/26px 三档）

### 分享
- share_routes.py 新增 /share/{token}/asset 端点（引用图片服务）
- 前端 markdown 图片路径重写 + onerror 兜底

### 反馈面板
- 默认关闭，操作后自动打开 + 同步 grid 列宽 + 按钮态
- 移动端右侧面板保持浮层（非底部 sheet）
- 新增底部反馈添加面板（选区→✏️→底部滑出→填备注→提交）

### 代码质量
- CSS 去重 + 删除 200+ 行无用样式（preview-body、feedback-tooltip 等）
- JS hljs → window.hljs 统一引用，移除 debug 日志
- preview.js / preview-common.js 模块化，移动端 JS 提取为独立文件
- 文件类型常量统一到 preview-common.js，parseCodeOutline/buildHeadingTOC 等共享
### 分享链接（新增功能）
- POST /api/clawmate/share/create 生成 24h 短链，同一文件复用 token
- /clawmate/share-view.html?token=*** 免登录只读预览
- 支持 Markdown/Mermaid/KaTeX/highlight.js /图片/音视频/Office
- share_links.json 与 config.json 同目录（磁盘持久化）
- Auth 白名单放行 share-view.html + share API（免登录）

### 移动端
- 底栏新增 ↗️ 分享按钮，弹出面板与大纲/反馈统一 m-panel 风格
- note 字段移除必填校验（与桌面版对齐）

### 后端修复
- 重命名 API 支持目录（此前仅支持文件）
- GitHub Actions docker.yml 构建上下文修复（context: ./dev → .）

### Skill
- clawmate project 统一更名为 init
- 新增 clawmate plan（规划/更新 CLAWLIST）
- 安全说明声明：数据不传第三方、仅本地操作、init/do 需用户确认
- 清理 cron/cron-tick 引用（已废弃）
- CLAWMATE_URL 配置化（用户自行配置）

## v1.33 (2026-06-08)
- task/run 统一为唯一入口（selections 数组，删除 feedback_create）
- wake_agent_for_root / cron-tick 迁至 task_runner
- feedback_create 删除
- store: _get_feedback_path 不自动创建目录（目录不存在则回退到 root，记录错误日志）
- store: 删除 if not text: continue（空内容不跳过）
- 安全: 删除操作防根目录（safe_rel 空值检查）+ _normalize_rel_path 拦截 "."
- 安全: wake message 附加 scope 范围约束提醒
- subtitle.py 合并到 subtitle_routes.py
- cron_template.txt 删除
- Mobile: submit 移至 /task/run（selections 格式）
- Mobile: fbInputTags 从 task_templates 动态加载
- Mobile: position 格式与 desktop 统一（Line/Page/Section 按文件类型）
- Mobile: Markdown 渲染模式 detectSectionFromDOM → Section #xxx
- Mobile: 100dvh 防止浏览器 chrome 遮盖
- Mobile: 点击文件在当前窗口打开
- UI: preview.html <430px 隐藏 preview-btn-group

## v1.32 (2026-06-08)
- Store 死代码清理（_detect_position_prefix 等）+ 内存泄漏修复
- feedback card 倒序排列、position 优先使用 item.position
- CLAWLIST/CHANGELOG/计划/笔记 移出 git 跟踪
- Skill 接口 URL 统一使用 {base_url}、README 同步

## v1.31 (2026-06-07)
- 移除所有窄屏 @media 和抽屉覆盖，保持 3 列网格
- 移除 batch-process 端点
- Wake 全链路去重/冲突检测、HTTP 标记 in_progress
- root/project 拼接到 message 首行、前端直接传 task_id
- 禁止文件内容被浏览器缓存

## v1.30 (2026-06-07)
- Position 格式标准化（Section/Line/Time/Range）
- Task 体系加固：schema 补全 action/scope/task_id，note 优先保留
- 移除未使用的 FeedbackTag、feedback.tags

## v1.29 (2026-06-07)
- Task Template 统一体系：task_templates.json + task_runner.py
- subtitle 路由独立，wake message data-driven（agent 零额外 API 调用）
- 前端标签从 /api/config 动态渲染

## v1.28 (2026-06-06)
- 移动端独立页面：m/index.html（目录浏览）+ m/preview.html（阅读+反馈）

## v1.27 (2026-06-06)
- 排序 select/button 与 state 同步
- GitHub Markdown CSS CDN 动态暗色/亮色切换
- marked → markdown-it（container/emoji/footnote/task-lists 插件）

## v1.26 (2026-06-06)
- config.py（类型化 ConfigLoader + TTL 缓存）+ store.py（纯函数 FeedbackStore）
- feedback_api 重写、cron_template 重写、subtitle.py 死代码清理

## v1.25 (2026-06-06)
- webhook 配置从 env 文件移至 config.json（openclaw 节）
- 删除独立 webhook_wake.py，cron_manager 精简
- 删除 hooks.mappings 旧条目 + env 文件 + 独立审计日志

## v1.3 (2026-06-06)
- preview.html 全类型预览统一（图片/音视频/Office/PDF/代码/Markdown）
- ONLYOFFICE 编辑模式 + JWT 安全集成
- 反馈面板、底部工具栏

## v1.24-c (2026-06-05)
- 移除 disk audit，仅保留 journalctl INFO（强哥决策）

## v1.24-b (2026-06-05)
- 前端过滤空白名目录（renderSidebarTree 入口 1 行 filter）

## v1.24-a (2026-06-05)
- feedback API 5 端点补全 logger.info 审计

## v1.22 (2026-06-05)
- systemd unit 加 Environment=PATH（含 ~/.npm-global/bin），修复 wake

## v1.21 (2026-06-05)
- _wake_agent_for_root 加 success/failure INFO 日志
- ?status=all 字面过滤 bug 修复

## v1.20 (2026-06-05)
- README/PRD 标记 desktop-only（v1.19 mobile 回退说明）

## v1.19 (2026-06-05)
- 全面回退 mobile（~1903 行代码移除），仅保留 desktop 友好修复

## v1.18 (2026-06-05)
- preview-mask inset 改为 top:48px/bottom:48px 让出顶底栏

## v1.17 (2026-06-05)
- mobile UX 4 项修复（SPAPreview label、按钮隐藏等）

## v1.16 (2026-06-05)
- 移动端 button 28px、上传按钮改 fixed bottom bar

## v1.15 (2026-06-05)
- topbar/bottombar 元素垂直居中统一

## v1.14 (2026-06-05)
- topbar/bottombar 风格统一 + 状态机 bug 修复

## v1.13 (2026-06-04)
- preview-mask 桌面 display:none、SPAPreview 冗余 × 按钮移除

## v1.12 (2026-06-04)
- CLAWMATE_PUBLIC_BASE_URL 启动检查

## v1.11 (2026-06-04)
- 移动端 13 项一次性修复（Mermaid 缩放、44px 触摸目标、上传、SPA 预览等）

## v1.10 (2026-06-04)
- 移动端 P0 4 项修复（Sheet、遮罩、safe-area、断点）

## v1.9 (2026-06-04)
- DELETE 操作写 audit log（JSONL）、本机 bypass 保留但记录 caller

## v1.8 (2026-06-04)
- 异常日志结构化、_load_config TTL 缓存
- feedback.json 归档（90 天 done → archive）

## v1.7.1 (2026-06-04)
- 图片导航计数器改为 "N / M" 格式

## v1.7 (2026-06-04)
- 图片预览上/下一张、feedback 标签配置化

## v1.6.1 (2026-06-04)
- constants.py 工程化收尾（5 个 env 常量、替换 10 处硬编码）

## v1.6 (2026-06-04)
- 架构重构（feedback 路由独立 + cron 管理独立 + validators）
- Auth 改进（localhost bypass + query string 保留）
- 字幕提取（faster-whisper）、媒体工具栏集成

## v1.5 (2026-06-04)
- clawmate.service.system 模板参数化（__VAR__ 占位符）
- 删除 install.sh，README 更新

## v1.4 (2026-06-04)
- 502 故障修复：部署 user-level systemd + nginx 配置确认
- 验证：内部/外部全 200，无副作用

## v1.3 (2026-06-01)
- 反馈增强 + 代码大纲 + 质量提升（详见主 CLAWLIST）

## v1.2 (2026-05-31)
- Feedback 重构 + Standalone 三栏布局

## v1.1 (2026-05-30)
- Slash Commands 增强 + Feedback Push Wake

## v1.0 (2026-05-30)
- UI 增强 + 完善 + PDF 降级

## v0.4 (2026-05-30)
- 批量反馈 + Daemon

## v0.3 (2026-05-30)
- 反馈闭环

## v0.2 (2026-05-30)
- Standalone 预览 + Skill

## v0.1 (2026-05-30)
- MVP
