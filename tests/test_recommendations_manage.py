import json
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dev"))

from main import app

from types import SimpleNamespace
import auth
from config import set_config_path, clear_config_cache, load as load_cfg
from task_executor import TaskExecutor
from project_routes import _extract_codex_tasks, _project_task_catalog, _merge_codex_recommendations
import project_routes as PR


@pytest.fixture()
def _rec_proj(tmp_path):
    d = tmp_path / "proj"
    (d / ".clawmate").mkdir(parents=True)
    (d / ".clawmate" / "project.json").write_text("{}", encoding="utf-8")
    return d


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


def test_run_summary_analysis_claude_uses_skip_permissions(monkeypatch):
    class FakeCfg:
        class Agent:
            project_backend = "claude"
            env = {}
        agent = Agent()
    captured = {}
    import subprocess
    def fake_binary(backend):
        return "claude" if backend == "claude" else None
    def fake_run(args, **kw):
        captured["args"] = args
        return SimpleNamespace(returncode=0, stdout="[]", stderr="", code=0)
    monkeypatch.setattr(TaskExecutor, "_cli_binary", lambda self, b: fake_binary(b))
    monkeypatch.setattr(subprocess, "run", fake_run)
    res = TaskExecutor(FakeCfg()).run_summary_analysis("hi", cwd=".")
    assert res["ok"] is True
    assert captured["args"] == ["claude", "--dangerously-skip-permissions", "-p", "hi"]


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


def test_catalog_suppresses_dismissed_default_without_raw_entry(_rec_proj):
    cfg = PR._read_project_json(_rec_proj)
    cfg["dismissed_recommendations"] = ["commit_version"]
    PR._write_project_json(_rec_proj, cfg)
    ids = [t["id"] for t in _project_task_catalog(_rec_proj)]
    assert "commit_version" not in ids


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


def test_merge_codex_respects_label_derived_dismissal(_rec_proj):
    cfg = PR._read_project_json(_rec_proj)
    cfg["recommended_tasks"] = [
        {"label": "Foo", "source": "project_json"},
        {"id": "bar", "label": "保留", "source": "project_json"},
    ]
    cfg["dismissed_recommendations"] = ["Foo"]
    PR._write_project_json(_rec_proj, cfg)
    merged = _merge_codex_recommendations(_rec_proj, [
        {"id": "new1", "label": "新增", "prompt": "p", "source": "codex"},
    ])
    ids = [t["id"] for t in merged]
    assert "Foo" not in ids
    assert "bar" in ids
    assert "new1" in ids


def _client():
    return TestClient(app)


def test_recommendation_delete_persists_dismissed(_rec_proj, monkeypatch):
    import project_routes as PR
    monkeypatch.setattr(auth, "is_auth_enabled", lambda config=None: False)
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
    monkeypatch.setattr(auth, "is_auth_enabled", lambda config=None: False)
    monkeypatch.setattr(PR, "_project_target", lambda root, project: _rec_proj)
    res = _client().post("/api/clawmate/project/r/proj/recommendations/missing/delete")
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_recommendation_delete_removes_idless_label_entry(_rec_proj, monkeypatch):
    import project_routes as PR
    monkeypatch.setattr(auth, "is_auth_enabled", lambda config=None: False)
    monkeypatch.setattr(PR, "_project_target", lambda root, project: _rec_proj)
    PR._write_project_json(_rec_proj, {
        "recommended_tasks": [{"label": "Foo", "source": "discover"}],
        "dismissed_recommendations": [],
    })
    res = _client().post("/api/clawmate/project/r/proj/recommendations/Foo/delete")
    assert res.status_code == 200
    cfg = PR._read_project_json(_rec_proj)
    assert cfg["recommended_tasks"] == []
    assert "Foo" in cfg["dismissed_recommendations"]


class _FakeExecutor:
    def __init__(self, result): self._result = result
    def run_summary_analysis(self, message, cwd, timeout_seconds=90): return self._result


def test_recommendations_analyze_success(_rec_proj, monkeypatch):
    import project_routes as PR
    import task_executor as TE
    monkeypatch.setattr(auth, "is_auth_enabled", lambda config=None: False)
    monkeypatch.setattr(PR, "_project_target", lambda root, project: _rec_proj)
    monkeypatch.setattr(TE, "TaskExecutor", lambda cfg: _FakeExecutor(
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
    import task_executor as TE
    monkeypatch.setattr(auth, "is_auth_enabled", lambda config=None: False)
    monkeypatch.setattr(PR, "_project_target", lambda root, project: _rec_proj)
    monkeypatch.setattr(TE, "TaskExecutor", lambda cfg: _FakeExecutor(
        {"ok": False, "backend": "", "output": "", "error": "codex: timeout", "code": -1}))
    monkeypatch.setattr(PR, "load_cfg", lambda: SimpleNamespace())
    res = _client().post("/api/clawmate/project/r/proj/recommendations/analyze")
    assert res.status_code == 502
    assert res.json()["ok"] is False


def test_recommendations_analyze_unparseable(_rec_proj, monkeypatch):
    import project_routes as PR
    import task_executor as TE
    monkeypatch.setattr(auth, "is_auth_enabled", lambda config=None: False)
    monkeypatch.setattr(PR, "_project_target", lambda root, project: _rec_proj)
    monkeypatch.setattr(TE, "TaskExecutor", lambda cfg: _FakeExecutor(
        {"ok": True, "backend": "codex", "output": "garbage no json", "error": "", "code": 0}))
    monkeypatch.setattr(PR, "load_cfg", lambda: SimpleNamespace())
    res = _client().post("/api/clawmate/project/r/proj/recommendations/analyze")
    assert res.status_code == 422
