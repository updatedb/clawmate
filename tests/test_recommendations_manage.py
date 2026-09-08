import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dev"))

from types import SimpleNamespace
from config import set_config_path, clear_config_cache, load as load_cfg
from task_executor import TaskExecutor
from project_routes import _extract_codex_tasks


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
