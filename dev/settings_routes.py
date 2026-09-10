"""Administrator-only account and child-root management endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from auth import get_user_store

router = APIRouter()


def _admin(request: Request):
    session = getattr(request.state, "session", None)
    if not session or not session.get("is_admin"):
        raise HTTPException(status_code=403, detail="Administrator access required")
    return session


def _directory_choices(system_root: Path) -> list[str]:
    choices: list[str] = []
    for path in sorted(system_root.rglob("*")):
        if path.is_dir() and system_root in path.resolve().parents:
            choices.append(path.relative_to(system_root).as_posix())
    return choices


@router.get("/api/clawmate/settings/users")
async def list_users(request: Request):
    _admin(request)
    store = get_user_store()
    return JSONResponse({"users": store.list_public_users(), "root_dirs": _directory_choices(store.system_root_dir)})


@router.post("/api/clawmate/settings/users", status_code=201)
async def create_user(request: Request):
    _admin(request)
    body = await request.json()
    try:
        user = get_user_store().create_user(str(body.get("username", "")), str(body.get("password", "")),
                                            body.get("root_dirs", []), is_admin=bool(body.get("is_admin", False)))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(user.public(), status_code=201)


@router.patch("/api/clawmate/settings/users/{user_id}")
async def update_user(user_id: str, request: Request):
    _admin(request)
    body = await request.json()
    try:
        user = get_user_store().update_user(user_id, username=body.get("username"), password=body.get("password"),
                                             root_dirs=body.get("root_dirs"), is_admin=body.get("is_admin"))
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
