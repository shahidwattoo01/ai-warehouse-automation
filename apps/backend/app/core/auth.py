"""Authentication and authorization.

* **Access token** (JWT, HS256, 15 min): sent by the browser as `Authorization: Bearer …`, held in
  memory only. Claims: sub (user id), name, role, iat, exp, jti, typ=access.
* **Refresh token** (random 64 bytes, 7 days): an httpOnly cookie the browser's JavaScript cannot
  read; stored only as a SHA-256 hash. Each refresh replaces it (rotation). Using an old, already
  replaced token again means it was stolen: the whole family of tokens is revoked.
* **Lockout:** after `login_max_failures` wrong passwords the account is locked for
  `lockout_minutes`.

Endpoints declare what they need with `Depends(require("wms:adjust"))`: no or invalid token →
401, missing permission → 403. The user is re-read on every request, so a disabled account or a
changed role takes effect at once, not when the token expires.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status

from app.core.config import get_settings
from app.core.permissions import ROLES, permissions_of
from app.services.users import (
    MemoryUserStore,
    SqlUserStore,
    User,
    hash_password,
    now,
    verify_password,
)

log = logging.getLogger(__name__)
ALGORITHM = "HS256"
ISSUER = "warehouse-ai"
REFRESH_COOKIE = "wai_refresh"


@lru_cache
def _secret() -> str:
    configured = get_settings().jwt_secret
    if configured:
        if len(configured) < 32:
            raise RuntimeError("JWT_SECRET must be at least 32 characters")
        return configured
    log.warning("JWT_SECRET is not set: using a random secret; logins end when the server restarts")
    return secrets.token_urlsafe(48)


@lru_cache
def _dummy_hash() -> str:
    return hash_password(secrets.token_hex(16))


@lru_cache
def get_store():
    settings = get_settings()
    return (
        MemoryUserStore()
        if settings.auth_store == "memory"
        else SqlUserStore(settings.database_url)
    )


@dataclass(frozen=True)
class Principal:
    """The authenticated user of a request."""

    user_id: str
    username: str
    full_name: str
    role: str
    permissions: frozenset[str]

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def public(self) -> dict:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "full_name": self.full_name,
            "role": self.role,
            "role_label": ROLES[self.role]["label"],
            "home": ROLES[self.role]["home"],
            "permissions": sorted(self.permissions),
        }


def principal_of(user: User) -> Principal:
    return Principal(
        user.user_id, user.username, user.full_name, user.role, frozenset(permissions_of(user.role))
    )


# ----- tokens -----------------------------------------------------------------------------------
def create_access_token(user: User) -> tuple[str, int]:
    minutes = get_settings().access_token_minutes
    issued = now()
    claims = {
        "sub": user.user_id,
        "name": user.username,
        "role": user.role,
        "iat": issued,
        "exp": issued + dt.timedelta(minutes=minutes),
        "jti": uuid.uuid4().hex,
        "iss": ISSUER,
        "typ": "access",
    }
    return jwt.encode(claims, _secret(), algorithm=ALGORITHM), minutes * 60


def decode_access_token(token: str) -> dict:
    claims = jwt.decode(
        token,
        _secret(),
        algorithms=[ALGORITHM],
        issuer=ISSUER,
        options={"require": ["exp", "sub", "typ"]},
    )
    if claims.get("typ") != "access":
        raise jwt.InvalidTokenError("not an access token")
    return claims


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_refresh_token(user_id: str, family: str | None = None) -> tuple[str, dt.datetime]:
    raw = secrets.token_urlsafe(64)
    expires = now() + dt.timedelta(days=get_settings().refresh_token_days)
    get_store().add_token(_hash(raw), user_id, family or str(uuid.uuid4()), expires)
    return raw, expires


# ----- login, refresh, logout ---------------------------------------------------------------------
class AuthError(Exception):
    def __init__(self, message: str, code: int = status.HTTP_401_UNAUTHORIZED) -> None:
        super().__init__(message)
        self.code = code


def login(username: str, password: str, client: str | None) -> User:
    """Check the password (with lockout); returns the user or raises AuthError."""
    store, settings = get_store(), get_settings()
    user = store.get_by_username(username)
    if user is None:
        verify_password(_dummy_hash(), password)  # same time as a real check: no username probing
        store.log(username, None, "unknown_user", client)
        raise AuthError("Wrong username or password")
    if user.locked_until and user.locked_until > now():
        store.log(username, user.user_id, "locked", client)
        raise AuthError("Account locked after too many failed logins; try again later", 423)
    if not user.active:
        store.log(username, user.user_id, "disabled", client)
        raise AuthError("Account disabled")
    if not verify_password(user.password_hash, password):
        failures = user.failed_logins + 1
        locked = (
            now() + dt.timedelta(minutes=settings.lockout_minutes)
            if failures >= settings.login_max_failures
            else None
        )
        store.update(user.user_id, failed_logins=0 if locked else failures, locked_until=locked)
        store.log(username, user.user_id, "locked_now" if locked else "wrong_password", client)
        raise AuthError("Wrong username or password")
    store.update(user.user_id, failed_logins=0, locked_until=None, last_login=now())
    store.log(username, user.user_id, "success", client)
    return user


def rotate_refresh_token(raw: str) -> tuple[User, str, dt.datetime]:
    store = get_store()
    record = store.get_token(_hash(raw)) if raw else None
    if record is None:
        raise AuthError("Not logged in")
    if record["revoked_at"] is not None:
        store.revoke_family(record["family"])  # an old token used again: assume theft
        raise AuthError("Session ended; log in again")
    if record["expires_at"] <= now():
        raise AuthError("Session expired; log in again")
    user = store.get(record["user_id"])
    if user is None or not user.active:
        raise AuthError("Account disabled")
    store.revoke_token(record["token_hash"])
    new_raw, expires = issue_refresh_token(user.user_id, record["family"])
    return user, new_raw, expires


def logout(raw: str | None) -> None:
    if raw:
        record = get_store().get_token(_hash(raw))
        if record:
            get_store().revoke_family(record["family"])


# ----- FastAPI dependencies -----------------------------------------------------------------------
def principal_from_token(token: str | None) -> Principal:
    if not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Not logged in", headers={"WWW-Authenticate": "Bearer"}
        )
    try:
        claims = decode_access_token(token)
    except jwt.ExpiredSignatureError as err:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Token expired", headers={"WWW-Authenticate": "Bearer"}
        ) from err
    except jwt.InvalidTokenError as err:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid token", headers={"WWW-Authenticate": "Bearer"}
        ) from err
    user = get_store().get(claims["sub"])
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled")
    return principal_of(user)


def current_user(request: Request) -> Principal:
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else None
    return principal_from_token(token)


def require(*permissions: str):
    """Dependency: the user must hold every listed permission."""
    for p in permissions:
        if p not in ROLES["admin"]["permissions"]:
            raise KeyError(f"unknown permission {p}")  # a typo must fail at start-up

    def check(user: Annotated[Principal, Depends(current_user)]) -> Principal:
        missing = [p for p in permissions if not user.can(p)]
        if missing:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "forbidden",
                    "message": f"Your role ({ROLES[user.role]['label']}) cannot do this",
                    "missing": missing,
                },
            )
        return user

    return check


def need(permission: str):
    """For a route decorator: `dependencies=[need("wms:view")]`."""
    return Depends(require(permission))
