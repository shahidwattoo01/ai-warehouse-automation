# Users, roles and login

Everyone logs in with their own account. The account's **role** decides which pages they see,
which buttons they get, and, enforced on the server, which requests are allowed. Every change is
recorded under the person who made it. Decision record: [ADR 009](adr/009-jwt-rbac.md).

## 1. Roles

| Role | Who | Start page | In short |
|---|---|---|---|
| **Administrator** | system owner | Users & roles | everything, including user management |
| **Shift supervisor** | shift lead | Dashboard | everything except users; approves count differences and copilot actions |
| **Control-room operator** | control room | Dashboard | runs the simulation, robots, orders, vision, copilot (and its approvals) |
| **Inventory clerk** | receiving, stock control | Inventory | receiving and putaway, moves, adjustments, holds, cycle counts; copilot questions |
| **Viewer** | managers, analysts, trainers | Analytics | reads everything, changes nothing |

## 2. Permissions

| Permission | Admin | Supervisor | Operator | Clerk | Viewer |
|---|:-:|:-:|:-:|:-:|:-:|
| `dashboard:view`, `analytics:view`, `wms:view` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `simulation:control` (start, pause, reset, speed, strategy) | ✓ | ✓ | ✓ | | |
| `robots:command` (pause / resume / reroute, aisles) | ✓ | ✓ | ✓ | | |
| `safety:reset` (release and reset an emergency stop, slow zones) | ✓ | ✓ | ✓ | | |
| `alerts:handle` (acknowledge and resolve alerts) | ✓ | ✓ | ✓ | ✓ | |
| `alerts:configure` (alert rules, thresholds, notifications) | ✓ | ✓ | | | |
| `orders:create`, `orders:assign` | ✓ | ✓ | ✓ | | |
| `orders:manage` (hold, release, cancel, ship partial) | ✓ | ✓ | ✓ | | |
| `vision:use` (run detection) | ✓ | ✓ | ✓ | | |
| `copilot:use` (copilot and knowledge assistant) | ✓ | ✓ | ✓ | ✓ | |
| `copilot:approve` (approve copilot actions) | ✓ | ✓ | ✓ | | |
| `wms:receive`, `wms:move`, `wms:adjust`, `wms:hold`, `wms:count` | ✓ | ✓ | | ✓ | |
| `wms:ship` (pack, weight-check audit, load trucks) | ✓ | ✓ | | ✓ | |
| `wms:count_approve` (sign off count differences) | ✓ | ✓ | | | |
| `wms:settings` (what associates do automatically, release mode) | ✓ | ✓ | | | |
| `users:manage` | ✓ | | | | |

**Emergency stop:** every logged-in user may press it (`dashboard:view`, which all roles have),
like the red buttons on the floor; only `safety:reset` may release and restart (docs/safety.md).

The table lives in `apps/backend/app/core/permissions.py`; the **Users & roles** page shows it,
and a test checks every role against the endpoints (`apps/backend/tests/test_auth.py`). Approving
a copilot action also needs the permission of the action itself (approving "pause robot 3" needs
`robots:command`).

## 3. How login works

```
Sign in ─► POST /auth/login ─► password checked (Argon2id) ─► access token (JWT, 15 min)
                                                              + refresh token (httpOnly cookie, 7 days)
Each request ─► Authorization: Bearer <access token> ─► permission checked ─► 401 / 403 / OK
Live stream  ─► first message {"type": "auth", "token": …}
Token about to expire ─► POST /auth/refresh (cookie) ─► new access token + new refresh token
```

* The access token stays **in the browser's memory** (never localStorage); the refresh cookie
  cannot be read by JavaScript and is only sent to `/api/v1/auth`.
* Each refresh **replaces** the refresh token; using an old one again ends the whole session
  (it was probably copied).
* **5 wrong passwords** lock the account for 15 minutes (an admin can unlock it).
* **Rate limit per address:** at most 10 login attempts per minute from one client address (any
  usernames), then `429 Too Many Requests` with `Retry-After`. The lockout stops guessing one
  account's password; the rate limit stops trying one password on many accounts
  (`app/core/ratelimit.py`, [SECURITY.md](../SECURITY.md)).
* Disabling a user or changing their role **takes effect at once** (the server re-reads the user
  on every request and ends their sessions).
* Every login attempt is recorded (`login_events`), visible under Users & roles.

## 4. Setting up

```bash
cd apps/backend && alembic upgrade head          # tables users, refresh_tokens, login_events
python scripts/create_user.py --username <you> --name "<Your Name>" --role admin   # asks the password
```

`.env` needs `JWT_SECRET` (a long random string:
`python -c "import secrets; print(secrets.token_urlsafe(48))"`). Then log in at
http://localhost:3000 and create the other accounts under **Users & roles**. There is no sign-up:
only administrators create accounts. Passwords: at least 10 characters, letters mixed with digits
or symbols, not containing the username. Everyone can change their own password under **My
account** (click your name in the header).

For development and the browser tests, `python scripts/create_dev_users.py` creates one user per
role (dev-admin, dev-supervisor, dev-operator, dev-clerk, dev-viewer) with random passwords saved
in the git-ignored `dev_users.local.json`.

## 5. API

| Endpoint | Who | What |
|---|---|---|
| `POST /auth/login` | anyone | username + password → access token, refresh cookie |
| `POST /auth/refresh`, `POST /auth/logout` | with the cookie | new tokens / end the session |
| `GET /auth/me`, `PUT /auth/password`, `GET /auth/roles` | logged in | own profile, change password, the role table |
| `GET/POST /users`, `PUT /users/{id}`, `POST /users/{id}/password`, `POST /users/{id}/unlock`, `GET /users/login-events` | `users:manage` | user administration |

`GET /health` stays open for monitoring; everything else needs a login.

## 6. Still to do (backlog)

* HTTPS with `COOKIE_SECURE=true` and rate limiting per address (PR-02).
* Single sign-on with a company identity provider (OIDC), if the site has one.
