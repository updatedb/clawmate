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


def _validate_root_ids(root_ids: object) -> list[str]:
    """Grant ids must reference registered roots. Unknown ids are a 422.

    Existence lives here rather than in UserStore so that the store holds no
    registry knowledge, mirroring how RootRegistry.delete(referenced_by=...)
    keeps the registry free of user knowledge.
    """
    if not isinstance(root_ids, list):
        raise HTTPException(status_code=422, detail="root_ids 必须是列表")
    registry = _registry()
    result: list[str] = []
    for value in root_ids:
        root_id = str(value).strip()
        try:
            entry = registry.get(root_id)
        except RootRegistryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if entry is None:
            raise HTTPException(status_code=422, detail=f"未知的 root id: {root_id}")
        if root_id not in result:
            result.append(root_id)
    return result


@router.get("/api/clawmate/settings/roots")
async def list_roots(request: Request):
    _admin(request)
    try:
        roots = _registry().public_list()
    except RootRegistryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse({"roots": roots})


@router.post("/api/clawmate/settings/roots", status_code=201)
async def create_root(request: Request):
    _admin(request)
    body = await request.json()
    try:
        entry = _registry().create(
            # An explicit JSON null is treated like an absent key for id/label:
            # without the `or ""` the value would stringify to "None".
            label=str(body.get("label") or ""),
            dir=str(body.get("dir", "")),
            agent_id=str(body.get("agent_id", "") or "default"),
            root_id=str(body.get("id") or "").strip() or None,
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
        _registry().delete(root_id, referenced_by=_registry().referenced_ids(
            get_user_store().list_public_users()))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RootRegistryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse({"ok": True})


@router.get("/api/clawmate/settings/users")
async def list_users(request: Request):
    _admin(request)
    store = get_user_store()
    try:
        roots = [{"id": entry.id, "label": entry.label} for entry in _registry().list_all()]
    except RootRegistryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse({"users": store.list_public_users(), "roots": roots})


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
        raise HTTPException(status_code=404, detail="用户不存在")
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


@router.delete("/api/clawmate/settings/users/{user_id}")
async def delete_user(user_id: str, request: Request):
    session = _admin(request)
    try:
        get_user_store().delete_user(user_id, actor_id=str(session.get("user_id", "")))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse({"ok": True})
