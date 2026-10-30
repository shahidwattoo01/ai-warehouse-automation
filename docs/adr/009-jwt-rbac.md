# ADR 009 — Built-in accounts with JWT access tokens, rotating refresh cookies and RBAC

**Status:** Accepted · 2026-10-30

## Context

Anyone who could open the UI could operate everything, and actions were recorded under a name
typed into the page (backlog PR-01). Real warehouse systems need personal accounts, roles,
permissions checked on the server, and an audit of who did what. The project runs locally and in
Docker, without a company identity provider.

## Decision

1. **Built-in accounts** in PostgreSQL (`users`), created only by administrators; passwords hashed
   with **Argon2id**; a password policy; lockout after 5 failures; a login audit.
2. **Access token = JWT (HS256), 15 minutes**, signed with `JWT_SECRET`, sent as a Bearer header
   and kept in browser memory only.
3. **Refresh token = random 64 bytes in an httpOnly, SameSite=Strict cookie**, valid 7 days,
   stored only as a SHA-256 hash, **rotated on every use**; reuse of a replaced token revokes its
   whole family (theft detection).
4. **RBAC in code:** 18 permissions (21 since: `orders:manage` and `wms:ship` for outbound, `safety:reset`), 5 roles (`app/core/permissions.py`). Every endpoint declares
   its permission; the user is re-read on each request, so disabling or demoting acts at once.
5. **The user is taken from the token**, never from the request body, for every recorded action
   (inventory ledger, copilot approvals, count approvals).
6. **The live WebSocket authenticates with its first message** (not a URL parameter, which would
   be logged).
7. The **frontend** hides what a role cannot use (menu, buttons, start page) for convenience only.

## Consequences

* Stolen access tokens are useful for at most 15 minutes; refresh tokens cannot be read by
  scripts, and a copied one stops working after its first reuse.
* A per-request user lookup costs one small database query; acceptable at this scale.
* Tests run without a database (memory user store) and log in as a test administrator unless
  they test authentication itself.
* Without HTTPS the tokens travel in clear text: fine on one machine, not on a network (PR-02).
* Single sign-on (OIDC) can be added later in front of the same roles.
