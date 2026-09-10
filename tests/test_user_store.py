from __future__ import annotations

from pathlib import Path

import pytest

from dev.config import _parse_config
from dev.user_store import UserStore, resolve_granted_root


def test_config_parses_one_system_root(tmp_path: Path):
    cfg = _parse_config({"system_root_dir": str(tmp_path)})

    assert cfg.system_root_dir == tmp_path.resolve()


def test_missing_user_file_bootstraps_forced_change_admin(tmp_path: Path):
    store = UserStore(tmp_path / "users.json", tmp_path)

    user = store.authenticate("admin", "password")

    assert user is not None
    assert user.is_admin is True
    assert user.must_change_password is True


def test_granted_root_rejects_symlink_escape(tmp_path: Path):
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="outside system root"):
        resolve_granted_root(tmp_path, "escape")
