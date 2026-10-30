"""Login, session and user administration.

POST /auth/login            username + password -> access token; refresh token as httpOnly cookie
POST /auth/refresh          new access token (and a new refresh cookie) from the cookie
POST /auth/logout           ends the session (refresh tokens revoked, cookie removed)
GET  /auth/me               the logged-in user, role and permissions
PUT  /auth/password         change your own password
GET  /auth/roles            roles and permissions (the access-control table)
/users ...                  user administration (permission users:manage)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.core import auth
from app.core.config import get_settings
from app.core.permissions import PERMISSIONS, ROLES
from app.services.users import hash_password, password_problem, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])
Me = Annotated[auth.Principal, Depends(auth.current_user)]
Admin = Annotated[auth.Principal, Depends(auth.require("users:manage"))]


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)


def _client(request: Request) -> str:
    host = request.client.host if request.client else "?"
    return f"{host} {request.headers.get('user-agent', '')[:40]}"


def _session(response: Response, user, refresh: str, expires) -> dict:
    s = get_settings()
    response.set_cookie(
        auth.REFRESH_COOKIE,
        refresh,
        httponly=True,  # JavaScript cannot read it
        secure=s.cookie_secure,
        samesite="strict",
        path="/api/v1/auth",  # only sent to the auth endpoints
        expires=expires,
    )
    access, ttl = auth.create_access_token(user)
    return {
        "access_token": access,
        "token_type": "bearer",
        "expires_in": ttl,
        "user": auth.principal_of(user).public(),
    }


def _fail(err: auth.AuthError) -> HTTPException:
    return HTTPException(err.code, detail={"code": "auth", "message": str(err)})


class SetupIn(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")
    full_name: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=1, max_length=200)


@router.get("/setup")
def setup_status() -> dict:
    """First run: true while no account exists yet (the login page then offers to create the
    first administrator)."""
    return {"needs_setup": not auth.get_store().list()}


@router.post("/setup", status_code=201)
def setup(body: SetupIn, request: Request, response: Response) -> dict:
    """Create the first administrator. Only possible while there are no accounts at all; after
    that, accounts are created by administrators under Users & roles."""
    store = auth.get_store()
    if store.list():
        raise HTTPException(
            409, detail={"code": "setup_done", "message": "Setup is already done; log in"}
        )
    problem = password_problem(body.password, body.username)
    if problem:
        raise HTTPException(
            422, detail={"code": "weak_password", "message": f"Password: {problem}"}
        )
    user = store.create(body.username, body.full_name, "admin", hash_password(body.password))
    store.log(user.username, user.user_id, "first_admin_created", _client(request))
    refresh, expires = auth.issue_refresh_token(user.user_id)
    return _session(response, user, refresh, expires)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response) -> dict:
    try:
        user = auth.login(body.username.strip(), body.password, _client(request))
    except auth.AuthError as err:
        raise _fail(err) from err
    refresh, expires = auth.issue_refresh_token(user.user_id)
    return _session(response, user, refresh, expires)


@router.post("/refresh")
def refresh(request: Request, response: Response) -> dict:
    try:
        user, new_refresh, expires = auth.rotate_refresh_token(
            request.cookies.get(auth.REFRESH_COOKIE, "")
        )
    except auth.AuthError as err:
        response.delete_cookie(auth.REFRESH_COOKIE, path="/api/v1/auth")
        raise _fail(err) from err
    return _session(response, user, new_refresh, expires)


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    auth.logout(request.cookies.get(auth.REFRESH_COOKIE))
    response.delete_cookie(auth.REFRESH_COOKIE, path="/api/v1/auth")
    return {"ok": True}


@router.get("/me")
def me(user: Me) -> dict:
    return user.public()


class PasswordIn(BaseModel):
    current: str = Field(min_length=1, max_length=200)
    new: str = Field(min_length=1, max_length=200)


@router.put("/password")
def change_password(body: PasswordIn, user: Me) -> dict:
    store = auth.get_store()
    record = store.get(user.user_id)
    if record is None or not verify_password(record.password_hash, body.current):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "auth", "message": "Current password is wrong"},
        )
    problem = password_problem(body.new, user.username)
    if problem:
        raise HTTPException(
            422, detail={"code": "weak_password", "message": f"New password: {problem}"}
        )
    store.update(user.user_id, password_hash=hash_password(body.new))
    store.revoke_user_tokens(user.user_id)  # other sessions end
    return {"ok": True}


@router.get("/roles")
def roles(_: Me) -> dict:
    return {
        "permissions": PERMISSIONS,
        "roles": {k: {**v, "permissions": sorted(v["permissions"])} for k, v in ROLES.items()},
    }


# ----- user administration -----------------------------------------------------------------------
class NewUser(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")
    full_name: str = Field(min_length=2, max_length=80)
    role: str
    password: str = Field(min_length=1, max_length=200)


class UserChange(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=80)
    role: str | None = None
    active: bool | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=1, max_length=200)


def _check_role(role: str) -> None:
    if role not in ROLES:
        raise HTTPException(422, detail={"code": "role", "message": f"Unknown role {role}"})


def _other_active_admins(exclude: str) -> int:
    return sum(
        1
        for u in auth.get_store().list()
        if u.role == "admin" and u.active and u.user_id != exclude
    )


@users_router.get("")
def list_users(_: Admin) -> list[dict]:
    return [u.public() for u in auth.get_store().list()]


@users_router.post("", status_code=201)
def create_user(body: NewUser, _: Admin) -> dict:
    _check_role(body.role)
    problem = password_problem(body.password, body.username)
    if problem:
        raise HTTPException(
            422, detail={"code": "weak_password", "message": f"Password: {problem}"}
        )
    try:
        user = auth.get_store().create(
            body.username, body.full_name, body.role, hash_password(body.password)
        )
    except ValueError as err:
        raise HTTPException(409, detail={"code": "taken", "message": str(err)}) from err
    return user.public()


@users_router.put("/{user_id}")
def change_user(user_id: str, body: UserChange, admin: Admin) -> dict:
    store = auth.get_store()
    user = store.get(user_id)
    if user is None:
        raise HTTPException(404, detail="No such user")
    fields = body.model_dump(exclude_none=True)
    if "role" in fields:
        _check_role(fields["role"])
    losing_admin = user.role == "admin" and (
        fields.get("role", "admin") != "admin" or fields.get("active") is False
    )
    if losing_admin and _other_active_admins(user_id) == 0:
        raise HTTPException(
            409,
            detail={"code": "last_admin", "message": "There must stay at least one active admin"},
        )
    store.update(user_id, **fields)
    if fields.get("active") is False or "role" in fields:
        store.revoke_user_tokens(user_id)  # the change applies at once
    return store.get(user_id).public()


@users_router.post("/{user_id}/password")
def reset_password(user_id: str, body: PasswordReset, _: Admin) -> dict:
    store = auth.get_store()
    user = store.get(user_id)
    if user is None:
        raise HTTPException(404, detail="No such user")
    problem = password_problem(body.password, user.username)
    if problem:
        raise HTTPException(
            422, detail={"code": "weak_password", "message": f"Password: {problem}"}
        )
    store.update(
        user_id, password_hash=hash_password(body.password), failed_logins=0, locked_until=None
    )
    store.revoke_user_tokens(user_id)
    return {"ok": True}


@users_router.post("/{user_id}/unlock")
def unlock(user_id: str, _: Admin) -> dict:
    if auth.get_store().get(user_id) is None:
        raise HTTPException(404, detail="No such user")
    auth.get_store().update(user_id, failed_logins=0, locked_until=None)
    return {"ok": True}


@users_router.get("/login-events")
def login_events(_: Admin, limit: int = 100) -> list[dict]:
    return [
        {**e, "created_at": e["created_at"].isoformat()}
        for e in auth.get_store().login_events(min(limit, 500))
    ]
