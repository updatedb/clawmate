# ClawMate 🦞

> Agent 产出的每一个文件，点击即预览，选中即反馈。

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## 📸 核心工作流

```mermaid
flowchart LR
    A[Agent 产出文件] -->|写入目录| B[用户点击预览链接]
    B --> C[preview.html 全屏渲染<br>Mermaid / KaTeX / Office / 视频]
    C --> D{发现问题?}
    D -->|是| E[选中文本 → 浮层弹出<br>填备注 → ✅ 提交]
    E --> F[写入 FEEDBACK.md<br>Push Wake 唤醒 Agent]
    F --> G[Agent 读取反馈<br>精确定位选区 → 修改文件]
    G --> H[更新 Feedback 状态<br>done / failed]
    H --> B
    D -->|否| I[完成]
```

### 选中反馈操作流

| Step 1: 选中文本 | Step 2: 填写备注 | Step 3: 提交完成 |
|:---:|:---:|:---:|
| 在预览页选中任意文本<br>浮层自动弹出 | 在 textarea 中输入修改建议<br>可累积多条反馈 | 一键批量提交到 FEEDBACK.md<br>Agent 即时被唤醒处理 |

| 文件浏览 | Markdown 预览 |
|:---:|:---:|
| ![File Browser](assets/screenshot-browser.png) | ![Markdown Preview](assets/screenshot-preview.png) |

---

## 我们解决了什么问题？

在 AI Agent 工作流中，Agent 每天产出大量文件 — Markdown、Mermaid 图表、Office 文档、代码、音视频。但「看一眼结果 → 指出问题 → 让 Agent 修改」这个最自然的反馈循环，一直被截断：

| 环节 | 传统方式 | ClawMate |
|------|---------|----------|
| 预览 | 下载 → 本地打开 | **点击即渲染**，Mermaid/KaTeX/Office 一键预览 |
| 反馈 | 截图 → 打字描述位置 | **选中文本 → 填备注 → 提交**，3 秒完成 |
| 修改 | Agent 盲猜用户意图 | **精准位置 + 选区内容直送 Agent**，零歧义 |
| 循环 | 反复切换工具 | **preview → feedback → agent → 修改 → 再预览** 全在一屏 |

---

## 核心能力

### 📂 文件管理
- 多项目白名单目录，浏览器直接管理
- 画廊/列表双视图，类型过滤、排序、搜索
- 批量打包下载、拖拽上传、删除确认

### 🔍 预览引擎
- **Markdown**：Mermaid 图表 + KaTeX 公式 + 代码语法高亮 + 大纲导航
- **HTML**：独立渲染预览 + 实时编辑，与 Markdown 并列为 Agent 产出两大核心格式
- **Office**：ONLYOFFICE 浏览/编辑双模式，编辑自动回写保存
- **PDF**：ONLYOFFICE 优先，自动降级 pdf.js
- **音视频**：内嵌播放器 + SRT 字幕面板，自动解析字幕文件，支持时间轴同步、字幕内容浏览与编辑改进
- **代码/文本**：JSON/XML/GPX/KML 语法高亮 + 编辑模式
- **图片**：全屏渲染 + 工具栏

### 💬 反馈闭环 🔑 核心差异化

这是 ClawMate 与其他文件管理器**最根本的区别**。不只是预览文件，而是将用户的每一个反馈精确送达 Agent，形成闭环修改链路。

**完整的反馈生命周期**：

```mermaid
stateDiagram
    [*] --> 选中文本
    选中文本 --> 浮层弹出: mouseup 事件
    浮层弹出 --> 累计反馈: 填写备注 → 加入 panel
    累计反馈 --> 提交: ✅ 一键批量 POST
    提交 --> pending: 写入 FEEDBACK.md
    pending --> in_progress: Agent 开始处理
    in_progress --> done: 修改完成
    in_progress --> failed: 无法处理
    done --> [*]
    failed --> [*]
```

**关键能力**：
- **选中文本 → 3 秒反馈**：在 preview.html 中选中文本，浮层自动弹出，填备注即可提交
- **精确选区定位**：选区内容 + 文件路径直达 Agent，零歧义，不用「第几段第几行」描述
- **批量累积**：可连续选中多个位置，统一提交，不用反复切换
- **FEEDBACK.md 托管**：所有反馈持久化在项目文件中，可追溯、可检索
- **Push Wake 即时唤醒**：提交后 Agent 立即被唤醒处理，不等待定时轮询
- **四态流转**：pending → in_progress → done/failed，每步状态可查
- **心跳 cron 自动处理**：即使 Push Wake 失败，5 分钟定时检查不会遗漏

**FEEDBACK.md 格式**：
```markdown
- [待处理] #FD-CM-004
  - 用户备注：突出这部分功能，这是核心
  - 文件: clawmate/README.md
  - 选区内容: "💬 反馈闭环\n选中文本..."
  - 更新: 2026-06-01 12:51:37
```

**Agent 处理流程**：
```
心跳/cron 检查 → GET /feedback/status → pending > 0
→ 读取 FEEDBACK.md → 解析每条 pending feedback
→ 读文件 → 定位选区 → AI 理解备注 → 修改 → /feedback/update done
→ 无法处理 → /feedback/update failed
```

### 🔗 OpenClaw 融合
- `/clawmate preview` — 生成直达 preview.html 链接
- `/clawmate feedback` — 提交反馈并唤醒 Agent
- `/clawmate todo` — 查看待处理反馈
- `/clawmate do` — 自动执行反馈

### 🚀 部署
- curl 一行命令本地启动，与 OpenClaw 同主机运行
- Systemd Daemon 安装，开机自启
- GitHub Actions CI 自动构建发布

---

## 与竞品的差异

| | FileBrowser | Alist | **ClawMate** |
|---|:---:|:---:|:---:|
| Mermaid 图表渲染 | ❌ | ❌ | ✅ |
| KaTeX 公式渲染 | ❌ | ❌ | ✅ |
| ONLYOFFICE 编辑 | ❌ | ❌ | ✅ |
| 音视频 + SRT | ❌ | ❌ | ✅ |
| Agent 工作流集成 | ❌ | ❌ | ✅ |
| 选中反馈闭环 | ❌ | ❌ | ✅ |
| 维护状态 | 已停更 | 活跃 | 活跃开发中 |
| 许可证 | Apache 2.0 | AGPL 3.0 | MIT |

---

## 技术栈

| 层 | 选型 |
|----|------|
| 后端 | FastAPI (Python)，1134 行 |
| 前端 | Vanilla JS + CSS，14万行预览引擎 + 9.5万行业务逻辑 |
| Markdown | marked + highlight.js + mermaid v11 + KaTeX |
| Office | ONLYOFFICE Document Server，JWT HS256 安全集成 |
| 部署 | curl 本地启动 + Systemd Daemon + GitHub Actions |

---

## 快速开始

```bash
# 1. 准备配置
cp config.example.json config.json
# 编辑 config.json，填入你的目录路径

# 2. 安装依赖并启动
pip install -r requirements.txt
python3 server.py &

# 3. 或使用 curl 一键启动（配合 systemd daemon）
# 详见下方部署章节
```

打开 `http://localhost:5533/clawmate/`，选择项目目录，点击文件即可预览。

> **注意**：ClawMate 依赖与 OpenClaw 在同一主机上运行（通过 system event 唤醒 Agent）。Docker 部署方案暂未提供，当前仅支持本地直接启动。

---

## 产品状态

| 维度 | 状态 |
|------|:--:|
| 核心文件管理 | ✅ v1.0 |
| 预览引擎（Markdown/Office/音视频/代码） | ✅ v1.3 |
| ONLYOFFICE 编辑链路 | ✅ v1.3 |
| 反馈闭环（选中→提交→Agent处理） | ✅ v1.3 |
| Daemon 部署 | ✅ |
| Slash Commands 集成 | ✅ v1.1 |
| 移动端响应式 | ✅ v1.2 |

---

*ClawMate — 让 Agent 的输出不再是一次性的，而是可以不断打磨的作品。*
