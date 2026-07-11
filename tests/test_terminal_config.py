from dev.config import _parse_config


def test_terminal_defaults_are_safe():
    cfg = _parse_config({})

    assert cfg.agent.replay_bytes == 4 * 1024 * 1024
    assert cfg.agent.scrollback == 10_000
    assert cfg.agent.terminal_idle_seconds == 24 * 3600
    assert cfg.agent.terminal_max_lifetime_seconds == 24 * 3600


def test_terminal_limits_are_clamped():
    cfg = _parse_config({"agent": {"replay_bytes": 99_000_000, "scrollback": 999_999}})

    assert cfg.agent.replay_bytes == 16 * 1024 * 1024
    assert cfg.agent.scrollback == 50_000


def test_resize_lease_seconds_is_clamped():
    cfg = _parse_config({"agent": {"resize_lease_seconds": 99}})

    assert cfg.agent.resize_lease_seconds == 60
