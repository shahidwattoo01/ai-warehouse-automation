# Phase 12 — Finalization

**Status:** done  
**Backlog items:** PR-02 (HTTPS), PR-24 (licence), PR-33 (multi-site / 3PL)  
**Phases updated to done:** 10 (Integration), 11 (Evaluation)

---

## PR-24 — Licence decision

The project source code is released under the **MIT Licence** (`LICENSE`).

The one dependency that requires attention is **Ultralytics YOLO (AGPL-3.0)**:
- Using YOLO for personal, research or portfolio work: **free**.
- Distributing or serving the platform over a network: the AGPL-3.0 terms require publishing the complete source (or obtaining an Ultralytics Enterprise Licence).
- Switching to a permissive alternative (torchvision Faster R-CNN / Apache-2.0 RT-DETR) is straightforward: the detector is isolated to `ai/computer_vision/live.py` and the `/api/v1/vision/detect` endpoint.

See `THIRD_PARTY_LICENSES.md` for the full dependency list and `LICENSE` for the full text.

---

## PR-02 — HTTPS configuration

Application-level security was already in place (rate limits, security headers, HSTS, httpOnly cookies, 15 min access tokens).  Phase 12 adds the deployment-level TLS layer:

- **`docker/nginx-tls.conf`** — nginx config with TLS 1.2/1.3 termination, strong ciphers (ECDHE + ChaCha20), OCSP stapling, permanent HTTP → HTTPS redirect, WebSocket pass-through.
- **`docker-compose.tls.yml`** — Compose overlay that adds the nginx service and removes the direct backend port. Activated with:

  ```bash
  docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d
  ```

  Operator places certificates at `./certs/warehouse.crt` and `./certs/warehouse.key` (Let's Encrypt or self-signed).

---

## PR-33 — Multi-site / 3PL support

A two-level hierarchy: **clients** own one or more **sites** (physical warehouses).

### Database (migration 008)

| Table | Key columns |
|-------|-------------|
| `clients` | client_id (UUID), name, description, active |
| `sites` | site_id (UUID), client_id FK, name, timezone, active |
| `users.site_id` | nullable FK → sites; NULL = all-site admin |
| `simulation_runs.site_id` | nullable FK → sites; tags a run to its site |

### Backend (`apps/backend/app/`)

- `services/sites.py` — `MemorySiteStore` and `SqlSiteStore`, both implementing `list_clients`, `create_client`, `list_sites`, `create_site`, `update_*`, `delete_*`.
- `api/v1/sites.py` — REST endpoints:
  - `GET/POST /sites/clients` — list / create clients
  - `PUT/DELETE /sites/clients/{id}` — update / delete
  - `GET/POST /sites` — list / create sites (optional `?client_id=` filter)
  - `PUT/DELETE /sites/{id}` — update / delete
  - `GET /sites/reports` — per-site last-run metrics (throughput, late %, avg completion)
  - `POST /sites/{id}/assign-user` — scope a user to a site
- `core/permissions.py` — `sites:manage` permission added; admin only.
- `services/users.py` — `User.site_id` field; propagated through `Principal`.

### Frontend

- `/admin/sites` (`app/admin/sites/page.tsx`) — create/delete clients and sites, displays site list per client.
- `/reports` (`app/reports/page.tsx`) — per-client and per-site throughput, late %, and avg completion time for the last simulation run tagged to each site.

---

## All 33 backlog items closed

PR-01 through PR-33 are all `status: done` in `reports/professional_backlog.yaml`.
