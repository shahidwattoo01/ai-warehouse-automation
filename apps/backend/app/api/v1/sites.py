"""Multi-site / 3PL management endpoints (Phase 12, PR-33).

Clients and sites are the two-level hierarchy for 3PL deployments:
  - A client owns one or more warehouse sites.
  - Each site runs its own simulation; users can be scoped to a site.

GET  /sites/clients               — list all clients
POST /sites/clients               — create a client
PUT  /sites/clients/{id}          — update a client
DELETE /sites/clients/{id}        — delete an empty client

GET  /sites                       — list all sites (or filter ?client_id=)
POST /sites                       — create a site
PUT  /sites/{id}                  — update a site
DELETE /sites/{id}                — delete a site

GET  /sites/reports               — per-site simulation run summary (last run metrics)
POST /sites/{site_id}/assign-user — scope a user to a site (admin only)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import Principal, need, require
from app.services.sites import get_site_store
from app.services.users import get_store as get_user_store
from app.services.simulator import simulator

router = APIRouter(prefix="/sites", tags=["sites"])
Admin = Annotated[Principal, Depends(require("sites:manage"))]


# ---- pydantic models ---------------------------------------------------------------

class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)


class ClientUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    active: bool | None = None


class SiteIn(BaseModel):
    client_id: str = Field(min_length=1, max_length=36)
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)
    timezone: str = Field(default="UTC", max_length=64)


class SiteUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    timezone: str | None = Field(default=None, max_length=64)
    active: bool | None = None


class AssignUserIn(BaseModel):
    user_id: str


# ---- client endpoints --------------------------------------------------------------

@router.get("/clients", dependencies=[need("sites:manage")])
async def list_clients() -> list[dict]:
    store = get_site_store()
    return [c.public() for c in store.list_clients()]


@router.post("/clients")
async def create_client(body: ClientIn, _: Admin) -> dict:
    store = get_site_store()
    try:
        client = store.create_client(body.name, body.description)
    except ValueError as e:
        raise HTTPException(409, {"code": "conflict", "message": str(e)}) from e
    return client.public()


@router.put("/clients/{client_id}")
async def update_client(client_id: str, body: ClientUpdate, _: Admin) -> dict:
    store = get_site_store()
    if not store.get_client(client_id):
        raise HTTPException(404, {"code": "not_found", "message": f"client {client_id} not found"})
    updates = body.model_dump(exclude_none=True)
    store.update_client(client_id, **updates)
    return store.get_client(client_id).public()


@router.delete("/clients/{client_id}")
async def delete_client(client_id: str, _: Admin) -> dict:
    store = get_site_store()
    if not store.get_client(client_id):
        raise HTTPException(404, {"code": "not_found", "message": f"client {client_id} not found"})
    try:
        store.delete_client(client_id)
    except ValueError as e:
        raise HTTPException(409, {"code": "conflict", "message": str(e)}) from e
    return {"deleted": client_id}


# ---- site endpoints ----------------------------------------------------------------

@router.get("", dependencies=[need("sites:manage")])
async def list_sites(client_id: str | None = None) -> list[dict]:
    store = get_site_store()
    return [s.public() for s in store.list_sites(client_id)]


@router.post("")
async def create_site(body: SiteIn, _: Admin) -> dict:
    store = get_site_store()
    try:
        site = store.create_site(body.client_id, body.name, body.description, body.timezone)
    except ValueError as e:
        raise HTTPException(409, {"code": "conflict", "message": str(e)}) from e
    return site.public()


@router.put("/{site_id}")
async def update_site(site_id: str, body: SiteUpdate, _: Admin) -> dict:
    store = get_site_store()
    if not store.get_site(site_id):
        raise HTTPException(404, {"code": "not_found", "message": f"site {site_id} not found"})
    updates = body.model_dump(exclude_none=True)
    store.update_site(site_id, **updates)
    return store.get_site(site_id).public()


@router.delete("/{site_id}")
async def delete_site(site_id: str, _: Admin) -> dict:
    store = get_site_store()
    if not store.get_site(site_id):
        raise HTTPException(404, {"code": "not_found", "message": f"site {site_id} not found"})
    store.delete_site(site_id)
    return {"deleted": site_id}


# ---- per-site reports --------------------------------------------------------------

@router.get("/reports", dependencies=[need("analytics:view")])
async def site_reports() -> dict:
    """Return a summary of simulation runs grouped by site and client."""
    eng = simulator.engine
    site_store = get_site_store()
    clients = {c.client_id: c.public() for c in site_store.list_clients()}
    sites = {s.site_id: s.public() for s in site_store.list_sites()}

    # Gather last-run metrics from the engine's run store if available.
    run_store = getattr(eng, "_run_store", None)
    runs: list[dict] = []
    if run_store is not None:
        try:
            runs = run_store.recent(limit=50)
        except Exception:
            pass

    # Group by site_id.
    by_site: dict[str, list[dict]] = {}
    for run in runs:
        sid = run.get("site_id") or "_unassigned"
        by_site.setdefault(sid, []).append(run)

    report_rows = []
    for sid, site_runs in by_site.items():
        last = site_runs[-1]
        metrics = last.get("metrics") or {}
        site_info = sites.get(sid, {"site_id": sid, "name": "Unassigned", "client_id": None})
        client_id = site_info.get("client_id")
        client_info = clients.get(client_id, {"name": "—"}) if client_id else {"name": "—"}
        report_rows.append({
            "site_id": sid,
            "site_name": site_info.get("name", sid),
            "client_name": client_info.get("name", "—"),
            "runs": len(site_runs),
            "last_run_id": str(last.get("run_id", "")),
            "throughput_per_hour": metrics.get("throughput_per_hour"),
            "late_percent": metrics.get("late_percent"),
            "avg_completion_ticks": metrics.get("avg_completion_ticks"),
        })

    return {
        "clients": list(clients.values()),
        "sites": list(sites.values()),
        "report": report_rows,
    }


# ---- user ↔ site assignment --------------------------------------------------------

@router.post("/{site_id}/assign-user")
async def assign_user(site_id: str, body: AssignUserIn, _: Admin) -> dict:
    """Scope a user to a specific site (or pass site_id=null to remove the scope)."""
    site_store = get_site_store()
    if not site_store.get_site(site_id):
        raise HTTPException(404, {"code": "not_found", "message": f"site {site_id} not found"})
    user_store = get_user_store()
    user = user_store.get(body.user_id)
    if not user:
        raise HTTPException(404, {"code": "not_found", "message": f"user {body.user_id} not found"})
    user_store.update(body.user_id, site_id=site_id)
    return {"user_id": body.user_id, "site_id": site_id}
