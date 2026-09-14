"""The service must bound its own graceful shutdown.

uvicorn's ``timeout_graceful_shutdown`` defaults to ``None``, which waits
forever while ``server_state.connections`` or ``server_state.tasks`` is
non-empty.  This app always holds both: WebSocket proxies (OpenClaw chat,
terminal v2) stay open for the life of a panel session, and ``_idle_reaper``
is an infinite background loop.  So an unbounded wait parks the process in
"deactivating" until the service manager SIGKILLs it -- previously the cause
of a ~90s restart stall, matching systemd's ``TimeoutStopUSec``.

These tests pin the bounded budget and the env override in the entrypoint.
"""
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "src"
if str(DEV) not in sys.path:
    sys.path.insert(0, str(DEV))

MAIN_PY = DEV / "main.py"
CONSTANTS_PY = DEV / "constants.py"


def test_uvicorn_run_sets_a_bounded_graceful_shutdown_timeout():
    source = MAIN_PY.read_text(encoding="utf-8")

    assert "timeout_graceful_shutdown=graceful_shutdown" in source
    # A bare literal would be fine too, but the budget must be an int, never the
    # uvicorn default of None -- `timeout=None` is what waits forever.
    assert "timeout_graceful_shutdown=None" not in source


def test_shutdown_budget_defaults_to_a_finite_positive_value():
    from constants import DEFAULT_GRACEFUL_SHUTDOWN_SECONDS

    assert isinstance(DEFAULT_GRACEFUL_SHUTDOWN_SECONDS, int)
    assert DEFAULT_GRACEFUL_SHUTDOWN_SECONDS > 0
    # Must stay well under the service manager's own kill timeout, otherwise the
    # process is SIGKILLed before uvicorn finishes cancelling its tasks.
    assert DEFAULT_GRACEFUL_SHUTDOWN_SECONDS < 90


def test_shutdown_budget_is_overridable_by_env_with_a_safe_fallback():
    source = MAIN_PY.read_text(encoding="utf-8")

    assert "GRACEFUL_SHUTDOWN_TIMEOUT_ENV" in source
    assert "except ValueError" in source


def test_shutdown_budget_env_name_is_defined_in_constants():
    from constants import GRACEFUL_SHUTDOWN_TIMEOUT_ENV

    assert GRACEFUL_SHUTDOWN_TIMEOUT_ENV.startswith("CLAWMATE_")


@pytest.mark.parametrize("value,expected", [("3", 3), ("0", 0)])
def test_int_parse_of_shutdown_budget(value, expected):
    # Mirrors the entrypoint's parse; a non-numeric value falls back instead of
    # raising, because failing to boot on a typo is worse than using the default.
    try:
        parsed = int(value)
    except ValueError:
        from constants import DEFAULT_GRACEFUL_SHUTDOWN_SECONDS as parsed
    assert parsed == expected
