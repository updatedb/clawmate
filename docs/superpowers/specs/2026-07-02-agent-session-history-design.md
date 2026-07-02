# Agent 会话历史持久化与搜索 — 设计文档

> 2026-07-02 | Status: Draft

## Context

当前 ClawMate Agent 面板（xterm.js + PTY）的所有会话输出完全基于内存：
`_AgentSession.output_buffer` 是一个 `deque(maxlen=200)` 的 ring buffer。会话一旦被 idle reaper
杀掉或服务重启，全部输出丢失，无法查询、搜索或回放过去的会话。

**目标**：自动录制所有 Claude/Codex 会话输出到磁盘，提供历史会话浏览器（按日期分组列表、
全文搜索、回放查看），并带 TTL 自动清理。

## 存储结构

日志存放在项目目录下的 `.clawmate/sessions/` 中，按根目录（root）/项目（project）分组：

```
{root_dir}/{project}/.clawmate/sessions/
├── index.json                            ← 全局索引
├── claude_webprojects_clawmate_20260702_143000.meta.json  ← 会话元数据
├── claude_webprojects_clawmate_20260702_143000.ansi.log   ← 原始 ANSI 输出
├── claude_webprojects_clawmate_20260702_143000.text.log   ← 剥离 ANSI 的纯文本
└── claude_webprojects_clawmate_20260702_153000.ansi.log   ← 另一个会话
```

**路径推导**：从 session key `{backend}:{root}:{project}` 推导：
- `root_dir` → config.json 中 `roots[{root}].dir`
- `project` → session key 中的 project 段
- 日志路径 → `{root_dir}/{project}/.clawmate/sessions/`

**文件名格式**：`{backend}_{root}_{project}_{YYYYMMDD}_{HHMMSS}`（URL/filesystem safe）

## 数据文件

### index.json

顶层索引，加载时读取到内存，变更时原子更新：

```json
{
  "version": 1,
  "sessions": [
    {
      "id": "claude_webprojects_clawmate_20260702_143000",
      "key": "claude:webprojects:clawmate",
      "backend": "claude",
      "root": "webprojects",
      "project": "clawmate",
      "started_at": 1719900000.0,
      "last_active": 1719903600.0,
      "ended_at": 1719907200.0,
      "title": "重构数据库模型",
      "ansi_size": 2487291,
      "text_size": 1823450,
      "status": "ended"
    }
  ]
}
```

`title` 字段：从 `.text.log` 前几行自动提取的会话摘要（首个非空行，截断到 60 字符）。

### meta.json（每会话一个）

```json
{
  "session_id": "claude_webprojects_clawmate_20260702_143000",
  "key": "claude:webprojects:clawmate",
  "backend": "claude",
  "cwd": "/home/openclaw/webprojects/clawmate",
  "started_at": 1719900000.0,
  "last_active": 1719903600.0,
  "ended_at": 1719907200.0,
  "status": "ended",
  "close_reason": "idle_reaper"
}
```

### .ansi.log

UTF-8 编码的原始 PTY 输出（包含 ANSI 转义序列），直接追加写入，无分隔符。
用于回放时写入 xterm 还原完整终端输出。

### .text.log

每行格式：`[+MM:SS] {纯文本行}`

```
[+00:00] $ claude
[+00:01] ── 分析项目结构 ──
[+00:02] 正在扫描 dev/ 目录...
[+00:05] 发现 12 个 Python 文件, 3 个 JS 文件
[+00:12] ── 开始重构 ──
[+00:15] $ git add -A
```

时间戳为从会话开始经过的相对时间（`+MM:SS`），便于在列表中快速定位。

## 后端改动

### 新增文件：`dev/session_logger.py`

两个核心类：

#### `SessionLogger`

| 方法 | 说明 |
|------|------|
| `__init__(session_id, meta, log_dir)` | 创建文件句柄，写入 meta.json |
| `write(data: str)` | 写入 `.ansi.log` + 剥离 ANSI 写入 `.text.log` |
| `flush()` | 强制刷写到磁盘 |
| `close(status="ended")` | 更新 meta.json 的 `ended_at`/`status`，关闭句柄 |
| `get_title() -> str` | 从 `.text.log` 提取会话标题 |

#### `SessionIndex`

| 方法 | 说明 |
|------|------|
| `load(log_dir) -> list` | 加载 `index.json` |
| `save(log_dir, sessions)` | 原子写入 `index.json` |
| `add(log_dir, entry)` | 添加新会话条目 |
| `update(log_dir, session_id, updates)` | 更新指定条目字段 |
| `remove(log_dir, session_id)` | 删除条目 |
| `reap(log_dir, ttl_hours)` | 清理过期会话 |

**TTL 清理**：`reap()` 遍历 index，`last_active < now - ttl_hours` 则删除该会话的
所有文件（`.meta.json`、`.ansi.log`、`.text.log`）并从 index 移除。

### 修改文件：`dev/agent_routes.py`

| 位置 | 改动 |
|------|------|
| `_AgentSession` dataclass | 新增 `logger: Optional[SessionLogger] = None` |
| `_spawn_pt()` / session 创建 | 初始化 `SessionLogger`，写入 meta |
| `pty_to_ws()` | `os.read()` 后调用 `sess.logger.write(data)` |
| `_cleanup_dead_sessions()` | 调用 `sess.logger.close("ended")` |
| `_idle_reaper()` | kill session 前调用 `sess.logger.close("killed")`；末尾调用 `SessionIndex.reap()` |
| WebSocket 连接建立 | 恢复已有 session 时，检查是否需要重新打开 logger |

### 新增 API

挂载在 `agent_routes.py` 的 router 上：

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/clawmate/agent/sessions` | GET | 列出会话（支持 `?root=&project=&backend=&status=` 过滤）。从 index.json 读取 |
| `/api/clawmate/agent/sessions/{session_id}` | GET | 返回单条会话元数据 + 内容摘要（开头 20 行 + 结尾 20 行） |
| `/api/clawmate/agent/sessions/{session_id}/log` | GET | 返回日志内容。`?format=text`（纯文本，默认）或 `?format=ansi`（原始 ANSI）。支持 `?offset=&limit=` 分页 |
| `/api/clawmate/agent/sessions/search` | GET | 搜索。`?q=关键词&root=&project=&backend=`。在 `.text.log` 中逐行搜索，返回匹配的会话 + 行号 + 上下文片段 |
| `/api/clawmate/agent/sessions/{session_id}` | DELETE | 删除指定会话（删文件 + 更新 index） |

### 修改文件：`dev/config.py`

```python
@dataclass
class AgentConfig:
    ...
    session_log_ttl_hours: int = 168   # 默认 7 天
```

## 前端改动

### 修改文件：`dev/static/js/agent.js`

**1. Agent 面板 header 新增按钮**

```html
<button class="agent-sessions-btn" title="历史会话">📋</button>
```

点击后切换面板内容到会话历史视图。

**2. 会话历史视图**

布局：

```
┌──────────────────────────────────────┐
│ 历史会话               project名  × │
├──────────────────────────────────────┤
│ 🔍 搜索会话...                      │
├──────────────────────────────────────┤
│ 今天                                 │
│ # 重构数据库模型          10:00-10:12│
│   代码审查反馈处理，修改了 service...      │
│ # 优化图片预览          09:15-09:17  │
│   添加懒加载、缩略图缓存、WebP...          │
│ 昨天                                 │
│ # 修复搜索模块乱码      14:30-14:37 │
│   search_routes.py 编码处理...           │
│ # 添加用户认证模块      11:00-11:45 │
│   session + JWT 双方案...                │
├──────────────────────────────────────┤
│ [上一页]                  1/3 [下一页] │
└──────────────────────────────────────┘
```

- 按日期分组（今天/昨天/更早）
- 每行：标题（自动摘要）+ 起止时间 + 时长 + 首发行内容预览
- 点击行展开/收起活动会话详情
- 双击行或点击「查看」进入完整查看模式

**3. 会话查看模式**

```
┌──────────────────────────────────────┐
│ ← 返回列表    纯文本/ANSI回放  ⋮    │
├──────────────────────────────────────┤
│ [+00:00] $ claude                    │
│ [+00:01] ── 分析项目结构 ──         │
│ [+00:02] 正在扫描 dev/ 目录...       │
│ [+00:05] 发现 12 个 Python 文件     │
│ [+00:12] ── 开始重构 ──            │
│ [+00:15] $ git add -A               │
│ ...                                  │
├──────────────────────────────────────┤
│ 🔍 在本次会话中搜索...              │
└──────────────────────────────────────┘
```

- **纯文本模式**（默认）：加载 `.text.log`，在 `<pre>` 区域展示，浏览器 `Ctrl+F` 可用
- **ANSI 回放模式**：加载 `.ansi.log`，快速写入 xterm 实例（分离的、只读的 xterm，不与活跃会话共用）
- 会话内搜索框：前端过滤当前显示的文本行

**4. 状态管理**

```javascript
// Agent 模块新增状态
var agentState = {
  view: 'terminal',         // 'terminal' | 'history' | 'session-view'
  historySessions: [],      // 缓存的会话列表
  currentSessionId: null,    // 当前查看的会话 ID
  historyPage: 0,
  historyQuery: '',
};
```

### 修改文件：`dev/static/css/style.css`

新增样式：

- `.agent-sessions-view` — 历史会话容器
- `.agent-session-group` — 日期分组 header
- `.agent-session-item` — 每行会话
- `.agent-session-viewer` — 会话内容查看容器
- `.agent-session-search` — 会话内搜索框

## TTL 清理机制

在 `_idle_reaper()` 中集成（每 60 秒运行一次）：

```
_idle_reaper():
    1. 原有的 session 过期 kill 逻辑（不变）
    2. 新增：遍历所有已知 project 的 .clawmate/sessions/
       for each root in config.roots:
           for each project with .clawmate/ marker:
               SessionIndex.reap(project_sessions_dir, ttl_hours)
    3. 日志：记录清理的会话数量
```

默认 TTL：168 小时（7 天），通过 `config.py` 的 `agent.session_log_ttl_hours` 配置。

## 文件改动清单

| 文件 | 操作 |
|------|------|
| `dev/session_logger.py` | **新增** — 日志写入、索引管理、TTL 清理 |
| `dev/agent_routes.py` | **修改** — 集成日志写入、新增 API 路由、TTL 清理 |
| `dev/config.py` | **修改** — 增加 `session_log_ttl_hours` |
| `dev/static/js/agent.js` | **修改** — 历史会话视图、搜索、回放 |
| `dev/static/css/style.css` | **修改** — 会话历史相关样式 |

## 验证方案

1. **启动 ClawMate**，打开 Agent 面板（Claude 后端）
2. 执行一些命令，产生 PTY 输出
3. **检查磁盘**：`.clawmate/sessions/` 目录下应有 `.ansi.log` 和 `.text.log` 文件
4. **查看 index**：`index.json` 应有对应条目
5. **关闭面板**（不 kill PTY），等待几秒后重新打开（reconnect 场景）
6. **点击历史按钮**：应看到按日期分组的会话列表
7. **搜索**：输入关键词，应能搜到匹配的会话
8. **查看会话**：点击进入查看模式，应显示带时间戳的文本内容
9. **ANSI 回放**：切换到回放模式，xterm 应快速回放输出
10. **TTL 清理**：设置短 TTL（如 1 分钟），等待 reaper 运行，确认旧文件被删除
11. **服务重启**：重启后历史会话仍可查询
