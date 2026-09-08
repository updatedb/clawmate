# ClawMate 推荐任务:codex 生成 + 删除 + 后端配置 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 ClawMate project panel 的推荐任务增加「codex 分析生成」与「持久删除」,并通过新增的 `agent.project_backend` 配置选择执行/分析后端(默认 `auto` = codex 优先、失败兜底)。

**Architecture:** 后端在 `config.py` 新增 `agent.project_backend` 字段;`task_executor.py` 增加一个捕获 stdout 的同步 CLI 分析方法;`project_routes.py` 新增 `recommendations/analyze`(跑 codex 分析并合并)与 `recommendations/{task_id}/delete`(写 `dismissed_recommendations` 持久删除),并让 `_project_task_catalog` 过滤 dismissed。前端只在共享渲染器 `project-panel.js` 加「分析项目（Codex）」按钮与每项「删除」按钮——index 与 preview 两处都经由该共享 mount,一处改动两端生效。

**Tech Stack:** FastAPI + 原生 JS 前端;`subprocess` 调 codex/claude CLI;项目目录 `.clawmate/project.json` 为数据源;pytest + fastapi.testclient 测试。

## Global Constraints

- `agent.project_backend` 取值严格为 `claude | codex | openclaw | auto`,未设置时默认 **`auto`**(`TaskExecutor.launch` 的 `auto` 顺序为 codex → claude → openclaw)。
- codex 分析只允许项目内路径;`prompt` 已经内联该约束。
- `dismissed_recommendations` 用于持久删除;默认任务(`commit_version`/`maintain_project_docs`/`update_meeting_info`)删除后也**不复活**。
- `.clawmate/project.json` 用现有 `_read_project_json`/`_write_project_json` 读写,遵循既有原子写。
- `/tasks/{id}/run` 本轮**不改**(仍读 `agent.backend`);仅新增的 analyze 路径读 `project_backend`。
- 前端只在共享 `project-panel.js` 实现;不新增/迁移 app.js 渲染器。

---

### Task 1: 新增 `agent.project_backend` 配置

**Files:**
- Modify: `dev/config.py`(AgentConfig 字段 + load_cfg 解析)
- Test: `tests/test_recommendations_manage.py`(新建)

**Interfaces:**
- Consumes: `_agent_backend(value: str) -> str`(config.py:169,校验 claude/codex/openclaw/auto)
- Produces: `cfg.agent.project_backend: str`(后续 Task 2 的 `TaskExecutor.run_summary_analysis` 读取)。

- [ ] **Step 1: 写失败测试**

`tests/test_recommendations_manage.py`(新建文件):
```python
import json
import tempfile
from pathlib import Path
from config import set_config_path, clear_config_cache, load_cfg


def _write_cfg(agent: dict) -> Path:
    tmp = tempfile.mkdtemp()
    p = Path(tmp) / "config.json"
    p.write_text(json.dumps({"roots": [{"id": "r", "label": "R", "dir": tmp}], "agent": agent}, ensure_ascii=False))
    clear_config_cache()
    set_config_path(str(p))
    return p


def test_project_backend_defaults_auto():
    _write_cfg({"backend": "claude"})
    assert load_cfg().agent.project_backend == "auto"


def test_project_backend_explicit():
    _write_cfg({"project_backend": "codex"})
    assert load_cfg().agent.project_backend == "codex"


def test_project_backend_env_override(monkeypatch):
    _write_cfg({"project_backend": "claude"})
    monkeypatch.setenv("CLAWMATE_AGENT_PROJECT_BACKEND", "openclaw")
    clear_config_cache()
    assert load_cfg().agent.project_backend == "openclaw"
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `python3 -m pytest tests/test_recommendations_manage.py -v`
Expected: FAIL —— `AttributeError: 'AgentConfig' object has no attribute 'project_backend'`

- [ ] **Step 3: 实现**

`dev/config.py`:
1) 在 `AgentConfig`(line ~46)`ui_backend` 下方新增字段:
```python
    backend: str = "claude"          # "claude" | "openclaw" | "codex" | "auto"
    ui_backend: str = "claude"       # interactive panel: concrete backend only
    project_backend: str = "auto"    # project-panel (recommendation) backend: codex-first w/ fallback
```
2) 在 `load_cfg()` 的 env 区域(line ~265)增加:
```python
    env_project_backend = os.getenv("CLAWMATE_AGENT_PROJECT_BACKEND")
```
3) 在 `AgentConfig(...)`(line ~283-285)增加一项:
```python
        agent=AgentConfig(
            backend=_agent_backend(env_agent_backend or str(ag.get("backend", "claude"))),
            ui_backend=_ui_agent_backend(str(ag.get("ui_backend", "")), env_agent_backend or str(ag.get("backend", "claude"))),
            project_backend=_agent_backend(str(ag.get("project_backend") or env_project_backend or "auto")),
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `python3 -m pytest tests/test_recommendations_manage.py -v`
Expected: PASS(3 项通过)

- [ ] **Step 5: 提交**

```bash
git add dev/config.py tests/test_recommendations_manage.py
git commit -m "feat(config): add agent.project_backend for project-panel tasks (default auto)"
```

---

### Task 2: `TaskExecutor.run_summary_analysis` —— 捕获 stdout 的同步 CLI 分析

**Files:**
- Modify: `dev/task_executor.py`
- Test: `tests/test_recommendations_manage.py`

**Interfaces:**
- Consumes: `TaskExecutor`(self.cfg.agent.project_backend)、`CLI_BACKENDS`、`self._cli_binary(backend)`。
- Produces: `TaskExecutor.run_summary_analysis(message: str, cwd: str, timeout_seconds: int = 90) -> dict`,返回 `{ok, backend, output, error, code}`。后续 Task 6 的 analyze 端点消费。

- [ ] **Step 1: 写失败测试**

在 `tests/test_recommendations_manage.py` 追加:
```python
from task_executor import TaskExecutor


def test_run_summary_analysis_uses_codex_first(monkeypatch):
    class FakeCfg:
        class Agent:
            project_backend = "codex"
            env = {}
        agent = Agent()
    captured = {}
    def fake_binary(backend):
        return "codex" if backend == "codex" else None
    def fake_run(args, **kw):
        captured["args"] = args
        return SimpleNamespace(returncode=0, stdout='[{"label":"x"}]', stderr="", code=0)
    import subprocess
    monkeypatch.setattr(TaskExecutor, "_cli_binary", lambda self, b: fake_binary(b))
    monkeypatch.setattr(subprocess, "run", fake_run)
    res = TaskExecutor(FakeCfg()).run_summary_analysis("hi", cwd=".")
    assert res["ok"] is True
    assert captured["args"][0] == "codex"
    assert captured["args"][-1] == "hi"


def test_run_summary_analysis_auto_prefers_codex(monkeypatch):
    class FakeCfg:
        class Agent:
            project_backend = "auto"
            env = {}
        agent = Agent()
    calls = []
    import subprocess
    def fake_binary(backend):
        return "codex" if backend == "codex" else None
    def fake_run(args, **kw):
        calls.append(args[0])
        return SimpleNamespace(returncode=0, stdout="[]", stderr="", code=0)
    monkeypatch.setattr(TaskExecutor, "_cli_binary", lambda self, b: fake_binary(b))
    monkeypatch.setattr(subprocess, "run", fake_run)
    res = TaskExecutor(FakeCfg()).run_summary_analysis("hi", cwd=".")
    assert res["ok"] is True
    assert calls == ["codex"]


def test_run_summary_analysis_non_cli_backend_fails(monkeypatch):
    class FakeCfg:
        class Agent:
            project_backend = "openclaw"
            env = {}
        agent = Agent()
    res = TaskExecutor(FakeCfg()).run_summary_analysis("hi", cwd=".")
    assert res["ok"] is False
```
(在文件顶部加 `from types import SimpleNamespace`。)

- [ ] **Step 2: 运行测试,确认失败**

Run: `python3 -m pytest tests/test_recommendations_manage.py::test_run_summary_analysis -v`
Expected: FAIL —— `AttributeError: 'TaskExecutor' object has no attribute 'run_summary_analysis'`

- [ ] **Step 3: 实现**

`dev/task_executor.py` 在 `TaskExecutor` 类内、`_launch_gateway` 之后新增方法:
```python
    def run_summary_analysis(self, message: str, cwd: str, timeout_seconds: int = 90) -> dict:
        """Run the project-panel backend in pipe mode and return its captured output.

        Only CLI backends (codex/claude) support buffered analysis; a gateway
        backend (openclaw) has no local process to capture, so it is skipped.
        'auto' resolves codex first, then claude — never a gateway.
        """
        requested = str(self.cfg.agent.project_backend).strip().lower()
        candidates = ("codex", "claude") if requested == "auto" else (requested,)
        failures = []
        for backend in candidates:
            if backend not in CLI_BACKENDS:
                continue
            binary = self._cli_binary(backend)
            if not binary:
                failures.append(f"{backend}: CLI unavailable")
                continue
            env = os.environ.copy()
            env.update(self.cfg.agent.env or {})
            if backend == "claude":
                env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
            args = [binary, "-p", message]
            try:
                proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                                      timeout=timeout_seconds, env=env, start_new_session=True)
            except subprocess.TimeoutExpired:
                failures.append(f"{backend}: timeout")
                continue
            except OSError:
                failures.append(f"{backend}: could not start")
                continue
            return {"ok": proc.returncode == 0, "backend": backend,
                    "output": proc.stdout, "error": proc.stderr, "code": proc.returncode}
        return {"ok": False, "backend": "", "output": "",
                "error": "; ".join(failures) or "No CLI backend available", "code": -1}
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `python3 -m pytest tests/test_recommendations_manage.py::test_run_summary_analysis -v`
Expected: PASS(3 项通过)

- [ ] **Step 5: 提交**

```bash
git add dev/task_executor.py tests/test_recommendations_manage.py
git commit -m "feat(executor): add run_summary_analysis (codex-first capture)"
```

---

### Task 3: `_extract_codex_tasks` 解析 codex 输出

**Files:**
- Modify: `dev/project_routes.py`
- Test: `tests/test_recommendations_manage.py`

**Interfaces:**
- Consumes: 无(纯函数)。
- Produces: `_extract_codex_tasks(output: str) -> list[dict]`,每个 dict 含 `id/label/prompt/kind/frequency/source(codex)`。Task 6 消费。

- [ ] **Step 1: 写失败测试**

追加:
```python
from project_routes import _extract_codex_tasks


def test_extract_codex_tasks_parses_clean_json():
    out = '[{"id":"a","label":"甲","prompt":"做甲","kind":"plan","frequency":0}]'
    tasks = _extract_codex_tasks(out)
    assert len(tasks) == 1
    assert tasks[0]["id"] == "a" and tasks[0]["source"] == "codex"


def test_extract_codex_tasks_strips_fences():
    out = '```json\n[{"label":"乙"}]\n```'
    tasks = _extract_codex_tasks(out)
    assert tasks[0]["label"] == "乙"
    assert tasks[0]["id"] == "乙"  # id 回退到 label


def test_extract_codex_tasks_skips_invalid_and_raises_when_empty():
    out = '[{"prompt":"无 label"}, {"label":"有效"}]'
    tasks = _extract_codex_tasks(out)
    assert len(tasks) == 1 and tasks[0]["label"] == "有效"
    import pytest as _p
    with _p.raises(ValueError):
        _extract_codex_tasks("no json here")
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `python3 -m pytest tests/test_recommendations_manage.py::test_extract_codex_tasks -v`
Expected: FAIL —— `ImportError: cannot import name '_extract_codex_tasks'`

- [ ] **Step 3: 实现**

`dev/project_routes.py` 新增(放在 `_recommendations_for` 之后):
```python
def _extract_codex_tasks(output: str) -> list[dict]:
    """Pull a JSON array of recommended tasks out of a free-form CLI response."""
    text = str(output or "").strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("No JSON array in codex response")
    payload = json.loads(text[start:end + 1])
    if not isinstance(payload, list):
        raise ValueError("Expected a JSON array from codex")
    tasks: list[dict] = []
    for item in payload:
        if not isinstance(item, dict) or not str(item.get("label", "")).strip():
            continue
        label = str(item["label"]).strip()
        tasks.append({
            "id": str(item.get("id") or label).strip() or label,
            "label": label,
            "prompt": str(item.get("prompt") or f"在项目内完成推荐任务：{label}。"),
            "kind": str(item.get("kind") or "plan"),
            "frequency": int(item.get("frequency") or 0),
            "source": "codex",
        })
    return tasks
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `python3 -m pytest tests/test_recommendations_manage.py -k extract_codex -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add dev/project_routes.py tests/test_recommendations_manage.py
git commit -m "feat(project): add _extract_codex_tasks parser"
```

---

### Task 4: `_project_task_catalog` 过滤 dismissed + `_merge_codex_recommendations`

**Files:**
- Modify: `dev/project_routes.py`
- Test: `tests/test_recommendations_manage.py`

**Interfaces:**
- Consumes: `_read_project_json`/`_write_project_json`。
- Produces:
  - `_project_task_catalog(target) -> list[dict]`(过滤 `dismissed_recommendations`,默认任务也遵循;语义不变,新增跳过逻辑)。
  - `_merge_codex_recommendations(target, new_tasks) -> list[dict]`(替换 source=codex 的旧条目,追加新的,写回 project.json)。

- [ ] **Step 1: 写失败测试**

追加:
```python
from project_routes import _project_task_catalog, _merge_codex_recommendations
import project_routes as PR


def test_catalog_filters_dismissed(_rec_proj):
    cfg = PR._read_project_json(_rec_proj)
    cfg["recommended_tasks"] = [
        {"id": "commit_version", "label": "提交版本", "source": "project_json"},
        {"id": "zap", "label": "删除我", "source": "discover"},
    ]
    cfg["dismissed_recommendations"] = ["commit_version", "zap"]
    PR._write_project_json(_rec_proj, cfg)
    ids = [t["id"] for t in _project_task_catalog(_rec_proj)]
    assert "zap" not in ids
    assert "commit_version" not in ids  # 默认任务也被 dismissed 压制,不复活


def test_merge_codex_replaces_old_codex(_rec_proj):
    cfg = PR._read_project_json(_rec_proj)
    cfg["recommended_tasks"] = [
        {"id": "a", "label": "旧codex", "source": "codex"},
        {"id": "b", "label": "保留", "source": "project_json"},
    ]
    PR._write_project_json(_rec_proj, cfg)
    merged = _merge_codex_recommendations(_rec_proj, [
        {"id": "a", "label": "新codex", "prompt": "p", "source": "codex"},
        {"id": "c", "label": "新增", "prompt": "p", "source": "codex"},
    ])
    ids = [t["id"] for t in merged]
    assert ids == ["b", "a", "c"]
    assert merged[1]["label"] == "新codex"
    assert "dismissed_recommendations" in PR._read_project_json(_rec_proj)
```
需在文件里加一个 fixture `_rec_proj`,返回一个创建了 `.clawmate/project.json` 的临时项目目录路径:
```python
@pytest.fixture()
def _rec_proj(tmp_path):
    d = tmp_path / "proj"
    (d / ".clawmate").mkdir(parents=True)
    (d / ".clawmate" / "project.json").write_text("{}", encoding="utf-8")
    return d
```
(在文件顶部 `import pytest` 与 `import project_routes as PR`。)

- [ ] **Step 2: 运行测试,确认失败**

Run: `python3 -m pytest tests/test_recommendations_manage.py -k "catalog_filters or merge_codex" -v`
Expected: FAIL —— `Unit test: model vs field mismatch` 或 `ImportError`(依赖 Task 4 实现;先失败)

- [ ] **Step 3: 实现**

`dev/project_routes.py` 修改 `_project_task_catalog`(line ~617)为:
```python
def _project_task_catalog(target: Path) -> list[dict]:
    """Return compatible recommended tasks, preferring persisted task records.

    Records whose id is in ``dismissed_recommendations`` are skipped — including
    the built-in defaults, so a dismissed default never resurrects."""
    cfg = _read_project_json(target)
    dismissed = set(cfg.get("dismissed_recommendations") or [])
    raw = cfg.get("recommended_tasks") or cfg.get("recommendations") or []
    known: set[str] = set()
    tasks: list[dict] = []
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("label", "")).strip():
            continue
        task = dict(item)
        task["id"] = str(task.get("id") or task["label"])
        task["label"] = str(task["label"]).strip()
        task["frequency"] = int(task.get("frequency") or 0)
        if task.get("estimated_minutes") is not None:
            task["estimated_minutes"] = max(0, int(task["estimated_minutes"]))
        known.add(task["id"])
        if task["id"] in dismissed:
            continue
        tasks.append(task)
    defaults = [
        {"id": "commit_version", "label": "提交版本", "kind": "commit", "prompt": "检查项目当前改动；仅提交与本次项目工作直接相关、且已完成自检的文件。", "frequency": 0},
        {"id": "maintain_project_docs", "label": "维护项目文档", "kind": "documentation", "prompt": "阅读 PROJECT_NOTE.md 和 CLAWLIST.md，依据当前项目实际进展更新必要文档，不要编造事实。", "frequency": 0},
    ]
    if str(cfg.get("type", "")).lower() == "meeting":
        defaults.append({"id": "update_meeting_info", "label": "更新会议信息", "kind": "meeting", "prompt": "更新项目中的会议纪要、日程或行动项；只写入已知会议事实。", "frequency": 0})
    tasks.extend(task for task in defaults if task["id"] not in known and task["id"] not in dismissed)
    return tasks
```

`dev/project_routes.py` 新增 `_merge_codex_recommendations`:
```python
def _merge_codex_recommendations(target: Path, new_tasks: list[dict]) -> list[dict]:
    """Replace prior codex-sourced records with fresh ones, respecting dismissal."""
    cfg = _read_project_json(target)
    existing = cfg.get("recommended_tasks") if isinstance(cfg.get("recommended_tasks"), list) else []
    dismissed = set(cfg.get("dismissed_recommendations") or [])
    preserved = [t for t in existing if t.get("source") != "codex" and t.get("id") not in dismissed]
    kept = {t["id"] for t in preserved}
    merged = preserved + [t for t in new_tasks if t["id"] not in dismissed and t["id"] not in kept]
    cfg["recommended_tasks"] = merged
    cfg["dismissed_recommendations"] = sorted(dismissed)
    _write_project_json(target, cfg)
    return merged
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `python3 -m pytest tests/test_recommendations_manage.py -k "catalog_filters or merge_codex" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add dev/project_routes.py tests/test_recommendations_manage.py
git commit -m "feat(project): dismiss-filter catalog + merge codex recommendations"
```

---

### Task 5: 推荐删除端点

**Files:**
- Modify: `dev/project_routes.py`
- Test: `tests/test_share_routes.py` 风格 —— 在 `tests/test_recommendations_manage.py` 用 TestClient

**Interfaces:**
- Consumes: `_read_project_json`/`_write_project_json`、`_project_target`。
- Produces: `POST /api/clawmate/project/{root}/{project}/recommendations/{task_id}/delete` → `{ok: True, task_id}`。

- [ ] **Step 1: 写失败测试**

追加(文件顶部加 `from fastapi.testclient import TestClient`):
```python
from main import app


def _client():
    return TestClient(app)


def test_recommendation_delete_persists_dismissed(_rec_proj, monkeypatch):
    import project_routes as PR
    monkeypatch.setattr(PR, "_project_target", lambda root, project: _rec_proj)
    PR._write_project_json(_rec_proj, {
        "recommended_tasks": [{"id": "zap", "label": "删我", "source": "discover"}],
        "dismissed_recommendations": [],
    })
    res = _client().post("/api/clawmate/project/r/proj/recommendations/zap/delete")
    assert res.status_code == 200
    cfg = PR._read_project_json(_rec_proj)
    assert cfg["recommended_tasks"] == []
    assert "zap" in cfg["dismissed_recommendations"]


def test_recommendation_delete_idempotent(_rec_proj, monkeypatch):
    import project_routes as PR
    monkeypatch.setattr(PR, "_project_target", lambda root, project: _rec_proj)
    res = _client().post("/api/clawmate/project/r/proj/recommendations/missing/delete")
    assert res.status_code == 200
    assert res.json()["ok"] is True
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `python3 -m pytest tests/test_recommendations_manage.py -k "recommendation_delete" -v`
Expected: FAIL —— `404`/`405`(路由不存在)

- [ ] **Step 3: 实现**

`dev/project_routes.py` 在 `project_task_retry` 之后新增:
```python
@router.post("/api/clawmate/project/{root}/{project}/recommendations/{task_id}/delete")
async def project_recommendation_delete(root: str, project: str, task_id: str):
    """Persistently dismiss a recommendation; it will not resurrect."""
    try:
        target = _project_target(root, project)
    except (ValueError, PermissionError):
        raise HTTPException(status_code=403, detail="Forbidden")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    cfg = _read_project_json(target)
    dismissed = set(cfg.get("dismissed_recommendations") or [])
    dismissed.add(task_id)
    existing = cfg.get("recommended_tasks") if isinstance(cfg.get("recommended_tasks"), list) else []
    cfg["recommended_tasks"] = [t for t in existing if isinstance(t, dict) and str(t.get("id")) != task_id]
    cfg["dismissed_recommendations"] = sorted(dismissed)
    _write_project_json(target, cfg)
    return JSONResponse(content={"ok": True, "task_id": task_id})
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `python3 -m pytest tests/test_recommendations_manage.py -k "recommendation_delete" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add dev/project_routes.py tests/test_recommendations_manage.py
git commit -m "feat(project): recommendation delete (dismiss) endpoint"
```

---

### Task 6: codex 分析生成端点

**Files:**
- Modify: `dev/project_routes.py`
- Test: `tests/test_recommendations_manage.py`

**Interfaces:**
- Consumes: `TaskExecutor(cfg).run_summary_analysis`、`_extract_codex_tasks`、`_merge_codex_recommendations`、`_project_task_catalog`。
- Produces: `POST /api/clawmate/project/{root}/{project}/recommendations/analyze` → `{ok: True, recommended_tasks: [...]}` 或 `{ok: False, detail}`。

- [ ] **Step 1: 写失败测试**

追加:
```python
class _FakeExecutor:
    def __init__(self, result): self._result = result
    def run_summary_analysis(self, message, cwd, timeout_seconds=90): return self._result


def test_recommendations_analyze_success(_rec_proj, monkeypatch):
    import project_routes as PR
    from task_executor import TaskExecutor
    monkeypatch.setattr(PR, "_project_target", lambda root, project: _rec_proj)
    monkeypatch.setattr(PR, "TaskExecutor", lambda cfg: _FakeExecutor(
        {"ok": True, "backend": "codex", "output": '[{"label":"做甲","id":"a"}]', "error": "", "code": 0}))
    monkeypatch.setattr(PR, "load_cfg", lambda: SimpleNamespace())
    res = _client().post("/api/clawmate/project/r/proj/recommendations/analyze")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    ids = [t["id"] for t in data["recommended_tasks"]]
    assert "a" in ids


def test_recommendations_analyze_failure(_rec_proj, monkeypatch):
    import project_routes as PR
    monkeypatch.setattr(PR, "_project_target", lambda root, project: _rec_proj)
    monkeypatch.setattr(PR, "TaskExecutor", lambda cfg: _FakeExecutor(
        {"ok": False, "backend": "", "output": "", "error": "codex: timeout", "code": -1}))
    monkeypatch.setattr(PR, "load_cfg", lambda: SimpleNamespace())
    res = _client().post("/api/clawmate/project/r/proj/recommendations/analyze")
    assert res.status_code == 502
    assert res.json()["ok"] is False


def test_recommendations_analyze_unparseable(_rec_proj, monkeypatch):
    import project_routes as PR
    monkeypatch.setattr(PR, "_project_target", lambda root, project: _rec_proj)
    monkeypatch.setattr(PR, "TaskExecutor", lambda cfg: _FakeExecutor(
        {"ok": True, "backend": "codex", "output": "garbage no json", "error": "", "code": 0}))
    monkeypatch.setattr(PR, "load_cfg", lambda: SimpleNamespace())
    res = _client().post("/api/clawmate/project/r/proj/recommendations/analyze")
    assert res.status_code == 422
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `python3 -m pytest tests/test_recommendations_manage.py -k "recommendations_analyze" -v`
Expected: FAIL —— `404`/`405`(路由不存在)

- [ ] **Step 3: 实现**

`dev/project_routes.py` 顶部常量区新增:
```python
_CODEK_ANALYZE_PROMPT = (
    "你是项目分析助手。用 sumi/superpower/productmanager 等技能深入分析当前项目（仅限当前目录），"
    "识别最值得交给 Agent 执行的下一步任务。只输出一个 JSON 数组，不要解释文字。每项字段："
    "id(短 kebab)、label(中文短标题)、prompt(给执行 Agent 的完整指令)、kind(plan|maintenance|documentation|meeting|research)、"
    "frequency(0)。只基于项目真实状态与文档，不要编造。"
)
```
在 `project_recommendation_delete` 新增:
```python
@router.post("/api/clawmate/project/{root}/{project}/recommendations/analyze")
async def project_recommendations_analyze(root: str, project: str):
    """Generate recommendations by analyzing the project with the project-panel backend."""
    try:
        target = _project_target(root, project)
    except (ValueError, PermissionError):
        raise HTTPException(status_code=403, detail="Forbidden")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    from task_executor import TaskExecutor
    cfg = load_cfg()
    result = TaskExecutor(cfg).run_summary_analysis(_CODEK_ANALYZE_PROMPT, cwd=str(target), timeout_seconds=90)
    if not result.get("ok"):
        return JSONResponse(status_code=502, content={"ok": False, "detail": result.get("error") or "codex 分析失败"})
    try:
        new_tasks = _extract_codex_tasks(result.get("output") or "")
    except (ValueError, json.JSONDecodeError) as exc:
        return JSONResponse(status_code=422, content={"ok": False, "detail": f"无法解析 codex 输出：{exc}"})
    if not new_tasks:
        return JSONResponse(content={"ok": True, "recommended_tasks": _project_task_catalog(target), "detail": "codex 未返回可执行任务"})
    merged = _merge_codex_recommendations(target, new_tasks)
    return JSONResponse(content={"ok": True, "recommended_tasks": merged})
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `python3 -m pytest tests/test_recommendations_manage.py -k "recommendations_analyze" -v`
Expected: PASS(3 项通过)

- [ ] **Step 5: 提交**

```bash
git add dev/project_routes.py tests/test_recommendations_manage.py
git commit -m "feat(project): codex recommendations analyze endpoint"
```

---

### Task 7: 前端 —— 共享渲染器加「分析项目」+ 每项「删除」

**Files:**
- Modify: `dev/static/js/project-panel.js`、`dev/static/css/style.css`
- Test: `tests/test_project_panel_shared.py`(更新字符串断言)

**Interfaces:**
- Consumes: 共享 `mount.render()` 内的 `request(endpoint(path))`、`notify(msg)`、`refresh()`。
- Produces: 推荐区 `data-project-analyze` 按钮、每项 `data-recommend-delete="<id>"` 按钮及其 handler。

- [ ] **Step 1: 写失败测试**

更新 `tests/test_project_panel_shared.py`,追加断言:
```python
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_recommendation_controls_present():
    js = (ROOT / "dev/static/js/project-panel.js").read_text(encoding="utf-8")
    assert "data-project-analyze" in js
    assert "data-recommend-delete" in js
    assert "recommendations/analyze" in js
    assert "recommendations/" in js and "delete" in js
```
(若无现成 `pytest`/`Path` 依赖,先在此文件顶部补齐。)

- [ ] **Step 2: 运行测试,确认失败**

Run: `python3 -m pytest tests/test_project_panel_shared.py -k "recommendation_controls" -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`dev/static/js/project-panel.js` 的 `render()` 里,把推荐区那段(当前 line 42)替换为:
```js
      html += '<section class="project-panel-section"><div class="project-panel-section-head"><b>推荐任务</b><button class="project-panel-action" data-project-analyze>分析项目（Codex）</button></div><p class="project-panel-hint">来自项目配置；规则提示不作为可执行任务。</p><ul class="recommended-list">' + (recs.map(function (r) { return '<li><span><strong>' + esc(r.label) + '</strong><small>频率 ' + (r.frequency || 0) + ' · ' + (r.estimated_minutes != null ? esc(String(r.estimated_minutes)) + ' 分钟' : '时长未知') + '</small></span><span class="recommend-actions"><button class="project-panel-action" data-project-task="' + esc(r.id) + '">执行</button><button class="project-panel-action" data-recommend-delete="' + esc(r.id) + '">删除</button></span></li>'; }).join('') || '<li>暂无可执行推荐任务</li>') + '</ul></section><section class="project-panel-section"><b>CLAWLIST</b><ul class="claw-list">' + (projectTasks.filter(function (item) { return !item.completed; }).map(function (item) { return '<li class="claw-row"><span class="claw-check" aria-hidden="true"></span><span class="claw-text">' + esc(item.task) + '</span><button class="project-panel-action" data-clawlist-task="' + esc(item.task) + '">完成</button></li>'; }).join('') || '<li>暂无未完成任务</li>');
```
在 `render()` 内、`renderRuns();`(当前 line 48)之前插入 handler 绑定:
```js
      var analyzeBtn = body.querySelector('[data-project-analyze]');
      if (analyzeBtn) analyzeBtn.onclick = async function () {
        analyzeBtn.disabled = true; analyzeBtn.textContent = '分析中…';
        var res = await request(endpoint('/recommendations/analyze'), {method:'POST'});
        analyzeBtn.disabled = false; analyzeBtn.textContent = '分析项目（Codex）';
        if (res.ok) { notify('项目分析完成，推荐已更新'); await refresh(); }
        else { var detail = ''; try { detail = (await res.json()).detail || ''; } catch (_) {} notify('项目分析失败' + (detail ? '：' + detail : '')); }
      };
      body.querySelectorAll('[data-recommend-delete]').forEach(function (button) {
        button.onclick = async function () {
          button.disabled = true;
          var id = button.getAttribute('data-recommend-delete');
          var res = await request(endpoint('/recommendations/' + encodeURIComponent(id) + '/delete'), {method:'POST'});
          if (res.ok) { notify('推荐任务已删除'); await refresh(); }
          else { button.disabled = false; notify('无法删除推荐任务'); }
        };
      });
```

`dev/static/css/style.css` 新增(放在 `.project-panel-section` 附近):
```css
.project-panel-section-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.recommend-actions { display: flex; gap: 6px; align-items: center; }
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `python3 -m pytest tests/test_project_panel_shared.py -k "recommendation_controls" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add dev/static/js/project-panel.js dev/static/css/style.css tests/test_project_panel_shared.py
git commit -m "feat(panel): codex analyze + delete buttons for recommendations"
```

---

### Task 8: 回归与收尾

**Files:**
- 无新增;跑全量。

**Interfaces:** 无。

- [ ] **Step 1: 全量测试**

Run: `python3 -m pytest -q`
Expected: 基线 312(或 +新增)无失败;新增用例通过。

- [ ] **Step 2: 前端语法校验**

Run: `node --check dev/static/js/project-panel.js`
Expected: 无输出(OK)。

- [ ] **Step 3: 提交收尾(如有微调)**

```bash
git add -A
git commit -m "test: project recommendations & config cleanup" || echo "nothing to commit"
```

---

## Self-Review

**1. Spec coverage:** spec 的目标/非目标逐条对应——
- `agent.project_backend`：Task 1 ✅;默认 auto(codex 优先兜底)Task 1 + Global Constraints ✅。
- 推荐删除(持久、默认任务不复活)：Task 4(`_project_task_catalog` 过滤 + `_merge_codex_recommendations`)+ Task 5(端点)✅。
- codex 生成(手动按钮 + `cli -p` + 解析合并)：Task 2 + 3 + 6 + 7 ✅。
- 前端仅共享渲染器：Task 7 ✅。
- 本轮不做 runs/clawlist/`/tasks/run`：未含对应任务 ✅。

**2. Placeholder scan:** 所有步骤含完整代码/命令/期望输出;无 TBD/TODO。

**3. Type consistency:** `run_summary_analysis` 返回 dict 键 `ok/backend/output/error/code`，在 Task 6、Task 2 测试中一致;`_extract_codex_tasks` 返回 id/label/prompt/kind/frequency/source，`_merge_codex_recommendations` 消费 source=codex;端点路径前缀 `.../recommendations/{id}/delete` 与 Task 7 前端 `endpoint('/recommendations/'+encodeURIComponent(id)+'/delete')` 一致;`.../recommendations/analyze` 一致。
