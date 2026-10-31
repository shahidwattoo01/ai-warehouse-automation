"""Load and soak tests for the backend (backlog PR-18; docs/load_testing.md).

    python -m tests.load.loadtest --spawn                     # 60 s: 25 API users, 25 streams
    python -m tests.load.loadtest --spawn --users 50 --streams 100 --duration 120
    python -m tests.load.loadtest --spawn --soak 30           # 30-minute soak (memory, lag)
    python -m tests.load.loadtest --url http://host:8000      # an already running backend

What runs at the same time, for --duration seconds (or --soak minutes):

* API users: each one behaves like an open screen: a request picked from a weighted mix of the
  reads the pages poll (KPIs, alerts, robots, orders, outbound, events ...) and, less often,
  the large ones (full warehouse state, inventory, locations), then 0.3-1.5 s of think time.
* Stream clients: browsers on the live WebSocket stream (auth message, layout, a frame per tick).
  The time between tick frames shows whether the server keeps up with every client.
* A sampler reads /metrics every 5 s: simulator loop lag, ticks done, backend memory and CPU.

The results are judged against configs/load_targets.yaml and written to reports/load/ as JSON
and Markdown; the exit code is 1 when a target is missed.

--spawn starts a separate backend on port 8010 (rate limiting off, so the test measures the
platform and not the limiter; nothing saved to the state directory; runs not recorded unless
--persist), logs in as the development admin and stops it afterwards. Against --url, pass an
access token in LOAD_TOKEN; requests refused by the rate limiter (429) are counted apart.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import random
import re
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import psutil
import websockets
import yaml

ROOT = Path(__file__).resolve().parents[2]
TARGETS = ROOT / "configs" / "load_targets.yaml"
OUT = ROOT / "reports" / "load"

# (path, weight, group): what open screens ask for, roughly how often.
MIX = [
    ("/api/v1/wms/kpis", 10, "light"),
    ("/api/v1/alerts?status=active", 6, "light"),
    ("/api/v1/safety/status", 6, "light"),
    ("/api/v1/robots", 5, "light"),
    ("/api/v1/prediction/live", 4, "light"),
    ("/api/v1/orders", 3, "light"),
    ("/api/v1/wms/outbound/orders", 3, "light"),
    ("/api/v1/events?after=0&limit=50", 3, "light"),
    ("/api/v1/wms/rf/summary", 2, "light"),
    ("/api/v1/erp/status", 2, "light"),
    ("/api/v1/vda5050/status", 2, "light"),
    ("/api/v1/auth/me", 2, "light"),
    ("/api/v1/simulation/state", 3, "heavy"),
    ("/api/v1/inventory", 1, "heavy"),
    ("/api/v1/wms/locations", 1, "heavy"),
    ("/api/v1/wms/tasks", 1, "heavy"),
]


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q / 100 * (len(s) - 1))))]


@dataclass
class Results:
    requests: list[tuple[str, str, int, float]] = field(default_factory=list)  # path group code ms
    connects: list[float] = field(default_factory=list)
    gaps: list[float] = field(default_factory=list)
    frames: int = 0
    dropped: int = 0
    stream_errors: list[str] = field(default_factory=list)
    samples: list[dict] = field(default_factory=list)
    client_cpu: float | None = None
    client_errors: dict[str, int] = field(default_factory=dict)
    refused: dict[str, list] = field(default_factory=dict)  # 4xx code -> [count, first s, last s]
    started: float = field(default_factory=time.monotonic)


# ----- workers ---------------------------------------------------------------------------------
async def api_user(client: httpx.AsyncClient, auth: dict, until: float, res: Results, rng):
    paths, weights = [m[0] for m in MIX], [m[1] for m in MIX]
    group = {m[0]: m[2] for m in MIX}
    await asyncio.sleep(rng.uniform(0, 1.5))  # users do not all arrive in the same millisecond
    while time.monotonic() < until:
        path = rng.choices(paths, weights)[0]
        began = time.perf_counter()
        try:
            r = await client.get(path, headers={"Authorization": f"Bearer {auth['token']}"})
            code = r.status_code
            await r.aread()
        except httpx.HTTPError as err:
            code = 0  # no answer (timeout, connection refused)
            res.client_errors[type(err).__name__] = res.client_errors.get(type(err).__name__, 0) + 1
        res.requests.append((path, group[path], code, (time.perf_counter() - began) * 1000))
        if 400 <= code < 500:
            at = round(time.monotonic() - res.started)
            row = res.refused.setdefault(str(code), [0, at, at])
            row[0], row[2] = row[0] + 1, at
        await asyncio.sleep(rng.uniform(0.3, 1.5))


async def stream_client(ws_url: str, auth: dict, until: float, res: Results, rng):
    await asyncio.sleep(rng.uniform(0, 2.0))
    began = time.perf_counter()
    try:
        async with websockets.connect(ws_url, max_size=None, open_timeout=10) as ws:
            await ws.send(json.dumps({"type": "auth", "token": auth["token"]}))
            last = None
            while time.monotonic() < until:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=10)
                except TimeoutError:
                    res.gaps.append(10_000.0)  # ten seconds without a frame
                    continue
                kind = raw[:40]
                now = time.perf_counter()
                if '"layout"' in kind:  # the first frame: connected and authenticated
                    res.connects.append((now - began) * 1000)
                elif '"tick"' in kind:
                    if last is not None:
                        res.gaps.append((now - last) * 1000)
                    last = now
                    res.frames += 1
    except websockets.ConnectionClosed as err:
        if time.monotonic() < until:
            res.dropped += 1
            res.stream_errors.append(f"closed {err.rcvd.code if err.rcvd else '?'}")
    except Exception as err:
        res.dropped += 1
        res.stream_errors.append(type(err).__name__)


METRIC = re.compile(r"^([a-z_]+)(\{[^}]*\})? (\S+)$")


def parse_metrics(text: str) -> dict[str, float]:
    out = {}
    for line in text.splitlines():
        m = METRIC.match(line)
        if m and not m.group(2):
            out[m.group(1)] = float(m.group(3))
    return out


async def sampler(client: httpx.AsyncClient, until: float, res: Results, every: float = 5.0):
    t0 = time.monotonic()
    while True:
        try:
            r = await client.get("/metrics")
            m = parse_metrics(r.text)
            res.samples.append({
                "t": round(time.monotonic() - t0, 1),
                "lag": m.get("warehouse_sim_loop_lag_seconds"),
                "ticks": m.get("warehouse_sim_ticks_total"),
                "rss_mb": round(m.get("process_resident_memory_bytes", 0) / 1e6, 1) or None,
                "cpu_s": m.get("process_cpu_seconds_total"),
                "in_flight": m.get("warehouse_http_requests_in_flight"),
            })  # fmt: skip
        except httpx.HTTPError:
            res.samples.append({"t": round(time.monotonic() - t0, 1), "error": True})
        if time.monotonic() >= until:
            return
        await asyncio.sleep(min(every, max(0.0, until - time.monotonic())))


async def renew_token(auth: dict, until: float, every: float | None = None) -> None:
    """Access tokens live 15 minutes: log in again every 10 so a soak never runs on an expired
    one (streams authenticate once, when they connect)."""
    every = every or float(os.environ.get("LOAD_RENEW_SECONDS", 600))
    while auth.get("renew") and time.monotonic() + every < until:
        await asyncio.sleep(every)
        auth["token"] = await asyncio.to_thread(auth["renew"])


# ----- the run ---------------------------------------------------------------------------------
def call(base: str, path: str, method: str, token: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        base + path, method=method, data=json.dumps(body or {}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )  # fmt: skip
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (the URL under test)
        return json.loads(r.read() or b"{}")


async def run(base: str, auth: dict, users: int, streams: int, seconds: float, speed: float):
    """`auth`: {"token": access token, "renew": a function returning a fresh one, or None}."""
    state = call(base, "/api/v1/simulation/state", "GET", auth["token"])
    was_running = state["running"]
    call(base, "/api/v1/simulation/speed", "PUT", auth["token"], {"multiplier": speed})
    call(base, "/api/v1/simulation/start", "POST", auth["token"])
    res = Results()
    me = psutil.Process()
    cpu0, wall0 = sum(me.cpu_times()[:2]), time.monotonic()
    rng = random.Random(7)
    ws_url = base.replace("http", "ws", 1) + "/api/v1/simulation/stream"
    limits = httpx.Limits(max_connections=users + 10, max_keepalive_connections=users + 10)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=30, limits=limits) as client:
            until = time.monotonic() + seconds
            await asyncio.gather(
                sampler(client, until, res),
                renew_token(auth, until),
                *(api_user(client, auth, until, res, random.Random(rng.random()))
                  for _ in range(users)),
                *(stream_client(ws_url, auth, until, res, random.Random(rng.random()))
                  for _ in range(streams)),
            )  # fmt: skip
        # The generator's own CPU: near 100 % of a core means the client, not the server, is the
        # limit and the run says little about the platform.
        res.client_cpu = round(100 * (sum(me.cpu_times()[:2]) - cpu0) / (time.monotonic() - wall0))
    finally:
        try:  # put the simulation back; never lose the measurements over it
            if auth.get("renew"):
                auth["token"] = auth["renew"]()
            if not was_running:
                call(base, "/api/v1/simulation/pause", "POST", auth["token"])
            call(base, "/api/v1/simulation/speed", "PUT", auth["token"],
                 {"multiplier": state.get("speed", 1)})  # fmt: skip
        except Exception as err:
            print(f"could not restore the simulation state: {err}")
    return res


# ----- judging ---------------------------------------------------------------------------------
def summarise(res: Results, cfg: dict, args, seconds: float, tick_hz: float) -> dict:
    t = cfg
    checks: list[dict] = []

    def check(name: str, value, target, ok: bool | None) -> None:
        checks.append({"check": name, "value": value, "target": target,
                       "result": "n/a" if ok is None else ("pass" if ok else "FAIL")})  # fmt: skip

    reqs = res.requests
    answered = [r for r in reqs if r[2] != 429]
    errors = [r for r in answered if r[2] == 0 or r[2] >= 500]
    other = [r for r in answered if 400 <= r[2] < 500]
    groups = {}
    for g, target in t["api"]["groups"].items():
        ms = [r[3] for r in answered if r[1] == g and 0 < r[2] < 400]
        groups[g] = {"requests": len(ms), "p50_ms": pct(ms, 50), "p95_ms": pct(ms, 95),
                     "p99_ms": pct(ms, 99), "max_ms": max(ms) if ms else None}  # fmt: skip
        for q in ("p95_ms", "p99_ms"):
            v = groups[g][q]
            check(f"API {g} {q[:3]}", None if v is None else round(v), f"<= {target[q]} ms",
                  None if v is None else v <= target[q])  # fmt: skip
    rate = len(errors) / len(answered) if answered else 0.0
    check("API error rate", f"{rate:.2%}", f"<= {t['api']['error_rate_max']:.0%}",
          rate <= t["api"]["error_rate_max"])  # fmt: skip
    per_path = {}
    for path, *_ in MIX:
        ms = [r[3] for r in answered if r[0] == path and 0 < r[2] < 400]
        per_path[path] = {"n": len(ms), "p50_ms": pct(ms, 50), "p95_ms": pct(ms, 95)}

    s = t["stream"]
    stream = {"clients": args.streams, "frames": res.frames, "dropped": res.dropped,
              "connect_p95_ms": pct(res.connects, 95), "gap_p50_ms": pct(res.gaps, 50),
              "gap_p95_ms": pct(res.gaps, 95), "gap_max_ms": max(res.gaps) if res.gaps else None,
              "errors": res.stream_errors[:10]}  # fmt: skip
    if args.streams:
        v = stream["connect_p95_ms"]
        ok = v is not None and v <= s["connect_p95_ms"]
        check("Stream connect p95", None if v is None else round(v),
              f"<= {s['connect_p95_ms']} ms", ok)  # fmt: skip
        # tick frames come every 1/(hz*speed) s: the target scales with the chosen speed
        nominal = 1000 / (tick_hz * args.speed)
        limit = s["frame_gap_p95_ms"] * nominal / 500
        v = stream["gap_p95_ms"]
        check("Stream frame gap p95", None if v is None else round(v), f"<= {limit:.0f} ms",
              v is not None and v <= limit)  # fmt: skip
        check("Stream clients dropped", res.dropped, f"<= {s['dropped_clients_max']}",
              res.dropped <= s["dropped_clients_max"])  # fmt: skip

    good = [x for x in res.samples if not x.get("error") and x.get("lag") is not None]
    lags = [x["lag"] for x in good]
    sim = {"loop_lag_p95_s": pct(lags, 95), "loop_lag_max_s": max(lags) if lags else None}
    v = sim["loop_lag_p95_s"]
    check("Loop lag p95", v, f"<= {t['simulator']['loop_lag_p95_s']} s",
          v is not None and v <= t["simulator"]["loop_lag_p95_s"])  # fmt: skip
    if len(good) >= 2 and good[-1]["ticks"] is not None:
        span = good[-1]["t"] - good[0]["t"]
        done = good[-1]["ticks"] - good[0]["ticks"]
        share = done / (span * tick_hz * args.speed) if span else None
        sim["tick_rate_share"] = None if share is None else round(share, 3)
        check("Ticks done / scheduled", sim["tick_rate_share"],
              f">= {t['simulator']['tick_rate_min_share']}",
              share is not None and share >= t["simulator"]["tick_rate_min_share"])  # fmt: skip
    rss = [(x["t"], x["rss_mb"]) for x in good if x.get("rss_mb")]
    memory = {"start_mb": rss[0][1] if rss else None, "end_mb": rss[-1][1] if rss else None,
              "max_mb": max(r for _, r in rss) if rss else None}  # fmt: skip
    if len(rss) >= 3:
        xs, ys = [x for x, _ in rss], [y for _, y in rss]
        slope = statistics.linear_regression(xs, ys).slope * 3600  # MB per hour
        memory["trend_mb_per_hour"] = round(slope, 1)
        judged = seconds / 60 >= t["soak"]["min_minutes_for_trend"]
        check("Memory trend", f"{slope:+.1f} MB/h",
              f"<= {t['soak']['rss_growth_max_mb_per_hour']} MB/h",
              (slope <= t["soak"]["rss_growth_max_mb_per_hour"]) if judged else None)  # fmt: skip
    cpu = [(x["t"], x["cpu_s"]) for x in good if x.get("cpu_s") is not None]
    if len(cpu) >= 2 and cpu[-1][0] > cpu[0][0]:
        memory["cpu_percent_of_one_core"] = round(
            100 * (cpu[-1][1] - cpu[0][1]) / (cpu[-1][0] - cpu[0][0]), 1
        )
    return {
        "when": dt.datetime.now().isoformat(timespec="seconds"),
        "setup": {
            "users": args.users,
            "streams": args.streams,
            "seconds": seconds,
            "speed": args.speed,
            "target": "spawned" if args.spawn else args.url,
            "persist_runs": bool(args.persist),
        },  # fmt: skip
        "api": {
            "requests": len(reqs),
            "per_second": round(len(reqs) / seconds, 1),
            "errors": len(errors),
            "no_answer": res.client_errors,
            "client_errors_4xx": len(other),
            "refused": res.refused,
            "rate_limited_429": len(reqs) - len(answered),
            "groups": groups,
            "per_path": per_path,
        },  # fmt: skip
        "stream": stream,
        "simulator": sim,
        "process": memory,
        "load_generator_cpu_percent": res.client_cpu,
        "checks": checks,
        "passed": all(c["result"] != "FAIL" for c in checks),
        "samples": res.samples,
    }


def markdown(r: dict) -> str:
    s = r["setup"]
    lines = [
        f"# Load test {r['when']}",
        "",
        f"{s['users']} API users, {s['streams']} stream clients, {s['seconds']:.0f} s, simulation "
        f"speed {s['speed']}x, target {s['target']}, runs recorded: {s['persist_runs']}.",
        "",
        f"**{'PASSED' if r['passed'] else 'FAILED'}**",
        "",
        "| Check | Value | Target | Result |",
        "|---|---|---|---|",
    ]
    for c in r["checks"]:
        lines.append(f"| {c['check']} | {c['value']} | {c['target']} | {c['result']} |")
    a = r["api"]
    lines += ["", f"API: {a['requests']} requests ({a['per_second']}/s), {a['errors']} errors, "
              f"{a['client_errors_4xx']} 4xx, {a['rate_limited_429']} rate-limited.", "",
              "| Endpoint | n | p50 ms | p95 ms |", "|---|---|---|---|"]  # fmt: skip
    for path, v in sorted(a["per_path"].items(), key=lambda kv: -(kv[1]["p95_ms"] or 0)):
        p50 = "" if v["p50_ms"] is None else f"{v['p50_ms']:.0f}"
        p95 = "" if v["p95_ms"] is None else f"{v['p95_ms']:.0f}"
        lines.append(f"| `{path}` | {v['n']} | {p50} | {p95} |")
    st, p = r["stream"], r["process"]
    lines += ["", f"Stream: {st['frames']} tick frames, gap p50 {st['gap_p50_ms']} ms, "
              f"max {st['gap_max_ms']} ms, {st['dropped']} dropped.",
              f"Process: memory {p.get('start_mb')} -> {p.get('end_mb')} MB "
              f"(max {p.get('max_mb')}, trend {p.get('trend_mb_per_hour')} MB/h), "
              f"CPU {p.get('cpu_percent_of_one_core')} % of one core.",
              f"Load generator CPU: {r['load_generator_cpu_percent']} % of one core "
              "(near 100 %: the client is the limit, not the server)."]  # fmt: skip
    return "\n".join(lines) + "\n"


# ----- the backend under test ------------------------------------------------------------------
def spawn(port: int, persist: bool):
    env = {**os.environ, "RATE_LIMIT_ENABLED": "false", "STATE_DIR": tempfile.mkdtemp(),
           "SNAPSHOT_SECONDS": "30", "PERSIST_RUNS": "true" if persist else "false",
           "LOG_LEVEL": "WARNING"}  # fmt: skip
    log = open(Path(tempfile.gettempdir()) / f"loadtest_backend_{port}.log", "w")  # noqa: SIM115
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=ROOT / "apps" / "backend", env=env, stdout=log, stderr=subprocess.STDOUT,
    )  # fmt: skip
    base = f"http://127.0.0.1:{port}"
    for _ in range(240):
        try:
            with urllib.request.urlopen(base + "/ready", timeout=2) as r:  # noqa: S310
                if r.status == 200:
                    return proc, base
        except Exception:
            pass
        if proc.poll() is not None:
            raise SystemExit(f"backend exited; see {log.name}")
        time.sleep(0.5)
    proc.kill()
    raise SystemExit("backend did not become ready")


def login(base: str) -> str:
    os.environ["E2E_API_URL"] = base
    sys.path.insert(0, str(ROOT))
    from tests.e2e.test_ui import token  # reads the development users file

    return token.__wrapped__()  # a new login each time: the helper caches its token


def credentials(base: str, spawned: bool) -> dict:
    """A token for the run and how to renew it: the development admin's login, or LOAD_TOKEN
    (which cannot be renewed) against a backend given with --url."""
    if not spawned and os.environ.get("LOAD_TOKEN"):
        return {"token": os.environ["LOAD_TOKEN"], "renew": None}
    return {"token": login(base), "renew": lambda: login(base)}


def ramp(a) -> None:
    """Step the API users up and report p95 per step: where the targets stop being met is the
    capacity of this backend on this machine."""
    cfg = yaml.safe_load(TARGETS.read_text(encoding="utf-8"))
    light = cfg["api"]["groups"]["light"]["p95_ms"]
    proc, base = spawn(a.port, a.persist) if a.spawn else (None, a.url.rstrip("/"))
    rows = []
    try:
        auth = credentials(base, a.spawn)
        for users in (int(x) for x in a.ramp.split(",")):
            res = asyncio.run(run(base, auth, users, 0, a.duration, a.speed))
            answered = [r for r in res.requests if r[2] != 429]
            ok = [r[3] for r in answered if 0 < r[2] < 400]
            fails = len(answered) - len(ok)
            lags = [x["lag"] for x in res.samples if x.get("lag") is not None]
            row = {"users": users, "per_second": round(len(res.requests) / a.duration, 1),
                   "p50_ms": round(pct(ok, 50) or 0), "p95_ms": round(pct(ok, 95) or 0),
                   "failed": fails, "loop_lag_p95_s": pct(lags, 95),
                   "load_generator_cpu": res.client_cpu}  # fmt: skip
            row["meets_light_p95"] = row["p95_ms"] <= light and fails == 0
            rows.append(row)
            print(row)
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(30)
    ok_rows = [r for r in rows if r["meets_light_p95"]]
    lines = [f"# Capacity ramp {dt.datetime.now():%Y-%m-%d %H:%M}", "",
             f"API users only (no streams), {a.duration:.0f} s per step, target p95 <= {light} ms.",
             "", "| Users | Requests/s | p50 ms | p95 ms | Failed | Loop lag p95 s | Client CPU % |"
             " Meets target |", "|---|---|---|---|---|---|---|---|"]  # fmt: skip
    lines += [f"| {r['users']} | {r['per_second']} | {r['p50_ms']} | {r['p95_ms']} | {r['failed']} "
              f"| {r['loop_lag_p95_s']} | {r['load_generator_cpu']} | "
              f"{'yes' if r['meets_light_p95'] else 'no'} |" for r in rows]  # fmt: skip
    best = max((r["users"] for r in ok_rows), default=None)
    lines += ["", f"Capacity: {best} concurrent API users meet the target." if best
              else "Capacity: no step met the target."]  # fmt: skip
    OUT.mkdir(parents=True, exist_ok=True)
    name = f"ramp_{dt.datetime.now():%Y%m%d_%H%M%S}"
    (OUT / f"{name}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (OUT / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--spawn", action="store_true", help="start a separate backend on --port")
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--persist", action="store_true", help="spawned backend records the run")
    ap.add_argument("--users", type=int, default=25)
    ap.add_argument("--streams", type=int, default=25)
    ap.add_argument("--duration", type=float, default=60, help="seconds")
    ap.add_argument("--soak", type=float, help="minutes (overrides --duration)")
    ap.add_argument("--speed", type=float, default=1.0, help="simulation speed during the run")
    ap.add_argument("--ramp", help="capacity: API user counts to step through, e.g. 10,25,50,100"
                    " (--duration seconds each, no stream clients)")  # fmt: skip
    a = ap.parse_args()
    if a.ramp:
        ramp(a)
        return
    seconds = a.soak * 60 if a.soak else a.duration
    cfg = yaml.safe_load(TARGETS.read_text(encoding="utf-8"))
    proc = None
    try:
        if a.spawn:
            proc, base = spawn(a.port, a.persist)
        else:
            base = a.url.rstrip("/")
        auth = credentials(base, a.spawn)
        if not auth["renew"] and seconds > 14 * 60:
            print("warning: LOAD_TOKEN expires after 15 minutes; later requests will get 401")
        print(f"load test: {a.users} users, {a.streams} streams, {seconds:.0f} s against {base}")
        res = asyncio.run(run(base, auth, a.users, a.streams, seconds, a.speed))
        hz = float(os.environ.get("SIM_TICK_HZ", 2.0))
        report = summarise(res, cfg, a, seconds, hz)
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(30)
            except subprocess.TimeoutExpired:
                proc.kill()
    OUT.mkdir(parents=True, exist_ok=True)
    name = f"{'soak' if a.soak else 'load'}_{dt.datetime.now():%Y%m%d_%H%M%S}"
    (OUT / f"{name}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = markdown(report)
    (OUT / f"{name}.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"written: reports/load/{name}.md and .json")
    sys.exit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
