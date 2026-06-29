# Changelog

## v1.45 (2026-06-27)
### Agent Panel 后端切换
- badge 点击循环切换后端 claude→codex→openclaw，前后端联动（WS 传递 backend 参数）
- header 精简 — 移除 agent-panel-root 标签，保留 badge + title
- Ctrl+L 清屏 → 改为 clear 按钮（本地 term.clear() + PTY 发送 \x0c）
- 面板最大宽度 +100px（默认 700→800，拖拽 800→900）

### Agent 渲染实验与回退
- ansi-up DOM 渲染器 + 按钮切换双模式（DOM/xterm）→ 回退到纯 xterm 方案
- xterm CSS transform:scale 适配面板宽度 → 回退，保留其他修复

### xterm.js 可靠性
- 多屏适配：实测字符宽度 + COLUMNS/LINES 环境变量 + 移除 reset
- 统一 index 与 preview 的 agent panel 宽度限制
- panelTitleEl 显示会话名 + drag 适配 DOM 模式 + null 守卫

### Mermaid 弹窗缩放
- 缩放控件增加弹窗查看按钮（expand dialog □）
- 弹窗内支持缩放/拖拽，内容居中
- 弹窗内鼠标滚轮直接缩放（不需 Ctrl）
- expand 按钮复用 iconSVG() 生成，改为纯文本 □

### Mobile 完善
- 移动端面板 z-index 调整为 overlay7 < panel8 < topbar10
- 目录/大纲条目点击后自动关闭侧边面板
- html,body 锁定视口 overflow:hidden（对齐 preview）
- bfcache 恢复时自动刷新 + CSS/JS 版本号更新

### PWA + 主题 + 图片导航
- PWA 支持（manifest + Service Worker）+ Agent 文件上下文注入 + 无限滚动
- 主题防闪烁（data-theme 在 <head> 同步设置）
- 自动模式图标从 sun 改为 sun-moon（与浅色模式区分）
- 图片导航按钮固定视口位置 + isImageMode 扩展支持全部图片格式

### Docs
- README 截图全部重新截取 + 精简为两张（文件管理/预览+反馈）
- SKILL.md 模板去重 + 章节编号修正 + 版本号 bump 至 2.7.2

## v1.47 (2026-06-29)
### Preview &line=N 滚动 + 搜索清除 + 内容匹配面板 + 源码高亮修复
- Preview: `&line=N` 渲染模式下不再强制切换源码视图，滚动到最近标题段落（`_scrollRenderedMarkdownToLine`）
- Preview: HTML 文件切换源码/编辑模式内容空白（`srcPre.style.display` 未同步 3 处）
- Preview: Markdown 源码模式高亮修复（`textContent` 和 `code` 元素重复导致裸文本覆盖高亮）
- Search: 清除搜索按钮完整清理内容匹配状态（IIFE 猴子补丁移到事件绑定之前）
- 内容匹配面板: `cmd-file-header` 点击区域修复（spacer 替代 `flex:1` 链接，仅文件名打开预览）
- 内容匹配面板: chevron 箭头方向修正（展开↓ 收起→）

## v1.46 (2026-06-28)
### Agent Panel 空白修复（grid-column 错位）
- 根因：`.agent-panel` 无显式 grid-column，auto-placement 在 sidebar/resize-handle 都 `display:none` 时把面板放到第 2 列（1fr≈25px→4px）
- 修复：`.agent-panel { grid-column: 4; }` 始终占第 4 列（750px）
- `createTerminal()` 容器尺寸检测加固：`clientWidth < 50px` 时用 600px 回退（4px 是 truthy 会绕过 `||600`）
- CSS transition 动画期间跳过 `fitAddon.fit()`（`doFit()` 守卫），ResizeObserver/win-resize 统一走 `doFit()`
- `connectWs()` 优先用预估算的 `_agentInitCols` 而非可能缩水后的 `term.cols`

### OpenClaw 输入框提示
- placeholder 添加 `/clawmate project` 切换项目提示

### README 业务架构图
- 用 `flowchart LR` 业务架构图替换技术实现图（去掉文件名、协议、端口）
- 结构：入口（skill/API）→ 功能域（filesystem/project/feedback）→ 后端（openclaw/codex/claude）
- 明确功能域与后端是正交维度，连线表示主要侧重而非绑定

## v1.44 (2026-06-26)
### Codex Agent 后端
- 新增 Codex 作为第三 Agent 后端（与 claude/openclaw 并列）
- session key 格式重构为 `{backend}:{root}[:{project}]`，确保不同后端会话隔离
- `get_claude_session` → `get_agent_session`，自动遍历所有 PTY 后端查找活跃会话
- 新增 `max_sessions` 上限（默认 10）+ `agent.env` 环境变量透传
- 新增 `CLAWMATE_AGENT_BACKEND` 环境变量覆盖配置，`config.example.json` 同步更新

### 画廊卡片菜单重构
- 卡片操作从底部 card-actions 迁移到右上角 ⋯ 菜单按钮（Dropdown 浮层）
- 复选框移入 thumb 内部，使用自定义无依赖样式（appearance:none + 对勾 ::after）
- 移动端菜单按钮尺寸调大（26px 触摸目标），dropdown 最小宽度 130px
- 列表视图新增行内复制按钮（.list-copy-btn）

### 文件移动 + 目录选择器
- 新增 `POST /api/clawmate/move` 端点 + `service.move_file()` 实现
- 安全校验：禁止目录移入自身/子目录、目标同名冲突检测
- 前端：目录选择器 Modal（树形展开 + 导航 + 确认），画廊 ⋯ 菜单集成
- `icons.js` 新增 `move` 图标（十字箭头）

### 面板 translate 动画
- 左右面板隐藏改用 `translate` 替代 `width/opacity` 过渡（GPU 合成层加速）
- 统一 `.preview-left/.preview-right/.preview-agent-panel` 三处动画模式
- share-view TOC 面板同步改为 translate 动效，新增 `hideTocInstant()` 无动画即时隐藏

### xterm.js 流控（输入延迟修复后续）
- 接入 `onFlowControlPause/Resume`：写入缓冲超限时丢弃帧而非无限堆积
- 终端断连时 `term.blur()` 暂停光标闪烁定时器，避免后台消耗主线程
- 重连时主动 `unobserve → observe` 避免 Firefox `InvalidStateError`
- 面板关闭时断开 `ResizeObserver`，减少后台回调竞争

### 其他
- 面包屑新增刷新按钮（带旋转 CSS 动画）
- deps: +websockets>=12.0, -aiofiles
- `.gitignore` 增加 `.claude/` 本地 IDE 配置排除


## v1.43 (2026-06-25)
### Mermaid 高度手动调整
- 每个 mermaid 图表底部新增拖拽手柄，支持鼠标/触摸拖拽调整显示区域高度
- DOM 结构重构：`.mermaid-inner` 承载滚动内容，handle 和 zoom controls 固定在外层不动
- 使用 Pointer Events + `setPointerCapture` 确保拖拽不与 mermaid zoom/pan 冲突
- handle 样式：无边框，12px 高，88px 宽柔色 grip 指示条

### Agent 输入延迟修复
- xterm 输入从 30ms debounce 改为立即 flush，消除 PTY echo 延迟导致的输入不可见问题

## v1.42 (2026-06-24)
### 图标系统重构
- 新增彩色字母标签：Markdown(M紫)/Python(Py蓝)/Shell($绿)/JSON({}橙)/Text(T灰)/JS(黄)
- 通用代码文件使用 `file-code` SVG（`<>` 尖括号图标），区别于默认 `file`
- 图标尺寸参数化：画廊 32px / 列表 22px，字体和圆角按比例自动缩放
- `_tag()` 辅助函数统一彩色标签生成，消除重复代码

### 侧边栏隐藏 dotfiles
- 目录树过滤 `.` 开头的隐藏目录（`.git`/`.clawmate`/`.claude` 等不再显示）

### Feedback 存储迁移
- `feedback.json` 从项目根目录迁移到 `.clawmate/feedback.json`
- 读取严格依赖 `.clawmate/` marker，无 marker 目录报错而非静默回退
- `feedback_api.py` + `store.py` 同步更新路径

### 新 API 端点
- `GET /api/clawmate/link` — 一站式搜索 + 预览链接生成（q/root/ext/limit）
- `POST /api/clawmate/mkdir` — 在指定目录下创建子目录
- `GET /api/clawmate/list?marker_filter=true` — 只返回含 `.clawmate/` marker 的项目目录

### Agent 面板增强
- PTY 输出 60fps 分组刷新，防止输出交错
- 用户输入后短暂 yield 确保 echo 先于输出到达
- chdir 时同步 session key 到所有已连接 WebSocket

### Auth 增强
- `auth.local_hosts` 配置项，支持 LAN 主机名/IP 免登录（`config.json`）

## v1.41 (2026-06-23)
### 压缩包预览
- `list_archive()` 支持 zip / tar / tar.gz / tar.bz2 / tar.xz / rar / 7z
- 预览页树形展开压缩包内容，显示文件/目录数、压缩前后大小
- 加密压缩包提示、下载按钮

### 文件移动
- `POST /api/clawmate/move` — 同 root 内移动文件/目录

### 目录面板修复
- 切换 root 时侧边栏和面包屑现在正确刷新（缓存 key 改为 `rootId:dir` 组合）
- 面包屑「复制」→「复制目录」，复制内容从相对路径改为绝对路径

### Feedback 存储
- `feedback.json` → `.feedback.json`，默认隐藏
- 所有 root 下现有 feedback.json 已重命名

## v1.40 (2026-06-22)
### 响应式策略统一 — Agent 面板打开时渐进隐藏
- Agent 打开时 `body.agent-open`，CSS 断点自动匹配移动端策略：
  - ≤1500px：隐藏目录面板 → ≤1300px：隐藏 label + 按钮文字 + list type/size 列
- 通用断点合并：≤1000px 隐藏 label + 按钮文字
- 目录自动隐藏/显示同步按钮状态（`matchMedia` + `getComputedStyle`）
- 目录隐藏时 agent 面板宽度不变，main 自动扩展

### 列表视图优化
- 日期缩短为 `M/D HH:mm` 格式
- `minmax(0, 1fr) + max-content` 自适应列宽，不换行
- ≤700px 隐藏 size，≤520px 隐藏 type
- 面包屑后添加「复制」链接

### Agent 面板
- 最大宽度降至 680px，默认 45vw
- 打开/关闭幻灯片动画（`forceExpand` 防 race condition）
- Claude Code 反馈注入（`get_claude_session` + `inject_to_session`）
- 修复 `open()` grid 不展开 bug

### 移动端
- 目录按钮替代 hamburger，sidebar overlay 与 agent 统一 `top:48px`
- Topbar 始终单行（`flex-wrap: nowrap`），搜索自适应收缩
- 搜索按钮高度/圆角与 topbar 按钮统一

### 清理
- 移除 `_md_to_ansi` 死代码
- Markdown 暗色主题改用 `[data-theme="dark"]`
- 注释 preview.js 4 个 debug `console.log`
- xterm addon CDN 版本对齐 5.5.0

## v1.39 (2026-06-22)
### Agent 面板 — Claude Code + OpenClaw 双后端
- 右侧面板嵌入 AI Agent 终端，支持拖拽调整宽度（360–1100px）
- **Claude Code 后端**：Python PTY 直连，完整 CLI 体验（--dangerously-skip-permissions）
- **OpenClaw 后端**：WebSocket JSON 协议 → Markdown 聊天视图（markdown-it 渲染）
- 会话持久化：Claude Code 进程存活于 WebSocket 断开期间（10min idle 超时），重连回放输出缓冲
- Feedback 任务路由：Claude 活跃时注入 PTY，否则回退 OpenClaw gateway webhook

### 首页改进
- 目录切换按钮（顶栏 📁），桌面端切换左侧栏显隐，移动端浮层滑入
- 切换 root 时自动关闭 Agent 面板（session root 绑定）
- Agent 按钮放在主题按钮之前
- 移动端顶栏：搜索始终同行，品牌名隐藏，≤480px 搜索按钮仅图标
- 移动端工具栏：隐藏多选/画廊/列表文字、隐藏类型/排序标签
- 侧栏浮层和 Agent 面板统一 top:48px 高度

### 预览页改进
- 反馈面板拖拽调整宽度（260–700px）
- 文件点击新标签页打开（保护 Agent 会话）
- 底栏移除「返回」按钮
- 反馈卡片删除按钮风格统一

### 配置文件
- config.json / config.example.json 新增 `agent` 配置块
- docker-compose.yml 新增 `CLAWMATE_AGENT_BACKEND` 环境变量

### 修复
- Ctrl+C/V 在终端中行为正常（有选区时复制，Ctrl+V 粘贴）
- 不支持文件类型显示友好 fallback + 下载按钮
- uvicorn WebSocket ping 间隔 30s，超时 60s
- 移动端 main 宽度修复（grid-column 错位）
- agent panel slide-in/slide-out 动画
- output_buffer 按条目数限制（200条），防止内存泄漏
- chat.history 响应消费，聊天重连状态提示，流式自动滚屏

## v1.38 (2026-06-21)
### 性能优化
- KaTeX CSS 按需加载：仅含 `$`/`$$` 数学公式的 Markdown 才注入 KaTeX 样式
- 本地化 CSS 资源（github-markdown-dark、highlight.js），不再依赖外部 CDN
- Logo 图片压缩（PNG → SVG/WebP）
- `<script defer>` 加载所有脚本，CSS 独立文件并行下载
- Mermaid/KaTeX/highlight.js 懒加载：首屏不阻塞
- 目录列表内存缓存（30s TTL），减少重复 API 请求

### PDF 预览重构
- 自托管 pdf.js viewer（`/clawmate/pdfjs/`），完全脱离 CDN 依赖
- PDF 文件直接使用 pdf.js 渲染，不再经过 ONLYOFFICE 编辑器

### ONLYOFFICE 修复
- `toolbarNoTabs` 移除，解决 `indexPostfix=_loader` 导致的 JS 加载失败
- 最小化 UI：紧凑工具栏（无侧面板、无标尺、无右侧面板）
- 查看/编辑模式统一 minimal chrome
- `forcesave`/`goback`/`feedback` 等无效 customization key 移除
- `dataclass.get()` 替换为属性访问（兼容性修复）

### 首页改进
- 类型过滤 `<select>`：选中非"全部"时紫色高亮
- 480-768px 断点顶栏重排：搜索输入置于品牌与操作按钮之间
- ≤768px 仅显示 logo（隐藏 "ClawMate" 文字）

### 分享视图修复
- HTML 文件在 iframe 中渲染（与 preview 行为一致）
- 非 Markdown 文件自动隐藏左侧 TOC 大纲
- 添加关闭按钮（返回首页）

### 移动端修复
- 反馈面板：选中文本延迟复制+高亮（等待面板开启），关闭时清理

### 登录页修复
- 资源/CSS 使用相对路径加载，多 base URL 部署可移植

### 不支持文件类型的预览体验
- `.tar.gz`/`.rar`/`.exe` 等二进制文件显示友好 fallback 页面：文件图标 + 名称/类型/大小 + 下载按钮
- `<img>` 加载失败显示降级提示，而非浏览器默认破碎图标
- `<video>`/`<audio>` 加载失败显示编码/损坏提示

### 杂物
- `.gitignore` 新增 Playwright 临时文件

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
