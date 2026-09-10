"""Private multi-user account storage and system-root grant validation."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import bcrypt

try:  # dev/ on sys.path (app runtime, bare `root_registry` imports)
    from root_registry import RootRegistryError, atomic_write_json, validate_root_dir
except ImportError:  # imported as `dev.user_store` (package-style tests)
    from dev.root_registry import RootRegistryError, atomic_write_json, validate_root_dir

_RID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class UserRecord:
    id: str
    username: str
    password_hash: str
    is_admin: bool
    must_change_password: bool
    root_ids: tuple[str, ...]

    def public(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "is_admin": self.is_admin,
            "must_change_password": self.must_change_password,
            "root_ids": list(self.root_ids),
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
                root_ids=(),
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
                root_ids=tuple(self._root_ids(item.get("root_ids", []))),
            ))
        if not result or not any(user.is_admin for user in result):
            raise RuntimeError("User configuration must contain an administrator")
        return result

    def _write(self, users: list[UserRecord]) -> None:
        atomic_write_json(self.path, {
            "users": [{**asdict(user), "root_ids": list(user.root_ids)} for user in users]})

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

    @staticmethod
    def _root_ids(values: object) -> list[str]:
        """Validate grant shape only. Existence is checked at write time."""
        if not isinstance(values, list):
            raise ValueError("root_ids must be a list")
        result: list[str] = []
        for value in values:
            root_id = str(value).strip()
            if not _RID_RE.match(root_id):
                raise ValueError("Invalid root id")
            if root_id not in result:
                result.append(root_id)
        return result

    def _validate_grants(self, root_ids: list[str]) -> list[str]:
        """Write-time validation: each id must name an existing system-root subdirectory."""
        result: list[str] = []
        for root_id in root_ids:
            try:
                validate_root_dir(self.system_root_dir, root_id)
            except RootRegistryError as exc:
                raise ValueError(str(exc)) from exc
            if root_id not in result:
                result.append(root_id)
        return result

    def authenticate(self, username: str, password: str) -> UserRecord | None:
        target = str(username).strip()
        user = self.get_by_username(target)
        if user is not None and self.verify_password(password, user.password_hash):
            return user
        return None

    def get_by_username(self, username: str) -> UserRecord | None:
        target = str(username).strip()
        for user in self._read():
            if user.username == target:
                return user
        return None

    def get_administrator(self) -> UserRecord | None:
        return next((user for user in self._read() if user.is_admin), None)

    def reset_password(self, username: str, password: str) -> UserRecord:
        """Reset a named account password for the local recovery CLI."""
        target = self._username(username)
        user = self.get_by_username(target)
        if user is None:
            raise LookupError("User not found")
        return self.update_user(user.id, password=password)

    def get(self, user_id: str) -> UserRecord | None:
        return next((user for user in self._read() if user.id == user_id), None)

    def list_public_users(self) -> list[dict]:
        return [user.public() for user in self._read()]

    def create_user(self, username: str, password: str, root_ids: list[str], *, is_admin: bool = False) -> UserRecord:
        users = self._read()
        name = self._username(username)
        if any(user.username == name for user in users):
            raise ValueError("Username already exists")
        roots = self._validate_grants(self._root_ids(root_ids)) if not is_admin else []
        if not is_admin and not roots:
            raise ValueError("A regular user requires at least one root directory")
        user = UserRecord(str(uuid.uuid4()), name, self.hash_password(password), is_admin, False, tuple(roots))
        self._write([*users, user])
        return user

    def update_user(self, user_id: str, *, username: str | None = None, password: str | None = None,
                    root_ids: list[str] | None = None, is_admin: bool | None = None) -> UserRecord:
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
        roots = (self._validate_grants(self._root_ids(root_ids)) if root_ids is not None
                 else ([] if admin else list(current.root_ids)))
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
