"""The generated `AGENTS.md` must describe the directory set that really exists.

Convert writes `AGENTS.md` from `_AGENTS_TEMPLATE`. That template previously
listed `.clawmate/feedback.json / feedback.audit.jsonl / sessions / cache` as
the runtime surface -- files and dirs the converter does not create and that
consumers create lazily. A project doc that names directories the project does
not have sends agents looking for things that are not there, so this locks the
template to the converged set.

Naming note: `src/` and `tests/` are the single set of names -- both the
ClawMate skill and the governance contract (`project-harness/roles.yaml` binds
`src/**` / `tests/**`) use them. They must not diverge again: a contract glob
that names a directory the project does not have silently authorizes nothing.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


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


def test_agents_template_uses_contract_dir_names():
    """`src/`/`tests/` are the only names; the old src/test aliases must not return."""
    import project_routes

    tpl = project_routes._AGENTS_TEMPLATE

    assert "`src/`" in tpl and "`tests/`" in tpl
    assert "`dev/`" not in tpl and "`test/`" not in tpl


def test_agents_template_does_not_reintroduce_legacy_reports_path():
    import project_routes

    tpl = project_routes._AGENTS_TEMPLATE

    assert ".clawmate/reports" not in tpl
    assert "docs/reports" in tpl


def test_agents_template_does_not_reintroduce_collect_dir():
    """`collect/` merged into `research/`; it had no code consumer and no
    distinct purpose. A template that still offers it would re-split one
    directory's job across two names in every new project."""
    import project_routes

    assert "collect/" not in project_routes._AGENTS_TEMPLATE
    assert "collect/" not in project_routes._CLAWLIST_TEMPLATE
