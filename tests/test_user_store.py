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


def test_reset_password_updates_named_user(tmp_path: Path):
    store = UserStore(tmp_path / "users.json", tmp_path)

    store.reset_password("admin", "replacement-password")

    assert store.get_administrator() is not None
    assert store.authenticate("admin", "replacement-password") is not None
    assert store.authenticate("admin", "password") is None


def test_read_tolerates_a_root_that_no_longer_exists(tmp_path: Path):
    store = UserStore(tmp_path / "users.json", tmp_path)
    (tmp_path / "projects").mkdir()
    store.create_user("writer", "writer-password", ["projects"])
    (tmp_path / "projects").rmdir()

    assert store.get_by_username("writer") is not None
    assert store.authenticate("writer", "writer-password") is not None


def test_admin_can_still_log_in_after_a_grant_target_disappears(tmp_path: Path):
    store = UserStore(tmp_path / "users.json", tmp_path)
    (tmp_path / "projects").mkdir()
    store.create_user("writer", "writer-password", ["projects"])
    (tmp_path / "projects").rmdir()

    assert store.authenticate("admin", "password") is not None


def test_update_user_replaces_root_ids(tmp_path: Path):
    store = UserStore(tmp_path / "users.json", tmp_path)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    writer = store.create_user("writer", "writer-password", ["a"])

    updated = store.update_user(writer.id, root_ids=["b"])

    assert updated.root_ids == ("b",)


def test_admin_accounts_keep_empty_root_ids(tmp_path: Path):
    store = UserStore(tmp_path / "users.json", tmp_path)
    (tmp_path / "a").mkdir()

    admin = store.create_user("root2", "root2-password", ["a"], is_admin=True)

    assert admin.is_admin is True
    assert admin.root_ids == ()


def test_create_user_rejects_a_root_id_outside_the_allowed_charset(tmp_path: Path):
    store = UserStore(tmp_path / "users.json", tmp_path)

    with pytest.raises(ValueError, match="Invalid root id"):
        store.create_user("writer", "writer-password", ["../outside"])
