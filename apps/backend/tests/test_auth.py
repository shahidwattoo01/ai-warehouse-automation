"""Authentication and role-based access: logging in, tokens, lockout, sessions, and a matrix of
every role against representative endpoints (allowed → not 401/403, refused → 403)."""

import pytest
from fastapi.testclient import TestClient

from app.core import auth
from app.core.permissions import PERMISSIONS, ROLES
from app.main import app

pytestmark = pytest.mark.real_auth
API = "/api/v1"
PASSWORD = "Test#Pass2026"


@pytest.fixture()
def client():
    return TestClient(app)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_every_endpoint_needs_a_login(client):
    assert client.get(f"{API}/simulation/state").status_code == 401
    assert client.get(f"{API}/wms/kpis", headers=bearer("garbage")).status_code == 401
    assert client.get("/health").status_code == 200  # liveness stays open


def test_login_refresh_logout(client, make_user):
    make_user("login-user", "operator")
    bad = client.post(f"{API}/auth/login", json={"username": "login-user", "password": "nope"})
    assert bad.status_code == 401
    ok = client.post(f"{API}/auth/login", json={"username": "LOGIN-USER", "password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "operator"
    me = client.get(f"{API}/auth/me", headers=bearer(ok.json()["access_token"])).json()
    assert me["home"] == "/dashboard" and "robots:command" in me["permissions"]
    again = client.post(f"{API}/auth/refresh")  # the httpOnly cookie is sent by the client
    assert again.status_code == 200 and again.json()["access_token"]
    client.post(f"{API}/auth/logout")
    assert client.post(f"{API}/auth/refresh").status_code == 401


def test_lockout_after_repeated_failures(client, make_user):
    make_user("lock-user", "viewer")
    for _ in range(5):
        client.post(f"{API}/auth/login", json={"username": "lock-user", "password": "wrong"})
    locked = client.post(f"{API}/auth/login", json={"username": "lock-user", "password": PASSWORD})
    assert locked.status_code == 423


def test_disabling_a_user_takes_effect_immediately(client, make_user):
    admin = make_user("matrix-admin", "admin")
    token = make_user("soon-gone", "operator")
    assert client.get(f"{API}/auth/me", headers=bearer(token)).status_code == 200
    uid = next(
        u["user_id"]
        for u in client.get(f"{API}/users", headers=bearer(admin)).json()
        if u["username"] == "soon-gone"
    )
    client.put(f"{API}/users/{uid}", headers=bearer(admin), json={"active": False})
    assert client.get(f"{API}/auth/me", headers=bearer(token)).status_code == 401


# (method, path, body, permission it needs)
ENDPOINTS = [
    ("get", "/simulation/state", None, "dashboard:view"),
    ("post", "/simulation/pause", None, "simulation:control"),
    ("post", "/robots/R1/pause", None, "robots:command"),
    ("post", "/orders", {"priority": "HIGH", "items": []}, "orders:create"),
    ("get", "/analytics/experiments", None, "analytics:view"),
    ("get", "/wms/items?limit=1", None, "wms:view"),
    (
        "post",
        "/wms/adjustments",
        {"sku": "X", "location": "X", "lot": "X", "delta": 1, "reason": "FOUND"},
        "wms:adjust",
    ),
    ("post", "/wms/holds", {"sku": "X", "reason": "test hold"}, "wms:hold"),
    ("post", "/wms/counts/CNT-X/decide", {"approve": True}, "wms:count_approve"),
    ("put", "/wms/settings", {"auto_tasks": {}}, "wms:settings"),
    ("post", "/wms/outbound/orders/NOPE/hold", {"reason": "test hold"}, "orders:manage"),
    ("post", "/wms/outbound/load", {"sscc": "000000000000000000"}, "wms:ship"),
    ("get", "/users", None, "users:manage"),
    ("post", "/copilot/actions/none/approve", None, "copilot:approve"),
]


@pytest.mark.parametrize("role", sorted(ROLES))
def test_role_matrix(client, role, make_user):
    token = make_user(f"matrix-{role}", role)
    for method, path, body, permission in ENDPOINTS:
        r = getattr(client, method)(
            f"{API}{path}", headers=bearer(token), **({"json": body} if body else {})
        )
        allowed = permission in ROLES[role]["permissions"]
        if allowed:
            assert r.status_code not in (401, 403), (role, path, r.status_code, r.text[:200])
        else:
            assert r.status_code == 403, (role, path, r.status_code)


def test_permission_table_is_consistent():
    for role, spec in ROLES.items():
        assert spec["permissions"] <= set(PERMISSIONS), role
    assert ROLES["admin"]["permissions"] == set(PERMISSIONS)
    assert "users:manage" not in ROLES["supervisor"]["permissions"]
    assert ROLES["viewer"]["permissions"] == {"dashboard:view", "analytics:view", "wms:view"}
    with pytest.raises(KeyError):
        auth.require("wms:typo")


def test_copilot_approval_also_needs_the_action_permission(client, make_user):
    """An inventory clerk may ask the copilot but cannot approve pausing a robot."""
    from ai.nlp.intent_parser import RuleParser
    from app.services.copilot import copilot

    original = copilot.parser
    copilot.parser = RuleParser()
    try:
        operator = make_user("cop-operator", "operator")
        reply = client.post(
            f"{API}/copilot/chat", headers=bearer(operator), json={"text": "pause robot 3"}
        ).json()
        clerk = make_user("cop-clerk", "inventory_clerk")
        denied = client.post(
            f"{API}/copilot/actions/{reply['action']['id']}/approve", headers=bearer(clerk)
        )
        assert denied.status_code == 403
        ok = client.post(
            f"{API}/copilot/actions/{reply['action']['id']}/approve", headers=bearer(operator)
        )
        assert ok.json()["ok"]
        last = client.get(f"{API}/copilot/history", headers=bearer(operator)).json()[0]
        assert last["asked_by"] == last["decided_by"] == "cop-operator"
    finally:
        copilot.parser = original


def test_first_administrator_only_while_there_are_no_accounts(client):
    store = auth.get_store()
    saved = dict(store.users)
    store.users.clear()
    try:
        assert client.get(f"{API}/auth/setup").json() == {"needs_setup": True}
        body = {
            "username": "first-admin",
            "full_name": "First Admin",
            "password": "First#Admin2026",
        }
        made = client.post(f"{API}/auth/setup", json=body)
        assert made.status_code == 201 and made.json()["user"]["role"] == "admin"
        assert client.get(f"{API}/auth/setup").json() == {"needs_setup": False}
        again = client.post(f"{API}/auth/setup", json={**body, "username": "second-admin"})
        assert again.status_code == 409  # nobody can make themselves admin later
    finally:
        store.users.clear()
        store.users.update(saved)
