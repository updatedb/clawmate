"""Governance skeleton scaffolding + post-convert validation for `project/convert`.

`project.harness_template_dir` points at the governance repo's
`project-template/` (the parent of `project-harness/`). Converting a plain
directory must lay down `project-harness/` from that template **without ever
overwriting** an existing harness, and must always ensure the `.clawmate/`
runtime subdirectories that consumers actually depend on exist -- even when no
template is configured.

The runtime-dir set is deliberately small: each entry must have a real
consumer. `.clawmate/reports/` in particular must never be created, because
formal reports belong in `docs/reports/` and the governance delivery check
treats `.clawmate/reports/` as a legacy path to reject.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "src"
if str(DEV) not in sys.path:
    sys.path.insert(0, str(DEV))


def _seed_template(tmp_path: Path) -> Path:
    """Build a minimal governance template mirroring project-template/."""
    tpl = tmp_path / "template"
    harness = tpl / "project-harness"
    (harness / "schemas").mkdir(parents=True)
    (harness / "manifest.yaml").write_text(
        "schema: clawmate.project/v2\nproject:\n  id: project-alpha\n", encoding="utf-8")
    (harness / "workflow.yaml").write_text(
        "schema: clawmate.workflow/v1\nobjective: 明确本项目要达成的目标\n", encoding="utf-8")
    (harness / "roles.yaml").write_text(
        "schema: clawmate.roles/v3\nroles: {}\n", encoding="utf-8")
    (harness / "acceptance.yaml").write_text(
        "schema: clawmate.acceptance/v2\ncriteria: []\n", encoding="utf-8")
    (harness / "schemas" / "message.schema.yaml").write_text(
        "schema: clawmate.message/v1\n", encoding="utf-8")
    (tpl / "docs" / "reports").mkdir(parents=True)
    (tpl / "docs" / "reports" / ".gitkeep").write_text("", encoding="utf-8")
    # A stray `reports/` here is the legacy formal-report path.
    for stale in ("reports", "decisions", "schemas"):
        (tpl / ".clawmate" / stale).mkdir(parents=True, exist_ok=True)
    (tpl / ".clawmate" / "README.md").write_text("# .clawmate\n", encoding="utf-8")
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


def test_runtime_dirs_are_only_the_ones_with_consumers(tmp_path, monkeypatch):
    import project_routes

    _use_config(tmp_path, monkeypatch, template_dir="")
    target = tmp_path / "proj"
    target.mkdir()

    result = project_routes._scaffold_governance(target)

    for sub in ("state", "tasks", "evidence", "audit"):
        assert (target / ".clawmate" / sub).is_dir(), sub
    assert result["project_harness"] is False
    assert "not configured" in result["skipped_reason"]


def test_legacy_and_lazily_created_dirs_are_never_seeded(tmp_path, monkeypatch):
    """Empty scaffolding is a liability: no dir without a hard dependency."""
    import project_routes

    _use_config(tmp_path, monkeypatch, template_dir="")
    target = tmp_path / "proj"
    target.mkdir()

    project_routes._scaffold_governance(target)

    # reports = legacy formal-report path; the rest are created on demand by
    # their own consumers, so seeding them would leave dead directories.
    for stale in ("reports", "decisions", "schemas", "runs", "logs", "sessions", "cache"):
        assert not (target / ".clawmate" / stale).exists(), stale


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


def test_template_only_runtime_dirs_do_not_leak(tmp_path, monkeypatch):
    """The template's stale .clawmate/ dirs must not be copied into projects."""
    import project_routes

    tpl = _seed_template(tmp_path)
    _use_config(tmp_path, monkeypatch, template_dir=str(tpl))
    target = tmp_path / "proj"
    target.mkdir()

    project_routes._scaffold_governance(target)

    for stale in ("reports", "decisions", "schemas"):
        assert not (target / ".clawmate" / stale).exists(), stale
    # The governance repo's own README is not shipped into projects.
    assert not (target / ".clawmate" / "README.md").exists()


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


def test_seed_template_preserves_existing_files(tmp_path):
    import project_routes

    tpl = tmp_path / "tpl"
    (tpl / "project-harness").mkdir(parents=True)
    (tpl / "project-harness" / "keep.yaml").write_text("new\n", encoding="utf-8")
    (tpl / "project-harness" / "fresh.yaml").write_text("fresh\n", encoding="utf-8")
    dst = tmp_path / "dst"
    (dst / "project-harness").mkdir(parents=True)
    (dst / "project-harness" / "keep.yaml").write_text("existing\n", encoding="utf-8")

    written = project_routes._seed_template(tpl, dst)

    assert (dst / "project-harness" / "keep.yaml").read_text(encoding="utf-8") == "existing\n"
    assert (dst / "project-harness" / "fresh.yaml").read_text(encoding="utf-8") == "fresh\n"
    assert written == ["project-harness/fresh.yaml"]


def test_seed_template_ignores_entries_outside_the_allowlist(tmp_path):
    """A whole-tree copy would drag unknown template content into projects."""
    import project_routes

    tpl = tmp_path / "tpl"
    (tpl / "project-harness").mkdir(parents=True)
    (tpl / "project-harness" / "manifest.yaml").write_text("x\n", encoding="utf-8")
    (tpl / "secrets").mkdir()
    (tpl / "secrets" / "token.txt").write_text("nope\n", encoding="utf-8")
    dst = tmp_path / "dst"
    dst.mkdir()

    project_routes._seed_template(tpl, dst)

    assert (dst / "project-harness" / "manifest.yaml").exists()
    assert not (dst / "secrets").exists()


# ── validation ───────────────────────────────────────────────────────

def test_validate_flags_missing_harness_and_docs(tmp_path, monkeypatch):
    import project_routes

    _use_config(tmp_path, monkeypatch, template_dir="")
    target = tmp_path / "proj"
    target.mkdir()

    result = project_routes._validate_project(target)

    assert result["ok"] is False
    assert any("docs" in i for i in result["issues"])
    assert any("project-harness" in i for i in result["issues"])


def test_validate_reports_unfilled_placeholders_as_pending(tmp_path, monkeypatch):
    """Unfilled placeholders are expected post-convert: pending, never an issue."""
    import project_routes

    tpl = _seed_template(tmp_path)
    _use_config(tmp_path, monkeypatch, template_dir=str(tpl))
    target = tmp_path / "proj"
    target.mkdir()

    project_routes._scaffold_governance(target)
    for d in ("PROJECT_NOTE.md", "CLAWLIST.md", "AGENTS.md", ".gitignore"):
        (target / d).write_text("x\n", encoding="utf-8")
    for sub in ("state", "tasks", "evidence", "audit"):
        (target / ".clawmate" / sub).mkdir(parents=True, exist_ok=True)

    result = project_routes._validate_project(target)

    assert result["checks"]["harness_filled"] is False
    assert result["pending"] and any("manifest.yaml" in p for p in result["pending"])
    # Placeholders alone must not declare the project broken.
    assert not any("pending" in i for i in result["issues"])


def test_validate_passes_on_a_filled_project(tmp_path, monkeypatch):
    import project_routes

    tpl = _seed_template(tmp_path)
    _use_config(tmp_path, monkeypatch, template_dir=str(tpl))
    target = tmp_path / "proj"
    target.mkdir()
    project_routes._scaffold_governance(target)
    for d in ("PROJECT_NOTE.md", "CLAWLIST.md", "AGENTS.md", ".gitignore"):
        (target / d).write_text("x\n", encoding="utf-8")
    for sub in ("state", "tasks", "evidence", "audit"):
        (target / ".clawmate" / sub).mkdir(parents=True, exist_ok=True)
    (target / ".git").mkdir()
    # Replace placeholders with real values.
    (target / "project-harness" / "manifest.yaml").write_text(
        "schema: clawmate.project/v2\nproject:\n  id: my-proj\n", encoding="utf-8")
    (target / "project-harness" / "workflow.yaml").write_text(
        "schema: clawmate.workflow/v1\nobjective: 交付 X\n", encoding="utf-8")

    result = project_routes._validate_project(target)

    assert result["ok"] is True, result["issues"]
    assert result["pending"] == []
    assert all(result["checks"].values())


def test_ensure_git_repo_reports_failure_instead_of_swallowing_it(tmp_path, monkeypatch):
    """A silent git failure must surface as a validation issue."""
    import project_routes

    monkeypatch.setattr(project_routes, "_run_git", lambda *a, **k: None)

    assert project_routes._ensure_git_repo(tmp_path) is False


def test_harness_template_dir_reaches_config():
    from config import ProjectConfig, _parse_config

    defaults = ProjectConfig()
    assert defaults.harness_template_dir == ""

    cfg = _parse_config({"project": {"harness_template_dir": "/opt/gov/project-template"}})
    assert cfg.project.harness_template_dir == "/opt/gov/project-template"

    # A partial section keeps the per-key default.
    assert _parse_config({"project": {"git_user_name": "Bob"}}).project.harness_template_dir == ""
