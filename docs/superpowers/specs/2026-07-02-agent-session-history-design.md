# Agent 会话历史持久化与搜索 — 设计文档

> 2026-07-02 | Status: Draft

## Context

当前 ClawMate Agent 面板（xterm.js + PTY）的所有会话输出完全基于内存：
`_AgentSession.output_buffer` 是一个 `deque(maxlen=200)` 的 ring buffer。会话一旦被 idle reaper
杀掉或服务重启，全部输出丢失，无法查询、搜索或回放过去的会话。

**目标**：自动录制所有 Claude/Codex 会话输出到磁盘，提供历史会话浏览器（按日期分组列表、
全文搜索、回放查看），并带 TTL 自动清理。

## 存储结构

日志存放在 `.clawmate/sessions/` 中，按根目录（root）/项目（project）两级组织：

### 项目级会话（带 .clawmate marker）

```
{root_dir}/{project}/.clawmate/sessions/
├── index.json                            ← 全局索引
├── claude_webprojects_clawmate_20260702_143000.meta.json  ← 会话元数据
├── claude_webprojects_clawmate_20260702_143000.chat.jsonl ← 结构化对话记录（JSONL）
├── claude_webprojects_clawmate_20260702_143000.ansi.log   ← 原始 ANSI 输出
└── claude_webprojects_clawmate_20260702_143000.text.log   ← 剥离 ANSI 的纯文本
```

### 根级会话（无 project，session key 只有 {backend}:{root}）

session key 不含 project 段时，会话直接存储在 root 自身的 `.clawmate/sessions/` 下：

```
{root_dir}/.clawmate/sessions/
├── index.json
└── codex_webprojects_20260703_091500.meta.json
```

### 路径推导

从 session key `{backend}:{root}[:{project}]` 推导：
- `root_dir` → config.json 中 `roots[{root}].dir`
- `project` 存在 → `{root_dir}/{project}/.clawmate/sessions/`
- `project` 不存在（根级）→ `{root_dir}/.clawmate/sessions/`

**文件名格式**：`{backend}_{root}_{project}_{YYYYMMDD}_{HHMMSS}`（URL/filesystem safe，无 project 时省略 project 段）

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
| `reap(log_dir, ttl_days)` | 清理过期会话 |

**TTL 清理**：`reap()` 遍历 index，`last_active < now - ttl_days * 86400` 则删除该会话的
所有文件（`.meta.json`、`.ansi.log`、`.text.log`、`.chat.jsonl`）并从 index 移除。

### 修改文件：`dev/agent_routes.py`

#### 基础日志

| 位置 | 改动 |
|------|------|
| `_AgentSession` dataclass | 新增 `logger: Optional[SessionLogger] = None` |
| `_spawn_pt()` / session 创建 | 初始化 `SessionLogger`，写入 meta |
| `pty_to_ws()` | `os.read()` 后调用 `sess.logger.write(data)` |
| `_cleanup_dead_sessions()` | 调用 `sess.logger.close("ended")` |
| `_idle_reaper()` | kill session 前调用 `sess.logger.close("killed")`；末尾调用 `SessionIndex.reap()` |
| WebSocket 连接建立 | 恢复已有 session 时，检查是否需要重新打开 logger |

#### 根级会话支持（2026-07-05）

`_session_log_dir()` 原逻辑在无 project 时返回 `None`，改为返回 root 自身 `.clawmate/sessions/`：

```python
if not project:
    return root_path / ".clawmate" / "sessions"
```

TTL reaper 增加 root 级 session 目录扫描（`_idle_reaper()` 中遍历 `seen_roots` 后先检查 root 级 `.clawmate/sessions/`，再遍历各 project 的子目录）。

提取辅助函数 `_roots_for_session_query()` 和 `_projects_for_session_query()`，统一 session API 中的目录遍历逻辑。`_projects_for_session_query()` 在无 project 约束时自动包含 root 级 sessions 目录。

#### 输入批处理（2026-07-05）

WebSocket → PTY 转发（`ws_to_pty()`）中新增输入批处理，防止每按一个键都生成独立 user turn：

- 用户输入的每一行先放入 `_input_batch` 数组
- 超过 1.5 秒无新输入 → flush 整个 batch 为一条 user turn 记录
- session 结束时 finally 块 flush 剩余 batch
- 解决：终端粘贴多行文本时合并为一条 user 消息，而非逐行记录

#### 会话记录增强（2026-07-05）

- **"分析文件"记录**：前端触发的分析文件 prompt 同步写入 `.chat.jsonl`，避免 session 因缺失 user turn 被过滤器跳过
- **Session liveliness 检查**：async sleep 后、FD 写入前校验 session 仍存活（`sess.key not in _sessions`），防止向已回收的 FD 写入（可能被新 session 复用）

#### Transcript 匹配优化（2026-07-05）

`_find_claude_transcript()` 和 `_find_codex_transcript()`：

- 不再依赖 mtime 匹配，改为扫描 transcript 文件内容寻找可解析的 timestamp
- 返回 timestamp 最接近 session `started_at` 的候选文件
- 若文件无法解析则为 null timestamp，回退 mtime 匹配
- `_parse_claude_transcript()` / `_parse_codex_transcript()` 新增 `started_at` 参数 → 过滤 60s 前的内容（**跨 session 污染防护**）：防止 transcript 中残留的旧 assistant 消息被错误关联到当前 session

#### 计数修正（2026-07-05）

`SessionLogger.count_turns()` 改为仅统计 `role == "user"` 的条目（原逻辑按行数统计，可能把 JSON decode 失败的脏行也算进去）。新增 `json.JSONDecodeError` 兜底。

### 新增 API

挂载在 `agent_routes.py` 的 router 上：

| 路由 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/api/clawmate/agent/sessions` | GET | `root`, `project`, `dir`, `backend`, `status`, `q` | 列出会话。`dir` 参数根据当前文件浏览目录自动推断 project。返回新增 `instruction_count`/`turn_count`/`total_turns`/`first_ts`/`last_ts` 统计字段 |
| `/api/clawmate/agent/sessions/{session_id}` | GET | `root`, `project`, `dir` | 返回会话元数据 + 统计（turn_count → instruction_count） |
| `/api/clawmate/agent/sessions/{session_id}/log` | GET | `root`, `project`, `dir`, `format`, `offset`, `limit` | 返回 `.chat.jsonl` 结构化对话。text 日志内容、ANSI 回放保留 |
| `/api/clawmate/agent/sessions/search` | GET | `q`, `root`, `project`, `backend` | 搜索 |
| `/api/clawmate/agent/sessions/{session_id}` | DELETE | `root`, `project`, `dir` | 删除指定会话（删文件 + 更新 index） |

所有 session API 新增 `dir` 参数，用于根据当前文件浏览器目录自动推断 project（无需用户手动指定 project 名前缀）。

#### 会话数据模型：`.chat.jsonl`

每个会话新增 `.chat.jsonl` 文件，结构化记录对话轮次：

```jsonl
{"role":"user","content":"分析文件: dev/main.py","ts":1719900000.0,"turn_index":1}
{"role":"assistant","content":"文件包含 3 个函数...","ts":1719900010.0}
{"role":"user","content":"修改第 42 行","ts":1719900020.0,"turn_index":2}
{"role":"assistant","content":"已完成修改...","ts":1719900030.0}
```

**写入时机**：
- user 消息：WebSocket 输入批处理 flush 时写入（1.5s idle 触发或 session 关闭时）
- assistant 消息：session 结束时从 transcript（Claude/Codex 的 JSONL）批量解析并入

**会话内容规范化**（`_normalize_chat_turns()`）：
1. 跳过空白内容的 turn
2. 按 timestamp 排序（因为 assistant 消息可能在 user 消息写入后才从 transcript 追加到文件）
3. 合并 1 秒内连续的 user turn（兼容终端多行粘贴场景）
4. 分配 `turn_index`（从 1 开始递增，仅 user turn 占位）

#### 浏览器目录感知

历史浏览器的文件导航目录当前指向项目子目录（如 `clawmate/dev/`）而非项目根时，session API 的 `dir` 参数自动通过 `find_project_marker()` 向上查找 `.clawmate/` marker 确定所属 project，无需用户手动切换目录。

### 修改文件：`dev/config.py`

```python
@dataclass
class AgentConfig:
    ...
    session_log_ttl_days: int = 30    # 默认 30 天
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
               SessionIndex.reap(project_sessions_dir, ttl_days)
    3. 日志：记录清理的会话数量
```

默认 TTL：30 天，通过 `config.json` 的 `agent.session_log_ttl_days` 配置。

## 文件改动清单

| 文件 | 操作 |
|------|------|
| `dev/session_logger.py` | **新增** — 日志写入、索引管理、TTL 清理 |
| `dev/agent_routes.py` | **修改** — 集成日志写入、新增 API 路由、TTL 清理 |
| `dev/config.py` | **修改** — 增加 `session_log_ttl_days` |
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
