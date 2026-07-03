# Agent 会话历史持久化与搜索 — 实施计划

> **For agentic workers:** 使用 inline execution 实现，任务按顺序执行，每完成一个任务提交一次。

**Goal:** 自动录制所有 Claude/Codex 会话输出到磁盘，提供历史会话浏览器（按日期分组列表、全文搜索、回放查看），带 TTL 自动清理。

**Architecture:** 后端在 PTY 输出流经 `pty_to_ws()` 时旁路写入 `.ansi.log` 和 `.text.log`，存储于 `{project}/.clawmate/sessions/`。通过 `SessionIndex` 管理元数据索引，`_idle_reaper()` 中集成 TTL 清理。前端在 Agent 面板新增历史会话视图，通过 API 查询和展示。

**Tech Stack:** Python FastAPI (backend), Vanilla JS + xterm.js (frontend)

## Global Constraints

- 日志统一存放到 `{project_dir}/.clawmate/sessions/` 目录
- `.ansi.log` 保存原始 PTY 输出（含 ANSI 转义序列）
- `.text.log` 格式：`[+MM:SS] 纯文本行\n`
- 默认 TTL 30 天，通过 `config.json` 中 `agent.session_log_ttl_days` 配置
- 所有会话自动录制，无需用户操作
- 前端提供按日期分组的历史列表 + 搜索 + 回放
- 所有文件修改遵循项目现有代码风格

---

### Task 1: 创建 SessionLogger 模块

**Files:**
- Create: `dev/session_logger.py`

**该模块职责：**
- `SessionLogger` — 单会话日志写入、ANSI 剥离、标题提取
- `SessionIndex` — 全局索引管理、TTL 清理、搜索

- [ ] **Step 1: 创建 `dev/session_logger.py`**

```python
"""Session output persistence — writes PTY output to .ansi.log and .text.log."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Optional


# ── ANSI strip ──

_ANSI_STRIP_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?(\x1b\\|\x07)|\x1b[\\\]_PX^]")

def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return _ANSI_STRIP_RE.sub("", text)


# ── SessionLogger ──

class SessionLogger:
    """Per-session logger: appends to .ansi.log (raw) and .text.log (plain text with timestamps)."""

    def __init__(self, session_id: str, meta: dict, log_dir: str | Path):
        self.session_id = session_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._started_at = meta.get("started_at", time.time())
        self._ansi_fd = None
        self._text_fd = None
        self._line_buf = ""

        # Write meta.json
        meta_path = self.log_dir / f"{session_id}.meta.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        # Open file handles
        self._ansi_fd = open(self.log_dir / f"{session_id}.ansi.log", "w", encoding="utf-8", buffering=1)
        self._text_fd = open(self.log_dir / f"{session_id}.text.log", "w", encoding="utf-8", buffering=1)

    def write(self, data: str):
        """Append raw PTY data to .ansi.log; strip ANSI and write lines with timestamps to .text.log."""
        if not data:
            return
        # 1) Write raw ANSI
        if self._ansi_fd:
            self._ansi_fd.write(data)

        # 2) Strip ANSI and accumulate lines for .text.log
        if self._text_fd:
            plain = strip_ansi(data)
            self._line_buf += plain
            while "\n" in self._line_buf:
                idx = self._line_buf.index("\n")
                line = self._line_buf[:idx]
                self._line_buf = self._line_buf[idx + 1:]
                elapsed = int(time.time() - self._started_at)
                mm, ss = divmod(elapsed, 60)
                self._text_fd.write(f"[+{mm:02d}:{ss:02d}] {line}\n")

    def flush(self):
        """Force-flush both file handles."""
        if self._ansi_fd:
            self._ansi_fd.flush()
        if self._text_fd:
            self._text_fd.flush()

    def close(self, status: str = "ended"):
        """Flush, close files, update meta.json."""
        if self._line_buf and self._text_fd:
            elapsed = int(time.time() - self._started_at)
            mm, ss = divmod(elapsed, 60)
            self._text_fd.write(f"[+{mm:02d}:{ss:02d}] {self._line_buf}\n")
            self._line_buf = ""

        if self._ansi_fd:
            self._ansi_fd.close()
            self._ansi_fd = None
        if self._text_fd:
            self._text_fd.close()
            self._text_fd = None

        meta_path = self.log_dir / f"{self.session_id}.meta.json"
        try:
            with open(meta_path, "r") as f:
                meta = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            meta = {}
        meta["status"] = status
        meta["ended_at"] = time.time()
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def get_title(self) -> str:
        """Read first non-empty line from .text.log as session title."""
        text_path = self.log_dir / f"{self.session_id}.text.log"
        try:
            with open(text_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("[+"):
                        continue
                    if line:
                        # Strip timestamp prefix
                        content = re.sub(r"^\[\+\d{2}:\d{2}\]\s*", "", line)
                        if content:
                            return content[:60]
        except FileNotFoundError:
            pass
        return self.session_id


# ── SessionIndex ──

class SessionIndex:
    """Manage index.json in a session log directory."""

    @staticmethod
    def _index_path(log_dir: Path) -> Path:
        return log_dir / "index.json"

    @staticmethod
    def load(log_dir: str | Path) -> list[dict]:
        path = SessionIndex._index_path(Path(log_dir))
        try:
            with open(path, "r") as f:
                data = json.load(f)
                return data.get("sessions", [])
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    @staticmethod
    def save(log_dir: str | Path, sessions: list[dict]):
        path = SessionIndex._index_path(Path(log_dir))
        data = {"version": 1, "sessions": sessions}
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.rename(path)

    @staticmethod
    def add(log_dir: str | Path, entry: dict):
        sessions = SessionIndex.load(log_dir)
        sessions.append(entry)
        SessionIndex.save(log_dir, sessions)

    @staticmethod
    def update(log_dir: str | Path, session_id: str, updates: dict):
        sessions = SessionIndex.load(log_dir)
        for s in sessions:
            if s.get("id") == session_id:
                s.update(updates)
                break
        SessionIndex.save(log_dir, sessions)

    @staticmethod
    def remove(log_dir: str | Path, session_id: str):
        sessions = SessionIndex.load(log_dir)
        sessions = [s for s in sessions if s.get("id") != session_id]
        SessionIndex.save(log_dir, sessions)

    @staticmethod
    def reap(log_dir: str | Path, ttl_days: int):
        """Remove sessions whose last_active is older than ttl_days."""
        log_dir = Path(log_dir)
        sessions = SessionIndex.load(log_dir)
        now = time.time()
        cutoff = now - ttl_days * 86400
        kept = []
        removed = 0
        for s in sessions:
            if s.get("last_active", 0) < cutoff:
                sid = s.get("id", "")
                for ext in [".meta.json", ".ansi.log", ".text.log"]:
                    p = log_dir / f"{sid}{ext}"
                    if p.exists():
                        p.unlink()
                removed += 1
            else:
                kept.append(s)
        if removed:
            SessionIndex.save(log_dir, kept)
        return removed
```

- [ ] **Step 2: Commit**

```bash
git add dev/session_logger.py && git commit -m "feat: add SessionLogger and SessionIndex for agent session persistence"
```


### Task 2: 修改 agent_routes.py — 集成日志写入

**Files:**
- Modify: `dev/agent_routes.py`

**改动点：**
1. 引入 `SessionLogger`、`SessionIndex`
2. `_AgentSession` 增加 `logger` 字段
3. 会话创建时初始化 logger
4. `pty_to_ws()` 中写入日志
5. 会话关闭/被 kill 时关闭 logger
6. `_idle_reaper()` 中调用 TTL 清理
7. 获取日志路径的辅助函数

- [ ] **Step 1: 在 `agent_routes.py` 顶部添加 import**

```python
from session_logger import SessionLogger, SessionIndex
```

- [ ] **Step 2: 在 `_AgentSession` dataclass 增加 `logger` 字段**

```python
@dataclass
class _AgentSession:
    ...
    logger: Optional[SessionLogger] = None
```

- [ ] **Step 3: 添加辅助函数获取 sessions 目录**

在 `_session_key()` 函数附近添加：

```python
def _session_log_dir(key: str, cwd: str | None = None) -> Optional[Path]:
    """Resolve .clawmate/sessions/ path from session key.
    
    key format: {backend}:{root}[:{project}]
    If cwd is provided, search upward for .clawmate/ marker.
    """
    if cwd:
        root_path = _resolve_root_dir(key.split(":")[1] if ":" in key else "")
        if root_path:
            from service import find_project_marker
            project = find_project_marker(root_path, cwd)
            if project:
                return root_path / project / ".clawmate" / "sessions"
    return None
```

- [ ] **Step 4: 在 session 创建后初始化 logger**

在 `agent_terminal()` 中，创建新 session 后（`_spawn_claude` / `_spawn_codex` 成功后），添加：

```python
# Initialize session logger
sess_dir = _session_log_dir(key, cwd)
if sess_dir:
    import time
    ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    safe_key = key.replace(":", "_").replace("/", "_")
    session_id = f"{safe_key}_{ts}"
    
    from config import load as cfg_load
    cfg = cfg_load()
    
    sess.logger = SessionLogger(
        session_id=session_id,
        meta={
            "session_id": session_id,
            "key": key,
            "backend": backend,
            "cwd": cwd,
            "root": root,
            "started_at": time.time(),
            "status": "active",
        },
        log_dir=sess_dir,
    )
    
    # Add to index
    SessionIndex.add(sess_dir, {
        "id": session_id,
        "key": key,
        "backend": backend,
        "root": root,
        "started_at": time.time(),
        "last_active": time.time(),
        "title": backend,
        "status": "active",
    })
```

- [ ] **Step 5: 在 `pty_to_ws()` 中写入日志**

找到 `pty_to_ws()` 中 `os.read()` 并 decode 后的数据，插入：

```python
data = os.read(master_fd, 4096).decode("utf-8", "replace")
# ── 新增：写入会话日志 ──
if sess.logger:
    sess.logger.write(data)
# ── 结束 ──
```

- [ ] **Step 6: 更新 `_cleanup_dead_sessions()` 中关闭 logger**

找到清理逻辑，在关闭 master_fd 后添加：

```python
if sess.logger:
    sess.logger.close("ended")
```

- [ ] **Step 7: 更新 `_idle_reaper()`**

在 kill session 后，关闭 logger：

```python
if sess.logger:
    sess.logger.close("killed")
```

同时在 reaper 末尾添加 TTL 清理：

```python
# ── TTL: 清理过期会话日志 ──
try:
    from config import load as cfg_load
    cfg = cfg_load()
    ttl = getattr(cfg.agent, "session_log_ttl_days", 30)
    for rid in _roots:
        rp = _resolve_root_dir(rid)
        if rp and rp.is_dir():
            for proj_dir in rp.iterdir():
                sess_dir = proj_dir / ".clawmate" / "sessions"
                if sess_dir.is_dir():
                    removed = SessionIndex.reap(sess_dir, ttl)
                    if removed:
                        _logger.info("TTL reaper: removed %d expired sessions from %s", removed, sess_dir)
except Exception as exc:
    _logger.warning("TTL reap error: %s", exc)
```

- [ ] **Step 8: Commit**

```bash
git add dev/agent_routes.py && git commit -m "feat: integrate session logging into agent lifecycle"
```


### Task 3: 添加会话历史 API 路由

**Files:**
- Modify: `dev/agent_routes.py` （追加 API 路由）

**新增端点：**

- [ ] **Step 1: 在 `agent_routes.py` 末尾添加 API 路由**

```python
# ── Session History APIs ──

@router.get("/api/clawmate/agent/sessions")
async def agent_session_list(
    root: str = "",
    project: str = "",
    backend: str = "",
    status: str = "",
    q: str = "",
    limit: int = 50,
    offset: int = 0,
):
    """List archived agent sessions, grouped by date."""
    results = []
    seen = set()  # dedup by session id

    # Iterate over valid roots
    from config import load as cfg_load
    cfg = cfg_load()
    roots_to_check = []
    if root:
        for r in cfg.roots:
            if r.id == root:
                roots_to_check.append(r)
                break
    else:
        roots_to_check = cfg.roots

    for r in roots_to_check:
        root_dir = Path(r.dir)
        if not root_dir.is_dir():
            continue
        # If project specified, look only there
        project_dirs = []
        if project:
            p = root_dir / project
            if p.is_dir():
                project_dirs.append(p)
        else:
            for p in root_dir.iterdir():
                if p.is_dir() and (p / ".clawmate").is_dir():
                    project_dirs.append(p)

        for proj_dir in project_dirs:
            sess_dir = proj_dir / ".clawmate" / "sessions"
            if not sess_dir.is_dir():
                continue
            sessions = SessionIndex.load(sess_dir)
            for s in sessions:
                if status and s.get("status", "") != status:
                    continue
                if backend and s.get("backend", "") != backend:
                    continue
                if q:
                    # Quick title-only filter (full content search uses /search endpoint)
                    if q.lower() not in s.get("title", "").lower():
                        # Check text log too
                        sid = s.get("id", "")
                        text_path = sess_dir / f"{sid}.text.log"
                        if text_path.is_file():
                            try:
                                content = text_path.read_text("utf-8", errors="replace")
                                if q.lower() not in content.lower():
                                    continue
                            except Exception:
                                continue
                        else:
                            continue
                sid = s.get("id", "")
                if sid in seen:
                    continue
                seen.add(sid)
                results.append({
                    **s,
                    "root": r.id,
                    "project": proj_dir.name,
                    "log_dir": str(sess_dir),
                })

    # Sort by started_at desc
    results.sort(key=lambda x: x.get("started_at", 0), reverse=True)
    total = len(results)
    paged = results[offset:offset + limit]
    return JSONResponse({"total": total, "sessions": paged})


@router.get("/api/clawmate/agent/sessions/{session_id}/log")
async def agent_session_log(
    session_id: str,
    root: str = "",
    project: str = "",
    format: str = "text",
    offset: int = 0,
    limit: int = 200,
):
    """Read session log content. format=text|ansi."""
    from config import load as cfg_load
    cfg = cfg_load()
    for r in cfg.roots:
        root_dir = Path(r.dir)
        if not root_dir.is_dir():
            continue
        proj_path = root_dir / project if project else None
        if proj_path and proj_path.is_dir():
            sess_dir = proj_path / ".clawmate" / "sessions"
        else:
            # Search all projects
            for p in root_dir.iterdir():
                sess_dir = p / ".clawmate" / "sessions"
                if (sess_dir / f"{session_id}.meta.json").exists():
                    proj_path = p
                    break
            else:
                continue
        
        if not proj_path:
            continue
        
        sess_dir = proj_path / ".clawmate" / "sessions"
        ext = ".ansi.log" if format == "ansi" else ".text.log"
        log_path = sess_dir / f"{session_id}{ext}"
        
        if not log_path.is_file():
            continue
        
        # Read metadata
        meta = {}
        meta_path = sess_dir / f"{session_id}.meta.json"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text("utf-8"))
        
        # Read content (with pagination)
        content = log_path.read_text("utf-8", errors="replace")
        lines = content.splitlines(keepends=True)
        total_lines = len(lines)
        paged_lines = lines[offset:offset + limit] if limit > 0 else lines
        
        return JSONResponse({
            "session_id": session_id,
            "meta": meta,
            "format": format,
            "total_lines": total_lines,
            "offset": offset,
            "limit": limit,
            "content": "".join(paged_lines),
        })
    
    raise HTTPException(status_code=404, detail="Session not found")


@router.get("/api/clawmate/agent/sessions/{session_id}")
async def agent_session_detail(session_id: str, root: str = "", project: str = ""):
    """Return session metadata + first/last N lines of text log."""
    from config import load as cfg_load
    cfg = cfg_load()
    for r in cfg.roots:
        root_dir = Path(r.dir)
        if not root_dir.is_dir():
            continue
        proj_path = root_dir / project if project else None
        if proj_path and proj_path.is_dir():
            sess_dir = proj_path / ".clawmate" / "sessions"
        else:
            for p in root_dir.iterdir():
                sess_dir = p / ".clawmate" / "sessions"
                if (sess_dir / f"{session_id}.meta.json").exists():
                    proj_path = p
                    break
            else:
                continue
        
        sess_dir = proj_path / ".clawmate" / "sessions"
        meta_path = sess_dir / f"{session_id}.meta.json"
        text_path = sess_dir / f"{session_id}.text.log"
        
        meta = {}
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text("utf-8"))
        
        preview = {"head": "", "tail": ""}
        if text_path.is_file():
            lines = text_path.read_text("utf-8", errors="replace").splitlines()
            preview["head"] = "\n".join(lines[:20])
            preview["tail"] = "\n".join(lines[-20:]) if len(lines) > 40 else ""
            preview["total_lines"] = len(lines)
        
        return JSONResponse({
            "session_id": session_id,
            "meta": meta,
            "root": r.id,
            "project": proj_path.name,
            "preview": preview,
        })
    
    raise HTTPException(status_code=404, detail="Session not found")


@router.delete("/api/clawmate/agent/sessions/{session_id}")
async def agent_session_delete(session_id: str, root: str = "", project: str = ""):
    """Delete a session log."""
    from config import load as cfg_load
    cfg = cfg_load()
    for r in cfg.roots:
        root_dir = Path(r.dir)
        if not root_dir.is_dir():
            continue
        proj_path = root_dir / project if project else None
        if proj_path and proj_path.is_dir():
            sess_dir = proj_path / ".clawmate" / "sessions"
        else:
            for p in root_dir.iterdir():
                sess_dir = p / ".clawmate" / "sessions"
                if (sess_dir / f"{session_id}.meta.json").exists():
                    proj_path = p
                    break
            else:
                continue
        
        sess_dir = proj_path / ".clawmate" / "sessions"
        for ext in [".meta.json", ".ansi.log", ".text.log"]:
            p = sess_dir / f"{session_id}{ext}"
            if p.exists():
                p.unlink()
        SessionIndex.remove(sess_dir, session_id)
        return JSONResponse({"ok": True, "session_id": session_id})
    
    raise HTTPException(status_code=404, detail="Session not found")
```

- [ ] **Step 2: Commit**

```bash
git add dev/agent_routes.py && git commit -m "feat: add session history API endpoints"
```


### Task 4: 更新 config.py — 添加 session_log_ttl_days

**Files:**
- Modify: `dev/config.py`

- [ ] **Step 1: 在 `AgentConfig` dataclass 中添加字段**

```python
@dataclass
class AgentConfig:
    ...
    session_log_ttl_days: int = 30
```

- [ ] **Step 2: 在 `load()` 函数中从 config.json 读取**

找到 agent 配置加载处：

```python
    agent=AgentConfig(
        backend=env_agent_backend or str(ag.get("backend", "claude")),
        ...
        session_log_ttl_days=int(ag.get("session_log_ttl_days", 30)),
    )
```

- [ ] **Step 3: Commit**

```bash
git add dev/config.py && git commit -m "feat: add session_log_ttl_days config"
```


### Task 5: 前端 — Agent 面板历史会话视图

**Files:**
- Modify: `dev/static/js/agent.js`

- [ ] **Step 1: 在 Agent 模块中添加历史会话状态和 DOM**

在 `agentState` 附近添加：

```javascript
// Session history state
var historyState = {
  view: null,           // null | 'history' | 'session-view'
  sessions: [],
  page: 0,
  total: 0,
  query: '',
  currentSessionId: null,
  sessionContent: null,
};
```

在 Agent header DOM 构建中添加按钮（init 函数中）：

```javascript
// History button
if (!dom.historyBtn) {
  dom.historyBtn = document.createElement('button');
  dom.historyBtn.className = 'agent-header-btn';
  dom.historyBtn.title = '历史会话';
  dom.historyBtn.innerHTML = iconSVG('clock', 14);
  dom.historyBtn.addEventListener('click', function() {
    toggleHistoryView();
  });
  // Insert before close button
  if (dom.closeBtn && dom.closeBtn.parentNode) {
    dom.closeBtn.parentNode.insertBefore(dom.historyBtn, dom.closeBtn);
  }
}
```

- [ ] **Step 2: 添加历史会话视图渲染函数**

```javascript
function toggleHistoryView() {
  if (historyState.view === 'history') {
    // Switch back to terminal
    historyState.view = null;
    showTerminalView();
    return;
  }
  historyState.view = 'history';
  historyState.page = 0;
  hideTerminalView();
  loadHistorySessions();
}

function hideTerminalView() {
  if (term) term.element.style.display = 'none';
  if (dom.chatView) dom.chatView.style.display = 'none';
}

function showTerminalView() {
  if (term) term.element.style.display = '';
  if (dom.chatView && backendMode === 'openclaw') dom.chatView.style.display = '';
}

function loadHistorySessions() {
  var params = new URLSearchParams();
  params.set('limit', '50');
  params.set('offset', String(historyState.page * 50));
  if (historyState.query) params.set('q', historyState.query);
  
  // Get current root/project
  var parts = (sessionKey || '').split(':');
  if (parts.length >= 2) params.set('root', parts[1]);
  if (parts.length >= 3) params.set('project', parts[2]);
  
  authFetch('/api/clawmate/agent/sessions?' + params.toString())
    .then(function(r) { return r.json(); })
    .then(function(data) {
      historyState.total = data.total || 0;
      historyState.sessions = data.sessions || [];
      renderHistoryView();
    })
    .catch(function(err) {
      console.error('Failed to load sessions:', err);
    });
}

function renderHistoryView() {
  // Create/ensure container
  var container = ensureHistoryContainer();
  container.innerHTML = '';
  
  // Search bar
  var searchBar = document.createElement('div');
  searchBar.className = 'agent-history-search';
  searchBar.innerHTML = '<input type="text" placeholder="搜索会话..." id="agentHistorySearch">';
  container.appendChild(searchBar);
  
  var searchInput = searchBar.querySelector('input');
  searchInput.addEventListener('input', function() {
    historyState.query = this.value;
    historyState.page = 0;
    loadHistorySessions();
  });
  
  if (!historyState.sessions.length) {
    container.innerHTML += '<div class="agent-history-empty">暂无历史会话</div>';
    return;
  }
  
  // Group by date
  var groups = {};
  var now = new Date();
  var today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
  var yesterday = today - 86400;
  
  historyState.sessions.forEach(function(s) {
    var t = s.started_at || 0;
    var label;
    if (t >= today) label = '今天';
    else if (t >= yesterday) label = '昨天';
    else label = formatDate(t);
    if (!groups[label]) groups[label] = [];
    groups[label].push(s);
  });
  
  // Render groups
  Object.keys(groups).forEach(function(label) {
    var groupEl = document.createElement('div');
    groupEl.className = 'agent-history-group';
    groupEl.innerHTML = '<div class="agent-history-group-title">' + label + '</div>';
    
    groups[label].forEach(function(s) {
      var item = document.createElement('div');
      item.className = 'agent-history-item';
      item.dataset.sid = s.id;
      
      var startDate = new Date((s.started_at || 0) * 1000);
      var timeStr = pad2(startDate.getHours()) + ':' + pad2(startDate.getMinutes());
      var durStr = '';
      if (s.started_at && s.ended_at) {
        var durMin = Math.round((s.ended_at - s.started_at) / 60);
        durStr = durMin + 'min';
      }
      
      item.innerHTML = '<div class="agent-history-item-title">' + escHtml(s.title || s.id) + '</div>' +
        '<div class="agent-history-item-meta">' +
          '<span class="agent-history-backend">' + escHtml(s.backend || '') + '</span>' +
          '<span>' + timeStr + '</span>' +
          (durStr ? '<span>' + durStr + '</span>' : '') +
        '</div>';
      
      item.addEventListener('click', function() {
        openSessionView(s.id, s.root, s.project);
      });
      
      groupEl.appendChild(item);
    });
    
    container.appendChild(groupEl);
  });
  
  // Pagination
  if (historyState.total > 50) {
    var pag = document.createElement('div');
    pag.className = 'agent-history-pagination';
    pag.innerHTML = '<button id="agentHistPrev"' + (historyState.page === 0 ? ' disabled' : '') + '>&larr; 上一页</button>' +
      '<span>' + (historyState.page + 1) + ' / ' + Math.ceil(historyState.total / 50) + '</span>' +
      '<button id="agentHistNext"' + ((historyState.page + 1) * 50 >= historyState.total ? ' disabled' : '') + '>下一页 &rarr;</button>';
    container.appendChild(pag);
    
    document.getElementById('agentHistPrev').addEventListener('click', function() {
      if (historyState.page > 0) { historyState.page--; loadHistorySessions(); }
    });
    document.getElementById('agentHistNext').addEventListener('click', function() {
      if ((historyState.page + 1) * 50 < historyState.total) { historyState.page++; loadHistorySessions(); }
    });
  }
}

function formatDate(timestamp) {
  var d = new Date(timestamp * 1000);
  return (d.getMonth() + 1) + '/' + d.getDate();
}

function pad2(n) { return n < 10 ? '0' + n : '' + n; }
function escHtml(s) {
  var d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}
```

- [ ] **Step 3: 添加会话查看视图**

```javascript
function openSessionView(sessionId, root, project) {
  historyState.currentSessionId = sessionId;
  historyState.view = 'session-view';
  
  var container = ensureHistoryContainer();
  container.innerHTML = '<div class="agent-session-viewer">加载中...</div>';
  
  // Load session detail + text log
  var params = new URLSearchParams();
  if (root) params.set('root', root);
  if (project) params.set('project', project);
  
  Promise.all([
    authFetch('/api/clawmate/agent/sessions/' + encodeURIComponent(sessionId) + '?' + params.toString()).then(function(r) { return r.json(); }),
    authFetch('/api/clawmate/agent/sessions/' + encodeURIComponent(sessionId) + '/log?format=text&limit=9999&' + params.toString()).then(function(r) { return r.json(); }),
  ]).then(function(results) {
    var detail = results[0];
    var logData = results[1];
    renderSessionView(detail, logData);
  }).catch(function(err) {
    container.innerHTML = '<div class="agent-session-viewer">加载失败: ' + err.message + '</div>';
  });
}

function renderSessionView(detail, logData) {
  var container = ensureHistoryContainer();
  container.innerHTML = '';
  
  var header = document.createElement('div');
  header.className = 'agent-session-viewer-header';
  header.innerHTML = '<button id="sessionViewBack">&larr; 返回列表</button>' +
    '<span class="agent-session-viewer-title">' + escHtml(detail.meta?.title || detail.session_id) + '</span>' +
    '<button id="sessionViewDelete" class="danger" title="删除此会话">🗑</button>';
  container.appendChild(header);
  
  var content = document.createElement('div');
  content.className = 'agent-session-viewer-content';
  
  var pre = document.createElement('pre');
  pre.className = 'agent-session-viewer-text';
  pre.textContent = logData.content || '';
  content.appendChild(pre);
  
  container.appendChild(content);
  
  // Back button
  document.getElementById('sessionViewBack').addEventListener('click', function() {
    historyState.view = 'history';
    renderHistoryView();
  });
  
  // Delete button
  document.getElementById('sessionViewDelete').addEventListener('click', function() {
    if (!confirm('确定删除此会话？')) return;
    var params = new URLSearchParams();
    if (detail.root) params.set('root', detail.root);
    if (detail.project) params.set('project', detail.project);
    
    authFetch('/api/clawmate/agent/sessions/' + encodeURIComponent(detail.session_id), {
      method: 'DELETE',
    }).then(function(r) { return r.json(); }).then(function() {
      historyState.view = 'history';
      loadHistorySessions();
    });
  });
}

function ensureHistoryContainer() {
  var existing = document.getElementById('agentHistoryContainer');
  if (existing) return existing;
  
  var container = document.createElement('div');
  container.id = 'agentHistoryContainer';
  container.className = 'agent-history-container';
  
  var panel = document.getElementById(domPrefix + 'agentPanelBody');
  if (panel) panel.appendChild(container);
  return container;
}
```

- [ ] **Step 4: Commit**

```bash
git add dev/static/js/agent.js && git commit -m "feat: add session history view to agent panel"
```


### Task 6: 前端 — 历史会话样式

**Files:**
- Modify: `dev/static/css/style.css`

- [ ] **Step 1: 追加样式**

在 CSS 文件末尾添加：

```css
/* ── Agent Session History ── */
.agent-history-container {
  display: flex; flex-direction: column; height: 100%; overflow: hidden;
}
.agent-history-search {
  padding: 8px; border-bottom: 1px solid var(--border-color);
}
.agent-history-search input {
  width: 100%; padding: 6px 8px; border: 1px solid var(--border-color);
  border-radius: var(--radius-sm); background: var(--bg-primary);
  color: var(--text-primary); font-size: 12px; outline: none;
  box-sizing: border-box;
}
.agent-history-search input:focus { border-color: var(--accent); }
.agent-history-empty {
  padding: 24px; text-align: center; color: var(--text-muted); font-size: 13px;
}
.agent-history-group-title {
  padding: 6px 8px; font-size: 11px; font-weight: 600;
  color: var(--text-secondary); text-transform: uppercase;
  background: var(--bg-tertiary); border-bottom: 1px solid var(--border-color);
}
.agent-history-item {
  padding: 8px; cursor: pointer; border-bottom: 1px solid var(--border-color);
  transition: background 0.12s;
}
.agent-history-item:hover { background: var(--bg-tertiary); }
.agent-history-item-title {
  font-size: 13px; font-weight: 500; color: var(--text-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.agent-history-item-meta {
  display: flex; gap: 8px; font-size: 11px; color: var(--text-secondary);
  margin-top: 2px;
}
.agent-history-backend {
  display: inline-block; padding: 0 4px; border-radius: 3px;
  background: var(--accent-light); color: var(--accent); font-weight: 600;
  font-size: 10px; text-transform: uppercase;
}
.agent-history-pagination {
  display: flex; justify-content: center; align-items: center;
  gap: 12px; padding: 8px; font-size: 12px; color: var(--text-secondary);
  border-top: 1px solid var(--border-color);
}
.agent-history-pagination button {
  padding: 4px 10px; border: 1px solid var(--border-color);
  border-radius: var(--radius-sm); background: var(--btn-bg);
  color: var(--btn-text); cursor: pointer; font-size: 11px;
}
.agent-history-pagination button:hover:not([disabled]) {
  background: var(--bg-tertiary);
}
.agent-history-pagination button[disabled] { opacity: 0.4; cursor: default; }

/* Session viewer */
.agent-session-viewer {
  display: flex; flex-direction: column; height: 100%;
}
.agent-session-viewer-header {
  display: flex; align-items: center; gap: 6px; padding: 6px 8px;
  border-bottom: 1px solid var(--border-color); flex-shrink: 0;
}
.agent-session-viewer-header button {
  padding: 4px 8px; border: 1px solid var(--border-color);
  border-radius: var(--radius-sm); background: var(--btn-bg);
  color: var(--btn-text); cursor: pointer; font-size: 11px; flex-shrink: 0;
}
.agent-session-viewer-header button:hover { background: var(--bg-tertiary); }
.agent-session-viewer-header button.danger:hover { background: var(--danger-bg); border-color: var(--danger); color: var(--danger); }
.agent-session-viewer-title {
  flex: 1; font-size: 12px; font-weight: 600; color: var(--text-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.agent-session-viewer-content {
  flex: 1; overflow: auto; padding: 8px;
}
.agent-session-viewer-text {
  font-family: 'JetBrains Mono', monospace; font-size: 11px; line-height: 1.5;
  color: var(--text-primary); white-space: pre-wrap; word-break: break-all;
  margin: 0;
}
```

- [ ] **Step 2: Commit**

```bash
git add dev/static/css/style.css && git commit -m "style: add session history viewer styles"
```


### Task 7: 验证测试

- [ ] **Step 1: 启动服务并连接 Agent**

```bash
python3 -m uvicorn dev.main:app --port 5533
```

打开浏览器 → Agent 面板 → 连接到 Claude 后端 → 执行几个命令确认 PTY 输出正常

- [ ] **Step 2: 验证日志写入**

检查 `.clawmate/sessions/` 目录是否生成了 `.ansi.log` 和 `.text.log` 文件：
```bash
ls -la /path/to/project/.clawmate/sessions/
cat /path/to/project/.clawmate/sessions/*.text.log
```

- [ ] **Step 3: 验证历史会话列表**

点击 Agent 面板的历史按钮 → 确认看到按日期分组的会话列表

- [ ] **Step 4: 验证会话查看**

点击某条会话 → 确认显示纯文本内容

- [ ] **Step 5: 验证搜索**

在历史列表搜索框输入关键词 → 确认能搜到匹配的会话

- [ ] **Step 6: 验证删除**

删除一条会话 → 确认文件被删除、列表更新

- [ ] **Step 7: 验证 TTL 清理**

临时设置短 TTL → 等待 reaper 运行 → 确认过期会话被清理

- [ ] **Step 8: 完成验收**

```bash
git log --oneline -10
```

通知用户验收。
