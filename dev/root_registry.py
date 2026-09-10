"""Private root registry: directories registered under one system root."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class RootRegistryError(ValueError):
    """Raised when a registry operation violates a constraint."""


@dataclass(frozen=True)
class RootEntry:
    id: str
    label: str
    dir: str
    agent_id: str = "default"

    def public(self) -> dict:
        return {"id": self.id, "label": self.label, "dir": self.dir, "agent_id": self.agent_id}


def validate_root_dir(system_root_dir: Path, relative: str) -> str:
    """Normalize a registry dir for a WRITE. Requires the directory to exist."""
    raw = str(relative).strip()
    if not raw or Path(raw).is_absolute():
        raise RootRegistryError("Rootdir 目录必须是系统根目录下的子目录")
    value = raw.strip("/")
    if not value or value == ".":
        raise RootRegistryError("Rootdir 目录必须是系统根目录下的子目录")
    resolved = (system_root_dir / value).resolve()
    if system_root_dir not in resolved.parents:
        raise RootRegistryError("Rootdir 目录位于系统根目录之外")
    if not resolved.is_dir():
        raise RootRegistryError("Rootdir 目录不存在")
    return resolved.relative_to(system_root_dir).as_posix()


def valid_root_id(value: object) -> bool:
    """Expose the id charset the registry enforces, for writers such as the migration."""
    return bool(_ID_RE.match(str(value).strip()))


def _agent_id(value: object) -> str:
    agent = str(value).strip() or "default"
    if not _ID_RE.match(agent):
        raise RootRegistryError("agent_id 含非法字符")
    return agent


def atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON through a same-directory temp file and an atomic replace.

    Shared by the root registry, the user store, and the legacy migration so
    the crash-safety pattern exists in exactly one place.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        Path(tmp_name).replace(path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


class RootRegistry:
    """JSON-backed root registry with atomic persistence and write-time validation."""

    def __init__(self, path: Path, system_root_dir: Path):
        self.path = path
        self.system_root_dir = system_root_dir.expanduser().resolve()

    def _read(self) -> list[RootEntry]:
        # Structure and type checks only: never re-resolve the filesystem here,
        # so one vanished directory cannot make the whole registry unreadable.
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RootRegistryError("Rootdir 配置无效") from exc
        items = raw.get("roots") if isinstance(raw, dict) else None
        if not isinstance(items, list):
            raise RootRegistryError("Rootdir 配置无效")
        result: list[RootEntry] = []
        for item in items:
            if not isinstance(item, dict):
                raise RootRegistryError("Rootdir 配置无效")
            root_id = str(item.get("id", "")).strip()
            if not _ID_RE.match(root_id):
                raise RootRegistryError(f"root id 含非法字符: {root_id!r}")
            result.append(RootEntry(
                id=root_id,
                label=str(item.get("label") or root_id),
                dir=str(item.get("dir", "")).strip(),
                agent_id=_agent_id(item.get("agent_id", "default")),
            ))
        return result

    def _write(self, roots: list[RootEntry]) -> None:
        atomic_write_json(self.path, {"roots": [asdict(entry) for entry in roots]})

    def list_all(self) -> list[RootEntry]:
        return self._read()

    def public_list(self) -> list[dict]:
        return [entry.public() for entry in self._read()]

    def get(self, root_id: str) -> RootEntry | None:
        target = str(root_id).strip()
        return next((entry for entry in self._read() if entry.id == target), None)

    def resolve(self, root_id: str) -> Path:
        """Return the absolute directory for a registered root.

        Re-validates containment and existence at use time and raises
        RootRegistryError when the directory has become unavailable.
        """
        entry = self.get(root_id)
        if entry is None:
            raise LookupError("Rootdir 不存在")
        resolved = (self.system_root_dir / entry.dir).resolve()
        if self.system_root_dir not in resolved.parents or not resolved.is_dir():
            raise RootRegistryError("Rootdir 目录不可用")
        return resolved

    def referenced_ids(self, users: list[dict]) -> set[str]:
        return {str(rid) for user in users for rid in (user.get("root_ids") or [])}

    def _derive_id(self, directory: str, taken: set[str]) -> str:
        base = re.sub(r"[^A-Za-z0-9._-]", "-", Path(directory).name).strip("-") or "root"
        if base not in taken:
            return base
        suffix = 2
        while f"{base}-{suffix}" in taken:
            suffix += 1
        return f"{base}-{suffix}"

    def create(self, *, label: str, dir: str, agent_id: str = "default",
               root_id: str | None = None) -> RootEntry:
        roots = self._read()
        normalized = validate_root_dir(self.system_root_dir, dir)
        if any(entry.dir == normalized for entry in roots):
            raise RootRegistryError("该目录已被其它 Rootdir 占用")
        taken = {entry.id for entry in roots}
        final_id = str(root_id).strip() if root_id else self._derive_id(normalized, taken)
        if not _ID_RE.match(final_id):
            raise RootRegistryError("root id 含非法字符")
        if final_id in taken:
            raise RootRegistryError("root id 已存在")
        entry = RootEntry(final_id, str(label).strip() or final_id, normalized, _agent_id(agent_id))
        self._write([*roots, entry])
        return entry

    def update(self, root_id: str, *, label: str | None = None, dir: str | None = None,
               agent_id: str | None = None) -> RootEntry:
        roots = self._read()
        index = next((i for i, entry in enumerate(roots) if entry.id == root_id), None)
        if index is None:
            raise LookupError("Rootdir 不存在")
        current = roots[index]
        new_dir = validate_root_dir(self.system_root_dir, dir) if dir is not None else current.dir
        if any(i != index and entry.dir == new_dir for i, entry in enumerate(roots)):
            raise RootRegistryError("该目录已被其它 Rootdir 占用")
        updated = RootEntry(
            id=current.id,
            label=str(label).strip() if label is not None else current.label,
            dir=new_dir,
            agent_id=_agent_id(agent_id) if agent_id is not None else current.agent_id,
        )
        roots[index] = updated
        self._write(roots)
        return updated

    def delete(self, root_id: str, *, referenced_by: set[str]) -> None:
        roots = self._read()
        target = next((entry for entry in roots if entry.id == root_id), None)
        if target is None:
            raise LookupError("Rootdir 不存在")
        if target.id in referenced_by:
            raise RootRegistryError("该 Rootdir 正被用户引用，无法删除")
        self._write([entry for entry in roots if entry.id != root_id])
