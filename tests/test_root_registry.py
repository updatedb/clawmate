from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))

from root_registry import RootRegistry, RootRegistryError  # noqa: E402


def _registry(tmp_path: Path) -> RootRegistry:
    (tmp_path / "projects").mkdir(exist_ok=True)
    (tmp_path / "helper" / "3gpp").mkdir(parents=True, exist_ok=True)
    return RootRegistry(tmp_path / "roots.json", tmp_path)


def test_create_derives_id_from_directory_name(tmp_path: Path):
    registry = _registry(tmp_path)

    entry = registry.create(label="3GPP Meetings", dir="helper/3gpp", agent_id="helper")

    assert entry.id == "3gpp"
    assert entry.dir == "helper/3gpp"
    assert entry.agent_id == "helper"
    assert registry.get("3gpp") == entry


def test_create_derives_unique_id_on_collision(tmp_path: Path):
    registry = _registry(tmp_path)
    (tmp_path / "work" / "3gpp").mkdir(parents=True)

    first = registry.create(label="A", dir="helper/3gpp")
    second = registry.create(label="B", dir="work/3gpp")

    assert first.id == "3gpp"
    assert second.id == "3gpp-2"


def test_create_rejects_directory_outside_system_root(tmp_path: Path):
    registry = _registry(tmp_path)

    with pytest.raises(RootRegistryError, match="outside the system root"):
        registry.create(label="Escape", dir="../outside")


def test_create_rejects_symlink_escape(tmp_path: Path):
    outside = tmp_path.parent / "outside-registry"
    outside.mkdir(exist_ok=True)
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
    registry = _registry(tmp_path)

    with pytest.raises(RootRegistryError, match="outside the system root"):
        registry.create(label="Escape", dir="escape")


@pytest.mark.parametrize("bad_dir", ["", ".", "/etc"])
def test_create_rejects_invalid_directory(tmp_path: Path, bad_dir: str):
    registry = _registry(tmp_path)

    with pytest.raises(RootRegistryError):
        registry.create(label="Bad", dir=bad_dir)


def test_create_rejects_missing_directory(tmp_path: Path):
    registry = _registry(tmp_path)

    with pytest.raises(RootRegistryError, match="does not exist"):
        registry.create(label="Ghost", dir="not-there")


def test_create_rejects_duplicate_directory(tmp_path: Path):
    registry = _registry(tmp_path)
    registry.create(label="A", dir="projects")

    with pytest.raises(RootRegistryError, match="already registered"):
        registry.create(label="B", dir="projects")


def test_create_rejects_explicit_duplicate_id(tmp_path: Path):
    registry = _registry(tmp_path)
    registry.create(label="A", dir="projects", root_id="shared")

    with pytest.raises(RootRegistryError, match="id already exists"):
        registry.create(label="B", dir="helper/3gpp", root_id="shared")


def test_update_keeps_the_id_while_changing_label_and_dir(tmp_path: Path):
    registry = _registry(tmp_path)
    entry = registry.create(label="A", dir="projects")
    (tmp_path / "renamed").mkdir()

    updated = registry.update(entry.id, label="Renamed", dir="renamed")

    assert updated.id == "projects"
    assert updated.label == "Renamed"
    assert updated.dir == "renamed"


def test_update_rejects_a_directory_already_registered(tmp_path: Path):
    registry = _registry(tmp_path)
    first = registry.create(label="A", dir="projects")
    registry.create(label="B", dir="helper/3gpp")

    with pytest.raises(RootRegistryError, match="already registered"):
        registry.update(first.id, dir="helper/3gpp")


def test_delete_rejects_referenced_root(tmp_path: Path):
    registry = _registry(tmp_path)
    entry = registry.create(label="A", dir="projects")

    with pytest.raises(RootRegistryError, match="referenced"):
        registry.delete(entry.id, referenced_by={entry.id})

    registry.delete(entry.id, referenced_by=set())
    assert registry.get(entry.id) is None


def test_read_does_not_touch_filesystem_when_directory_disappears(tmp_path: Path):
    registry = _registry(tmp_path)
    registry.create(label="A", dir="projects")
    (tmp_path / "projects").rmdir()

    assert registry.list_all()[0].id == "projects"
    with pytest.raises(RootRegistryError, match="unavailable"):
        registry.resolve("projects")


def test_read_rejects_malformed_registry(tmp_path: Path):
    registry = _registry(tmp_path)
    registry.path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(RootRegistryError, match="invalid"):
        registry.list_all()


def test_write_is_atomic_and_leaves_no_temp_files(tmp_path: Path):
    registry = _registry(tmp_path)
    registry.create(label="A", dir="projects")

    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".roots.json")]
    assert leftovers == []
    assert json.loads(registry.path.read_text(encoding="utf-8"))["roots"][0]["id"] == "projects"
