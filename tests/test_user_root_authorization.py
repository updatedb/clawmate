from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))

from root_auth import LocalAdmin, RootNotAuthorized, authorize_root  # noqa: E402
from root_registry import RootRegistry  # noqa: E402


def _registry(tmp_path: Path) -> RootRegistry:
    (tmp_path / "projects").mkdir(exist_ok=True)
    (tmp_path / "private").mkdir(exist_ok=True)
    registry = RootRegistry(tmp_path / "roots.json", tmp_path)
    registry.create(label="Private", dir="private")
    return registry


def test_admin_gets_the_system_root_itself(tmp_path: Path):
    registry = _registry(tmp_path)

    resolved = authorize_root(LocalAdmin(), ".", registry, tmp_path)

    assert resolved == tmp_path.resolve()


def test_admin_gets_any_registered_root(tmp_path: Path):
    registry = _registry(tmp_path)

    assert authorize_root(LocalAdmin(), "private", registry, tmp_path) == (tmp_path / "private").resolve()


def test_admin_cannot_resolve_an_unregistered_root(tmp_path: Path):
    registry = _registry(tmp_path)

    with pytest.raises(RootNotAuthorized):
        authorize_root(LocalAdmin(), "nope", registry, tmp_path)


def test_regular_user_gets_only_granted_roots(tmp_path: Path):
    registry = _registry(tmp_path)

    class Writer:
        is_admin = False
        root_ids = ("private",)

    assert authorize_root(Writer(), "private", registry, tmp_path) == (tmp_path / "private").resolve()
    with pytest.raises(RootNotAuthorized):
        authorize_root(Writer(), "projects", registry, tmp_path)


def test_regular_user_cannot_claim_the_system_root(tmp_path: Path):
    registry = _registry(tmp_path)

    class Writer:
        is_admin = False
        root_ids = ("private",)

    with pytest.raises(RootNotAuthorized):
        authorize_root(Writer(), ".", registry, tmp_path)


def test_missing_user_is_rejected(tmp_path: Path):
    registry = _registry(tmp_path)

    with pytest.raises(RootNotAuthorized):
        authorize_root(None, "private", registry, tmp_path)


def test_blank_root_id_is_rejected(tmp_path: Path):
    registry = _registry(tmp_path)

    with pytest.raises(RootNotAuthorized):
        authorize_root(LocalAdmin(), "", registry, tmp_path)


def test_granted_root_with_vanished_directory_is_rejected_not_crashed(tmp_path: Path):
    registry = _registry(tmp_path)
    (tmp_path / "private").rmdir()

    class Writer:
        is_admin = False
        root_ids = ("private",)

    with pytest.raises(RootNotAuthorized):
        authorize_root(Writer(), "private", registry, tmp_path)


def test_authorization_failure_is_a_permission_error(tmp_path: Path):
    registry = _registry(tmp_path)

    with pytest.raises(PermissionError):
        authorize_root(None, "private", registry, tmp_path)


def test_local_admin_serialises_like_a_real_account():
    summary = LocalAdmin().public()

    assert summary == {"id": "", "username": "local-admin", "is_admin": True,
                       "must_change_password": False, "root_ids": []}
