# Docker 启动时安装 Claude/Codex CLI 设计

## 目标

ClawMate 容器启动时默认确保 `claude`（Claude Code CLI）和 `codex`（OpenAI Codex CLI）可执行。安装完成后继续启动现有 FastAPI 服务，使终端面板可以直接使用两个 PTY 后端。

## 方案

在 runtime 镜像中提供 Node.js/npm，并新增容器入口脚本。入口脚本按以下顺序执行：

1. 若 `CLAWMATE_INSTALL_AGENT_CLIS=0`，跳过 CLI 安装。
2. 分别检查 `claude` 和 `codex` 是否已存在。
3. 对缺失的命令执行全局 npm 安装：
   - `@anthropic-ai/claude-code`
   - `@openai/codex`
4. 任一安装失败立即退出，并保留 npm 错误输出。
5. 执行原有 `python -u main.py` 服务入口。

安装逻辑保持幂等：已有命令不会重复安装；每次新建容器仍会自动补齐缺失 CLI。默认开启，关闭开关用于离线或仅运行文件浏览服务的部署。

## 运行时影响

首次启动需要容器能够访问 npm registry，且启动时间会增加。CLI 包及其依赖保留在容器层中，不写入宿主机数据卷。认证仍由 Claude/Codex CLI 自身的环境变量或用户配置负责，本次不新增凭据处理。

## 验证

- Python 测试验证 Dockerfile 和入口脚本声明两个 npm 包、默认开启开关，并保留 FastAPI 启动命令。
- Shell 级检查验证入口脚本在 CLI 已存在时跳过安装，在缺失或安装失败时返回非零状态。
- Docker 构建验证 runtime 镜像包含 Node/npm；容器启动日志显示 CLI 检查/安装后进入 FastAPI 服务。

