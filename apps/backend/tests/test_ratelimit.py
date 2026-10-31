"""Rate limits (429 with Retry-After, per client, login stricter than the rest) and the security
headers on every answer."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.ratelimit import (
    RateLimiter,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    client_address,
    default_rules,
)
from app.main import app as real_app

API = "/api/v1"


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_login_is_limited_per_client_and_refills_over_time():
    clock = Clock()
    limiter = RateLimiter(default_rules(API), clock)
    login = f"{API}/auth/login"
    assert all(limiter.check("1.2.3.4", login, "POST") is None for _ in range(10))  # the burst
    rule, wait = limiter.check("1.2.3.4", login, "POST")
    assert rule.name == "login" and 5 < wait <= 6  # 10 per minute: one every 6 s
    assert limiter.check("5.6.7.8", login, "POST") is None  # another client is not affected
    clock.t += 6
    assert limiter.check("1.2.3.4", login, "POST") is None
    assert limiter.check("1.2.3.4", login, "POST") is not None


def test_reads_have_a_much_higher_limit_than_changes():
    limiter = RateLimiter(default_rules(API), Clock())
    reads = sum(limiter.check("c", f"{API}/wms/kpis", "GET") is None for _ in range(250))
    writes = sum(limiter.check("d", f"{API}/robots/R1/pause", "POST") is None for _ in range(250))
    assert reads == 200 and writes == 60  # the bursts of "requests" and "changes"


def test_scale_raises_every_limit():
    limiter = RateLimiter(default_rules(API, scale=3), Clock())
    assert sum(limiter.check("c", f"{API}/auth/login", "POST") is None for _ in range(40)) == 30


def test_client_address_trusts_forwarded_for_only_when_configured():
    scope = {
        "client": ("10.0.0.5", 5000),
        "headers": [(b"x-forwarded-for", b"203.0.113.9, 10.0.0.1")],
    }
    assert client_address(scope, trust_proxy=False) == "10.0.0.5"
    assert client_address(scope, trust_proxy=True) == "203.0.113.9"


@pytest.fixture()
def limited():
    app = FastAPI()

    @app.post(f"{API}/auth/login")
    async def login() -> dict:
        return {"ok": True}

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    app.add_middleware(RateLimitMiddleware, limiter=RateLimiter(default_rules(API), Clock()))
    return TestClient(app)


def test_over_the_limit_answers_429_with_retry_after(limited):
    for _ in range(10):
        assert limited.post(f"{API}/auth/login").status_code == 200
    r = limited.post(f"{API}/auth/login")
    assert r.status_code == 429 and r.json()["detail"]["code"] == "rate_limited"
    assert 1 <= int(r.headers["Retry-After"]) <= 6
    assert all(limited.get("/health").status_code == 200 for _ in range(300))  # never limited


def test_security_headers_on_every_answer():
    client = TestClient(real_app)
    health = client.get("/health")
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in health.headers["content-security-policy"]
    me = client.get(f"{API}/auth/me")
    assert me.headers["cache-control"] == "no-store"  # token and user answers are never cached
    assert "strict-transport-security" not in health.headers  # only when served over HTTPS
    refused = client.get(f"{API}/wms/kpis", headers={"Authorization": "Bearer nope"})
    assert refused.headers["x-content-type-options"] == "nosniff"  # refusals too


def test_hsts_when_served_over_https():
    app = FastAPI()

    @app.get("/x")
    async def x() -> dict:
        return {}

    app.add_middleware(SecurityHeadersMiddleware, api_prefix=API, https=True)
    r = TestClient(app).get("/x")
    assert r.headers["strict-transport-security"].startswith("max-age=31536000")
