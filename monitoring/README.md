# Monitoring

* **Platform monitoring** (backlog PR-16): Prometheus scrape config and alert rules in
  `prometheus/`, Grafana provisioning and the "Warehouse AI Platform" dashboard in `grafana/`.
  The backend side is `apps/backend/app/core/observability.py` and
  `apps/backend/app/services/monitoring.py`. See [docs/monitoring.md](../docs/monitoring.md).
* **Model monitoring** (`model_monitor.py`, phase 10): model error vs actual outcomes, agent
  success / latency / cost (TRD 11.3).
