# Platform monitoring

Backlog PR-16. This page is about the platform itself: is it up, is the simulator keeping time,
are requests fast, do the integrations work. Problems on the warehouse floor (low stock, a missed
truck, an e-stop) are the job of the [alert centre](alerts.md).

Code: [`app/core/observability.py`](../apps/backend/app/core/observability.py) (request ids,
logs, HTTP metrics), [`app/services/monitoring.py`](../apps/backend/app/services/monitoring.py)
(readiness, platform metrics), [`monitoring/`](../monitoring) (Prometheus, Grafana).

## Health checks

| Endpoint | Meaning | Use |
|---|---|---|
| `GET /health` | Liveness: the process answers | Restart the container if it fails |
| `GET /ready` | Readiness: 200, or 503 with the failing check | Load balancer, docker-compose health check |

`/ready` checks the **simulator loop** (it ran in the last 5 s), the **database** (`SELECT 1`, when
`PERSIST_RUNS=true`) and the **MQTT broker** (when `MQTT_URL` is set). These are required. The
**knowledge base** and the **ERP** are reported too, but are not required: the floor keeps working
without them.

```json
{"ready": true, "checks": {
  "simulator_loop": {"ok": true, "required": true, "detail": "last pass 0.2 s ago, running=True"},
  "database": {"ok": true, "required": true, "detail": "ok"},
  "mqtt": {"ok": true, "required": false, "detail": "in-process bus"},
  "knowledge_base": {"ok": false, "required": false, "detail": "not loaded yet"},
  "erp": {"ok": true, "required": false, "detail": "in-process mock"}}}
```

## Metrics

`GET /metrics` returns the Prometheus text format. With `METRICS_TOKEN` set, it requires
`Authorization: Bearer <token>`. The values are read when Prometheus scrapes, so there is no
background work. All names start with `warehouse_`:

| Group | Metrics |
|---|---|
| HTTP | `http_requests_total{method,route,status}`, `http_request_duration_seconds` (histogram), `http_requests_in_flight`, `rate_limited_total` |
| Simulator | `sim_running`, `sim_tick`, `sim_speed`, `sim_ticks_total`, `sim_tick_seconds_total`, `sim_tick_seconds_max`, `sim_loop_lag_seconds`, `sim_loop_age_seconds`, `stream_clients` |
| Fleet, orders | `robots{status}`, `robot_battery_min_percent`, `robot_battery_avg_percent`, `orders_created_total`, `orders_completed_total`, `orders_late_percent`, `throughput_orders_per_hour`, `fleet_utilisation_percent`, `order_cycle_ticks_avg`, `outbound_orders{status}` |
| WMS | `wms_units_on_hand`, `wms_stockouts`, `wms_orders_waiting_stock`, `wms_fill_rate`, `wms_open_purchase_orders`, `wms_trucks_at_dock`, `wms_on_hold_units`, `wms_counts_pending_approval` |
| Safety, alerts | `safety_state{state}`, `safety_near_misses_total`, `alert_incidents{state}` |
| Integrations | `vda5050_messages_total{kind}`, `vda5050_vehicles{state}`, `erp_orders_imported_total`, `erp_orders_rejected_total`, `erp_outbox_messages{status}`, `erp_up`, `events_published_total{category}`, `events_subscribers`, `knowledge_base_loaded` |

The `route` label is the route **template** (`/api/v1/robots/{robot_id}`), never the raw path.
That keeps the number of series fixed however many ids are requested. Counters that belong to a
run (orders, near misses) start again at 0 after a reset; Prometheus `rate()` and `increase()`
handle counter resets.

## Logs

* Every request gets an id: the caller's `X-Request-ID` when it is a safe token (8–64 letters,
  digits, `.`, `_`, `-`), otherwise a new one. The id is returned in the `X-Request-ID` response
  header and written into every log line made during that request.
* `LOG_FORMAT=json` writes one JSON object per line: `time`, `level`, `logger`, `message`,
  `request_id`, any `extra=` fields, and `exception`. That suits Loki, ELK or CloudWatch.
  docker-compose sets it. `LOG_FORMAT=text` (the default) stays readable in a terminal.
* Uvicorn's per-request access log is off. The backend logs only requests that failed (5xx) or
  took longer than 2 s; Prometheus counts the rest.

## Prometheus, alert rules, Grafana

`docker compose up` also starts:

* **Prometheus** on http://localhost:9090. It scrapes the backend every 15 s and keeps 15 days.
  Config: `monitoring/prometheus/prometheus.yml`.
* **Grafana** on http://localhost:3001 (user `admin`, password `GRAFANA_ADMIN_PASSWORD` from
  `.env`). The data source and the **Warehouse AI Platform** dashboard are provisioned. The
  dashboard has three rows: platform health, fleet and orders, warehouse and integrations.

The alert rules are in `monitoring/prometheus/alert_rules.yml`:

| Alert | When | Severity |
|---|---|---|
| BackendDown | scrape fails for 1 min | critical |
| SimulatorLoopStalled | loop silent > 5 s for 30 s | critical |
| SimulatorFallingBehind | ticks start > 0.5 s late for 2 min | warning |
| HighErrorRate | > 5 % of requests are 5xx over 5 min | warning |
| SlowApi | p95 latency > 1 s for 10 min | warning |
| RateLimitedClients | > 50 refusals in 10 min | info |
| ErpOutboxFailing | ERP messages failed after all retries | warning |
| ErpUnreachable | ERP calls failing for 10 min | warning |
| VehiclesOffline | robots not ONLINE over VDA 5050 for 2 min | warning |
| EmergencyStopActive | e-stop engaged | critical |
| RobotsInFault | 3 or more robots in fault for 5 min | warning |
| CriticalIncidentsOpen | a critical alert-centre incident open for 15 min | warning |

To send these by e-mail or chat, add an Alertmanager and point Prometheus at it. That is the
standard Prometheus route and is not part of this setup yet.

## Tests

`apps/backend/tests/test_monitoring.py` covers:

* `/health` and `/ready`, and a 503 when the loop has died.
* Every `/metrics` line is valid exposition format.
* Route templates are used instead of ids.
* The metrics token is enforced.
* Request ids pass through, and unsafe ones are replaced.
* JSON log lines are well formed.
* Every metric named in the alert rules and the Grafana dashboard is actually exported, so a
  renamed metric breaks the test instead of silently emptying a panel.

Checked live against the dev backend: `/ready` returned 200 with the real database check, and
`/metrics` returned 110 samples.

## Not yet

* Prometheus and Grafana have not run here as containers (Docker is not installed). The configs
  are checked as YAML and JSON, and their metric names are checked against the real endpoint.
* Alertmanager (routing alerts to e-mail or chat) and log shipping (Loki or similar).
* Tracing (OpenTelemetry) across the backend, ERP and broker.
