"""Governance skeleton scaffolding for `project/convert`.

`project.harness_template_dir` points at the governance repo's
`project-template/` (the parent of `project-harness/`). Converting a plain
directory must lay down `project-harness/` from that template **without ever
overwriting** an existing harness, and must always ensure the `.clawmate/`
runtime subdirectories exist even when no template is configured.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "dev"
if str(DEV) not in sys.path:
    sys.path.insert(0, str(DEV))


def _seed_template(tmp_path: Path) -> Path:
    """Build a minimal governance template mirroring project-template/."""
    tpl = tmp_path / "template"
    harness = tpl / "project-harness"
    (harness / "schemas").mkdir(parents=True)
    (harness / "manifest.yaml").write_text("schema: clawmate.project/v2\n", encoding="utf-8")
    (harness / "workflow.yaml").write_text("schema: clawmate.workflow/v1\n", encoding="utf-8")
    (harness / "roles.yaml").write_text("schema: clawmate.roles/v3\nroles: {}\n", encoding="utf-8")
    (harness / "schemas" / "message.schema.yaml").write_text("schema: clawmate.message/v1\n", encoding="utf-8")
    (tpl / "docs" / "reports").mkdir(parents=True)
    (tpl / "docs" / "reports" / ".gitkeep").write_text("", encoding="utf-8")
    return tpl


def _use_config(tmp_path: Path, monkeypatch, template_dir: str) -> None:
    import config as config_module

    payload = {"project": {}}
    if template_dir:
        payload["project"]["harness_template_dir"] = template_dir
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("CLAWMATE_CONFIG", str(cfg_path))
    config_module.set_config_path(cfg_path)
    config_module.clear_config_cache()


def test_runtime_dirs_created_without_template(tmp_path, monkeypatch):
    import project_routes

    _use_config(tmp_path, monkeypatch, template_dir="")
    target = tmp_path / "proj"
    target.mkdir()

    result = project_routes._scaffold_governance(target)

    for sub in ("state", "tasks", "runs", "logs", "evidence", "audit", "decisions"):
        assert (target / ".clawmate" / sub).is_dir(), sub
    assert result["project_harness"] is False
    assert "not configured" in result["skipped_reason"]


def test_harness_is_seeded_from_template(tmp_path, monkeypatch):
    import project_routes

    tpl = _seed_template(tmp_path)
    _use_config(tmp_path, monkeypatch, template_dir=str(tpl))
    target = tmp_path / "proj"
    target.mkdir()

    result = project_routes._scaffold_governance(target)

    assert result["project_harness"] is True
    assert result["skipped_reason"] == ""
    assert (target / "project-harness" / "manifest.yaml").exists()
    assert (target / "project-harness" / "schemas" / "message.schema.yaml").exists()
    assert (target / "docs" / "reports" / ".gitkeep").exists()


def test_existing_harness_is_never_overwritten(tmp_path, monkeypatch):
    import project_routes

    tpl = _seed_template(tmp_path)
    _use_config(tmp_path, monkeypatch, template_dir=str(tpl))
    target = tmp_path / "proj"
    (target / "project-harness").mkdir(parents=True)
    (target / "project-harness" / "manifest.yaml").write_text(
        "# hand-written, do not clobber\n", encoding="utf-8")

    result = project_routes._scaffold_governance(target)

    assert result["project_harness"] is False
    assert "already exists" in result["skipped_reason"]
    assert "hand-written" in (target / "project-harness" / "manifest.yaml").read_text(encoding="utf-8")


def test_missing_template_dir_is_a_skip_not_an_error(tmp_path, monkeypatch):
    import project_routes

    _use_config(tmp_path, monkeypatch, template_dir=str(tmp_path / "does-not-exist"))
    target = tmp_path / "proj"
    target.mkdir()

    result = project_routes._scaffold_governance(target)

    assert result["project_harness"] is False
    assert "not found" in result["skipped_reason"]
    # Runtime dirs still land: the conversion itself must still succeed.
    assert (target / ".clawmate" / "state").is_dir()


def test_copy_tree_no_clobber_preserves_existing_files(tmp_path):
    import project_routes

    src = tmp_path / "src"
    src.mkdir()
    (src / "keep.txt").write_text("new", encoding="utf-8")
    (src / "fresh.txt").write_text("fresh", encoding="utf-8")
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "keep.txt").write_text("existing", encoding="utf-8")

    written = project_routes._copy_tree_no_clobber(src, dst)

    assert (dst / "keep.txt").read_text(encoding="utf-8") == "existing"
    assert (dst / "fresh.txt").read_text(encoding="utf-8") == "fresh"
    assert written == ["fresh.txt"]


def test_harness_template_dir_reaches_config():
    from config import ProjectConfig, _parse_config

    defaults = ProjectConfig()
    assert defaults.harness_template_dir == ""

    cfg = _parse_config({"project": {"harness_template_dir": "/opt/gov/project-template"}})
    assert cfg.project.harness_template_dir == "/opt/gov/project-template"

    # A partial section keeps the per-key default.
    assert _parse_config({"project": {"git_user_name": "Bob"}}).project.harness_template_dir == ""
