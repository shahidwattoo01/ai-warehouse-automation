"""Monitoring plumbing (backlog PR-16): request ids, structured logs and HTTP metrics.

* Every HTTP request gets a request id: the caller's `X-Request-ID` when it is a short, safe
  token (so one id follows a call through a proxy), else a new one. It is returned in the
  response header and added to every log line written while the request runs.
* `LOG_FORMAT=json` writes one JSON object per log line (time, level, logger, message,
  request_id, exception) for a log collector (Loki, ELK, CloudWatch); `text` stays readable.
* HTTP requests are counted by method, route template (`/api/v1/wms/orders/{order_id}`, never
  the raw path, so ids cannot blow up the number of series) and status, with a latency
  histogram. `render()` writes the Prometheus text format (version 0.0.4) by hand: a few
  counters and gauges need no client library.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import threading
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
# Long-lived responses: their duration is the client's choice, not a latency.
STREAMS = ("/api/v1/events/stream", "/api/v1/stream")

log = logging.getLogger("app.access")


# ----- Prometheus text format ------------------------------------------------------------------
def _escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(labels: dict | None) -> str:
    if not labels:
        return ""
    return "{" + ",".join(f'{k}="{_escape(v)}"' for k, v in labels.items()) + "}"


def _number(value: float) -> str:
    if value == float("inf"):
        return "+Inf"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return repr(float(value))


class Family:
    """One metric name: its type, help text and samples (labels -> value)."""

    def __init__(self, name: str, kind: str, help_text: str) -> None:
        self.name, self.kind, self.help = name, kind, help_text
        self.samples: list[tuple[str, dict | None, float]] = []

    def add(self, value: float | None, suffix: str = "", **labels) -> Family:
        if value is not None:
            self.samples.append((suffix, labels or None, value))
        return self

    def lines(self) -> list[str]:
        out = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} {self.kind}"]
        out += [f"{self.name}{s}{_labels(lb)} {_number(v)}" for s, lb, v in self.samples]
        return out


def render(families: list[Family]) -> str:
    return "\n".join(line for f in families for line in f.lines()) + "\n"


# ----- HTTP metrics ----------------------------------------------------------------------------
class HttpMetrics:
    """Request counts and latencies, safe to update from any thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests: dict[tuple[str, str, str], int] = {}
        # (method, route) -> [bucket counts..., sum, count]
        self.latency: dict[tuple[str, str], list[float]] = {}
        self.in_flight = 0
        self.started = time.time()

    def observe(self, method: str, route: str, status: int, seconds: float | None) -> None:
        with self._lock:
            key = (method, route, str(status))
            self.requests[key] = self.requests.get(key, 0) + 1
            if seconds is None:
                return
            row = self.latency.setdefault((method, route), [0.0] * (len(LATENCY_BUCKETS) + 2))
            for i, bound in enumerate(LATENCY_BUCKETS):
                if seconds <= bound:
                    row[i] += 1
            row[-2] += seconds
            row[-1] += 1

    def families(self) -> list[Family]:
        with self._lock:
            requests = dict(self.requests)
            latency = {k: list(v) for k, v in self.latency.items()}
            in_flight = self.in_flight
        total = Family("warehouse_http_requests_total", "counter", "HTTP requests answered")
        for (method, route, status), n in sorted(requests.items()):
            total.add(n, method=method, route=route, status=status)
        hist = Family(
            "warehouse_http_request_duration_seconds", "histogram", "HTTP request latency"
        )
        for (method, route), row in sorted(latency.items()):
            for bound, n in zip(LATENCY_BUCKETS, row, strict=False):
                hist.add(n, "_bucket", method=method, route=route, le=_number(bound))
            hist.add(row[-1], "_bucket", method=method, route=route, le="+Inf")
            hist.add(row[-2], "_sum", method=method, route=route)
            hist.add(row[-1], "_count", method=method, route=route)
        flight = Family("warehouse_http_requests_in_flight", "gauge", "Requests being answered")
        return [total, hist, flight.add(in_flight)]


http_metrics = HttpMetrics()


def route_of(scope: Scope) -> str:
    """The matched route's full template; one label value for every unmatched path.

    FastAPI keeps an included router's routes relative to its prefix (`/robots/{robot_id}`), so
    the prefix is taken from the request path: all but the template's own segments (prefixes are
    fixed text, never ids)."""
    template = getattr(scope.get("route"), "path", None)
    if template is None:
        return "unmatched"
    depth = template.rstrip("/").count("/")
    parts = scope["path"].rstrip("/").split("/")
    prefix = "/".join(parts[: len(parts) - depth]) if depth else "/".join(parts)
    return prefix + template


class RequestMiddleware:
    """Request id, access log and HTTP metrics for every request (outermost middleware)."""

    def __init__(self, app: ASGIApp, metrics: HttpMetrics = http_metrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        given = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        rid = given if SAFE_ID.match(given) else uuid.uuid4().hex
        token = request_id.set(rid)
        start = time.perf_counter()
        status = 500
        streaming = scope["path"] in STREAMS

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [*message.get("headers", []), (b"x-request-id", rid.encode())]
            await send(message)

        with self.metrics._lock:
            self.metrics.in_flight += 1
        try:
            await self.app(scope, receive, send_with_id)
        finally:
            seconds = time.perf_counter() - start
            with self.metrics._lock:
                self.metrics.in_flight -= 1
            route = route_of(scope)
            self.metrics.observe(scope["method"], route, status, None if streaming else seconds)
            if status >= 500 or (seconds > 2.0 and not streaming):
                log.warning(
                    "%s %s -> %d in %.0f ms", scope["method"], scope["path"], status, seconds * 1e3
                )
            request_id.reset(token)


# ----- structured logs -------------------------------------------------------------------------
class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line; extra fields passed with `extra={...}` are kept."""

    STANDARD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "request_id"}

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if getattr(record, "request_id", "-") != "-":
            data["request_id"] = record.request_id
        data.update({k: v for k, v in vars(record).items() if k not in self.STANDARD})
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


def setup_logging(fmt: str = "text", level: str = "INFO") -> None:
    """Configure the root logger once (uvicorn's own loggers propagate to it)."""
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s [%(request_id)s] %(message)s")
        )
    root = logging.getLogger()
    for old in [h for h in root.handlers if getattr(h, "_warehouse", False)]:
        root.removeHandler(old)
    handler._warehouse = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()  # one format for everything: through the root handler
        lg.propagate = True
    # The access log is our own (slow and failing requests); uvicorn's would log every poll.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
