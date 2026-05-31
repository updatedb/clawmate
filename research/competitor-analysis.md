# 竞品对比分析 — ClawMate

**日期**: 2026-05-29

---

## 一、竞品概览

| 维度 | **FileBrowser** | **Alist** | **ClawMate** |
|------|:--:|:--:|:--:|
| ⭐ GitHub | 27.1K | 48K+ | — |
| 语言/框架 | Go 单二进制 | Go + Solidjs | 待定（Python FastAPI + Vanilla JS（继承自 openmedia）） |
| 定位 | 个人网盘 | 多云盘聚合 | OpenClaw 伴侣 |
| 项目状态 | ⚠️ 维护模式（停止新功能） | 🟢 活跃开发 | 🆕 新项目 |
| 部署 | 单二进制 | Docker + 二进制 | Docker + Daemon |
| License | Apache 2.0 | AGPL 3.0 | 待定 |

---

## 二、功能矩阵对比

### 2.1 文件管理

| 功能 | FileBrowser | Alist | ClawMate（目标） |
|------|:--:|:--:|:--:|
| 目录浏览 | ✅ | ✅ | ✅（继承自 openmedia） |
| 画廊/列表双视图 | ✅ | ✅ | ✅（已有） |
| 按类型过滤 | ❌ | ❌ | ✅（已有） |
| 搜索（递归） | ✅ | ✅ | ✅（已有） |
| 上传 | ✅ | ✅ | ✅（基础已有） |
| 删除 | ✅ | ✅ | ✅（已有） |
| 下载 | ✅ | ✅ | ✅（已有） |
| 打包下载 | ❌ | ✅ | ✅（已有） |
| 复制路径到剪贴板 | ❌ | ✅ | ✅（已有） |
| 多选批量操作 | ❌ | ❌ | 🎯 P1 新增 |
| 导出 | ❌ | ✅ | ✅（已有） |
| 排序（名称/时间/大小） | ✅ | ✅ | ✅（已有） |

### 2.2 文件预览

| 功能 | FileBrowser | Alist | ClawMate（目标） |
|------|:--:|:--:|:--:|
| Markdown 渲染 | 基础 | ✅ | ✅ **增强**（已有） |
| └ Mermaid 图表 | ❌ | ❌ | ✅ **独有** |
| └ KaTeX 数学公式 | ❌ | ❌ | ✅ **独有** |
| └ 代码语法高亮 | ❌ | ✅ | ✅ **增强**（highlight.js） |
| 图片预览 | ✅ | ✅ | ✅（已有） |
| 音视频预览 | ✅ | ✅ | ✅（已有） |
| Office 文档预览 | ❌ | ✅ (docx/xlsx/pptx) | ✅ **ONLYOFFICE**（已有 JWT 安全） |
| PDF 预览 | ✅ | ✅ | ✅（ONLYOFFICE） |
| JSON/XML/GPX/KML 文本 | ❌ | ✅ | ✅（已有） |
| Office 文件在线协作 | ❌ | ❌ | ❌（view-only，不计划） |

### 2.3 安全与权限

| 功能 | FileBrowser | Alist | ClawMate（目标） |
|------|:--:|:--:|:--:|
| 用户登录系统 | ✅ | ✅ | ❌ 默认无（本地优先） |
| 密码保护 | ✅ | ✅ | Basic Auth（Nginx 层） |
| **根目录白名单** | ❌ | ❌ | ✅ **独有**（openmedia 核心） |
| 路径 sanitize 防越权 | ❌ | ❌ | ✅ 已验证 |
| JWT 安全（ONLYOFFICE） | N/A | N/A | ✅ |
| 单目录限定 | ✅ 基础 | ❌ | ✅ 多 root 可选 |

### 2.4 生态集成

| 功能 | FileBrowser | Alist | ClawMate（目标） |
|------|:--:|:--:|:--:|
| WebDAV | ❌ | ✅ | ❌ |
| 多云存储后端 | ❌ | 30+ | ❌ 仅本地 |
| OpenClaw 工具集成 | ❌ | ❌ | 🎯 **核心差异化** |
| OpenClaw 内预览 | ❌ | ❌ | 🎯 embed 嵌入 |
| Agent 产出即时评审 | ❌ | ❌ | 🎯 独特价值 |
| API 供外部调用 | ❌ | ✅ | 🎯 REST API |

---

## 三、关键发现

### FileBrowser 的致命缺陷

1. **维护模式** — 2026年3月起停止新功能开发，作者本人发文声明
2. **无 Mermaid/KaTeX** — Agent 产出中大量 Mermaid 流程图、数学公式无法渲染
3. **无 ONLYOFFICE** — Office 文件只能下载无法预览
4. **无批量操作** — 逐一操作文件，效率低

### Alist 的错位

1. **太「重」** — 核心价值是 30+ 云盘聚合，对纯本地文件管理是杀鸡用牛刀
2. **非 OpenClaw 生态** — 不感知 OpenClaw 的 agent-workflow 需求
3. **无 Mermaid 渲染** — 对 agent 生成的流程图无能为力
4. **AGPL 3.0** — 若需修改嵌入，许可证约束较严格

### ClawMate 的差异化价值

```
FileBrowser:   "任何人在任何地方运行的文件浏览器"  → 通用个人网盘
Alist:         "连接所有云存储的文件列表程序"      → 云盘聚合器
ClawMate:      "OpenClaw 的必备文件伴侣"           → Agent 工作流加速器
```

**核心差异不在文件管理本身，而在 Agent 工作流闭环**：

```
没有 ClawMate:
  Agent 产出 → 用户看聊天窗口 → 复制粘贴到编辑器 → 修改 → 发给 Agent → 循环
  （文件在哪？版本乱不乱？怎么批量改？）

有 ClawMate:
  Agent 产出 → ClawMate 自动可见 → 用户直接预览（Mermaid/KaTeX/代码高亮）
  → 多选文件 → 一键引用告诉 Agent 需要优化什么 → Agent 改完 → 即时对比
```
  
---

## 四、结论

**ClawMate 的合理性和必要性明确**：

1. FileBrowser 已死（维护模式），无法跟随 agent 时代需求
2. Alist 方向不同（云盘聚合），且缺少 agent 产出文件的核心预览能力（Mermaid/KaTeX）
3. openmedia 已有 80% 的核心能力沉淀，ClawMate 是自然演进而非重复造轮子
4. 「Agent 工作流加速器」的定位是空白市场 — 目前没有任何工具专为 AI agent 的输入输出管理而设计
