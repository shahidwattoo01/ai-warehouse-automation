"""Cross-site protection for the local control API.

CORS alone does not stop another website from *sending* a request: a POST with no body is a
"simple" request, so any page open in the operator's browser could call /simulation/reset or
/robots/R1/pause on localhost. Browsers always attach an Origin header to cross-site requests and
WebSocket handshakes, so state-changing requests and stream connections from an origin that is
not allowed are refused. Requests without an Origin (curl, scripts, tests) are not affected.
"""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def origin_allowed(origin: str | None, allowed: list[str]) -> bool:
    return origin is None or origin in allowed


class OriginCheckMiddleware:
    """Reject state-changing HTTP requests and WebSocket handshakes from other websites."""

    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed = allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            origin = dict(scope["headers"]).get(b"origin")
            origin_str = origin.decode("latin-1") if origin else None
            is_write = scope["type"] == "websocket" or scope.get("method") in UNSAFE_METHODS
            if is_write and not origin_allowed(origin_str, self.allowed):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})  # policy violation
                    return
                response = JSONResponse(
                    {
                        "detail": {
                            "code": "forbidden_origin",
                            "message": f"Requests from {origin_str} are not allowed",
                        }
                    },
                    status_code=403,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
