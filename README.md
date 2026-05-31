# ClawMate 龙虾伴侣 — 产品介绍与宣传（v1.3）

> 基于当前产品功能，自动生成。版本：2026-06-01

---

## 一句话定位

**Agent 产出的每一个文件，点击即预览，选中即反馈。** ClawMate 是 OpenClaw Agent 工作流的文件层闭环加速器。

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
- **Office**：ONLYOFFICE 浏览/编辑双模式，编辑自动回写保存
- **PDF**：ONLYOFFICE 优先，自动降级 pdf.js
- **音视频**：内嵌播放器 + SRT 字幕面板
- **代码/文本**：JSON/XML/GPX/KML/HTML 语法高亮 + 编辑模式
- **图片**：全屏渲染 + 工具栏

### 💬 反馈闭环
- 选中文本 → 弹出浮层 → 填备注 → 「加入待办」或「立刻执行」
- 批量累积 + 一键提交 → FEEDBACK.md 托管
- Push Wake 即时唤醒 Agent → Agent 处理 → 状态流转

### 🔗 OpenClaw 融合
- `/clawmate preview` — 生成直达 preview.html 链接
- `/clawmate feedback` — 提交反馈并唤醒 Agent
- `/clawmate todo` — 查看待处理反馈
- `/clawmate do` — 自动执行反馈

### 🚀 部署
- Docker 一行启动，多架构支持（x86_64 + ARM64）
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
| 部署 | Docker 多架构 + Systemd Daemon + GitHub Actions |

---

## 快速开始

```bash
# Docker
docker run -d -p 5533:5533 \
  -v /path/to/config.json:/app/config.json \
  -v /your/projects:/data \
  clawmate

# Daemon
curl -fsSL https://raw.githubusercontent.com/.../install.sh | bash
```

打开 `http://localhost:5533/clawmate/`，选择项目目录，点击文件即可预览。

---

## 产品状态

| 维度 | 状态 |
|------|:--:|
| 核心文件管理 | ✅ v1.0 |
| 预览引擎（Markdown/Office/音视频/代码） | ✅ v1.3 |
| ONLYOFFICE 编辑链路 | ✅ v1.3 |
| 反馈闭环（选中→提交→Agent处理） | ✅ v1.3 |
| Docker + Daemon 部署 | ✅ |
| Slash Commands 集成 | ✅ v1.1 |
| 移动端响应式 | ✅ v1.2 |

---

*ClawMate — 让 Agent 的输出不再是一次性的，而是可以不断打磨的作品。*
