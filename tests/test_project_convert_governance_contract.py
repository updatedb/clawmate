"""The web UI's "转换为项目" path must match the converter's governance behaviour.

`project/convert` lays down a `project-harness/` skeleton, but a blank or
missing `project.harness_template_dir` makes that a reported *skip* rather
than an error. The UI must therefore (1) tell the user the harness will be
created, and (2) surface `governance.skipped_reason` when it did not land --
a project that silently lacks its governance contract is the failure mode
this locks against.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _app_js() -> str:
    return (ROOT / "dev/static/js/app.js").read_text(encoding="utf-8")


def _convert_block() -> str:
    src = _app_js()
    start = src.index("'转换为项目'")
    end = src.index("addItem('download'", start)
    return src[start:end]


def test_confirm_dialog_announces_project_harness():
    block = _convert_block()
    assert "project-harness/（治理契约骨架）" in block


def test_skipped_harness_is_surfaced_not_swallowed():
    block = _convert_block()
    # The skip path must be inspected...
    assert "data.governance" in block
    assert "project_harness" in block
    # ...and reported with its reason rather than silently ignored.
    assert "skipped_reason" in block
    assert "alert(" in block


def test_ui_does_not_claim_harness_on_a_skip_path():
    """The success toast must not assert the harness landed unconditionally."""
    block = _convert_block()
    toast = "updateStatus('已转换为项目：'"
    assert toast in block
    # The harness check must come after the toast, so the toast never claims it.
    assert block.index(toast) < block.index("data.governance")
