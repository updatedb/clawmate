# Project Backend Preference and Root Isolation Design

## Goal

让 Agent panel 默认使用系统配置的 backend，并按 `rootId:project` 记住用户最后在每个项目中选择的 backend；切换项目或 root 时，只恢复当前 scope 的 backend 会话和内容，禁止跨 root 展示旧上下文。

## Scope and invariants

- 系统配置 `agentConfig.backend` 是项目首次使用时的默认值。
- 用户在 Agent panel 中切换 backend 后，立即保存到浏览器 `localStorage`。
- 偏好键必须同时包含 root 和 project；root 级目录使用稳定的 root scope 表示。
- 偏好只接受 `claude`、`codex`、`openclaw`，损坏、未知或无法解析的数据回退系统默认 backend。
- backend 切换仍复用现有服务端 session key：`backend:root:project`。
- root 或 project 变化时，必须销毁旧 WebSocket/terminal、清空旧聊天 DOM 和内存缓存，再打开新 scope。
- OpenClaw 的前端缓存 scope 必须包含 backend、root、project，不能把不同 backend 或 root 的消息混用。

## Architecture

在 `agent-panel-adapter.ts` 中增加小型的 backend preference helper，负责从 `localStorage` 读取、校验和保存 `{[scope]: backend}`。Adapter 在 `init()` 和 `updateRoot()` 中根据当前 scope 解析 backend；`setBackend()` 先更新当前 scope 的偏好，再按现有流程关闭旧连接并打开新 backend。

`updateRoot()` 处理 scope 迁移时，先保存旧 scope 的 OpenClaw 消息，捕获旧 scope key，然后更新 root/project/backend，清理所有旧 UI/transport 状态，最后只为新 scope 建立连接。PTY 内容不由前端复制，服务端依据 backend/root/project session key 恢复；OpenClaw 仅恢复新 scope 的缓存。

`app.js` 继续提供系统默认 backend，并在初始化时把 root/project 传给 Agent。不要把项目 backend 偏好写回系统配置，也不新增服务端 API。

## Data flow

1. `_initAgent()` 取得系统默认 backend，调用 adapter 初始化当前 root/project。
2. Adapter 使用 `rootId:project` 查找 localStorage 偏好；命中有效值则覆盖系统默认值，否则使用系统默认值。
3. 用户调用 `setBackend(next)`：保存当前 scope 的 `next`，关闭旧 transport，重新打开同一 root/project 的新 backend。
4. 用户切换 project/root：保存旧 scope 的缓存和 backend，完全清理旧面板状态，读取新 scope backend 并重连。
5. 页面刷新：localStorage 偏好被重新读取；没有该 scope 偏好时仍使用系统默认 backend。

## Root isolation rules

- scope 比较必须同时比较 `rootId` 和 project；不能只依赖当前 `dir` 或 DOM 状态。
- 任何 root 变化都视为硬隔离边界，即使新旧 project 名称相同，也必须清空并重建 Agent panel 状态。
- 清理旧 scope 时不能在 config 已更新后才计算旧 key；旧 key 必须在更新 config 前捕获。
- 恢复缓存前必须以当前 backend/root/project 生成新 scope key；旧 root 的消息不得渲染到当前面板。

## Testing

Frontend tests cover:

- first use falls back to system backend;
- valid project preference overrides system backend;
- switching backend persists the preference and reopening the project restores it;
- preference survives a new adapter instance through localStorage;
- malformed or unsupported localStorage data falls back safely;
- root changes clear terminal/chat state and do not restore the previous root's OpenClaw messages;
- same root with different projects remains isolated.

Existing backend/session tests remain the authority that backend/root/project session keys are distinct and reusable.

## Non-goals

- No server-side preference storage or new API.
- No migration of historical session logs.
- No change to the system-wide configured default backend.
- No frontend replay of PTY output beyond the existing server-side session recovery.
