"""`project.git_user_email` / `project.git_user_name` must reach `cfg.project`.

`_parse_config()` declared `project=field(default_factory=ProjectConfig)` but
never passed `project=` to `AppConfig(...)`, so the dataclass defaults always
won at runtime.  `dev/project_routes.py` reads `cfg.project.git_user_email` /
`cfg.project.git_user_name` to author project commits, so editing the section
in `config.json` silently changed nothing -- files landed under the default
identity while the file said otherwise.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "dev"
if str(DEV) not in sys.path:
    sys.path.insert(0, str(DEV))


def test_explicit_project_values_reach_the_config():
    from config import _parse_config

    cfg = _parse_config({
        "project": {"git_user_email": "dev@example.com", "git_user_name": "Alice"}
    })

    assert cfg.project.git_user_email == "dev@example.com"
    assert cfg.project.git_user_name == "Alice"


def test_missing_project_section_keeps_defaults():
    from config import ProjectConfig, _parse_config

    defaults = ProjectConfig()
    cfg = _parse_config({})

    assert cfg.project.git_user_email == defaults.git_user_email
    assert cfg.project.git_user_name == defaults.git_user_name


def test_partial_project_section_fills_per_key_defaults():
    from config import ProjectConfig, _parse_config

    defaults = ProjectConfig()
    cfg = _parse_config({"project": {"git_user_name": "Bob"}})

    assert cfg.project.git_user_name == "Bob"
    assert cfg.project.git_user_email == defaults.git_user_email


def test_project_routes_git_identity_follows_config(monkeypatch, tmp_path):
    """The consumer must see the parsed values, not the dataclass defaults."""
    import config as config_module
    import project_routes

    payload = {
        "project": {"git_user_email": "ci@example.com", "git_user_name": "CI Bot"}
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(payload), encoding="utf-8")

    config_module.set_config_path(cfg_path)
    config_module.clear_config_cache()
    try:
        assert project_routes._git_identity() == ("ci@example.com", "CI Bot")
    finally:
        config_module.clear_config_cache()


def test_live_config_project_section_matches_parsed_config():
    """A live config.json with a project section must not be silently ignored."""
    live = ROOT / "config.json"
    if not live.exists():
        pytest.skip("no live config.json in this checkout")

    raw = json.loads(live.read_text(encoding="utf-8"))
    section = raw.get("project")
    if not isinstance(section, dict):
        pytest.skip("live config.json has no project section")

    from config import _parse_config

    cfg = _parse_config(raw)
    if "git_user_email" in section:
        assert cfg.project.git_user_email == section["git_user_email"]
    if "git_user_name" in section:
        assert cfg.project.git_user_name == section["git_user_name"]
