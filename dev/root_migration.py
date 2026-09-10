"""One-time migration from legacy absolute-path roots to the root registry."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path

from root_registry import RootEntry, atomic_write_json, valid_root_id


class MigrationError(RuntimeError):
    """Raised when legacy configuration cannot be expressed in the new model."""


def _legacy_roots(config_path: Path) -> list[dict]:
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    if not isinstance(raw, dict):
        return []
    return [item for item in (raw.get("roots") or [])
            if isinstance(item, dict) and str(item.get("id", "")).strip()]


def _relative_to(system_root: Path, raw: str) -> str:
    """Resolve a legacy path and return it relative to the system root.

    Legacy ``roots[].dir`` values were absolute, while legacy ``root_dirs``
    grants were relative to system_root_dir (the settings API offered
    ``path.relative_to(system_root)`` choices, and resolve_granted_root joined
    them onto the system root). Accept both shapes; a relative value must never
    be resolved against the process working directory.
    """
    candidate = Path(str(raw).strip()).expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (system_root / candidate).resolve()
    if resolved != system_root and system_root not in resolved.parents:
        raise MigrationError(f"路径 {resolved} 无法收纳于 system_root_dir ({system_root})")
    if resolved == system_root:
        raise MigrationError(f"路径 {resolved} 即 system_root_dir 本身，无法登记为 Rootdir")
    return resolved.relative_to(system_root).as_posix()


def migrate_legacy_roots(config_path: Path, system_root_dir: Path) -> bool:
    """Return True when a migration ran. Never modifies config.json."""
    registry_path = config_path.parent / "roots.json"
    legacy = _legacy_roots(config_path)
    if registry_path.exists() or not legacy:
        return False

    system_root = system_root_dir.expanduser().resolve()
    entries: list[RootEntry] = []
    dir_to_id: dict[str, str] = {}
    for item in legacy:
        root_id = str(item.get("id", "")).strip()
        # RootRegistry._read() rejects an off-charset id on every read, so
        # migrating one would produce a roots.json that can never be loaded.
        # Fail here with the offending value instead of bricking the registry.
        if not valid_root_id(root_id):
            raise MigrationError(
                f"旧 root id {root_id!r} 含非法字符，迁移后会无法读取，请先修正 config.json")
        # The registry runs the same charset check over agent_id on every read
        # (RootRegistry._read -> _agent_id), so an off-charset value would brick
        # the registry just like an off-charset id. Only a non-empty invalid
        # value is an error; a missing/empty one still falls back below.
        agent_id = str(item.get("agent_id") or "").strip()
        if agent_id and not valid_root_id(agent_id):
            raise MigrationError(
                f"旧 root {root_id} 的 agent_id {agent_id!r} 含非法字符，迁移后会无法读取，"
                "请先修正 config.json")
        try:
            relative = _relative_to(system_root, str(item.get("dir", "")))
        except MigrationError as exc:
            raise MigrationError(f"旧 root {root_id}: {exc}") from exc
        if relative in dir_to_id:
            # The registry treats dir as unique (RootRegistry.create rejects a
            # duplicate), and silently dropping one here would alias that
            # directory's grants to whichever id won. Fail instead.
            raise MigrationError(
                f"旧 root {root_id} 与 {dir_to_id[relative]} 共用目录 {relative!r}，"
                "无法同时登记，请先修正 config.json")
        dir_to_id[relative] = root_id
        entries.append(RootEntry(root_id, str(item.get("label") or root_id), relative,
                                 agent_id or "default"))

    users_path = config_path.parent / "users.json"
    raw_users: dict | None = None
    if users_path.exists():
        try:
            raw_users = json.loads(users_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise MigrationError("users.json 结构无效，无法迁移") from exc
        if not isinstance(raw_users, dict) or not isinstance(raw_users.get("users"), list):
            raise MigrationError("users.json 结构无效，无法迁移")
        for user in raw_users["users"]:
            if not isinstance(user, dict):
                raise MigrationError("users.json 结构无效，无法迁移")
            grants = user.get("root_dirs")
            if grants is None:
                continue
            if not isinstance(grants, list):
                raise MigrationError("users.json 的 root_dirs 结构无效，无法迁移")
            mapped: list[str] = []
            for grant in grants:
                try:
                    relative = _relative_to(system_root, str(grant))
                except MigrationError as exc:
                    raise MigrationError(
                        f"用户 {user.get('username')} 的授权 {grant}: {exc}") from exc
                root_id = dir_to_id.get(relative)
                if root_id is None:
                    raise MigrationError(
                        f"用户 {user.get('username')} 的授权 {grant} 未匹配任何已登记 Rootdir，"
                        "请先在 config.json 的 roots 中登记该目录")
                if root_id not in mapped:
                    mapped.append(root_id)
            user["root_ids"] = mapped
            user.pop("root_dirs", None)

    if raw_users is not None:
        shutil.copy2(users_path, users_path.parent / (users_path.name + ".bak"))
        atomic_write_json(users_path, raw_users)
    atomic_write_json(registry_path, {"roots": [asdict(entry) for entry in entries]})
    return True
