import json
import tempfile
from pathlib import Path
from config import set_config_path, clear_config_cache, load as load_cfg


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
