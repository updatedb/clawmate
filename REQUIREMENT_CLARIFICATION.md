# 需求澄清记录 — ClawMate

**澄清日期**: 2026-05-29
**项目类型**: 研发需求

## 1. 目的

构建独立可部署的文件管理服务 ClawMate（龙虾伴侣），支持 Docker/Daemon 双形态部署，提供白名单目录文件管理 + 多格式文件预览，并与 OpenClaw/Hermes 深度融合，成为 OpenClaw 的必备功能扩展。

## 2. 服务对象

### 产品用户
- **OpenClaw / Hermes 用户**：包括强哥本人及团队
- **核心痛点**：
  1. 飞书等外部 IM 作为文件管理后端，存在格式转换、权限管理、用户限制等瓶颈
  2. 需要一个更直接的工具来管理 OpenClaw 的输入（上传素材）和输出（agent 产出）
  3. 大量文件上传时附件管理不方便
  4. 直接的文件 CRUD 操作比通过 agent 更快
  5. Agent 产出需要大规模、快速的评审和反馈，需要比 agent 对话更高效的路径

### 项目管理人员
- **强哥**：负责决策、方向把控、最终验收

### 汇报对象
- 纯自用/内部工具项目，无外部汇报对象

## 3. 输出物

| # | 输出物 | 说明 |
|---|--------|------|
| 1 | **Docker Image** | 一键部署的容器镜像 |
| 2 | **Daemon 安装包** | 系统级服务的安装方式 |
| 3 | **REST API** | 文件 CRUD + 预览，供 OpenClaw Skill/CLI 调用 |
| 4 | **Web 前端** | 全新构建，提升美观性和操作便捷性 |
| 5 | **OpenClaw Skill** | clawmate 工具集成（按需） |
| 6 | **CLI 工具** | 命令行管理接口（按需） |

**部署约束**：
- 默认仅本地使用（localhost）
- 通过 Docker 端口映射 + Nginx 可对外暴露，配合 basic auth 提供基础权限管理

## 4. 评价标准

| 维度 | 标准 |
|------|------|
| **部署便捷性** | 会使用 Docker 的用户可在 5 分钟内完成搭建 |
| **集成无缝性** | 与 OpenClaw、ONLYOFFICE 无间配合，文件预览在 OpenClaw 内直接可用 |
| **功能完整度** | 现有功能（分类、过滤、删除、下载、复制、导出、复制路径）全覆盖 |
| **预览能力** | Markdown/XML/Text/HTML/Bash 等 agent 生成常见文件 + Office 文件（ONLYOFFICE）均可预览 |
| **操作效率** | 批量选择、一键操作，比 agent 对话更快 |

## 5. 工作范围

- **需要开发**: 是
  - 后端服务（Go/Node/Python）
  - 前端界面（全新构建）
  - Docker 构建 + Daemon 安装
  - OpenClaw Skill（按需）
- **需要测试**: 是
  - 功能回归（现有功能全覆盖）
  - 部署测试（Docker + Daemon）
  - 集成测试（OpenClaw + ONLYOFFICE）
- **涉及 Skill/技术栈**: 现有代码基、Docker、systemd、REST API 设计、前端增强
