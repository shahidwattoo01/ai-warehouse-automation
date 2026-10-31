"""Users, refresh tokens and the login audit.

Two stores with the same methods: PostgreSQL (the app) and memory (tests and machines without a
database). Only hashes are stored: Argon2 for passwords, SHA-256 for refresh tokens.
"""

from __future__ import annotations

import datetime as dt
import threading
import uuid
from dataclasses import dataclass, replace

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import create_engine, text

from app.core.permissions import ROLES

# Bumped on every account change in this process: cached logins (app/core/auth.py) made before
# it are dropped at once, so disabling a user or changing a role is never delayed by the cache.
VERSION = [0]


def _changed() -> None:
    VERSION[0] += 1


_hasher = PasswordHasher()  # Argon2id, library defaults (OWASP-recommended parameters)
MIN_PASSWORD = 10


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_problem(password: str, username: str) -> str | None:
    """A reason the password is not acceptable, or None."""
    if len(password) < MIN_PASSWORD:
        return f"at least {MIN_PASSWORD} characters"
    if password.lower() == username.lower() or username.lower() in password.lower():
        return "must not contain the username"
    if password.isdigit() or password.isalpha():
        return "mix letters with digits or symbols"
    return None


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclass
class User:
    user_id: str
    username: str
    full_name: str
    role: str
    password_hash: str
    active: bool = True
    failed_logins: int = 0
    locked_until: dt.datetime | None = None
    created_at: dt.datetime | None = None
    last_login: dt.datetime | None = None

    def public(self) -> dict:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "full_name": self.full_name,
            "role": self.role,
            "role_label": ROLES[self.role]["label"],
            "active": self.active,
            "locked": bool(self.locked_until and self.locked_until > now()),
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class MemoryUserStore:
    """In-memory store (tests, and a fallback when no database is configured)."""

    def __init__(self) -> None:
        self.users: dict[str, User] = {}
        self.tokens: dict[str, dict] = {}
        self.events: list[dict] = []
        self._lock = threading.Lock()

    def get_by_username(self, username: str) -> User | None:
        return next(
            (replace(u) for u in self.users.values() if u.username.lower() == username.lower()),
            None,
        )

    def get(self, user_id: str) -> User | None:
        u = self.users.get(user_id)
        return replace(u) if u else None

    def list(self) -> list[User]:
        return sorted((replace(u) for u in self.users.values()), key=lambda u: u.username.lower())

    def create(self, username: str, full_name: str, role: str, password_hash: str) -> User:
        with self._lock:
            if self.get_by_username(username):
                raise ValueError(f"username {username} is taken")
            user = User(
                str(uuid.uuid4()), username, full_name, role, password_hash, created_at=now()
            )
            self.users[user.user_id] = user
            _changed()
            return replace(user)

    def update(self, user_id: str, **fields) -> None:
        with self._lock:
            u = self.users[user_id]
            for k, v in fields.items():
                setattr(u, k, v)
            _changed()

    def add_token(
        self, token_hash: str, user_id: str, family: str, expires_at: dt.datetime
    ) -> None:
        self.tokens[token_hash] = {
            "user_id": user_id,
            "family": family,
            "expires_at": expires_at,
            "revoked_at": None,
        }

    def get_token(self, token_hash: str) -> dict | None:
        t = self.tokens.get(token_hash)
        return dict(t, token_hash=token_hash) if t else None

    def revoke_token(self, token_hash: str) -> None:
        if token_hash in self.tokens and self.tokens[token_hash]["revoked_at"] is None:
            self.tokens[token_hash]["revoked_at"] = now()

    def revoke_family(self, family: str) -> None:
        for t in self.tokens.values():
            if t["family"] == family and t["revoked_at"] is None:
                t["revoked_at"] = now()

    def revoke_user_tokens(self, user_id: str) -> None:
        for t in self.tokens.values():
            if t["user_id"] == user_id and t["revoked_at"] is None:
                t["revoked_at"] = now()

    def log(self, username: str, user_id: str | None, outcome: str, client: str | None) -> None:
        self.events.append(
            {
                "username": username,
                "user_id": user_id,
                "outcome": outcome,
                "client": client,
                "created_at": now(),
            }
        )

    def login_events(self, limit: int = 100) -> list[dict]:
        return list(reversed(self.events))[:limit]


class SqlUserStore:
    """PostgreSQL store (tables of migration 005)."""

    COLUMNS = (
        "user_id, username, full_name, role, password_hash, active, failed_logins, locked_until, "
        "created_at, last_login"
    )

    def __init__(self, database_url: str) -> None:
        self.db = create_engine(database_url, pool_pre_ping=True)

    def _user(self, row) -> User | None:
        if row is None:
            return None
        d = dict(row._mapping)
        d["user_id"] = str(d["user_id"])
        return User(**d)

    def get_by_username(self, username: str) -> User | None:
        with self.db.connect() as c:
            row = c.execute(
                text(f"SELECT {self.COLUMNS} FROM users WHERE lower(username) = lower(:u)"),
                {"u": username},
            ).first()
        return self._user(row)

    def get(self, user_id: str) -> User | None:
        try:
            uuid.UUID(user_id)
        except ValueError:
            return None
        with self.db.connect() as c:
            row = c.execute(
                text(f"SELECT {self.COLUMNS} FROM users WHERE user_id = CAST(:i AS uuid)"),
                {"i": user_id},
            ).first()
        return self._user(row)

    def list(self) -> list[User]:
        with self.db.connect() as c:
            rows = c.execute(
                text(f"SELECT {self.COLUMNS} FROM users ORDER BY lower(username)")
            ).all()
        return [self._user(r) for r in rows]

    def create(self, username: str, full_name: str, role: str, password_hash: str) -> User:
        if self.get_by_username(username):
            raise ValueError(f"username {username} is taken")
        with self.db.begin() as c:
            row = c.execute(
                text(
                    "INSERT INTO users (username, full_name, role, password_hash) "
                    f"VALUES (:u, :f, :r, :p) "
                    f"RETURNING {self.COLUMNS}"
                ),
                {"u": username, "f": full_name, "r": role, "p": password_hash},
            ).first()
        _changed()
        return self._user(row)

    def update(self, user_id: str, **fields) -> None:
        allowed = {
            "full_name",
            "role",
            "password_hash",
            "active",
            "failed_logins",
            "locked_until",
            "last_login",
        }
        sets = {k: v for k, v in fields.items() if k in allowed}
        if "password_hash" in sets:
            sets["password_changed_at"] = now()
        if not sets:
            return
        assignments = ", ".join(f"{k} = :{k}" for k in sets)
        with self.db.begin() as c:
            c.execute(
                text(f"UPDATE users SET {assignments} WHERE user_id = CAST(:id AS uuid)"),
                {**sets, "id": user_id},
            )
        _changed()

    def add_token(
        self, token_hash: str, user_id: str, family: str, expires_at: dt.datetime
    ) -> None:
        with self.db.begin() as c:
            c.execute(
                text(
                    "INSERT INTO refresh_tokens (token_hash, user_id, family, expires_at) "
                    "VALUES (:h, CAST(:u AS uuid), CAST(:f AS uuid), :e)"
                ),
                {"h": token_hash, "u": user_id, "f": family, "e": expires_at},
            )

    def get_token(self, token_hash: str) -> dict | None:
        with self.db.connect() as c:
            row = c.execute(
                text(
                    "SELECT token_hash, user_id, family, expires_at, revoked_at "
                    "FROM refresh_tokens "
                    "WHERE token_hash = :h"
                ),
                {"h": token_hash},
            ).first()
        if row is None:
            return None
        d = dict(row._mapping)
        d["user_id"], d["family"] = str(d["user_id"]), str(d["family"])
        return d

    def revoke_token(self, token_hash: str) -> None:
        with self.db.begin() as c:
            c.execute(
                text(
                    "UPDATE refresh_tokens SET revoked_at = now() "
                    "WHERE token_hash = :h AND revoked_at IS NULL"
                ),
                {"h": token_hash},
            )

    def revoke_family(self, family: str) -> None:
        with self.db.begin() as c:
            c.execute(
                text(
                    "UPDATE refresh_tokens SET revoked_at = now() "
                    "WHERE family = CAST(:f AS uuid) AND revoked_at IS NULL"
                ),
                {"f": family},
            )

    def revoke_user_tokens(self, user_id: str) -> None:
        with self.db.begin() as c:
            c.execute(
                text(
                    "UPDATE refresh_tokens SET revoked_at = now() "
                    "WHERE user_id = CAST(:u AS uuid) AND revoked_at IS NULL"
                ),
                {"u": user_id},
            )

    def log(self, username: str, user_id: str | None, outcome: str, client: str | None) -> None:
        with self.db.begin() as c:
            c.execute(
                text(
                    "INSERT INTO login_events (username, user_id, outcome, client) "
                    "VALUES (:u, CAST(:i AS uuid), :o, :c)"
                ),
                {"u": username[:40], "i": user_id, "o": outcome, "c": (client or "")[:64]},
            )

    def login_events(self, limit: int = 100) -> list[dict]:
        with self.db.connect() as c:
            rows = c.execute(
                text(
                    "SELECT username, user_id, outcome, client, created_at FROM login_events "
                    "ORDER BY event_id DESC LIMIT :n"
                ),
                {"n": limit},
            ).all()
        return [
            {**dict(r._mapping), "user_id": str(r.user_id) if r.user_id else None} for r in rows
        ]
