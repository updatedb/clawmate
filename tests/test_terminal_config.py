from dev.config import _parse_config


def test_terminal_v2_defaults_are_safe():
    cfg = _parse_config({})

    assert cfg.agent.terminal_v2 is True
    assert cfg.agent.renderer == "auto"
    assert cfg.agent.replay_bytes == 4 * 1024 * 1024
    assert cfg.agent.scrollback == 10_000
    assert cfg.agent.terminal_idle_seconds == 24 * 3600
    assert cfg.agent.terminal_max_lifetime_seconds == 24 * 3600


def test_terminal_limits_are_clamped():
    cfg = _parse_config({"agent": {"replay_bytes": 99_000_000, "scrollback": 999_999}})

    assert cfg.agent.replay_bytes == 16 * 1024 * 1024
    assert cfg.agent.scrollback == 50_000


def test_terminal_renderer_and_resize_lease_are_validated():
    cfg = _parse_config({"agent": {"renderer": "canvas", "resize_lease_seconds": 99}})

    assert cfg.agent.renderer == "auto"
    assert cfg.agent.resize_lease_seconds == 60


def test_terminal_v2_string_flag_is_parsed_without_truthiness_bug():
    assert _parse_config({"agent": {"terminal_v2": "false"}}).agent.terminal_v2 is False
    assert _parse_config({"agent": {"terminal_v2": "true"}}).agent.terminal_v2 is True
