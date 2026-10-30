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
| Authorization | Five roles, 20 permissions, checked on **every** endpoint and the live stream (401 without login, 403 without permission); copilot approvals also need the action's own permission; changes are booked under the logged-in user, never a name sent by the browser | `apps/backend/app/core/permissions.py`, `docs/authentication.md` |
| Accounts | Created only by an administrator (no sign-up); password policy; the last active admin cannot be removed; disabling a user or changing a role ends their sessions at once | `apps/backend/app/api/v1/auth.py` |
| Network exposure | Docker publishes the API (8000), UI (3000) and database (5432) on `127.0.0.1` only; nothing is reachable from other machines | `docker-compose.yml` |
| Cross-site requests | State-changing requests and the live stream are refused unless they come from an allowed origin (a malicious website cannot pause robots or reset a run through the operator's browser) | `apps/backend/app/core/security.py` |
| CORS | Only the configured UI origins; credentials (the refresh cookie) only for those origins | `apps/backend/app/main.py` |
| Secrets | Database password, `JWT_SECRET` and API keys only in `.env` (git-ignored); `.env.example` holds placeholders; development users' passwords only in the git-ignored `dev_users.local.json` | `.gitignore`, `.env.example` |
| Input validation | Typed request models (Pydantic) with limits; camera frames limited to 5 MB and decoded safely, clear 4xx errors | `apps/backend/app/schemas/`, `apps/backend/app/api/v1/vision.py` |
| SQL injection | Parameterised queries only (SQLAlchemy `text()` with bound parameters) | `apps/backend/app/services/run_store.py` |
| Containers | Run as non-root users; runtime images without build tools | `docker/*.Dockerfile` |
| Model loading | Only the project's own model files are loaded; the PyTorch networks load with `weights_only=True` (tensors and plain values only, no code); YOLO weights are loaded by Ultralytics from `models/vision_yolo_v1/` | `ai/deep_learning/`, `ai/computer_vision/live.py` |
| Privacy / telemetry | Ultralytics analytics off (`YOLO_OFFLINE`, `sync=False`), Next.js telemetry off in CI; no personal data in any dataset | `ai/computer_vision/live.py`, CI |
| Dependencies | Exact versions pinned; known-vulnerability scan (`pip-audit`, `npm audit`) on every CI run | `requirements*.txt`, `.github/workflows/ci.yml` |

**Still missing for a networked deployment:** TLS (set `COOKIE_SECURE=true` behind HTTPS),
single sign-on with the company identity provider, and rate limiting per address (backlog PR-02).

## Before production

A deployment that is reachable over a network, serves several users or connects to real robots
needs, at minimum:

1. **TLS** (HTTPS / WSS) with `COOKIE_SECURE=true`, and optionally **single sign-on** (OIDC) with
   the company identity provider in front of the built-in accounts.
2. A long random **`JWT_SECRET`** per environment, rotated if it may have leaked (all sessions end).
3. **Human approval and audit trail** for agent actions (Phase 8: the `agent_actions` table), as
   the copilot already does for its commands.
4. **Rate limiting** and request size limits at the reverse proxy.
5. **Secrets manager** instead of `.env` files; rotate the database password; least-privilege
   database user for the API.
6. **Model supply chain:** checksums for model files, and a review step before a new model
   version becomes active (`model_versions.is_active`).
7. **Physical safety stays with certified systems:** robot safety scanners and emergency stops;
   AI models (including the camera detector) only advise.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private reporting: **Security** tab of the
repository → **Report a vulnerability**. You will receive an answer within a few working days.
