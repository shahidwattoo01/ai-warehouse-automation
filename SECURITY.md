# Security

## Deployment model

The platform is a **local digital twin** with user accounts: the simulator, API, database and UI
run on one machine (development, training and demonstrations). It does not control physical
robots. The protections below fit that model; the
[production section](#before-production) lists what a real site needs on top.

## What is protected today

| Area | Protection | Where |
|---|---|---|
| Authentication | Username + password (Argon2id hashes); JWT access tokens (HS256, 15 min, in browser memory only) and rotating refresh tokens (httpOnly SameSite=Strict cookie, 7 days, stored as SHA-256 hashes; reuse of an old token revokes the whole session); 5 failed logins lock the account for 15 min; login audit | `apps/backend/app/core/auth.py`, migration 005 |
| Authorization | Five roles, 24 permissions, checked on **every** endpoint and the live stream (401 without login, 403 without permission); copilot approvals also need the action's own permission; changes are booked under the logged-in user, never a name sent by the browser | `apps/backend/app/core/permissions.py`, `docs/authentication.md` |
| Accounts | Created only by an administrator (no sign-up); password policy; the last active admin cannot be removed; disabling a user or changing a role ends their sessions at once | `apps/backend/app/api/v1/auth.py` |
| Network exposure | Docker publishes the API (8000), UI (3000) and database (5432) on `127.0.0.1` only; nothing is reachable from other machines | `docker-compose.yml` |
| Cross-site requests | State-changing requests and the live stream are refused unless they come from an allowed origin (a malicious website cannot pause robots or reset a run through the operator's browser) | `apps/backend/app/core/security.py` |
| CORS | Only the configured UI origins; credentials (the refresh cookie) only for those origins | `apps/backend/app/main.py` |
| Rate limiting | Per client address, answered with 429 and `Retry-After`: login and first-time setup 10 per minute (password guessing across accounts; the per-account lockout protects one account), token refresh 30, changes 120, all API requests 600 per minute; `/health`, `/ready`, `/metrics` and the live stream exempt. `RATE_LIMIT_SCALE` for a class behind one address; `TRUST_PROXY_HEADERS=true` only behind a reverse proxy | `apps/backend/app/core/ratelimit.py` |
| Security headers | API: `nosniff`, `X-Frame-Options: DENY`, `Content-Security-Policy: default-src 'none'`, no referrer, token answers `Cache-Control: no-store`, HSTS when `COOKIE_SECURE=true`. UI: a Content Security Policy that allows only the page itself, the API and the Google fonts (no framing, `object-src` only for the label PDFs), `nosniff`, a referrer policy, camera only for the page itself (barcode scanning), no `X-Powered-By` | `apps/backend/app/core/ratelimit.py`, `apps/frontend/next.config.mjs` |
| Secrets | Database password, `JWT_SECRET` and API keys only in `.env` (git-ignored); `.env.example` holds placeholders; development users' passwords only in the git-ignored `dev_users.local.json` | `.gitignore`, `.env.example` |
| Input validation | Typed request models (Pydantic) with limits; camera frames limited to 5 MB and decoded safely, clear 4xx errors | `apps/backend/app/schemas/`, `apps/backend/app/api/v1/vision.py` |
| Robot interface (VDA 5050) | MQTT broker of the compose setup published on 127.0.0.1 only; orders and states validated on both sides; a networked broker needs TLS, per-vehicle credentials and ACLs (docs/vda5050.md) | `integration/vda5050/`, `docker/mosquitto.conf` |
| ERP webhook | No user login (machine to machine) but HMAC-SHA256 signature of timestamp and body with ERP_WEBHOOK_SECRET, 5-minute replay window, constant-time comparison; off without a secret; idempotent by ERP order number | `integration/erp/connector.py`, `apps/backend/app/api/v1/erp.py` |
| Output injection | CSV exports neutralise spreadsheet formulas (`=`, `+`, `-`, `@`); ZPL labels strip the printer command characters `^` and `~`; label printers are reached only by configured name, never by an address from a request | `wms/exports.py`, `wms/zpl.py`, `apps/backend/app/services/printers.py` |
| SQL injection | Parameterised queries only (SQLAlchemy `text()` with bound parameters) | `apps/backend/app/services/run_store.py` |
| Containers | Run as non-root users; runtime images without build tools | `docker/*.Dockerfile` |
| Model loading | Only the project's own model files are loaded; the PyTorch networks load with `weights_only=True` (tensors and plain values only, no code); YOLO weights are loaded by Ultralytics from `models/vision_yolo_v1/` | `ai/deep_learning/`, `ai/computer_vision/live.py` |
| Privacy / telemetry | Ultralytics analytics off (`YOLO_OFFLINE`, `sync=False`), Next.js telemetry off in CI; no personal data in any dataset | `ai/computer_vision/live.py`, CI |
| Dependencies | Exact versions pinned; known-vulnerability scan (`pip-audit`, `npm audit`) on every CI run | `requirements*.txt`, `.github/workflows/ci.yml` |

**Still missing for a networked deployment:** TLS (set `COOKIE_SECURE=true` behind HTTPS) and
single sign-on with the company identity provider (backlog PR-02). The rate limits count in
memory per backend process; several processes need a shared store (Redis, backlog PR-17).

## Monitoring endpoints

`/health`, `/ready` and `/metrics` need no login: they hold counts and states, never order
contents, users or secrets (the readiness check reports an error's type, not the database URL).
Set `METRICS_TOKEN` to make Prometheus send a bearer token, or keep the API on a private network;
docker-compose publishes Prometheus (9090) and Grafana (3001) on this machine only, and Grafana
refuses to start without `GRAFANA_ADMIN_PASSWORD`. Unsafe `X-Request-ID` values are replaced, so a
caller cannot inject text into logs or headers.

## Saved state and backups

Warehouse-state snapshots (`STATE_DIR`) are pickles, and unpickling can run code. Each file
therefore carries an HMAC-SHA256 made with a key derived from `JWT_SECRET`, and a file whose HMAC
does not match is never unpickled. Keep `STATE_DIR` and `backups/` readable by the service account
only: they hold the warehouse's orders and stock. Database backups hold user names and password
hashes. `scripts/backup_db.py` passes the database password to the PostgreSQL tools through
`PGPASSWORD` and never prints it.

## Before production

A deployment that is reachable over a network, serves several users or connects to real robots
needs, at minimum:

1. **TLS** (HTTPS / WSS) with `COOKIE_SECURE=true`, and optionally **single sign-on** (OIDC) with
   the company identity provider in front of the built-in accounts.
2. A long random **`JWT_SECRET`** per environment, rotated if it may have leaked (all sessions end).
3. **Human approval and audit trail** for agent actions (Phase 8: the `agent_actions` table), as
   the copilot already does for its commands.
4. **Request size limits and a second layer of rate limiting** at the reverse proxy (the API's own
   limits are per process), with `TRUST_PROXY_HEADERS=true` so the API sees client addresses.
5. **Secrets manager** instead of `.env` files; rotate the database password; least-privilege
   database user for the API.
6. **Model supply chain:** checksums for model files, and a review step before a new model
   version becomes active (`model_versions.is_active`).
7. **Physical safety stays with certified systems:** robot safety scanners and emergency stops;
   AI models (including the camera detector) only advise.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private reporting: **Security** tab of the
repository → **Report a vulnerability**. You will receive an answer within a few working days.
