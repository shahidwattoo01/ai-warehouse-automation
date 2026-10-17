# Security

## Deployment model

The platform is a **local, single-operator digital twin**: the simulator, API, database and UI
run on one machine for one operator (development, training and demonstrations). It does not
control physical robots. The protections below fit that model; the
[production section](#before-production) lists what a real site needs on top.

## What is protected today

| Area | Protection | Where |
|---|---|---|
| Network exposure | Docker publishes the API (8000), UI (3000) and database (5432) on `127.0.0.1` only; nothing is reachable from other machines | `docker-compose.yml` |
| Cross-site requests | State-changing requests and the live stream are refused unless they come from an allowed origin (a malicious website cannot pause robots or reset a run through the operator's browser) | `apps/backend/app/core/security.py` |
| CORS | Only the configured UI origins; no cookies or credentials | `apps/backend/app/main.py` |
| Secrets | Database password and API keys only in `.env` (git-ignored); `.env.example` holds placeholders | `.gitignore`, `.env.example` |
| Input validation | Typed request models (Pydantic) with limits; camera frames limited to 5 MB and decoded safely, clear 4xx errors | `apps/backend/app/schemas/`, `apps/backend/app/api/v1/vision.py` |
| SQL injection | Parameterised queries only (SQLAlchemy `text()` with bound parameters) | `apps/backend/app/services/run_store.py` |
| Containers | Run as non-root users; runtime images without build tools | `docker/*.Dockerfile` |
| Model loading | Only the project's own model files are loaded; the PyTorch networks load with `weights_only=True` (tensors and plain values only, no code); YOLO weights are loaded by Ultralytics from `models/vision_yolo_v1/` | `ai/deep_learning/`, `ai/computer_vision/live.py` |
| Privacy / telemetry | Ultralytics analytics off (`YOLO_OFFLINE`, `sync=False`), Next.js telemetry off in CI; no personal data in any dataset | `ai/computer_vision/live.py`, CI |
| Dependencies | Exact versions pinned; known-vulnerability scan (`pip-audit`, `npm audit`) on every CI run | `requirements*.txt`, `.github/workflows/ci.yml` |

**Deliberately out of scope for the local model:** user accounts and authentication. Anyone who
can open the UI on the machine can operate the simulation, which is the intended behaviour of a
single-operator twin.

## Before production

A deployment that is reachable over a network, serves several users or connects to real robots
needs, at minimum:

1. **Authentication** (single sign-on via OIDC, e.g. through the company identity provider or a
   reverse proxy) and **TLS** (HTTPS / WSS).
2. **Roles:** *viewer* (read-only dashboards) vs *operator* (pause robots, change strategy, reset)
   vs *admin*; checked on every state-changing endpoint and the live stream.
3. **Human approval and audit trail** for actions that move robots (planned with Phase 6 commands
   and Phase 8 agents: `requires_approval` and the `agent_actions` table).
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
