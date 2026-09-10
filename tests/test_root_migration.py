from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))

from root_migration import MigrationError, migrate_legacy_roots  # noqa: E402


def _workspace(tmp_path: Path, *, outside_dir: str | None = None) -> Path:
    (tmp_path / "helper" / "3gpp").mkdir(parents=True)
    (tmp_path / "webprojects").mkdir()
    roots = [
        {"id": "3gpp", "label": "3GPP Meetings", "dir": str(tmp_path / "helper" / "3gpp"),
         "agent_id": "helper"},
        {"id": "webprojects", "label": "Web Projects", "dir": str(tmp_path / "webprojects"),
         "agent_id": "work"},
    ]
    if outside_dir:
        roots.append({"id": "legacy", "label": "Legacy", "dir": outside_dir, "agent_id": "main"})
    (tmp_path / "config.json").write_text(json.dumps({
        "system_root_dir": str(tmp_path),
        "roots": roots,
    }), encoding="utf-8")
    (tmp_path / "users.json").write_text(json.dumps({"users": [
        {"id": "u1", "username": "updatedb", "password_hash": "x", "is_admin": False,
         "must_change_password": False, "root_dirs": ["webprojects", "helper/3gpp"]},
    ]}), encoding="utf-8")
    return tmp_path / "config.json"


def test_migration_rewrites_roots_as_relative_paths(tmp_path: Path):
    config_path = _workspace(tmp_path)

    assert migrate_legacy_roots(config_path, tmp_path) is True

    roots = json.loads((tmp_path / "roots.json").read_text(encoding="utf-8"))["roots"]
    by_id = {entry["id"]: entry for entry in roots}
    assert by_id["3gpp"]["dir"] == "helper/3gpp"
    assert by_id["3gpp"]["label"] == "3GPP Meetings"
    assert by_id["3gpp"]["agent_id"] == "helper"
    assert by_id["webprojects"]["dir"] == "webprojects"


def test_migration_maps_user_grants_to_root_ids(tmp_path: Path):
    config_path = _workspace(tmp_path)

    migrate_legacy_roots(config_path, tmp_path)

    users = json.loads((tmp_path / "users.json").read_text(encoding="utf-8"))["users"]
    assert users[0]["root_ids"] == ["webprojects", "3gpp"]
    assert "root_dirs" not in users[0]


def test_migration_writes_backups(tmp_path: Path):
    config_path = _workspace(tmp_path)

    migrate_legacy_roots(config_path, tmp_path)

    assert (tmp_path / "users.json.bak").exists()
    assert json.loads((tmp_path / "users.json.bak").read_text(encoding="utf-8"))["users"][0]["root_dirs"]


def test_migration_refuses_a_root_outside_the_system_root(tmp_path: Path):
    outside = tmp_path.parent / "not-contained"
    outside.mkdir(exist_ok=True)
    config_path = _workspace(tmp_path, outside_dir=str(outside))

    with pytest.raises(MigrationError, match="无法收纳"):
        migrate_legacy_roots(config_path, tmp_path)


def test_migration_is_idempotent(tmp_path: Path):
    config_path = _workspace(tmp_path)
    migrate_legacy_roots(config_path, tmp_path)

    assert migrate_legacy_roots(config_path, tmp_path) is False


def test_migration_is_skipped_when_there_is_no_legacy_roots_key(tmp_path: Path):
    (tmp_path / "config.json").write_text(json.dumps({"system_root_dir": str(tmp_path)}), encoding="utf-8")

    assert migrate_legacy_roots(tmp_path / "config.json", tmp_path) is False


def test_migration_leaves_config_json_untouched(tmp_path: Path):
    config_path = _workspace(tmp_path)
    before = config_path.read_text(encoding="utf-8")

    migrate_legacy_roots(config_path, tmp_path)

    assert config_path.read_text(encoding="utf-8") == before


def test_migration_refuses_an_id_that_the_registry_could_not_read(tmp_path: Path):
    config_path = _workspace(tmp_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["roots"].append({"id": "bad id", "label": "Bad", "dir": str(tmp_path / "webprojects"),
                             "agent_id": "main"})
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MigrationError, match="含非法字符"):
        migrate_legacy_roots(config_path, tmp_path)

    assert not (tmp_path / "roots.json").exists()
