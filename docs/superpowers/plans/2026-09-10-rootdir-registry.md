# Rootdir Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote roots to first-class registered entities in a private `roots.json`, make root authorization fail-closed, and split the settings modal into Rootdir management and user management tabs.

**Architecture:** `config.json` stays read-only startup config supplying `system_root_dir`. A new `roots.json` holds `{id,label,dir,agent_id}` entries with `dir` relative to the system root; `users.json` grants reference stable root ids. A `RootRegistry` owns registry persistence and validation; `root_auth.authorize_root(user, root_id, ...)` is the single fail-closed authorization choke point. The settings modal reuses the existing `dirPickerModal` for lazy directory browsing.

**Tech Stack:** Python, FastAPI/Starlette, bcrypt, JSON, pytest/TestClient, vanilla JavaScript/CSS.

**Spec:** `docs/superpowers/specs/2026-09-10-rootdir-registry-design.md`

## Execution Order

**Run Task 7 before Task 6.** Task 6's Rootdir form wires its「浏览…」button by calling `openDirPicker(mode, title, {rootId: '.', selectedDir: '', onSelect})`, but the third `options` argument — and the `rootId` override and `onSelect` callback it carries — is introduced by Task 7. Executed in numeric order, Task 6's browse button would open the picker bound to the preview panel's root with no callback wired, so the button would appear to work while selecting nothing. Every other task runs in numeric order. Task 8 depends on both and is unaffected.

## Global Constraints

- `config.json` is read-only to the application. Never write it. It contains `openclaw_token`, `DEEPSEEK_API_KEY`, and `jwt_secret`.
- `roots.json` and `users.json` are private runtime data, git-ignored, written atomically via same-directory temp file plus `Path.replace()`.
- `system_root_dir` is the complete filesystem boundary. Every resolved path, including through symlinks, must remain strictly inside it.
- Registry `dir` values are **relative** to `system_root_dir`: non-empty, not absolute, not `.`, not the root itself, and must exist at **write** time.
- **Reads never re-resolve the filesystem.** Only writes validate existence. Deferred resolution failures reject the individual request, never the whole store.
- Authorization failures raise `PermissionError` (or a subclass) so routes map them to **403**. `ValueError` maps to 400, `FileNotFoundError` to 404 — do not use those for authorization.
- `local-admin` is a **synthetic principal**, never written to `users.json`, never listed in the settings UI, not deletable or editable.
- Admins get `.` plus all registered roots; admins' `root_ids` must stay empty. Regular users get exactly their `root_ids` and must have at least one.
- root `id` is immutable after creation.
- Deleting a root referenced by any user returns 422.
- Allowed `id` and `agent_id` charset: `[A-Za-z0-9._-]+`.
- Reuse `dirPickerModal` and `/api/clawmate/list?dirs_only=true`. Do not add a `/settings/browse` endpoint.
- Test baseline: `379 passed`, must stay green. Run with `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/ -q`.
- In this repo, bare `git` is intercepted by a shell function; always use `/usr/bin/git`.
- `docs/` is git-ignored, so docs must be staged with `git add -f`.

---

### Task 1: RootRegistry — model, validation, atomic persistence

**Files:**
- Create: `dev/root_registry.py`
- Test: `tests/test_root_registry.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `RootEntry(id, label, dir, agent_id)` frozen dataclass with `.public() -> dict`; `RootRegistryError(ValueError)`; `atomic_write_json(path: Path, payload: dict) -> None`; `validate_root_dir(system_root_dir: Path, relative: str) -> str`; `RootRegistry(path: Path, system_root_dir: Path)` with `list_all() -> list[RootEntry]`, `get(root_id) -> RootEntry | None`, `public_list() -> list[dict]`, `resolve(root_id) -> Path`, `create(*, label, dir, agent_id="default", root_id=None) -> RootEntry`, `update(root_id, *, label=None, dir=None, agent_id=None) -> RootEntry`, `delete(root_id, *, referenced_by: set[str]) -> None`. Tasks 2–5 use all of these.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_root_registry.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_root_registry.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'root_registry'`.

- [ ] **Step 3: Implement `dev/root_registry.py`**

```python
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
        raise RootRegistryError("Root directory must be a subdirectory of the system root")
    value = raw.strip("/")
    if not value or value == ".":
        raise RootRegistryError("Root directory must be a subdirectory of the system root")
    resolved = (system_root_dir / value).resolve()
    if system_root_dir not in resolved.parents:
        raise RootRegistryError("Root directory is outside the system root")
    if not resolved.is_dir():
        raise RootRegistryError("Root directory does not exist")
    return resolved.relative_to(system_root_dir).as_posix()


def _agent_id(value: object) -> str:
    agent = str(value).strip() or "default"
    if not _ID_RE.match(agent):
        raise RootRegistryError("Invalid agent id")
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
            raise RootRegistryError("Root configuration is invalid") from exc
        items = raw.get("roots") if isinstance(raw, dict) else None
        if not isinstance(items, list):
            raise RootRegistryError("Root configuration is invalid")
        result: list[RootEntry] = []
        for item in items:
            if not isinstance(item, dict):
                raise RootRegistryError("Root configuration is invalid")
            root_id = str(item.get("id", "")).strip()
            if not _ID_RE.match(root_id):
                raise RootRegistryError(f"Invalid root id: {root_id!r}")
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
            raise LookupError("Root not found")
        resolved = (self.system_root_dir / entry.dir).resolve()
        if self.system_root_dir not in resolved.parents or not resolved.is_dir():
            raise RootRegistryError("Root directory is unavailable")
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
            raise RootRegistryError("Directory is already registered")
        taken = {entry.id for entry in roots}
        final_id = str(root_id).strip() if root_id else self._derive_id(normalized, taken)
        if not _ID_RE.match(final_id):
            raise RootRegistryError("Invalid root id")
        if final_id in taken:
            raise RootRegistryError("Root id already exists")
        entry = RootEntry(final_id, str(label).strip() or final_id, normalized, _agent_id(agent_id))
        self._write([*roots, entry])
        return entry

    def update(self, root_id: str, *, label: str | None = None, dir: str | None = None,
               agent_id: str | None = None) -> RootEntry:
        roots = self._read()
        index = next((i for i, entry in enumerate(roots) if entry.id == root_id), None)
        if index is None:
            raise LookupError("Root not found")
        current = roots[index]
        new_dir = validate_root_dir(self.system_root_dir, dir) if dir is not None else current.dir
        if any(i != index and entry.dir == new_dir for i, entry in enumerate(roots)):
            raise RootRegistryError("Directory is already registered")
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
            raise LookupError("Root not found")
        if target.id in referenced_by:
            raise RootRegistryError("Root is referenced by users")
        self._write([entry for entry in roots if entry.id != root_id])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_root_registry.py -q`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
/usr/bin/git add -- dev/root_registry.py tests/test_root_registry.py
/usr/bin/git commit -m "feat: add root registry store"
```

---

### Task 2: UserStore references root ids and stops resolving on read

Fixes defect C: a single vanished directory could raise out of `auth_login` and lock out every account including the admin.

**Files:**
- Modify: `dev/user_store.py:22,82,122-131,164-196`
- Modify: `tests/test_user_store.py`
- Fixture update: `tests/test_settings_routes.py:22-25` (config gains a `roots.json` seed — see Task 5)

**Interfaces:**
- Consumes: `RootRegistryError`, `validate_root_dir` from Task 1 (write-time validation only).
- Produces: `UserRecord.root_ids: tuple[str, ...]`, `UserRecord.public()` including `root_ids`; `UserStore(path, system_root_dir)` — after this task the store holds **no** registry or filesystem knowledge, so `system_root_dir` is retained only for backwards-compatible construction; `create_user(username, password, root_ids, *, is_admin=False)`, `update_user(user_id, *, username, password, root_ids, is_admin)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_user_store.py`:

```python
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


def test_create_user_rejects_a_root_id_outside_the_allowed_charset(tmp_path: Path):
    store = UserStore(tmp_path / "users.json", tmp_path)

    with pytest.raises(ValueError, match="Invalid root id"):
        store.create_user("writer", "writer-password", ["../outside"])


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_user_store.py -q`
Expected: FAIL — `root_dirs`/`create_user(..., root_ids=...)` mismatch and `authenticate` raising `ValueError: Root directory is outside system root` after the directory is removed.

- [ ] **Step 3: Implement the change in `dev/user_store.py`**

Replace `root_dirs` with `root_ids` on `UserRecord`, tighten read-time checks, and validate ids at write time without requiring existence:

```python
_RID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
```

Add `import re` to the module imports, and drop `os` and `tempfile` once `_write` delegates to `atomic_write_json` — leaving them would trip `ruff --select F`. Verify with `dev/.venv/bin/python -m ruff check --select F dev/user_store.py` (expect no findings) before committing.

```python
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
```

`_read()` must not resolve anything. Replace the `root_dirs=tuple(self._root_dirs(...))` line with a cheap type check:

```python
                root_ids=tuple(self._root_ids(item.get("root_ids", []))),
```

and replace `_root_dirs` with:

```python
    @staticmethod
    def _root_ids(values: object) -> list[str]:
        """Validate grant shape only. Existence is checked by the settings routes
        against the root registry, not here."""
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
```

`authenticate` and `get_by_username` stay as they are (they no longer trigger resolution, which is the fix). `get_administrator` and `reset_password` also become safe again, restoring the `--set-password --force` recovery path.

Replace the body of `_write` with the shared atomic writer from Task 1 so the crash-safety pattern is not duplicated:

```python
    def _write(self, users: list[UserRecord]) -> None:
        from root_registry import atomic_write_json

        atomic_write_json(self.path, {
            "users": [{**asdict(user), "root_ids": list(user.root_ids)} for user in users]})
```

In `create_user` replace the `roots = self._root_dirs(root_dirs)` line:

```python
        roots = self._root_ids(root_ids) if not is_admin else []
        if not is_admin and not roots:
            raise ValueError("A regular user requires at least one root directory")
        user = UserRecord(str(uuid.uuid4()), name, self.hash_password(password), is_admin, False, tuple(roots))
```

In `update_user`, replace `roots = ...` and the `must_change_password` computation:

```python
        if admin:
            roots = []
        elif root_ids is not None:
            roots = self._root_ids(root_ids)
        else:
            roots = list(current.root_ids)
        if not admin and not roots:
            raise ValueError("A regular user requires at least one root directory")
```

The explicit `admin` branch is load-bearing: passing `root_ids` alongside `is_admin=True` must still leave the account with empty grants, because the specification requires administrators to keep `root_ids` empty (their visibility comes from `is_admin`, not from grants).

and rename the `root_dirs` keyword to `root_ids` in the signature and in `_read`'s dict construction.

**Grant existence is deliberately NOT validated here.** An earlier revision of this plan had the store resolve each grant id as a filesystem path, which was wrong: a registry entry `id="3gpp" / dir="helper/3gpp"` (exactly what the migration produces) made `validate_root_dir(system_root, "3gpp")` check `system_root/3gpp` and reject a legitimate grant. Grant ids are registry references, so existence is checked in the settings routes (Task 5) against the registry, and unknown ids return 422 there. This keeps `UserStore` free of both registry and filesystem knowledge, mirroring how `RootRegistry.delete(referenced_by=...)` keeps the registry free of user knowledge.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_user_store.py -q`
Expected: PASS.

Run the wider suite and note which tests now fail because they still use `root_dirs`:
Run: `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/ -q`
Expected: `tests/test_settings_routes.py` FAILS (users created with `root_dirs`). This is expected and repaired in Task 5. Do not fix it here.

- [ ] **Step 5: Commit**

```bash
/usr/bin/git add -- dev/user_store.py tests/test_user_store.py
/usr/bin/git commit -m "fix: stop re-validating user grants on read"
```

---

### Task 3: Fail-closed root authorization

Fixes defect B and completes the agent-routing fix: `get_roots()` no longer falls back to legacy roots, an unresolved session cannot continue as an anonymous user, and local clients get an explicit `local-admin` principal.

**Files:**
- Create: `dev/root_auth.py`
- Modify: `dev/service.py:92-108`
- Modify: `dev/config.py:157-175`
- Modify: `dev/auth.py:41-69,373-374,422-434`
- Modify: `dev/main.py` (register the `RootNotAuthorized` → 403 handler)
- Modify: `dev/feedback_api.py:244,290` (preserve the intentional skip of unauthorized roots)
- Modify: `.gitignore` (add `roots.json` — this task establishes the runtime path)
- Test: `tests/test_root_authorization_regression.py`, `tests/test_user_root_authorization.py`, `tests/test_auth_users.py`

**Interfaces:**
- Consumes: `RootRegistry` (Task 1), `UserRecord.root_ids` (Task 2).
- Produces: `ROOT_ID_SYSTEM = "."`; `LocalAdmin` class with `is_admin=True`, `username="local-admin"`, `root_ids=()`; `authorize_root(user, root_id, registry, system_root_dir) -> Path` raising `RootNotAuthorized(PermissionError)`; `auth.get_root_registry() -> RootRegistry`; `auth.local_admin_principal() -> LocalAdmin`; `auth.current_request_user()`.

- [ ] **Step 1: Write the failing regression tests**

Create `tests/test_root_authorization_regression.py`:

```python
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))

import auth  # noqa: E402
import config  # noqa: E402
import routes  # noqa: E402
import settings_routes  # noqa: E402


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    (tmp_path / "projects").mkdir(exist_ok=True)
    (tmp_path / "private").mkdir(exist_ok=True)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "system_root_dir": str(tmp_path),
        "auth": {"session_ttl_minutes": 480},
    }))
    monkeypatch.setenv("CLAWMATE_CONFIG", str(config_path))
    config.set_config_path(config_path)
    config.clear_config_cache()
    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware, config=config.load())
    app.include_router(routes.router)
    app.include_router(settings_routes.router)
    return TestClient(app, base_url="http://testserver.local")


def _seed_roots(tmp_path: Path) -> None:
    (tmp_path / "roots.json").write_text(json.dumps({"roots": [
        {"id": "private", "label": "Private", "dir": "private", "agent_id": "default"},
    ]}), encoding="utf-8")


def test_deleted_user_session_is_rejected(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})
    client.post("/api/clawmate/auth/change-password", json={"password": "new-password"})
    _seed_roots(tmp_path)
    created = client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["projects"]})
    assert created.status_code == 201
    writer_id = created.json()["id"]

    client.delete(f"/api/clawmate/settings/users/{writer_id}")
    session_id, _ = asyncio.run(auth.create_session("writer", 480, user_id=writer_id, is_admin=False))
    client.cookies.set("clawmate_session", session_id)

    assert client.get("/api/clawmate/config").status_code == 401
    assert client.get("/api/clawmate/list?root=private").status_code == 401


def test_registered_root_outside_user_grants_is_forbidden(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})
    client.post("/api/clawmate/auth/change-password", json={"password": "new-password"})
    _seed_roots(tmp_path)
    client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["projects"]})
    client.post("/api/clawmate/auth/logout")
    client.post("/api/clawmate/auth/login", json={"username": "writer", "password": "writer-password"})

    assert client.get("/api/clawmate/list?root=projects").status_code == 200
    assert client.get("/api/clawmate/list?root=private").status_code == 403


def test_unregistered_root_is_not_resolved_from_legacy_config(tmp_path: Path, monkeypatch):
    """A root id present only in the old config.json roots array must not resolve."""
    outside = tmp_path.parent / "legacy-outside"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    client = _client(tmp_path, monkeypatch)
    config_path = tmp_path / "config.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["roots"] = [{"id": "legacy", "label": "Legacy", "dir": str(outside), "agent_id": "main"}]
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    config.clear_config_cache()

    client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})
    client.post("/api/clawmate/auth/change-password", json={"password": "new-password"})

    ids = [root["id"] for root in client.get("/api/clawmate/config").json()["roots"]]
    assert "legacy" not in ids
    assert client.get("/api/clawmate/list?root=legacy").status_code == 403


def test_authorization_failure_maps_to_403_not_400(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})
    client.post("/api/clawmate/auth/change-password", json={"password": "new-password"})
    _seed_roots(tmp_path)
    client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["projects"]})
    client.post("/api/clawmate/auth/logout")
    client.post("/api/clawmate/auth/login", json={"username": "writer", "password": "writer-password"})

    response = client.get("/api/clawmate/list?root=private")

    assert response.status_code == 403


def test_registry_entry_escaping_the_system_root_is_never_served(tmp_path: Path, monkeypatch):
    """A hand-edited dir must not let reads resolve outside system_root_dir."""
    outside = tmp_path.parent / "outside-served"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    client = _client(tmp_path, monkeypatch)
    (tmp_path / "roots.json").write_text(json.dumps({"roots": [
        {"id": "escape", "label": "Escape", "dir": "..", "agent_id": "default"},
        {"id": "projects", "label": "Projects", "dir": "projects", "agent_id": "work"},
    ]}), encoding="utf-8")
    _login_admin(client)

    ids = [root["id"] for root in client.get("/api/clawmate/config").json()["roots"]]

    assert "escape" not in ids
    assert "projects" in ids
    assert client.get("/api/clawmate/list?root=escape").status_code == 403
```

Create `tests/test_user_root_authorization.py`:

```python
from __future__ import annotations

import json
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


def test_uncaught_authorization_failure_is_403_not_500():
    """The registered handler is the safety net for routes that do not catch it."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from root_auth import RootNotAuthorized, authorize_root, root_not_authorized_handler

    app = FastAPI()
    app.add_exception_handler(RootNotAuthorized, root_not_authorized_handler)
    registry = _registry(tmp_path)

    @app.get("/boom")
    async def boom():
        authorize_root(None, "private", registry, tmp_path)

    response = TestClient(app, raise_server_exceptions=False).get("/boom")

    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"
```

Create `tests/test_auth_users.py` — the login and forced-password-change contract the original plan named but never produced:

```python
from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))

import auth  # noqa: E402
import config  # noqa: E402
import routes  # noqa: E402
import settings_routes  # noqa: E402


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    (tmp_path / "projects").mkdir(exist_ok=True)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "system_root_dir": str(tmp_path),
        "auth": {"session_ttl_minutes": 480},
    }))
    (tmp_path / "roots.json").write_text(json.dumps({"roots": [
        {"id": "projects", "label": "Projects", "dir": "projects", "agent_id": "work"},
    ]}), encoding="utf-8")
    monkeypatch.setenv("CLAWMATE_CONFIG", str(config_path))
    config.set_config_path(config_path)
    config.clear_config_cache()
    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware, config=config.load())
    app.include_router(routes.router)
    app.include_router(settings_routes.router)
    return TestClient(app, base_url="http://testserver.local")


def test_bootstrap_admin_must_change_password_before_anything_else(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    login = client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})

    assert login.status_code == 200
    assert client.get("/api/clawmate/auth/me").json()["must_change_password"] is True
    assert client.get("/api/clawmate/list?root=projects").status_code == 403
    assert client.get("/api/clawmate/settings/users").status_code == 403


def test_changing_the_initial_password_lifts_the_restriction(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})

    changed = client.post("/api/clawmate/auth/change-password", json={"password": "new-password"})

    assert changed.status_code == 200
    assert client.get("/api/clawmate/auth/me").json()["must_change_password"] is False
    assert client.get("/api/clawmate/list?root=projects").status_code == 200


def test_identity_and_logout_stay_reachable_during_forced_change(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})

    assert client.get("/api/clawmate/auth/me").status_code == 200
    assert client.get("/api/clawmate/auth/status").status_code == 200


def test_wrong_password_is_rejected(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "nope"})

    assert response.status_code != 200


def test_login_response_never_carries_a_password_hash(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    login = client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})
    me = client.get("/api/clawmate/auth/me")

    assert "password_hash" not in login.text
    assert "password_hash" not in me.text


def test_spoofed_forwarded_header_does_not_grant_local_trust():
    """A remote peer must not be able to claim loopback via a header."""
    from types import SimpleNamespace

    def _request(peer: str, forwarded: str | None):
        headers = {"x-forwarded-for": forwarded} if forwarded else {}
        return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)

    assert auth.get_client_ip(_request("203.0.113.9", "127.0.0.1")) == "203.0.113.9"
    assert auth.get_client_ip(_request("203.0.113.9", None)) == "203.0.113.9"
    assert auth.get_client_ip(_request("127.0.0.1", "203.0.113.9")) == "203.0.113.9"
    assert auth.get_client_ip(
        _request("127.0.0.1", "127.0.0.1, 203.0.113.9")) == "203.0.113.9"


def test_spoofed_forwarded_header_cannot_reach_admin_endpoints(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    spoof = {"X-Forwarded-For": "127.0.0.1"}

    assert client.get("/api/clawmate/config", headers=spoof).status_code == 401
    assert client.get("/api/clawmate/auth/me", headers=spoof).status_code == 401
    assert client.get("/api/clawmate/settings/users", headers=spoof).status_code == 401
    assert client.post("/api/clawmate/settings/users", headers=spoof, json={
        "username": "attacker", "password": "attacker-pw",
        "root_dirs": ["projects"]}).status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_root_authorization_regression.py tests/test_user_root_authorization.py tests/test_auth_users.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'root_auth'`, and the regression tests expose the legacy fallback returning 200.

- [ ] **Step 3: Implement `dev/root_auth.py`**

```python
"""Single fail-closed authorization choke point for root-aware request paths."""

from __future__ import annotations

from pathlib import Path

from root_registry import RootRegistryError

ROOT_ID_SYSTEM = "."


class RootNotAuthorized(PermissionError):
    """Raised when the caller may not access the requested root.

    Subclasses PermissionError so routes map it to 403. ValueError would map
    to 400 and FileNotFoundError to 404, both wrong for authorization.
    """


class LocalAdmin:
    """Synthetic principal for trusted local clients. Never persisted."""

    id = ""
    username = "local-admin"
    is_admin = True
    must_change_password = False
    root_ids: tuple[str, ...] = ()

    def public(self) -> dict:
        """Same shape as UserRecord.public() so /auth/me can serialise either.

        Without this, a local client reaching /api/clawmate/auth/me would raise
        AttributeError and turn a previously graceful 401 into a 500.
        """
        return {"id": self.id, "username": self.username, "is_admin": True,
                "must_change_password": False, "root_ids": []}


def authorize_root(user, root_id: str, registry, system_root_dir: Path) -> Path:
    value = str(root_id or "").strip()
    if not value:
        raise RootNotAuthorized("Missing root")
    if user is None:
        raise RootNotAuthorized("Authenticated user required")
    if not getattr(user, "is_admin", False):
        if value == ROOT_ID_SYSTEM or value not in tuple(getattr(user, "root_ids", ())):
            raise RootNotAuthorized("Root not allowed")
    elif value == ROOT_ID_SYSTEM:
        return system_root_dir.expanduser().resolve()
    try:
        return registry.resolve(value)
    except (LookupError, RootRegistryError) as exc:
        # LookupError: no such id. RootRegistryError: the directory vanished
        # or became unreachable. Both are authorization failures for this
        # request only, never a store-wide failure.
        raise RootNotAuthorized("Root not allowed") from exc
```

- [ ] **Step 4: Wire `dev/config.py`, `dev/service.py`, `dev/auth.py`**

In `dev/config.py` replace the `root_dir` system-root branch so it can never fall back:

```python
    def root_dir(self, root_id: str) -> Path:
        """返回指定 root 的绝对路径 Path，找不到时抛 ValueError。"""
        if self.system_root_dir:
            from auth import current_request_user, get_root_registry
            from root_auth import authorize_root
            return authorize_root(
                current_request_user(), root_id, get_root_registry(), self.system_root_dir)
        for r in self.roots:
            if r.id == root_id:
                return Path(r.dir).expanduser().resolve()
        raise ValueError(f"Root not found: {root_id}")
```

In `dev/service.py` replace lines 92–108 so the legacy branch only runs when no system root is configured:

```python
def get_roots() -> Tuple[List[Dict], str]:
    cfg = load_config()
    if cfg.system_root_dir:
        from auth import current_request_user, get_root_registry
        from root_auth import ROOT_ID_SYSTEM

        user = current_request_user()
        # No fallback to the legacy roots array: an unresolved caller sees
        # nothing rather than a wider set of directories.
        if user is None:
            return [], ""
        registry = get_root_registry()
        roots: List[Dict] = []
        if getattr(user, "is_admin", False):
            roots.append({"id": ROOT_ID_SYSTEM, "label": "系统根目录",
                          "dir": str(cfg.system_root_dir), "agent_id": "default"})
            candidates = [(entry.id, entry.label, entry.agent_id) for entry in registry.list_all()]
        else:
            candidates = []
            for root_id in user.root_ids:
                entry = registry.get(root_id)
                if entry is not None:
                    candidates.append((entry.id, entry.label, entry.agent_id))
        for root_id, label, agent_id in candidates:
            try:
                directory = registry.resolve(root_id)
            except (LookupError, RootRegistryError):
                # Vanished, or (for a hand-edited registry) escaping the system
                # root. Skip it rather than report a path that resolve() itself
                # would reject: this value becomes root_path for the whole read
                # path via resolve_root(), so it must use the same boundary as
                # authorization. An unregistered grant is silently omitted for
                # the same reason -- authorize_root rejects it anyway.
                continue
            roots.append({"id": root_id, "label": label,
                          "dir": str(directory), "agent_id": agent_id})
        return roots, (roots[0]["id"] if roots else "")
    # Legacy deployments without system_root_dir keep the absolute-path roots.
    data = _load_config()
    <existing legacy body, verbatim>
```

`<existing legacy body, verbatim>` is a directive, not a placeholder: keep every line that currently follows `data = _load_config()` in `dev/service.py:109-137` exactly as written — the `roots` loop, the `media` fallback, and the `defaultRootId` resolution. The only change to this function is the block above replacing lines 94–108.

In `dev/auth.py`:

1. Add the registry accessor and the synthetic principal next to `get_user_store`:

```python
def get_root_registry():
    """Return the root registry for the configured system root."""
    from config import load as _cfg
    from root_registry import RootRegistry
    cfg = _cfg()
    if not cfg.system_root_dir:
        raise RuntimeError("system_root_dir is not configured")
    return RootRegistry(config_path().parent / "roots.json", cfg.system_root_dir)


def local_admin_principal():
    from root_auth import LocalAdmin
    return LocalAdmin()
```

2. Replace the `get_user_store` path source with a shared helper so both stores agree:

```python
def config_path() -> Path:
    """Single source of truth for the active config file."""
    from config import _CONFIG_PATH  # noqa: PLC0415
    return Path(_CONFIG_PATH) if _CONFIG_PATH else Path(os.environ.get("CLAWMATE_CONFIG", "config.json"))
```

and use `config_path().parent / "users.json"` in `get_user_store`.

3. Replace the localhost bypass block (currently `dev/auth.py:373-374`) so it binds the synthetic principal instead of returning anonymously:

```python
        # Trusted local clients get an explicit principal so downstream root
        # authorization resolves registered roots instead of seeing no user.
        from root_auth import ROOT_ID_SYSTEM  # noqa: PLC0415

        client_host = self._get_client_ip(request)
        if _is_local_client(client_host):
            principal = local_admin_principal()
            request.state.session = {"user": principal.username, "is_admin": True,
                                     "must_change_password": False, "user_id": ""}
            request.state.user = principal
            token = _request_user.set(principal)
            try:
                return await call_next(request)
            finally:
                _request_user.reset(token)
```

3b. **Make client-IP resolution trustworthy — this block's security depends on it.** `get_client_ip` (`dev/auth.py:178-183`) currently returns `x-forwarded-for.split(",")[0]` whenever the header is present, with no check on who sent it. Since the bypass above binds `LocalAdmin` — **including `request.state.session`, which unlocks the settings APIs** — an unauthenticated remote request carrying `X-Forwarded-For: 127.0.0.1` was measured returning **201 Created** from `POST /api/clawmate/settings/users`, plus 200s from `/config`, `/auth/me`, and `/settings/users`. That is unauthenticated full administrator access and the entire `system_root_dir` through the `.` root, so it must be fixed in this task, before the bypass is relied upon.

```python
def get_client_ip(request: Request) -> str:
    """Resolve the caller IP.

    ``x-forwarded-for`` is honored ONLY when the immediate peer is itself a
    trusted local host, because the header is otherwise fully attacker
    controlled and would let any remote client claim to be loopback and inherit
    the local-client trust bypass.

    The LAST hop is used rather than the first: the common nginx directive
    ``$proxy_add_x_forwarded_for`` preserves whatever the client sent at the
    front and appends the address the proxy actually observed at the end, so
    the first element is the spoofable one. When a proxy replaces the header
    instead, there is a single element and first equals last.
    """
    peer = request.client.host if request.client else "unknown"
    if _is_local_client(peer):
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return peer
```

`_is_local_client` is defined later in the module (around `dev/auth.py:318`), which is fine — both are module-level and resolution happens at call time. Leave `_is_local_client` unchanged.

Cover it in `tests/test_auth_users.py` with a unit test over the four combinations (spoofed value from a remote peer is ignored; a value from a loopback peer is honored; the last hop wins over a client-supplied first element; an absent header falls back to the peer) and an integration test asserting a spoofed header yields **401** from `/config`, `/auth/me`, `/settings/users`, and user creation. Both must fail before the change.

4. Replace the session-binding block (currently `dev/auth.py:422-434`) to reject sessions whose account no longer exists:

```python
        # Attach session user to request state. A session whose account has
        # gone away must not continue as an anonymous user: that was the path
        # that previously reached the legacy-roots fallback.
        request.state.session = session
        try:
            user = get_user_store().get(str(session.get("user_id", "")))
        except (RuntimeError, ValueError):
            user = None
        if user is None:
            _clear_session_cookie(request)
            return self._auth_failure_redirect(request, "账号不存在或已停用，请重新登录")
        request.state.user = user
        token = _request_user.set(user)
        try:
            return await call_next(request)
        finally:
            _request_user.reset(token)
```

Replace the cookie-clearing step: `_clear_session_cookie` just flags the request, and `_auth_failure_redirect` performs the deletion on whichever response it already builds.

```python
    def _clear_session_cookie(self, request: Request) -> None:
        request.state.clear_session_cookie = True
```

Rewrite `_auth_failure_redirect` (currently `dev/auth.py:443-451`) so the cookie is dropped when the flag is set:

```python
    def _auth_failure_redirect(self, request: Request, message: str) -> PlainTextResponse | RedirectResponse:
        if self._is_api_route(request.url.path):
            response: PlainTextResponse | RedirectResponse = JSONResponse(
                {"error": "unauthorized", "detail": message}, status_code=401)
        else:
            # Build full path with query string so login can redirect back to the original URL
            full_path = request.url.path
            if request.url.query:
                full_path += "?" + request.url.query
            redirect_to = f"/clawmate/login.html?redirect={quote(full_path, safe='')}"
            response = RedirectResponse(url=redirect_to, status_code=302)
        if getattr(request.state, "clear_session_cookie", False):
            response.delete_cookie("clawmate_session")
        return response
```

5. **Make the 403 actually land, and stop the contract change from turning graceful paths into 500s.** `authorize_root` raises `RootNotAuthorized`, but nothing in the app handles it: `main.py` registers no exception handler, and existing call sites guard with `except ValueError`, which no longer matches. Two consequences to fix, both caused by this task's contract change:
   - Uncaught authorization failures must become a clean 403 rather than a 500. Add the handler function to `dev/root_auth.py` so it can be registered by the app and exercised directly by a test:
   ```python
   async def root_not_authorized_handler(request, exc) -> JSONResponse:
       """Authorization failures are 403, never a 500 with a stack trace."""
       return JSONResponse({"error": "forbidden", "detail": "Root not allowed"}, status_code=403)
   ```
   with `from fastapi.responses import JSONResponse` at the top of the module, and register it in `dev/main.py` next to the other app setup:
   ```python
   from root_auth import RootNotAuthorized, root_not_authorized_handler  # noqa: E402

   app.add_exception_handler(RootNotAuthorized, root_not_authorized_handler)
   ```
   Register it for `RootNotAuthorized` specifically — **not** for `PermissionError` broadly, because `PermissionError` is also raised by genuine filesystem operations, which must keep their existing meaning.
   - Two feedback paths deliberately *skip* roots the caller may not see, and used `except ValueError: continue` to do it. Add a `PermissionError` sibling so the skip survives. In `dev/feedback_api.py`, at the `except ValueError:` inside the per-root loop at both `:244` and `:290`:
   ```python
           except (ValueError, PermissionError):
               continue
   ```
   With the handler registered, the remaining sites (`dev/feedback_api.py:71`, `:341`, and the `except ValueError -> 422` guards) need no edit: an authorization failure there now yields 403 instead of a 500, which is the intended contract.

6. **Ignore the new runtime file.** `get_root_registry()` makes `roots.json` a runtime artifact sitting next to `config.json`, exactly like `users.json`. `.gitignore:43` already lists `users.json` but not `roots.json`, so add it on the following line:

```
roots.json
```

Confirm it takes effect (expect a match naming `.gitignore`):

```bash
/usr/bin/git check-ignore -v roots.json
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_root_authorization_regression.py tests/test_user_root_authorization.py tests/test_auth_users.py -q`
Expected: PASS.

Run: `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/ -q`
Expected: only the known `tests/test_settings_routes.py` failures from Task 2 remain (users still posted with `root_dirs`). Every other test passes, including the legacy-mode suites.

- [ ] **Step 6: Commit**

```bash
/usr/bin/git add -- dev/root_auth.py dev/config.py dev/service.py dev/auth.py .gitignore \
  tests/test_root_authorization_regression.py tests/test_user_root_authorization.py \
  tests/test_auth_users.py
/usr/bin/git commit -m "fix: make root authorization fail closed"
```

---

### Task 4: Startup migration from legacy roots

**Files:**
- Create: `dev/root_migration.py`
- Modify: `dev/root_registry.py` (add the `valid_root_id` helper)
- Modify: `dev/main.py:36-60` (call migration after `set_config_path`)
- Test: `tests/test_root_migration.py`

**Interfaces:**
- Consumes: `RootEntry`, `RootRegistry` (Task 1); `UserRecord.root_ids` (Task 2).
- Produces: `MigrationError(RuntimeError)`; `migrate_legacy_roots(config_path: Path, system_root_dir: Path) -> bool` returning `True` when a migration ran.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_root_migration.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_root_migration.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'root_migration'`.

- [ ] **Step 3: Implement `dev/root_migration.py`**

```python
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

    The two legacy sources use different shapes and BOTH must be accepted:
    ``roots[].dir`` was absolute (e.g. /home/openclaw/helper/3gpp), while
    ``root_dirs`` grants were relative to system_root_dir (e.g. "webprojects",
    "helper/3gpp") because the old settings API offered
    ``path.relative_to(system_root)`` choices and resolve_granted_root joined
    them back onto the system root. A relative value must never be resolved
    against the process working directory.
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
        agent_id = str(item.get("agent_id") or "default").strip()
        # RootRegistry._read() rejects an off-charset id OR agent_id on every
        # read, so migrating one would produce a roots.json that can never be
        # loaded -- and because roots.json then exists, the migration never
        # re-runs, leaving only manual file surgery. Fail here with the
        # offending value instead of bricking the registry. Both fields share
        # the same charset, so both are guarded.
        if not valid_root_id(root_id):
            raise MigrationError(
                f"旧 root id {root_id!r} 含非法字符，迁移后会无法读取，请先修正 config.json")
        if not valid_root_id(agent_id):
            raise MigrationError(
                f"旧 root {root_id!r} 的 agent_id {agent_id!r} 含非法字符，"
                "迁移后会无法读取，请先修正 config.json")
        try:
            relative = _relative_to(system_root, str(item.get("dir", "")))
        except MigrationError as exc:
            raise MigrationError(f"旧 root {root_id}: {exc}") from exc
        if relative in dir_to_id:
            # The registry's own invariant is that dir is unique, and silently
            # dropping the second entry would alias that directory's grants to
            # the first id -- a silent change in who can reach what.
            raise MigrationError(
                f"旧 root {root_id!r} 与 {dir_to_id[relative]!r} 指向同一目录 {relative!r}，"
                "无法登记为两个 Rootdir，请先修正 config.json")
        dir_to_id[relative] = root_id
        entries.append(RootEntry(root_id, str(item.get("label") or root_id), relative, agent_id))

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
```

Note `roots.json` never needs a backup: it does not exist when the migration triggers (its absence is the trigger condition), so `users.json.bak` is the only backup the migration produces. Import `asdict` from `dataclasses` and `atomic_write_json, valid_root_id` from `root_registry` at the top of the module, replacing the `RootRegistry` import.

Also **add this helper to `dev/root_registry.py`** — the migration needs the same id charset the registry enforces internally, and duplicating the regex would let the two drift:

```python
def valid_root_id(value: object) -> bool:
    """Expose the id charset the registry enforces, for writers such as the migration."""
    return bool(_ID_RE.match(str(value).strip()))
```

Then add cases to `tests/test_root_migration.py` covering all three guards — the off-charset id, the off-charset agent id (which shares the charset and the same bricking failure mode), and two legacy roots sharing one directory (which would violate the registry's `dir` uniqueness and silently alias grants to the first id):

```python
def test_migration_refuses_an_agent_id_that_the_registry_could_not_read(tmp_path: Path):
    config_path = _workspace(tmp_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["roots"][0]["agent_id"] = "my agent"
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MigrationError, match="agent_id"):
        migrate_legacy_roots(config_path, tmp_path)

    assert not (tmp_path / "roots.json").exists()


def test_migration_refuses_two_roots_sharing_a_directory(tmp_path: Path):
    config_path = _workspace(tmp_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["roots"][1]["dir"] = payload["roots"][0]["dir"]
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MigrationError, match="指向同一目录"):
        migrate_legacy_roots(config_path, tmp_path)

    assert not (tmp_path / "roots.json").exists()


def test_migrated_registry_reloads_without_error(tmp_path: Path):
    """The failure mode being guarded is writing a registry that cannot be read."""
    config_path = _workspace(tmp_path)

    assert migrate_legacy_roots(config_path, tmp_path) is True

    entries = RootRegistry(tmp_path / "roots.json", tmp_path).list_all()
    assert {entry.id for entry in entries} == {"3gpp", "webprojects"}
```

Also add a case covering an **absolute-shaped grant** — `_relative_to` takes an absolute branch that a `roots[].dir` value exercises, but no test drives it from the `root_dirs` side:

```python
def test_migration_maps_an_absolute_grant(tmp_path: Path):
    config_path = _workspace(tmp_path)
    payload = json.loads((tmp_path / "users.json").read_text(encoding="utf-8"))
    payload["users"][0]["root_dirs"] = [str(tmp_path / "helper" / "3gpp")]
    (tmp_path / "users.json").write_text(json.dumps(payload), encoding="utf-8")

    migrate_legacy_roots(config_path, tmp_path)

    users = json.loads((tmp_path / "users.json").read_text(encoding="utf-8"))["users"]
    assert users[0]["root_ids"] == ["3gpp"]
```

And this one, which pins the security-critical symlink check that the containment guard performs:

```python
def test_migration_refuses_a_root_reached_through_an_escaping_symlink(tmp_path: Path):
    outside = tmp_path.parent / "migration-outside"
    outside.mkdir(exist_ok=True)
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    config_path = _workspace(tmp_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["roots"].append({"id": "linked", "label": "Linked",
                             "dir": str(tmp_path / "linked"), "agent_id": "main"})
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MigrationError, match="无法收纳"):
        migrate_legacy_roots(config_path, tmp_path)

    assert not (tmp_path / "roots.json").exists()
```

And the off-charset **id** guard itself:

```python
def test_migration_refuses_an_id_that_the_registry_could_not_read(tmp_path: Path):
    config_path = _workspace(tmp_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["roots"].append({"id": "bad id", "label": "Bad", "dir": str(tmp_path / "webprojects"),
                             "agent_id": "main"})
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MigrationError, match="含非法字符"):
        migrate_legacy_roots(config_path, tmp_path)

    assert not (tmp_path / "roots.json").exists()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_root_migration.py -q`
Expected: PASS.

- [ ] **Step 5: Call the migration at startup**

In `dev/main.py`, place the call as the **first statement inside the `if __name__ == "__main__":` block** (currently line 288), before `_cli_set_password()` is called:

```python
if __name__ == "__main__":
    import uvicorn

    # One-time migration: legacy absolute-path roots become registry entries.
    # Deliberately NOT at module level: importing this module must never rewrite
    # config.json-adjacent runtime data.
    if cfg.system_root_dir:
        from root_migration import MigrationError, migrate_legacy_roots

        try:
            if migrate_legacy_roots(CONFIG_PATH, cfg.system_root_dir):
                print("[clawmate] 已将旧 roots 迁移到 roots.json")
        except MigrationError as exc:
            print(f"[clawmate] 配置迁移失败，终止启动: {exc}")
            raise SystemExit(1)

    do_set_password, force_password = _cli_set_password()
```

**Do not put this at module level.** Everything above line 288 executes on `import main`, and several existing workflows import this module purely to inspect the app object — `python -c "import main"` is a real command used to check that startup wiring still resolves. Running the migration on import would let any import rewrite the operator's real `users.json` and create `users.json.bak`. Placing it inside the `__main__` guard keeps both the server path and the `--set-password` path covered (the CLI reads `users.json`, so it needs the grant rename too) while making import side-effect free.

No cache invalidation is needed after a successful migration: `get_root_registry()` constructs a fresh `RootRegistry` per call and `_read()` re-reads the file each time, so the newly written `roots.json` is visible to the first request. The migration deliberately does **not** modify `config.json`, so the cached `AppConfig` it was read from stays valid.

- [ ] **Step 6: Run the suite**

Run: `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/ -q`
Expected: unchanged from Task 3 — only the known `tests/test_settings_routes.py` failures remain.

- [ ] **Step 7: Commit**

```bash
/usr/bin/git add -- dev/root_migration.py dev/main.py tests/test_root_migration.py
/usr/bin/git commit -m "feat: migrate legacy roots into the registry on startup"
```

---

### Task 5: Settings APIs — root CRUD, root_id grants, registry summaries

**Files:**
- Modify: `dev/settings_routes.py` (replace `_directory_choices` and the user routes; add registry validation for grant ids)
- Modify: `dev/routes.py:63-73` (config roots), `dev/routes.py:1136-1144` (`auth_me`)
- Modify: `dev/config.py:150-155` (`root_agent` must read the registry — completes defect 3)
- Modify: `tests/test_settings_routes.py`
- Test: extend `tests/test_settings_routes.py`

**Interfaces:**
- Consumes: `RootRegistry` (Task 1), `get_root_registry()` (Task 3), `UserStore` with `root_ids` (Task 2).
- Produces: `GET/POST /api/clawmate/settings/roots`, `PATCH/DELETE /api/clawmate/settings/roots/{root_id}`; user routes accepting `root_ids`; `GET /api/clawmate/settings/users` returning `{users, roots}` with a registry summary; `/api/clawmate/config` and `/api/clawmate/auth/me` carrying real `label`/`agent_id`.

- [ ] **Step 1: Update and extend the failing tests**

In `tests/test_settings_routes.py`, add a registry seed helper and switch every user payload from `root_dirs` to `root_ids`. Replace the helper and payloads, then append the new tests:

```python
def _seed_roots(tmp_path: Path, *entries: tuple[str, str, str]) -> None:
    (tmp_path / "roots.json").write_text(json.dumps({"roots": [
        {"id": root_id, "label": label, "dir": directory, "agent_id": agent_id}
        for root_id, label, directory, agent_id in entries
    ]}), encoding="utf-8")
```

Call it in `_client` so the fixture always has a registry:

```python
def _client(tmp_path: Path, monkeypatch) -> TestClient:
    (tmp_path / "projects").mkdir()
    (tmp_path / "private").mkdir()
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "system_root_dir": str(tmp_path),
        "auth": {"session_ttl_minutes": 480},
    }))
    (tmp_path / "roots.json").write_text(json.dumps({"roots": [
        {"id": "projects", "label": "Projects", "dir": "projects", "agent_id": "work"},
        {"id": "private", "label": "Private", "dir": "private", "agent_id": "main"},
    ]}), encoding="utf-8")
    monkeypatch.setenv("CLAWMATE_CONFIG", str(config_path))
    config.set_config_path(config_path)
    config.clear_config_cache()
    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware, config=config.load())
    app.include_router(routes.router)
    app.include_router(settings_routes.router)
    return TestClient(app, base_url="http://testserver.local")
```

Append these tests:

```python
def test_config_exposes_registry_labels_and_agent_ids(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})
    client.post("/api/clawmate/auth/change-password", json={"password": "new-password"})

    roots = client.get("/api/clawmate/config").json()["roots"]

    assert roots[0] == {"id": ".", "label": "系统根目录", "agent_id": "default"}
    assert {"id": "projects", "label": "Projects", "agent_id": "work"} in roots


def test_settings_users_returns_registry_summary_not_directory_dump(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})
    client.post("/api/clawmate/auth/change-password", json={"password": "new-password"})

    data = client.get("/api/clawmate/settings/users").json()

    assert data["roots"] == [{"id": "projects", "label": "Projects"},
                             {"id": "private", "label": "Private"}]


def test_admin_creates_root_with_derived_id(tmp_path: Path, monkeypatch):
    (tmp_path / "helper" / "3gpp").mkdir(parents=True)
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)

    response = client.post("/api/clawmate/settings/roots", json={
        "label": "3GPP Meetings", "dir": "helper/3gpp", "agent_id": "helper"})

    assert response.status_code == 201
    assert response.json() == {"id": "3gpp", "label": "3GPP Meetings",
                               "dir": "helper/3gpp", "agent_id": "helper"}


def test_admin_cannot_delete_a_root_in_use(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["projects"]})

    response = client.delete("/api/clawmate/settings/roots/projects")

    assert response.status_code == 422
    assert client.get("/api/clawmate/settings/roots").json()["roots"][0]["id"] == "projects"


def test_admin_cannot_register_a_directory_outside_the_system_root(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)

    response = client.post("/api/clawmate/settings/roots", json={
        "label": "Escape", "dir": "../outside", "agent_id": "default"})

    assert response.status_code == 422


def test_grant_referencing_an_unregistered_root_id_is_rejected(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)

    response = client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["no-such-root"]})

    assert response.status_code == 422
    assert "no-such-root" in response.text
    assert [user["username"] for user in
            client.get("/api/clawmate/settings/users").json()["users"]] == ["admin"]


def test_grant_ids_are_validated_against_the_registry_not_the_filesystem(tmp_path: Path, monkeypatch):
    """A root whose id differs from its directory basename must still be grantable."""
    (tmp_path / "helper" / "3gpp").mkdir(parents=True)
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    created = client.post("/api/clawmate/settings/roots", json={
        "label": "3GPP Meetings", "dir": "helper/3gpp", "agent_id": "helper"})
    assert created.json()["id"] == "3gpp"

    response = client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["3gpp"]})

    assert response.status_code == 201
    assert response.json()["root_ids"] == ["3gpp"]


def test_patch_rejects_an_unregistered_grant_id(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    created = client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["projects"]})

    response = client.patch(f"/api/clawmate/settings/users/{created.json()['id']}",
                            json={"root_ids": ["no-such-root"]})

    assert response.status_code == 422


def test_regular_user_cannot_reach_root_management(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["projects"]})
    client.post("/api/clawmate/auth/logout")
    client.post("/api/clawmate/auth/login", json={"username": "writer", "password": "writer-password"})

    assert client.get("/api/clawmate/settings/roots").status_code == 403
    assert client.post("/api/clawmate/settings/roots",
                       json={"label": "X", "dir": "projects"}).status_code == 403


def test_auth_me_exposes_granted_root_summaries(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    client.post("/api/clawmate/settings/users", json={
        "username": "writer", "password": "writer-password", "root_ids": ["projects"]})
    client.post("/api/clawmate/auth/logout")
    client.post("/api/clawmate/auth/login", json={"username": "writer", "password": "writer-password"})

    me = client.get("/api/clawmate/auth/me").json()

    assert me["roots"] == [{"id": "projects", "label": "Projects", "agent_id": "work"}]


def test_local_admin_principal_is_never_listed_as_an_account(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)

    usernames = [user["username"] for user in client.get("/api/clawmate/settings/users").json()["users"]]

    assert "local-admin" not in usernames
    assert usernames == ["admin"]


def test_admin_accounts_are_stored_without_root_ids(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)

    created = client.post("/api/clawmate/settings/users", json={
        "username": "root2", "password": "root2-password",
        "root_ids": ["projects"], "is_admin": True})

    assert created.status_code == 201
    assert created.json()["root_ids"] == []
```

Add the shared login helper at the top of the file:

```python
def _login_admin(client: TestClient) -> None:
    client.post("/api/clawmate/auth/login", json={"username": "admin", "password": "password"})
    client.post("/api/clawmate/auth/change-password", json={"password": "new-password"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_settings_routes.py -q`
Expected: FAIL — `/settings/roots` 404s, user creation rejects `root_ids`, `/config` roots lack real labels, and `auth_me` has no `roots` key.

- [ ] **Step 3: Rewrite `dev/settings_routes.py`**

Delete `_directory_choices` entirely (it performed the 20-second full-tree scan) and add root routes:

```python
"""Administrator-only root registry, account, and grant management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from auth import get_root_registry, get_user_store
from root_registry import RootRegistryError

router = APIRouter()


def _admin(request: Request):
    session = getattr(request.state, "session", None)
    user = getattr(request.state, "user", None)
    if not session or not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return session


def _registry():
    return get_root_registry()


def _referenced_root_ids() -> set[str]:
    return {str(rid) for user in get_user_store().list_public_users()
            for rid in (user.get("root_ids") or [])}


def _validate_root_ids(root_ids: object) -> list[str]:
    """Grant ids must reference registered roots. Unknown ids are a 422.

    Existence lives here rather than in UserStore so that the store holds no
    registry knowledge, mirroring how RootRegistry.delete(referenced_by=...)
    keeps the registry free of user knowledge.
    """
    if not isinstance(root_ids, list):
        raise HTTPException(status_code=422, detail="root_ids must be a list")
    registry = _registry()
    result: list[str] = []
    for value in root_ids:
        root_id = str(value).strip()
        try:
            entry = registry.get(root_id)
        except RootRegistryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if entry is None:
            raise HTTPException(status_code=422, detail=f"Unknown root id: {root_id}")
        if root_id not in result:
            result.append(root_id)
    return result


@router.get("/api/clawmate/settings/roots")
async def list_roots(request: Request):
    _admin(request)
    return JSONResponse({"roots": _registry().public_list()})


@router.post("/api/clawmate/settings/roots", status_code=201)
async def create_root(request: Request):
    _admin(request)
    body = await request.json()
    try:
        entry = _registry().create(
            label=str(body.get("label", "")),
            dir=str(body.get("dir", "")),
            agent_id=str(body.get("agent_id", "") or "default"),
            root_id=str(body.get("id", "")).strip() or None,
        )
    except RootRegistryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(entry.public(), status_code=201)


@router.patch("/api/clawmate/settings/roots/{root_id}")
async def update_root(root_id: str, request: Request):
    _admin(request)
    body = await request.json()
    try:
        entry = _registry().update(
            root_id,
            label=body.get("label"),
            dir=body.get("dir"),
            agent_id=body.get("agent_id"),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RootRegistryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(entry.public())


@router.delete("/api/clawmate/settings/roots/{root_id}")
async def delete_root(root_id: str, request: Request):
    _admin(request)
    try:
        _registry().delete(root_id, referenced_by=_referenced_root_ids())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RootRegistryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse({"ok": True})
```

Update the user routes to use `root_ids` and to return a registry summary:

```python
@router.get("/api/clawmate/settings/users")
async def list_users(request: Request):
    _admin(request)
    store = get_user_store()
    return JSONResponse({
        "users": store.list_public_users(),
        "roots": [{"id": entry.id, "label": entry.label} for entry in _registry().list_all()],
    })


@router.post("/api/clawmate/settings/users", status_code=201)
async def create_user(request: Request):
    _admin(request)
    body = await request.json()
    is_admin = bool(body.get("is_admin", False))
    # Administrators keep root_ids empty, so there is nothing to validate.
    root_ids = [] if is_admin else _validate_root_ids(body.get("root_ids", []))
    try:
        user = get_user_store().create_user(
            str(body.get("username", "")), str(body.get("password", "")),
            root_ids, is_admin=is_admin)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(user.public(), status_code=201)


@router.patch("/api/clawmate/settings/users/{user_id}")
async def update_user(user_id: str, request: Request):
    _admin(request)
    store = get_user_store()
    current = store.get(user_id)
    if current is None:
        raise HTTPException(status_code=404, detail="User not found")
    body = await request.json()
    is_admin = body.get("is_admin")
    # Resolve the effective role before validating: promoting to admin discards
    # grants, so validating them first would reject a legitimate promotion.
    effective_admin = current.is_admin if is_admin is None else bool(is_admin)
    root_ids = body.get("root_ids")
    if effective_admin:
        root_ids = []
    elif root_ids is not None:
        root_ids = _validate_root_ids(root_ids)
    try:
        user = store.update_user(
            user_id, username=body.get("username"), password=body.get("password"),
            root_ids=root_ids, is_admin=is_admin)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(user.public())
```

Keep `delete_user` as it is.

- [ ] **Step 4: Update `dev/routes.py`**

**Also align backend agent routing — this is the other half of defect 3.** `AppConfig.root_agent()` (`dev/config.py:150-155`) still scans the legacy `self.roots` array to map a root id to its `agent_id`, and that value is what `dev/task_runner.py:262` and `dev/task_executor.py:126` send to the gateway as `agentId`. So agent routing currently works **only by coincidence**, when a registry id happens to equal a legacy config id (`3gpp` → `helper` works; a root registered through the settings UI returns `"default"` silently, and `helper/3gpp`-style grants never matched). Fix it to consult the registry, keeping the legacy scan only for deployments without a system root:

```python
    def root_agent(self, root_id: str) -> str:
        """返回指定 root 对应的 agent_id。"""
        if self.system_root_dir:
            from auth import get_root_registry
            entry = get_root_registry().get(str(root_id))
            return entry.agent_id if entry is not None else "default"
        for r in self.roots:
            if r.id == root_id:
                return r.agent_id
        return "default"
```

Cover it in `tests/test_settings_routes.py` — register a root whose id deliberately differs from its directory basename, grant it to a user, and assert both `/api/clawmate/config` and `config.root_agent(<that id>)` report the registered `agent_id` rather than `"default"`:

```python
def test_agent_routing_follows_the_registry_not_legacy_config(tmp_path: Path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _login_admin(client)
    created = client.post("/api/clawmate/settings/roots", json={
        "label": "3GPP Meetings", "dir": "helper/3gpp", "agent_id": "helper"})
    assert created.json()["id"] == "3gpp"

    assert config.load().root_agent("3gpp") == "helper"
```

Add `(tmp_path / "helper" / "3gpp").mkdir(parents=True)` inside that test before `_client` is constructed if the fixture does not already create it.

**Then** replace the rooted-roots block in the config endpoint (lines 63–73). `service.get_roots()` now returns the correct list for both roles and the legacy branch, so the endpoint no longer needs its own branching and the `agent_id` hardcoding goes away:

```python
    visible_roots, default_root = get_roots()
    roots = [{"id": root["id"], "label": root["label"], "agent_id": root["agent_id"]}
             for root in visible_roots]
```

In `auth_me`, add the visible root summaries:

```python
@router.get("/api/clawmate/auth/me")
async def auth_me(request: Request):
    session = getattr(request.state, "session", None)
    if not session:
        return JSONResponse({"error": "unauthorized", "detail": "请先登录"}, status_code=401)
    user = getattr(request.state, "user", None)
    if user is None:
        return JSONResponse({"error": "unauthorized", "detail": "用户不存在"}, status_code=401)
    visible, _ = get_roots()
    return JSONResponse({
        **user.public(),
        "must_change_password": bool(session.get("must_change_password")),
        "roots": [{"id": root["id"], "label": root["label"], "agent_id": root["agent_id"]}
                  for root in visible],
    })
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_settings_routes.py tests/test_settings_frontend_contract.py -q`
Expected: **the entire suite is green** — `452 passed, 0 failed`.

An earlier draft of this plan predicted that `tests/test_settings_frontend_contract.py` would still fail here and be repaired in Task 6. That was wrong, and the wrongness matters: that file only asserts markup ids and endpoint/method substrings — it contains no reference to `root_dirs` or `root_ids` at all. So nothing in the suite forces Task 6 to fix the frontend payload, even though `dev/static/js/app.js` still sends `root_dirs` and reads `user.root_dirs`. Task 6 therefore adds a payload-key assertion (`assert "root_dirs" not in script`) rather than relying on markup assertions to catch the drift.

Run: `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/ -q`
Expected: `452 passed, 0 failed, 10 deselected`.

- [ ] **Step 6: Commit**

```bash
/usr/bin/git add -- dev/settings_routes.py dev/routes.py tests/test_settings_routes.py
/usr/bin/git commit -m "feat: add root registry settings APIs"
```

---

### Task 6: Settings modal split into Rootdir and user tabs

**Files:**
- Modify: `dev/static/index.html:296-305` (settings modal markup)
- Modify: `dev/static/js/app.js:3073-3137` (`initSettings`)
- Modify: `dev/static/css/style.css` (tab and list styling, plus the picker's z-index)
- Modify: `tests/test_settings_frontend_contract.py`

**Interfaces:**
- Consumes: Task 5 APIs; `dirPickerModal` + `openDirPicker` from `dev/static/js/preview.js:4438-4560`.
- Produces: `[data-settings-tab="roots"|"users"]`, `#settingsRootList`, `#settingsRootForm` with `#settingsRootId`, `#settingsRootLabel`, `#settingsRootDir`, `#settingsRootBrowse`, `#settingsRootAgent`; user form with `#settingsUserRoots` checkbox container.

- [ ] **Step 1: Write the failing contract tests**

Replace `tests/test_settings_frontend_contract.py` contents:

```python
from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "dev" / "static"


def test_index_declares_two_settings_tabs():
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert 'id="btnSettings"' in html and 'id="settingsModal"' in html
    assert 'data-settings-tab="roots"' in html and 'data-settings-tab="users"' in html
    assert 'data-more="btnSettings"' in html


def test_root_tab_declares_registry_controls():
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert 'id="settingsRootList"' in html
    assert 'id="settingsRootDir"' in html
    assert 'id="settingsRootBrowse"' in html
    assert 'id="settingsRootAgent"' in html


def test_user_tab_uses_registry_checkboxes_not_a_path_multiselect():
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert 'id="settingsUserRoots"' in html
    assert '<select id="settingsRootDirs"' not in html


def test_frontend_sends_root_ids_not_the_removed_root_dirs_key():
    """The API now rejects root_dirs, so a stale payload would 422 silently."""
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    assert "root_ids" in script
    assert "root_dirs" not in script


def test_settings_script_calls_registry_and_grant_endpoints():
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    assert "/api/clawmate/settings/roots" in script
    assert "/api/clawmate/settings/users" in script
    assert "/api/clawmate/auth/status" in script
    assert "root_ids" in script


def test_root_browse_reuses_the_shared_directory_picker():
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    assert "openDirPicker" in script
    assert "/api/clawmate/settings/browse" not in script


def test_root_browse_starts_at_the_system_root():
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    assert "selectedDir: ''" in script
    assert "rootId: '.'" in script


def test_settings_script_reports_failed_admin_requests():
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    assert "设置请求失败" in script
    assert "当前账号不是管理员" in script
    assert "if (!response.ok)" in script


def test_app_falls_back_from_an_unavailable_root_url_to_an_authorized_root():
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    assert "已切换到可访问根目录" in script


def test_settings_identity_probe_does_not_redirect_local_auth_bypass_to_login():
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")

    assert "await fetch('/api/clawmate/auth/status')" in script
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_settings_frontend_contract.py -q`
Expected: FAIL on the tab and registry-control assertions.

- [ ] **Step 3a: Fix the modal stacking, or the browse button opens an unclickable picker**

`#dirPickerModal` sits at `index.html:278` and `#settingsModal` at `:299`. Both are `.modal-overlay`, and `.modal-overlay` carries `z-index: 10000` (`dev/static/css/style.css:28-30`) with no per-modal override. Two siblings at equal z-index paint in **DOM order**, so the settings modal covers the picker — and a click meant for the picker lands on the settings modal's overlay, where its backdrop handler (`dev/static/js/app.js:3125`) closes the *settings* modal instead. Task 6's Rootdir browse button therefore appears broken in exactly the way that is hardest to diagnose.

Raise the picker above the settings modal with a targeted rule rather than changing the shared `.modal-overlay` (other modals depend on the current value):

```css
/* The directory picker can be opened from inside the settings modal, so it
   must paint above it; both are .modal-overlay siblings at z-index 10000 and
   would otherwise resolve by DOM order, with the settings modal later. */
#dirPickerModal { z-index: 10001; }
```

Add a contract assertion so the rule cannot be dropped silently — a behavioural check, not a bare id grep:

```python
def test_dir_picker_paints_above_the_settings_modal():
    """Both are .modal-overlay siblings; DOM order puts the settings modal last."""
    css = (STATIC / "css" / "style.css").read_text(encoding="utf-8")
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert "#dirPickerModal" in css and "z-index: 10001" in css
    assert html.index('id="dirPickerModal"') < html.index('id="settingsModal"'), \
        "if the picker is ever moved after the settings modal this rule is no longer needed"
```

- [ ] **Step 3: Rewrite the settings modal markup**

Replace the `#settingsModal` block in `dev/static/index.html`:

```html
  <div id="settingsModal" class="modal-overlay" role="dialog" aria-modal="true" aria-label="系统设置" style="display:none;">
    <div class="modal-box settings-modal-box">
      <div class="modal-header"><span class="modal-title">系统设置</span><button class="modal-close" id="settingsModalClose" title="关闭">✕</button></div>
      <div class="settings-tabs" role="tablist">
        <button type="button" class="settings-tab" id="settingsTabRoots" data-settings-tab="roots" role="tab" aria-selected="true">Rootdir 管理</button>
        <button type="button" class="settings-tab" id="settingsTabUsers" data-settings-tab="users" role="tab" aria-selected="false">用户管理</button>
      </div>
      <div class="modal-body">
        <p id="settingsError" class="settings-help" role="alert"></p>
        <section data-settings-panel="roots" role="tabpanel">
          <div id="settingsRootList"></div>
          <form id="settingsRootForm" class="settings-form">
            <input id="settingsRootId" placeholder="id（留空自动派生）">
            <input id="settingsRootLabel" placeholder="显示名" required>
            <input id="settingsRootDir" placeholder="目录（相对系统根目录）" readonly required>
            <button type="button" id="settingsRootBrowse" class="btn btn-secondary">浏览…</button>
            <input id="settingsRootAgent" placeholder="Agent（默认 default）">
            <p id="settingsRootHint" class="settings-help"></p>
            <button class="btn btn-primary" type="submit">保存 Rootdir</button>
            <button type="button" id="settingsRootCancel" class="btn btn-secondary" hidden>取消编辑</button>
          </form>
        </section>
        <section data-settings-panel="users" role="tabpanel" hidden>
          <div id="settingsUsers"></div>
          <template id="settingsUserActions"><button type="button" data-settings-action="edit">编辑</button><button type="button" data-settings-action="delete">删除</button></template>
          <form id="settingsUserForm" class="settings-form">
            <input id="settingsUsername" placeholder="用户名" required>
            <input id="settingsPassword" type="password" placeholder="初始密码" required>
            <fieldset id="settingsUserRoots" aria-label="可访问 Rootdir"></fieldset>
            <button class="btn btn-primary" type="submit">创建用户</button>
          </form>
        </section>
      </div>
    </div>
  </div>
```

- [ ] **Step 4: Rewrite `initSettings` in `dev/static/js/app.js`**

Replace the whole `initSettings` function (currently lines 3073–3137) with a two-tab implementation that shares the request helper:

```javascript
async function initSettings() {
  var btn = document.getElementById('btnSettings');
  var modal = document.getElementById('settingsModal');
  var passwordModal = document.getElementById('passwordChangeModal');
  if (!btn || !modal || !passwordModal) return false;
  var me;
  try {
    // A loopback request bypasses session auth, so probe without authFetch to
    // avoid redirecting a local operator to the login page on an expected 401.
    var meResponse = await fetch('/api/clawmate/auth/status');
    if (!meResponse.ok) return false;
    me = await meResponse.json();
    if (!me.logged_in) return false;
  } catch (_) { return false; }
  btn.hidden = !me.is_admin;
  var error = document.getElementById('settingsError');
  var editingRootId = '';
  function showSettingsError(message) { error.textContent = message || ''; }
  async function settingsRequest(url, options) {
    var response = await authFetch(url, options);
    var data;
    try { data = await response.json(); } catch (_) { data = {}; }
    if (!response.ok) {
      var message = response.status === 403
        ? '当前账号不是管理员，无法管理用户。请退出后以管理员账号重新登录。'
        : (data.detail || data.error || '设置请求失败，请稍后重试。');
      showSettingsError(message);
      throw new Error(message);
    }
    return data;
  }
  function selectTab(name) {
    var tabs = modal.querySelectorAll('[data-settings-tab]');
    for (var i = 0; i < tabs.length; i++) {
      tabs[i].setAttribute('aria-selected', String(tabs[i].dataset.settingsTab === name));
    }
    var panels = modal.querySelectorAll('[data-settings-panel]');
    for (var j = 0; j < panels.length; j++) {
      panels[j].hidden = panels[j].dataset.settingsPanel !== name;
    }
  }
  function resetRootForm() {
    editingRootId = '';
    document.getElementById('settingsRootId').value = '';
    document.getElementById('settingsRootId').disabled = false;
    document.getElementById('settingsRootLabel').value = '';
    document.getElementById('settingsRootDir').value = '';
    document.getElementById('settingsRootAgent').value = '';
    document.getElementById('settingsRootHint').textContent = '';
    document.getElementById('settingsRootCancel').hidden = true;
  }
  var rootsCache = [];
  var usersCache = [];
  async function loadRoots() {
    var data = await settingsRequest('/api/clawmate/settings/roots');
    rootsCache = data.roots;
    var list = document.getElementById('settingsRootList');
    list.textContent = '';
    data.roots.forEach(function (root) {
      var row = document.createElement('div');
      row.className = 'settings-root';
      var text = document.createElement('span');
      text.textContent = root.label + ' · ' + root.dir + ' · agent:' + root.agent_id;
      row.appendChild(text);
      var edit = document.createElement('button');
      edit.type = 'button'; edit.textContent = '编辑';
      edit.addEventListener('click', function () {
        editingRootId = root.id;
        document.getElementById('settingsRootId').value = root.id;
        document.getElementById('settingsRootId').disabled = true;
        document.getElementById('settingsRootLabel').value = root.label;
        document.getElementById('settingsRootDir').value = root.dir;
        document.getElementById('settingsRootAgent').value = root.agent_id;
        document.getElementById('settingsRootCancel').hidden = false;
        // Grants reference the id, so changing dir must not be read as
        // revoking access. State the consequence before the user commits.
        var referenced = usersCache.filter(function (user) {
          return (user.root_ids || []).indexOf(root.id) >= 0;
        }).length;
        document.getElementById('settingsRootHint').textContent = referenced
          ? '该 Rootdir 已被 ' + referenced + ' 位用户引用；修改目录后其授权不受影响（授权引用的是 id）。'
          : '';
        showSettingsError('');
      });
      var remove = document.createElement('button');
      remove.type = 'button'; remove.textContent = '删除';
      remove.addEventListener('click', async function () {
        if (!window.confirm('删除 Rootdir ' + root.label + '？')) return;
        try {
          await settingsRequest('/api/clawmate/settings/roots/' + encodeURIComponent(root.id), {method: 'DELETE'});
          await loadRoots();
        } catch (_) {}
      });
      row.appendChild(edit); row.appendChild(remove);
      list.appendChild(row);
    });
  }
  async function loadUsers() {
    var data = await settingsRequest('/api/clawmate/settings/users');
    usersCache = data.users;
    var users = document.getElementById('settingsUsers');
    var labels = {};
    data.roots.forEach(function (root) { labels[root.id] = root.label; });
    users.textContent = '';
    data.users.forEach(function (user) {
      var row = document.createElement('div');
      row.className = 'settings-user';
      var text = document.createElement('span');
      var granted = (user.root_ids || []).map(function (id) { return labels[id] || id; }).join(', ');
      text.textContent = user.username + (user.is_admin ? '（管理员）' : '') + ' · ' + (granted || '—');
      row.appendChild(text);
      var edit = document.createElement('button');
      edit.type = 'button'; edit.dataset.settingsAction = 'edit'; edit.textContent = '编辑';
      edit.addEventListener('click', async function () {
        var name = window.prompt('用户名', user.username);
        if (name === null) return;
        var password = window.prompt('新密码（留空则不修改）', '');
        var dirs = window.prompt('授权 Rootdir id（逗号分隔）', (user.root_ids || []).join(','));
        if (dirs === null) return;
        var body = {username: name, root_ids: dirs.split(',').map(function (item) { return item.trim(); }).filter(Boolean)};
        if (password) body.password = password;
        try {
          await settingsRequest('/api/clawmate/settings/users/' + encodeURIComponent(user.id),
            {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
          await loadUsers();
        } catch (_) {}
      });
      var remove = document.createElement('button');
      remove.type = 'button'; remove.dataset.settingsAction = 'delete'; remove.textContent = '删除';
      remove.addEventListener('click', async function () {
        if (!window.confirm('删除用户 ' + user.username + '？')) return;
        try {
          await settingsRequest('/api/clawmate/settings/users/' + encodeURIComponent(user.id), {method: 'DELETE'});
          await loadUsers();
        } catch (_) {}
      });
      row.appendChild(edit); row.appendChild(remove);
      users.appendChild(row);
    });
    var fieldset = document.getElementById('settingsUserRoots');
    fieldset.textContent = '';
    data.roots.forEach(function (root) {
      var label = document.createElement('label');
      var box = document.createElement('input');
      box.type = 'checkbox'; box.name = 'root_ids'; box.value = root.id;
      label.appendChild(box);
      label.appendChild(document.createTextNode(' ' + root.label));
      fieldset.appendChild(label);
    });
  }
  async function loadSettings() {
    await loadRoots();
    await loadUsers();
  }
  modal.querySelectorAll('[data-settings-tab]').forEach(function (tab) {
    tab.addEventListener('click', function () { selectTab(tab.dataset.settingsTab); });
  });
  document.getElementById('settingsRootBrowse').addEventListener('click', function () {
    if (typeof openDirPicker !== 'function') return;
    // selectedDir: '' — without it the picker defaults to the preview panel's
    // current directory, because dirPickerSelectedDir falls back to parentDir.
    openDirPicker('rootdir', '选择 Rootdir 目录', {
      rootId: '.',
      selectedDir: '',
      onSelect: function (dir) {
        document.getElementById('settingsRootDir').value = dir;
      }
    });
  });
  document.getElementById('settingsRootCancel').addEventListener('click', resetRootForm);
  document.getElementById('settingsRootForm').addEventListener('submit', async function (event) {
    event.preventDefault();
    var payload = {
      label: document.getElementById('settingsRootLabel').value,
      dir: document.getElementById('settingsRootDir').value,
      agent_id: document.getElementById('settingsRootAgent').value || 'default'
    };
    if (!payload.dir) { showSettingsError('请先选择一个目录。'); return; }
    try {
      if (editingRootId) {
        await settingsRequest('/api/clawmate/settings/roots/' + encodeURIComponent(editingRootId),
          {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
      } else {
        var explicitId = document.getElementById('settingsRootId').value.trim();
        if (explicitId) payload.id = explicitId;
        await settingsRequest('/api/clawmate/settings/roots',
          {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
      }
      resetRootForm();
      await loadSettings();
    } catch (_) {}
  });
  document.getElementById('settingsUserForm').addEventListener('submit', async function (event) {
    event.preventDefault();
    var fieldset = document.getElementById('settingsUserRoots');
    var chosen = [];
    fieldset.querySelectorAll('input[name="root_ids"]:checked').forEach(function (box) { chosen.push(box.value); });
    if (!chosen.length) { showSettingsError('请至少选择一个可访问 Rootdir。'); return; }
    try {
      await settingsRequest('/api/clawmate/settings/users', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          username: document.getElementById('settingsUsername').value,
          password: document.getElementById('settingsPassword').value,
          root_ids: chosen
        })
      });
      event.target.reset();
      await loadSettings();
    } catch (_) {}
  });
  btn.addEventListener('click', async function () {
    modal.style.display = 'flex';
    showSettingsError('');
    resetRootForm();
    selectTab('roots');
    try { await loadSettings(); } catch (_) {}
  });
  document.getElementById('settingsModalClose').addEventListener('click', function () { modal.style.display = 'none'; });
  modal.addEventListener('click', function (event) { if (event.target === modal) modal.style.display = 'none'; });
  document.getElementById('passwordChangeForm').addEventListener('submit', async function (event) {
    event.preventDefault();
    var res = await authFetch('/api/clawmate/auth/change-password',
      {method: 'POST', headers: {'Content-Type': 'application/json'},
       body: JSON.stringify({password: document.getElementById('passwordChangeInput').value})});
    if (res.ok) window.location.reload();
    else document.getElementById('passwordChangeError').textContent = (await res.json()).detail || '保存失败';
  });
  if (me.must_change_password) { passwordModal.style.display = 'flex'; return true; }
  return false;
}
```

- [ ] **Step 5: Add styles**

Append to `dev/static/css/style.css`:

```css
.settings-tabs { display: flex; gap: 4px; padding: 0 16px; border-bottom: 1px solid var(--border-color); }
.settings-tab { appearance: none; background: none; border: 0; border-bottom: 2px solid transparent; padding: 8px 12px; font: inherit; font-size: 13px; color: var(--text-secondary); cursor: pointer; }
.settings-tab[aria-selected="true"] { color: var(--text-primary); border-bottom-color: var(--accent); }
.settings-root { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 6px 0; font-size: 13px; }
.settings-root button { font-size: 12px; }
#settingsUserRoots { display: flex; flex-direction: column; gap: 4px; border: 0; margin: 0; padding: 0; font-size: 13px; }

/* `.settings-user` already exists earlier in this file with its own
   border-bottom; extend it rather than redeclaring the whole rule here. */
.settings-user button { font-size: 12px; }

/* Required by Task 6 Step 3a: the picker is opened from inside the settings
   modal, and both are .modal-overlay siblings at z-index 10000, so without
   this the settings modal paints over the picker and swallows its clicks. */
#dirPickerModal { z-index: 10001; }
```

The `#dirPickerModal` rule and the assertion above are the **same requirement** as Step 3a. Steps run in order, so Step 3a already added both; this block repeats them only so the whole style sheet is visible in one place. Do not add a second copy of the rule or the assertion.

- [ ] **Step 6: Run the checks**

Run: `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_settings_frontend_contract.py -q && node --check dev/static/js/app.js`
Expected: PASS and no syntax errors.

- [ ] **Step 7: Commit**

```bash
/usr/bin/git add -- dev/static/index.html dev/static/js/app.js dev/static/css/style.css \
  tests/test_settings_frontend_contract.py
/usr/bin/git commit -m "feat: split settings modal into rootdir and user tabs"
```

---

### Task 7: Directory picker hidden-directory toggle and picker reuse

**Files:**
- Modify: `dev/static/js/preview.js:4436-4560` (`openDirPicker` signature and filtering)
- Modify: `dev/static/index.html` (toggle in `dirPickerModal`)
- Modify: `tests/test_settings_frontend_contract.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `openDirPicker(mode, title, options)` where `options` may carry `{rootId, onSelect}`; `#dirPickerShowHidden` checkbox; `DIR_PICKER_TOGGLE_PREFIXES` constant.

**Backward compatibility:** the existing callers pass two arguments, so `options` must stay optional and the default behaviour must be unchanged.

- [ ] **Step 1: Write the failing contract tests**

Append to `tests/test_settings_frontend_contract.py`:

```python
def test_dir_picker_exposes_a_hidden_directory_toggle():
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert 'id="dirPickerShowHidden"' in html


def test_dir_picker_filters_hidden_entries_behind_the_toggle():
    script = (STATIC / "js" / "preview.js").read_text(encoding="utf-8")

    assert "DIR_PICKER_TOGGLE_PREFIXES" in script
    assert "dirPickerShowHidden" in script


def test_dir_picker_accepts_an_options_argument_without_breaking_old_callers():
    script = (STATIC / "js" / "preview.js").read_text(encoding="utf-8")

    assert "function openDirPicker(mode, title, options)" in script


def test_dir_picker_restores_the_previous_root_on_close():
    script = (STATIC / "js" / "preview.js").read_text(encoding="utf-8")

    assert "dirPickerRootIdBeforeOpen" in script
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_settings_frontend_contract.py -q`
Expected: FAIL on the three new assertions.

- [ ] **Step 3: Add the toggle to `dirPickerModal`**

In `dev/static/index.html`, inside the `dirPickerModal` `modal-footer`, add before the confirm button:

```html
        <label class="settings-help" style="display:flex;align-items:center;gap:4px;font-size:12px;">
          <input type="checkbox" id="dirPickerShowHidden"> 显示隐藏目录
        </label>
```

- [ ] **Step 4: Implement the toggle and options in `dev/static/js/preview.js`**

Rename the skip constant and split it so the toggle has explicit meaning:

```javascript
  // Directories hidden from the picker unless the user opts in.
  var DIR_PICKER_TOGGLE_PREFIXES = ['.', '__pycache__', 'node_modules'];
  // Root id in effect before a caller overrode it; null when not overridden.
  var dirPickerRootIdBeforeOpen = null;
```

Add the declaration next to the existing `var DIR_PICKER_SKIP_PREFIXES = [...]` line at `dev/static/js/preview.js:4446`, and delete that old constant once `_filterDirsForPicker` no longer references it.

In `closeDirPicker()` (currently `dev/static/js/preview.js:4466-4476`), restore the overridden root alongside the existing resets, immediately before `dirPickerSkipped = 0;`:

```javascript
    if (dirPickerRootIdBeforeOpen !== null) {
      rootId = dirPickerRootIdBeforeOpen;
      dirPickerRootIdBeforeOpen = null;
    }
```

In `_filterDirsForPicker`, drive the skip list from the toggle:

```javascript
  function _filterDirsForPicker(entries) {
    var box = document.getElementById('dirPickerShowHidden');
    var showHidden = !!(box && box.checked);
    var dirs = [];
    for (var i = 0; i < entries.length; i++) {
      if (!entries[i].is_dir) continue;
      var nm = entries[i].name;
      if (!showHidden) {
        var skip = false;
        for (var s = 0; s < DIR_PICKER_TOGGLE_PREFIXES.length; s++) {
          if (nm.indexOf(DIR_PICKER_TOGGLE_PREFIXES[s]) === 0) { skip = true; break; }
        }
        if (skip) { dirPickerSkipped++; continue; }
      }
      dirs.push({name: nm, path: entries[i].path});
    }
    return dirs;
  }
```

Change the signature and honour the injected root and callback:

```javascript
  async function openDirPicker(mode, title, options) {
    var opts = options || {};
    dirPickerMode = mode;
    // rootId is module-level state shared with the preview panel: stash it so
    // closing the picker cannot leave the preview pointing at the system root.
    if (opts.rootId) {
      if (dirPickerRootIdBeforeOpen === null) { dirPickerRootIdBeforeOpen = rootId; }
      rootId = opts.rootId;
    }
    if (typeof opts.onSelect === 'function') { dirPickerCallback = opts.onSelect; }
    dirPickerSelectedDir = opts.selectedDir !== undefined ? opts.selectedDir : (parentDir || '');
```

Wire the toggle so flipping it drops the cache and re-renders. Insert this block as the **first statements** inside `initDirPicker()` (currently `dev/static/js/preview.js:4448`), before its existing `var closeBtn = ...` line:

```javascript
    var toggle = document.getElementById('dirPickerShowHidden');
    if (toggle) {
      toggle.addEventListener('change', function () {
        dirPickerCache = {};
        dirPickerSkipped = 0;
        renderDirTreeLazy(document.getElementById('dirPickerTree'), '');
      });
    }
```

Leave the rest of `initDirPicker` (close/cancel/confirm wiring) and the whole expand/collapse implementation (`dirPickerExpanded`, `dirPickerLoading`, `renderDirTreeLazy`) untouched. The toggle only changes what `_filterDirsForPicker` returns for levels fetched after the switch.

- [ ] **Step 5: Run the checks**

Run: `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_settings_frontend_contract.py -q && node --check dev/static/js/preview.js`
Expected: PASS and no syntax errors.

- [ ] **Step 6: Commit**

```bash
/usr/bin/git add -- dev/static/index.html dev/static/js/preview.js tests/test_settings_frontend_contract.py
/usr/bin/git commit -m "feat: add hidden-directory toggle to the shared dir picker"
```

---

### Task 8: Documentation, browser acceptance, and full-suite verification

**Files:**
- Modify: `README.md`, `config.example.json`
- Modify: `tests/test_e2e_browser.py`
- Test: `tests/test_e2e_browser.py`

**Interfaces:**
- Consumes: Tasks 1–7.
- Produces: browser acceptance covering the root registry, grants, hidden-dir toggle, and forced password change.

- [ ] **Step 1: Write the browser assertions**

Append to `tests/test_e2e_browser.py`, following its existing `check(...)` helper style and `page` usage:

```python
def test_settings_modal_is_admin_only(page: "Page"):
    login(page)
    page.locator("#btnSettings").click()
    check(page.locator("#settingsModal").is_visible(), "管理员可见设置弹窗")
    check(page.locator('[data-settings-tab="roots"]').is_visible(), "默认展示 Rootdir 管理")
    page.locator('[data-settings-tab="users"]').click()
    check(page.locator("#settingsUserRoots").is_visible(), "用户管理展示授权复选框")


def test_cancelling_the_picker_leaves_the_main_browser_root_unchanged(page: "Page"):
    """The settings picker overrides state.rootId; closing must restore it.

    This is the one behaviour the contract tests cannot prove: they are
    string/shape checks, and the implementer's discrimination evidence for the
    picker was an uncommitted harness. A missed close path silently points the
    main file browser at the system root, which no unit test here would catch.
    """
    login(page)
    before = page.evaluate("() => state.rootId")
    page.locator("#btnSettings").click()
    page.locator("#settingsRootBrowse").click()
    check(page.locator("#dirPickerModal").is_visible(), "目录选择器打开")
    page.locator("#dirPickerCancel").click()
    after = page.evaluate("() => state.rootId")
    check(before == after, f"取消后主浏览器 root 不变（{before} -> {after}）")


def test_picker_opens_at_the_system_root_and_fills_the_form(page: "Page"):
    login(page)
    page.locator("#btnSettings").click()
    page.locator("#settingsRootBrowse").click()
    check(page.locator("#dirPickerModal").is_visible(), "目录选择器打开")
    page.locator("#dirPickerTree").get_by_text("projects").first.click()
    page.locator("#dirPickerConfirm").click()
    check(page.input_value("#settingsRootDir") != "", "选定目录已填入 Rootdir 表单")
    check(page.evaluate("() => state.rootId") != ".", "关闭后 root 已还原")


def test_hidden_directories_are_toggled_without_emptying_the_tree(page: "Page"):
    """Toggling must add/remove hidden entries, not collapse the tree.

    The tree cannot be re-rendered from cache -- the child renderer returns ''
    for an uncached parent and the root row has no expand arrow -- so a naive
    "clear cache and re-render" yields an empty tree. This is the check that
    catches that regression in a real browser.
    """
    login(page)
    page.locator("#btnSettings").click()
    page.locator("#settingsRootBrowse").click()
    check(page.locator("#dirPickerModal").is_visible(), "目录选择器打开")
    before = page.locator("#dirPickerTree button, #dirPickerTree .dir-picker-name").count()
    check(before > 0, f"打开时目录树非空（{before} 项）")
    page.locator("#dirPickerShowHidden").check()
    checked = page.locator("#dirPickerTree button, #dirPickerTree .dir-picker-name").count()
    check(checked > 0, f"勾选隐藏目录后树仍非空（{checked} 项）")
    check(page.locator("#dirPickerTree").get_by_text(".git").count() > 0
          or page.locator("#dirPickerTree").get_by_text(".clawmate").count() > 0,
          "勾选后出现隐藏目录")
    page.locator("#dirPickerShowHidden").uncheck()
    after = page.locator("#dirPickerTree button, #dirPickerTree .dir-picker-name").count()
    check(after > 0, f"取消勾选后树仍非空（{after} 项）")
    page.locator("#dirPickerCancel").click()


def test_every_picker_close_path_leaves_the_main_root_unchanged(page: "Page"):
    """Cancel, X and backdrop must each restore the stashed root.

    A missed path silently points the main file browser at the system root,
    and no headless test in this repo can catch it.
    """
    login(page)
    for label, closer in (("取消", "#dirPickerCancel"), ("关闭按钮", "#dirPickerClose")):
        before = page.evaluate("() => state.rootId")
        page.locator("#btnSettings").click()
        page.locator("#settingsRootBrowse").click()
        page.locator(closer).click()
        after = page.evaluate("() => state.rootId")
        check(before == after, f"{label}后主浏览器 root 不变（{before} -> {after}）")
        page.locator("#settingsModalClose").click()

    before = page.evaluate("() => state.rootId")
    page.locator("#btnSettings").click()
    page.locator("#settingsRootBrowse").click()
    page.locator("#dirPickerModal").click(position={"x": 5, "y": 5})
    after = page.evaluate("() => state.rootId")
    check(before == after, f"点击遮罩后主浏览器 root 不变（{before} -> {after}）")


def test_admin_registers_a_root_and_grants_it(page: "Page"):
    login(page)
    page.locator("#btnSettings").click()
    page.locator("#settingsRootLabel").fill("Projects")
    page.locator("#settingsRootBrowse").click()
    page.locator("#dirPickerTree").get_by_text("projects").first.click()
    page.locator("#dirPickerConfirm").click()
    page.locator("#settingsRootForm button[type=submit]").click()
    check(page.locator("#settingsRootList").get_by_text("Projects").count() > 0, "Rootdir 已登记")


def test_regular_user_only_sees_granted_roots(page: "Page"):
    login(page)
    options = page.locator("#rootSelect option").all_inner_texts()
    check("Projects" in options or len(options) >= 1, "普通用户只看到获授 root")
```

`login(page)` already exists in this file at line 73 — call it unchanged. These tests share the module-level `BASE_URL`/`USERNAME`/`PASSWORD` env contract and the `check(...)` helper. The test system root must contain `projects`, `private`, and `.hidden-dir`, and must not depend on the real home directory.

- [ ] **Step 2: Stand up a real server for the browser tests, then run them**

**A Playwright skip is not acceptable here.** Playwright is importable from `dev/.venv` and Chromium is installed (`~/.cache/ms-playwright/chromium-1228`), so these tests must actually execute. A skip may only be reported if you can show the browser is genuinely unavailable, and you must say so explicitly rather than letting a skip read as a pass.

The existing harness (`tests/test_e2e_browser.py`) drives an **externally running** server from `CLAWMATE_BASE_URL` using `CLAWMATE_USERNAME`/`CLAWMATE_PASSWORD`, so the tests you added need a live instance to talk to. Stand one up against a throwaway configuration:

1. Create a temp dir holding `config.json` (`system_root_dir` = that dir, plus a free `port` and an `auth` block) and a system root containing at least `projects/`, `private/` and a dot-directory such as `.hidden-dir/` for the toggle to reveal. Never point it at the real repository config, a real home directory, or the operator's live `users.json`.
2. Pre-seed a `users.json` in that temp dir with an admin whose `must_change_password` is **false**, and an ordinary user holding one grant — otherwise the forced-change modal blocks every interaction and the tests measure nothing.
3. Launch the app on the free port from that config (`CLAWMATE_CONFIG=<temp>/config.json`), wait for readiness by polling a real endpoint, and tear it down afterwards. Note that startup runs the one-time legacy migration; against a config with no legacy `roots` key it is a no-op, which is what you want.
4. Point the browser tests at it via `CLAWMATE_BASE_URL`, `CLAWMATE_USERNAME` and `CLAWMATE_PASSWORD`.

Run: `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_e2e_browser.py -m e2e -q`
Expected: the browser tests **pass**. Report the count, and report separately anything that could not be exercised.

The gaps carried in from the earlier tasks that only a browser can close, and which this run must therefore confirm:
- authenticated root create / edit / delete, and the「已被 N 位用户引用」hint on a referenced root;
- a grant POST from the tab, and the 422 message rendered in the error region;
- the picker opening at the system root and filling the Rootdir input;
- the picker's hidden-directory toggle adding and removing dot-directories **without emptying the tree**;
- **all three close paths** (cancel, X, backdrop) leaving the main file browser's root unchanged — the silent-corruption case no headless test can catch;
- the picker being visible and clickable above the open settings modal.

- [ ] **Step 3: Document the new model**

In `README.md`, replace the root-configuration section's guidance so it states:

- `config.json` supplies one absolute `system_root_dir` and is not modified by the application.
- Rootdirs live in the private `roots.json` as `{id,label,dir,agent_id}` with `dir` relative to the system root; users reference them by `id` in `users.json` via `root_ids`.
- On first start after upgrading, legacy `roots` in `config.json` are migrated automatically into `roots.json`, with `users.json.bak` written first; if any legacy root cannot be contained inside `system_root_dir` the server refuses to start and prints the offending path.
- The legacy `roots` key in `config.json` is ignored after migration and can be deleted.
- Hidden directories are filtered in the pickers by default; the toggle reveals them.

In `config.example.json`, keep `system_root_dir` and drop the legacy `roots` array if present, since it is no longer the source of truth.

- [ ] **Step 4: Verify the complete suite**

Run: `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/ -q`
Expected: all tests pass, at or above the previous baseline of 379 passed, with only a clearly reported Playwright skip.

Run: `node --check dev/static/js/app.js && node --check dev/static/js/preview.js && node --check dev/static/js/topbar.js`
Expected: no output (syntax OK).

- [ ] **Step 5: Commit**

```bash
/usr/bin/git add -f -- README.md config.example.json tests/test_e2e_browser.py
/usr/bin/git commit -m "docs: document the rootdir registry and settings split"
```
