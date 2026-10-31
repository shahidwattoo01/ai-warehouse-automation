# Load and soak testing

Backlog PR-18. Code: [`tests/load/loadtest.py`](../tests/load/loadtest.py). Targets:
[`configs/load_targets.yaml`](../configs/load_targets.yaml). Reports: `reports/load/`
(Markdown and JSON per run).

## What it does

Three things run at the same time against one backend:

* **API users.** Each one acts like an open screen. It sends a request picked from a weighted mix
  of what the pages poll (WMS KPIs, alerts, safety, robots, orders, outbound, events, ERP, VDA,
  handheld) and, less often, the large answers (full warehouse state, inventory, locations,
  tasks). Then it waits 0.3–1.5 s of think time.
* **Stream clients.** Browsers on the live WebSocket. Each sends the auth message, gets the
  layout, then one frame per tick. The time between tick frames shows whether the server keeps
  up with every client.
* **A sampler.** It reads `/metrics` every 5 s: simulator loop lag, ticks done, backend memory
  and CPU (`process_*`, added for this).

```
python -m tests.load.loadtest --spawn                          # 25 users + 25 streams, 60 s
python -m tests.load.loadtest --spawn --users 100 --streams 100 --duration 120
python -m tests.load.loadtest --spawn --ramp 10,25,50,75,100 --duration 30   # capacity
python -m tests.load.loadtest --spawn --soak 30                # memory and lag over 30 min
python -m tests.load.loadtest --url http://host:8000           # LOAD_TOKEN=<access token>
```

`--spawn` starts a separate backend on port 8010 and logs in as the development admin. That
backend has:

* rate limiting off, so the test measures the platform and not the limiter;
* a temporary state directory;
* run recording off, unless you pass `--persist`.

Against `--url`, requests refused by the rate limiter (429) are counted separately.

Access tokens live 15 minutes, so the tool logs in again every 10 minutes during a long run
(`LOAD_RENEW_SECONDS` changes the interval). A token given in `LOAD_TOKEN` cannot be renewed, and
the tool warns about that for runs longer than 14 minutes. Refused requests (4xx) are reported
by code, with the first and last second they occurred.

The first two soak attempts are the reason for this:

1. The token expired at minute 15 and the clean-up failed with 401, so the run lost its report.
2. With renewal added, a quarter of the requests were still refused, exactly the last 5 minutes.
   The development login helper caches its token (`@cache`), so "logging in again" returned the
   expired one. The tool now makes a real new login each time.

Checked with 1-minute tokens and renewal every 40 s: 820 requests over 150 s, none refused.

## Targets

| Check | Target |
|---|---|
| Small reads (KPIs, alerts, status, short lists) p95 / p99 | ≤ 250 / 600 ms |
| Large reads (state, inventory, locations, tasks) p95 / p99 | ≤ 1,200 / 2,500 ms |
| Errors (5xx or no answer) | ≤ 1 % |
| Stream connect (open, auth, layout) p95 | ≤ 1,500 ms |
| Gap between tick frames p95 | ≤ 1,200 ms at 1× (ticks every 500 ms; scales with speed) |
| Stream clients dropped by the server | 0 |
| Simulator loop lag p95 | ≤ 0.25 s |
| Ticks done / ticks scheduled | ≥ 0.9 |
| Memory trend over a soak of at least 10 min | ≤ 60 MB per hour |

The report also records the load generator's own CPU use. When it gets near 100 % of a core, the
client is the limit and the run says little about the server.

## What the first runs found, and what was fixed

1. **`/api/v1/inventory` took 13 s and froze the whole platform.** Every API answer and every
   stream frame stopped for 16 s. `inventory.stock[pid]` built the available-to-promise number
   for all 1,584 products on every access, and each of those scans the stock rows. Listing the
   inventory therefore did 2.5 million ATP calculations.
   * Fix: a per-product `stock_of()`, and one stock pass for the list. Time: **13,104 ms → 18 ms**.
   * The same pattern ran on the **tick path** when runs are recorded: every pick event rebuilt
     all products' stock. The copilot and order creation had it too. All now use `stock_of()`.
2. **The login check asked PostgreSQL on every request.** It was a connection health ping plus a
   query (about 7 ms), run in a worker thread. That capped the API near 35 requests/s.
   * Fix: the check is async and the user record is cached for 5 s. Any account change in the
     process clears the cache at once, so disabling a user or changing a role still takes effect
     immediately (`test_disabling_a_user_takes_effect_immediately`).
   * A change made on another instance (active/standby) is seen within 5 s.
3. **The WMS KPIs cost about 80 ms on the large layout**, and every open screen polls them.
   * Fix: one answer per tick is shared by all callers. It is recomputed after 1 s while paused,
     so receipts and counts still show up.

`apps/backend/tests/test_performance.py` guards all three. It also checks that every request in
the load mix names a route that exists.

## Measured (this laptop)

Measured on a 4-thread laptop, with the browser and the dev servers running on the same
machine. The large layout has 40 robots and 1,584 SKUs. Treat the numbers as a floor, not as
server figures.

**Default run (25 API users + 25 stream clients, 60 s): passed.**

| Check | Result |
|---|---|
| Small reads p95 / p99 | 216 / 348 ms |
| Large reads p95 / p99 | 275 / 347 ms |
| Errors | 0 of 1,594 requests (26.6/s) |
| Stream connect p95 | 317 ms |
| Tick-frame gap p95 / max | 600 / 681 ms (3,006 frames, 0 dropped) |
| Loop lag p95 | 0.03 s |
| Ticks done / scheduled | 1.00 |
| Backend CPU | 34 % of one core |

**Capacity ramp (API users only, 30 s per step, after the fixes):**

| Users | Requests/s | p50 ms | p95 ms | Failed | Meets 250 ms |
|---|---|---|---|---|---|
| 10 | 11.1 | 5 | 111 | 0 | yes |
| 25 | 26.8 | 6 | 181 | 0 | yes |
| 50 | 52.5 | 12 | 228 | 0 | yes |
| 75 | 74.7 | 32 | 470 | 1 | no |
| 100 | 85.6 | 115 | 958 | 8 | no |

About **50 concurrent screens** per backend process meet the target on this machine. Above that,
requests queue on the single Python event loop. Beyond about 75 users the load generator also
competes for the same CPU (the failures are client-side timeouts; the backend logged no
errors).

**Soak (16 min, 25 users + 25 streams, through a token renewal):**

| Check | Result |
|---|---|
| Small reads p95 / p99 | 162 / 404 ms |
| Large reads p95 / p99 | 281 / 535 ms |
| Errors | 5 of 25,636 requests (0.02 %, client-side read errors), 0 refused |
| Stream connect p95 | 67 ms |
| Tick-frame gap p95 / max | 616 / 1,847 ms (47,997 frames, 0 dropped) |
| Loop lag p95 | 0.06 s |
| Ticks done / scheduled | 1.00 |
| Memory | 415 → 468 MB, trend +118 MB/h (**missed** the 60 MB/h target) |

The memory trend found a fourth problem: the **route-distance cache**
(`simulation/navigation/distance.py`). It keeps one map of every cell's distance per destination
(about 0.4 MB each on the large layout), and every new rack an order sends a robot to adds one.
The cap was 2,048 maps, which is about 750 MB, more than the rest of the backend.

* Fix: the cache now evicts the least recently used map, capped at 256 (about 100 MB).
* A miss costs one 13 ms search.
* The maps depend only on the grid, so behaviour is unchanged (the simulator fingerprint is
  identical).
* `test_distance_cache_is_bounded_and_keeps_recent_goals` guards it.

A headless run of 12,000 ticks (about 100 minutes of warehouse time, with the optimizer, alert
centre, VDA, ERP and events) shows that the cache is the only thing that grows.

| Tick | Python memory (traced) | Cached maps |
|---|---|---|
| 1,500 | 26 MB | 56 |
| 3,000 | 51 MB | 118 |
| 4,500 | 13 MB | 5 (an aisle closed or a hazard appeared: the cache was cleared) |
| 6,000 | 20 MB | 11 |
| 10,500 | 81 MB | 137 |
| 12,000 | 88 MB | 147 |

Without the maps, memory stays near 13–20 MB. With the cap it cannot exceed about 100 MB on top.

## Scaling beyond one process

The simulation runs in one process (PR-17 explains why). Read traffic can scale out without
changing that:

* Put a cache or read replica in front of the large read-only answers.
* Serve the stream through a fan-out relay. Frames are already built once per tick and shared by
  every client.

Both belong to PR-06 (scale).

## Not yet

* Runs from several machines (the generator is one Python process). Locust or k6 would be the
  next step for loads beyond about 100 users.
* Browser-level timings (page render) under load.
* A load run in CI. The suite's `test_performance.py` guards the specific regressions instead.
