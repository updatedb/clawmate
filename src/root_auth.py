"""Single fail-closed authorization choke point for root-aware request paths."""

from __future__ import annotations

from pathlib import Path

from fastapi.responses import JSONResponse

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


async def root_not_authorized_handler(request, exc) -> JSONResponse:
    """Authorization failures are 403, never a 500 with a stack trace."""
    return JSONResponse({"error": "forbidden", "detail": "Root not allowed"}, status_code=403)
