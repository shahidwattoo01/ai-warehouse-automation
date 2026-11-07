"""Multi-site / 3PL support (Phase 12, PR-33).

Two stores with the same interface: memory (tests, no-DB installs) and PostgreSQL.
Both manage two resources:
  - clients  — a 3PL customer or single owner
  - sites    — a physical warehouse belonging to one client
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.core.config import get_settings


# ---- domain objects ----------------------------------------------------------------

@dataclass
class Client:
    client_id: str
    name: str
    description: str
    active: bool = True
    created_at: str = ""

    def public(self) -> dict:
        return {
            "client_id": self.client_id,
            "name": self.name,
            "description": self.description,
            "active": self.active,
            "created_at": self.created_at,
        }


@dataclass
class Site:
    site_id: str
    client_id: str
    name: str
    description: str
    timezone: str = "UTC"
    active: bool = True
    created_at: str = ""

    def public(self) -> dict:
        return {
            "site_id": self.site_id,
            "client_id": self.client_id,
            "name": self.name,
            "description": self.description,
            "timezone": self.timezone,
            "active": self.active,
            "created_at": self.created_at,
        }


# ---- memory store (tests / no-DB) --------------------------------------------------

class MemorySiteStore:
    def __init__(self) -> None:
        self._clients: dict[str, Client] = {}
        self._sites: dict[str, Site] = {}
        self._lock = threading.Lock()

    # Clients -----------------------------------------------------------------------
    def list_clients(self) -> list[Client]:
        return sorted(self._clients.values(), key=lambda c: c.name.lower())

    def get_client(self, client_id: str) -> Client | None:
        return self._clients.get(client_id)

    def create_client(self, name: str, description: str = "") -> Client:
        with self._lock:
            if any(c.name.lower() == name.lower() for c in self._clients.values()):
                raise ValueError(f"client name '{name}' is already taken")
            c = Client(str(uuid.uuid4()), name, description)
            self._clients[c.client_id] = c
            return c

    def update_client(self, client_id: str, **fields: Any) -> None:
        with self._lock:
            c = self._clients[client_id]
            for k, v in fields.items():
                setattr(c, k, v)

    def delete_client(self, client_id: str) -> None:
        with self._lock:
            if any(s.client_id == client_id for s in self._sites.values()):
                raise ValueError("cannot delete a client that still has sites")
            self._clients.pop(client_id, None)

    # Sites -------------------------------------------------------------------------
    def list_sites(self, client_id: str | None = None) -> list[Site]:
        sites = self._sites.values()
        if client_id:
            sites = (s for s in sites if s.client_id == client_id)
        return sorted(sites, key=lambda s: s.name.lower())

    def get_site(self, site_id: str) -> Site | None:
        return self._sites.get(site_id)

    def create_site(self, client_id: str, name: str, description: str = "", timezone: str = "UTC") -> Site:
        with self._lock:
            if client_id not in self._clients:
                raise ValueError(f"client {client_id} does not exist")
            if any(s.client_id == client_id and s.name.lower() == name.lower() for s in self._sites.values()):
                raise ValueError(f"site name '{name}' is already taken for this client")
            s = Site(str(uuid.uuid4()), client_id, name, description, timezone)
            self._sites[s.site_id] = s
            return s

    def update_site(self, site_id: str, **fields: Any) -> None:
        with self._lock:
            s = self._sites[site_id]
            for k, v in fields.items():
                setattr(s, k, v)

    def delete_site(self, site_id: str) -> None:
        with self._lock:
            self._sites.pop(site_id, None)


# ---- SQL store (PostgreSQL migration 008) ------------------------------------------

class SqlSiteStore:
    def __init__(self, database_url: str) -> None:
        from sqlalchemy import create_engine
        self.db = create_engine(database_url, pool_pre_ping=True)

    def _client(self, row) -> Client | None:
        if row is None:
            return None
        d = dict(row._mapping)
        d.setdefault("description", "")
        d["created_at"] = str(d.get("created_at", ""))
        return Client(**{k: v for k, v in d.items() if k in Client.__dataclass_fields__})

    def _site(self, row) -> Site | None:
        if row is None:
            return None
        d = dict(row._mapping)
        d.setdefault("description", "")
        d["created_at"] = str(d.get("created_at", ""))
        return Site(**{k: v for k, v in d.items() if k in Site.__dataclass_fields__})

    def list_clients(self) -> list[Client]:
        from sqlalchemy import text
        with self.db.connect() as c:
            rows = c.execute(text("SELECT client_id, name, description, active, created_at FROM clients ORDER BY lower(name)")).all()
        return [self._client(r) for r in rows]

    def get_client(self, client_id: str) -> Client | None:
        from sqlalchemy import text
        with self.db.connect() as c:
            row = c.execute(text("SELECT client_id, name, description, active, created_at FROM clients WHERE client_id = :i"), {"i": client_id}).first()
        return self._client(row)

    def create_client(self, name: str, description: str = "") -> Client:
        from sqlalchemy import text
        with self.db.begin() as c:
            row = c.execute(
                text("INSERT INTO clients (name, description) VALUES (:n, :d) RETURNING client_id, name, description, active, created_at"),
                {"n": name, "d": description}
            ).first()
        return self._client(row)

    def update_client(self, client_id: str, **fields: Any) -> None:
        from sqlalchemy import text
        allowed = {"name", "description", "active"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        assignments = ", ".join(f"{k} = :{k}" for k in sets)
        with self.db.begin() as c:
            c.execute(text(f"UPDATE clients SET {assignments} WHERE client_id = :id"), {**sets, "id": client_id})

    def delete_client(self, client_id: str) -> None:
        from sqlalchemy import text
        with self.db.begin() as c:
            count = c.execute(text("SELECT count(*) FROM sites WHERE client_id = :i"), {"i": client_id}).scalar()
            if count:
                raise ValueError("cannot delete a client that still has sites")
            c.execute(text("DELETE FROM clients WHERE client_id = :i"), {"i": client_id})

    def list_sites(self, client_id: str | None = None) -> list[Site]:
        from sqlalchemy import text
        q = "SELECT site_id, client_id, name, description, timezone, active, created_at FROM sites"
        params: dict = {}
        if client_id:
            q += " WHERE client_id = :c"
            params["c"] = client_id
        q += " ORDER BY lower(name)"
        with self.db.connect() as c:
            rows = c.execute(text(q), params).all()
        return [self._site(r) for r in rows]

    def get_site(self, site_id: str) -> Site | None:
        from sqlalchemy import text
        with self.db.connect() as c:
            row = c.execute(text("SELECT site_id, client_id, name, description, timezone, active, created_at FROM sites WHERE site_id = :i"), {"i": site_id}).first()
        return self._site(row)

    def create_site(self, client_id: str, name: str, description: str = "", timezone: str = "UTC") -> Site:
        from sqlalchemy import text
        with self.db.begin() as c:
            row = c.execute(
                text("INSERT INTO sites (client_id, name, description, timezone) VALUES (:ci, :n, :d, :tz) RETURNING site_id, client_id, name, description, timezone, active, created_at"),
                {"ci": client_id, "n": name, "d": description, "tz": timezone}
            ).first()
        return self._site(row)

    def update_site(self, site_id: str, **fields: Any) -> None:
        from sqlalchemy import text
        allowed = {"name", "description", "timezone", "active"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        assignments = ", ".join(f"{k} = :{k}" for k in sets)
        with self.db.begin() as c:
            c.execute(text(f"UPDATE sites SET {assignments} WHERE site_id = :id"), {**sets, "id": site_id})

    def delete_site(self, site_id: str) -> None:
        from sqlalchemy import text
        with self.db.begin() as c:
            c.execute(text("DELETE FROM sites WHERE site_id = :i"), {"i": site_id})


# ---- singleton factory -------------------------------------------------------------

@lru_cache
def get_site_store() -> MemorySiteStore | SqlSiteStore:
    settings = get_settings()
    if settings.auth_store == "memory" or not settings.database_url:
        return MemorySiteStore()
    return SqlSiteStore(settings.database_url)
