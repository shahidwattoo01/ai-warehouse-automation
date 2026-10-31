# Load test reports

Written by `python -m tests.load.loadtest` (docs/load_testing.md). One Markdown and one JSON file
per run. The runs from 31 October 2026, in order:

| Run | What it shows |
|---|---|
| `load_20261031_154652` | First run, 10 users and 10 streams: everything stopped for 16 s (the inventory listing rebuilt every product's stock per row) |
| `load_20261031_155201` | After the stock fix: the default run (25 users, 25 streams) passes every target |
| `load_20261031_155431` | 100 users and 100 streams: the API queues (about 27 requests/s) |
| `load_20261031_155736` | 100 users, no streams: the server, not the client, is the limit |
| `load_20261031_160230` | After caching the login check: 66 requests/s |
| `load_20261031_160441` | Login check made async: 70 requests/s |
| `load_20261031_160740` | After sharing the KPIs per tick (a noisy run: other programs were using the CPU) |
| `ramp_20261031_161150` | Capacity ramp after all fixes: 50 concurrent users meet p95 250 ms |
| `soak_20261031_164856` | 20-minute soak: memory stable, but the last 5 minutes refused (the renewed login token was a cached, expired one: fixed in the tool) |
| later `soak_*` | 16-minute soak after the fix |
