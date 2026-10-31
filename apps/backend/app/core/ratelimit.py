"""Rate limiting and security headers (backlog PR-02).

Rate limits are token buckets per client address, checked before a request reaches its endpoint:

    login, first-time setup   10 per minute    password guessing across many accounts (the
                                               per-account lockout only protects one account)
    token refresh             30 per minute
    changes (POST/PUT)       120 per minute    a script or a stuck page flooding the controls
    every API request        600 per minute    (10 per second: polling pages stay far below)

Over the limit the answer is 429 with Retry-After. /health and the live WebSocket are never
limited. Behind a reverse proxy set TRUST_PROXY_HEADERS=true, so the client address is taken from
X-Forwarded-For (only then: anyone can send that header).

The buckets live in memory, so with several backend processes each counts on its own; a shared
store (Redis) is the next step for a multi-server deployment (backlog PR-17).
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Rule:
    name: str
    per_minute: int
    burst: int  # requests allowed at once before the rate applies

    def matches(self, path: str, method: str) -> bool:
        raise NotImplementedError


@dataclass(frozen=True)
class PathRule(Rule):
    paths: tuple[str, ...] = ()

    def matches(self, path: str, method: str) -> bool:
        return method == "POST" and path in self.paths


@dataclass(frozen=True)
class MethodRule(Rule):
    methods: tuple[str, ...] = ()

    def matches(self, path: str, method: str) -> bool:
        return method in self.methods


def default_rules(api: str, scale: float = 1.0) -> list[Rule]:
    def n(x: int) -> int:
        return max(1, round(x * scale))

    return [
        PathRule("login", n(10), n(10), (f"{api}/auth/login", f"{api}/auth/setup")),
        PathRule("refresh", n(30), n(15), (f"{api}/auth/refresh",)),
        MethodRule("changes", n(120), n(60), ("POST", "PUT", "PATCH", "DELETE")),
        MethodRule("requests", n(600), n(200), ("GET", "POST", "PUT", "PATCH", "DELETE")),
    ]


class RateLimiter:
    """Token buckets per (rule, client). Not thread-safe: used from the event loop only."""

    def __init__(self, rules: list[Rule], clock=time.monotonic) -> None:
        self.rules = rules
        self.clock = clock
        self.buckets: dict[tuple[str, str], tuple[float, float]] = {}  # tokens, last time
        self.refused = 0

    def check(self, client: str, path: str, method: str) -> tuple[Rule, float] | None:
        """None if allowed, else (the rule hit, seconds until the next request is allowed).
        Every matching rule spends a token, so the general limits count login attempts too."""
        now = self.clock()
        hit: tuple[Rule, float] | None = None
        for rule in self.rules:
            if not rule.matches(path, method):
                continue
            rate = rule.per_minute / 60.0
            tokens, last = self.buckets.get((rule.name, client), (float(rule.burst), now))
            tokens = min(float(rule.burst), tokens + (now - last) * rate)
            if tokens < 1.0:
                wait = (1.0 - tokens) / rate
                if hit is None or wait > hit[1]:
                    hit = (rule, wait)
                self.buckets[(rule.name, client)] = (tokens, now)
            else:
                self.buckets[(rule.name, client)] = (tokens - 1.0, now)
        if hit:
            self.refused += 1
        if len(self.buckets) > 50_000:  # forget idle clients (memory bound)
            self.buckets = {k: v for k, v in self.buckets.items() if now - v[1] < 600}
        return hit


def client_address(scope: Scope, trust_proxy: bool) -> str:
    if trust_proxy:
        forwarded = dict(scope["headers"]).get(b"x-forwarded-for")
        if forwarded:
            return forwarded.decode("latin-1").split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


class RateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        limiter: RateLimiter,
        enabled: bool = True,
        trust_proxy: bool = False,
        exempt: tuple[str, ...] = ("/health",),
    ) -> None:
        self.app = app
        self.limiter = limiter
        self.enabled = enabled
        self.trust_proxy = trust_proxy
        self.exempt = exempt

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.enabled or scope["type"] != "http" or scope["path"] in self.exempt:
            await self.app(scope, receive, send)
            return
        client = client_address(scope, self.trust_proxy)
        hit = self.limiter.check(client, scope["path"], scope["method"])
        if hit is None:
            await self.app(scope, receive, send)
            return
        rule, wait = hit
        retry = max(1, math.ceil(wait))
        log.warning("Rate limit '%s' hit by %s on %s", rule.name, client, scope["path"])
        response = JSONResponse(
            {
                "detail": {
                    "code": "rate_limited",
                    "message": f"Too many requests; try again in {retry} s",
                }
            },
            status_code=429,
            headers={"Retry-After": str(retry)},
        )
        await response(scope, receive, send)


# ----- security headers ------------------------------------------------------------------------
API_HEADERS = {
    b"x-content-type-options": b"nosniff",  # never guess a content type (no script from JSON)
    b"x-frame-options": b"DENY",  # API answers are never shown inside a frame
    b"referrer-policy": b"no-referrer",
    b"cross-origin-opener-policy": b"same-origin",
    b"permissions-policy": b"camera=(), microphone=(), geolocation=()",
}
# JSON and PDFs need nothing else; the interactive docs (/docs) load Swagger UI from a CDN.
API_CSP = b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'"


class SecurityHeadersMiddleware:
    """Adds the security headers to every HTTP response. Token responses (/auth) are never cached.
    HSTS is sent only when the site is served over HTTPS (COOKIE_SECURE=true)."""

    def __init__(self, app: ASGIApp, api_prefix: str, https: bool = False) -> None:
        self.app = app
        self.auth_prefix = f"{api_prefix}/auth"
        self.api_prefix = api_prefix
        self.https = https

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                extra = dict(API_HEADERS)
                if path.startswith(self.api_prefix) or path == "/health":
                    extra[b"content-security-policy"] = API_CSP
                if path.startswith(self.auth_prefix):
                    extra[b"cache-control"] = b"no-store"
                    extra[b"pragma"] = b"no-cache"
                if self.https:
                    extra[b"strict-transport-security"] = b"max-age=31536000; includeSubDomains"
                headers += [(k, v) for k, v in extra.items() if k not in present]
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
