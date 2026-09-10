"""Private multi-user account storage and system-root grant validation."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import bcrypt


@dataclass(frozen=True)
class UserRecord:
    id: str
    username: str
    password_hash: str
    is_admin: bool
    must_change_password: bool
    root_dirs: tuple[str, ...]

    def public(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "is_admin": self.is_admin,
            "must_change_password": self.must_change_password,
            "root_dirs": list(self.root_dirs),
        }


def resolve_granted_root(system_root_dir: Path, relative_root: str) -> Path:
    """Return an existing child directory, rejecting lexical and symlink escapes."""
    root = system_root_dir.expanduser().resolve()
    value = str(relative_root).strip()
    if not value or Path(value).is_absolute():
        raise ValueError("Root directory is outside system root")
    target = (root / value).resolve()
    if root not in target.parents or not target.is_dir():
        raise ValueError("Root directory is outside system root")
    return target


class UserStore:
    """Small JSON-backed account store with atomic persistence."""

    def __init__(self, path: Path, system_root_dir: Path):
        self.path = path
        self.system_root_dir = system_root_dir.expanduser().resolve()

    def _read(self) -> list[UserRecord]:
        if not self.path.exists():
            admin = UserRecord(
                id=str(uuid.uuid4()),
                username="admin",
                password_hash=self.hash_password("password"),
                is_admin=True,
                must_change_password=True,
                root_dirs=(),
            )
            self._write([admin])
            return [admin]
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("User configuration is invalid") from exc
        users = raw.get("users") if isinstance(raw, dict) else None
        if not isinstance(users, list):
            raise RuntimeError("User configuration is invalid")
        result: list[UserRecord] = []
        for item in users:
            if not isinstance(item, dict):
                raise RuntimeError("User configuration is invalid")
            result.append(UserRecord(
                id=str(item.get("id", "")),
                username=self._username(item.get("username", "")),
                password_hash=str(item.get("password_hash", "")),
                is_admin=bool(item.get("is_admin", False)),
                must_change_password=bool(item.get("must_change_password", False)),
                root_dirs=tuple(self._root_dirs(item.get("root_dirs", []))),
            ))
        if not result or not any(user.is_admin for user in result):
            raise RuntimeError("User configuration must contain an administrator")
        return result

    def _write(self, users: list[UserRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"users": [{**asdict(user), "root_dirs": list(user.root_dirs)} for user in users]}
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            Path(tmp_name).replace(self.path)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    @staticmethod
    def hash_password(password: str) -> str:
        if len(password) < 4:
            raise ValueError("Password must contain at least 4 characters")
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _username(value: object) -> str:
        username = str(value).strip()
        if not username or len(username) > 64:
            raise ValueError("Invalid username")
        return username

    def _root_dirs(self, values: object) -> list[str]:
        if not isinstance(values, list):
            raise ValueError("root_dirs must be a list")
        result: list[str] = []
        for value in values:
            resolved = resolve_granted_root(self.system_root_dir, str(value))
            relative = resolved.relative_to(self.system_root_dir).as_posix()
            if relative not in result:
                result.append(relative)
        return result

    def authenticate(self, username: str, password: str) -> UserRecord | None:
        target = str(username).strip()
        for user in self._read():
            if user.username == target and self.verify_password(password, user.password_hash):
                return user
        return None

    def get(self, user_id: str) -> UserRecord | None:
        return next((user for user in self._read() if user.id == user_id), None)

    def list_public_users(self) -> list[dict]:
        return [user.public() for user in self._read()]

    def create_user(self, username: str, password: str, root_dirs: list[str], *, is_admin: bool = False) -> UserRecord:
        users = self._read()
        name = self._username(username)
        if any(user.username == name for user in users):
            raise ValueError("Username already exists")
        roots = self._root_dirs(root_dirs)
        if not is_admin and not roots:
            raise ValueError("A regular user requires at least one root directory")
        user = UserRecord(str(uuid.uuid4()), name, self.hash_password(password), is_admin, False, tuple(roots))
        self._write([*users, user])
        return user

    def update_user(self, user_id: str, *, username: str | None = None, password: str | None = None,
                    root_dirs: list[str] | None = None, is_admin: bool | None = None) -> UserRecord:
        users = self._read()
        index = next((i for i, user in enumerate(users) if user.id == user_id), None)
        if index is None:
            raise LookupError("User not found")
        current = users[index]
        name = self._username(username) if username is not None else current.username
        if any(user.id != user_id and user.username == name for user in users):
            raise ValueError("Username already exists")
        admin = bool(is_admin) if is_admin is not None else current.is_admin
        if current.is_admin and not admin and sum(user.is_admin for user in users) == 1:
            raise ValueError("At least one administrator is required")
        roots = self._root_dirs(root_dirs) if root_dirs is not None else list(current.root_dirs)
        if not admin and not roots:
            raise ValueError("A regular user requires at least one root directory")
        updated = UserRecord(current.id, name, self.hash_password(password) if password is not None else current.password_hash,
                             admin, False if password is not None else current.must_change_password, tuple(roots))
        users[index] = updated
        self._write(users)
        return updated

    def change_password(self, user_id: str, password: str) -> UserRecord:
        return self.update_user(user_id, password=password)

    def delete_user(self, user_id: str, *, actor_id: str) -> None:
        users = self._read()
        target = next((user for user in users if user.id == user_id), None)
        if target is None:
            raise LookupError("User not found")
        if target.id == actor_id:
            raise ValueError("Current administrator cannot be deleted")
        if target.is_admin and sum(user.is_admin for user in users) == 1:
            raise ValueError("At least one administrator is required")
        self._write([user for user in users if user.id != user_id])
