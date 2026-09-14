"""The generated `AGENTS.md` must describe the directory set that really exists.

Convert writes `AGENTS.md` from `_AGENTS_TEMPLATE`. That template previously
listed `.clawmate/feedback.json / feedback.audit.jsonl / sessions / cache` as
the runtime surface -- files and dirs the converter does not create and that
consumers create lazily. A project doc that names directories the project does
not have sends agents looking for things that are not there, so this locks the
template to the converged set.

Naming note: the skill's `dev/` and `test/` are the ClawMate-side working
directories; the governance contract calls them `src/` and `tests/`. The
template states that mapping explicitly rather than leaving agents to guess.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT / "dev") not in sys.path:
    sys.path.insert(0, str(ROOT / "dev"))


def test_agents_template_names_the_governance_anchors():
    import project_routes

    tpl = project_routes._AGENTS_TEMPLATE

    assert "project-harness/" in tpl
    for sub in ("state", "tasks", "evidence", "audit"):
        assert f"`{sub}/`" in tpl, sub


def test_agents_template_does_not_promise_lazily_created_dirs():
    """`sessions/` and `cache/` are created on demand; docs must not imply they exist."""
    import project_routes

    tpl = project_routes._AGENTS_TEMPLATE

    assert "feedback.audit.jsonl" not in tpl
    # If mentioned at all, they must be described as lazily created.
    if "cache/" in tpl:
        assert "按需" in tpl


def test_agents_template_maps_working_dirs_to_contract_names():
    import project_routes

    tpl = project_routes._AGENTS_TEMPLATE

    assert "`src/`" in tpl and "`tests/`" in tpl


def test_agents_template_does_not_reintroduce_legacy_reports_path():
    import project_routes

    tpl = project_routes._AGENTS_TEMPLATE

    assert ".clawmate/reports" not in tpl
    assert "docs/reports" in tpl
