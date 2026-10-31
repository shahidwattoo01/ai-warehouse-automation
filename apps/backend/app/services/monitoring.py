"""Readiness and Prometheus metrics for the whole platform (backlog PR-16).

`/health` (liveness) only says the process answers. `/ready` checks what the platform needs to do
its job: the simulator loop is ticking, the database answers (when runs are recorded), the message
broker is connected (when MQTT_URL is set). The knowledge base and the ERP are reported but do not
make the platform unready: the floor keeps working without them.

`/metrics` gathers the live numbers at scrape time (no background work): HTTP, the simulator
loop, fleet and order KPIs, WMS stock and outbound, safety, alert centre, VDA 5050, ERP outbox,
platform events, rate-limit refusals.
"""

from __future__ import annotations

import time
from collections import Counter

from app.core.config import get_settings
from app.core.observability import Family, http_metrics, render
from app.services.alerts import centre as alert_centre
from app.services.erp import erp
from app.services.events import events_service
from app.services.knowledge import knowledge
from app.services.mlops import mlops
from app.services.vda5050 import vda

LOOP_STALE_SECONDS = 5.0  # the loop runs every 0.5 s or faster; 5 s silent means it is stuck
SAFETY_STATES = ("NORMAL", "ESTOP", "RELEASED")


def _database_ok() -> tuple[bool, str]:
    from sqlalchemy import text

    from app.database.session import engine

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as err:  # the reason, not the connection string (it holds the password)
        return False, type(err).__name__


def readiness(simulator) -> tuple[bool, dict]:
    s = get_settings()
    checks: dict[str, dict] = {}
    checks["role"] = {
        "ok": simulator.role == "active",
        "required": True,
        "detail": simulator.role if s.ha_mode != "single" else "active (single instance)",
    }
    age = time.monotonic() - simulator.loop_heartbeat
    task = simulator._task
    loop_ok = task is not None and not task.done() and age < LOOP_STALE_SECONDS
    checks["simulator_loop"] = {
        "ok": loop_ok,
        "required": True,
        "detail": f"last pass {age:.1f} s ago, running={simulator.engine.running}",
    }
    if s.persist_runs:
        ok, detail = _database_ok()
        checks["database"] = {"ok": ok, "required": True, "detail": detail}
    else:
        checks["database"] = {"ok": True, "required": False, "detail": "not used (PERSIST_RUNS)"}
    bus = vda.bus
    if s.mqtt_url and bus is not None:
        connected = bool(getattr(bus, "connected", False))
        checks["mqtt"] = {"ok": connected, "required": True, "detail": bus.kind}
    else:
        checks["mqtt"] = {"ok": True, "required": False, "detail": "in-process bus"}
    kb = knowledge.status()
    checks["knowledge_base"] = {
        "ok": kb["loaded"],
        "required": False,
        "detail": "loaded" if kb["loaded"] else ("loading" if kb["loading"] else "not loaded yet"),
    }
    if erp.connector is not None:
        st = erp.connector.status()
        checks["erp"] = {"ok": not st["last_error"], "required": False,
                         "detail": st["last_error"] or st["client"]}  # fmt: skip
    rec = simulator.recovery.status()
    checks["state_snapshot"] = {
        "ok": rec["last_error"] is None,
        "required": False,
        "detail": (
            f"saved {rec['age_seconds']} s ago"
            if rec["saved_at"]
            else ("no snapshot yet" if rec["enabled"] else "recovery off")
        ),
    }
    ready = all(c["ok"] for c in checks.values() if c["required"])
    return ready, checks


def _process():
    try:
        import psutil
    except ImportError:  # optional: the process metrics are left out
        return None
    return psutil.Process()


def collect(simulator, limiter=None) -> str:
    eng = simulator.engine
    f: list[Family] = list(http_metrics.families())

    def fam(name: str, kind: str, help_text: str) -> Family:
        family = Family(f"warehouse_{name}", kind, help_text)
        f.append(family)
        return family

    fam("up_seconds", "gauge", "Seconds since the backend started").add(
        round(time.time() - http_metrics.started, 1)
    )
    # ----- the process (standard Prometheus names; memory trend for soak tests)
    proc = _process()
    if proc is not None:
        with proc.oneshot():
            mem, cpu = proc.memory_info(), proc.cpu_times()
            threads = proc.num_threads()
        f.append(Family("process_resident_memory_bytes", "gauge", "Resident memory").add(mem.rss))
        f.append(
            Family("process_cpu_seconds_total", "counter", "User and system CPU time").add(
                round(cpu.user + cpu.system, 2)
            )
        )
        f.append(Family("process_threads", "gauge", "Operating-system threads").add(threads))
    # ----- simulator loop
    fam("sim_running", "gauge", "1 while the simulation runs").add(int(eng.running))
    fam("sim_tick", "gauge", "Simulated time in ticks").add(eng.time)
    fam("sim_speed", "gauge", "Simulation speed factor").add(eng.speed)
    fam("sim_ticks_total", "counter", "Ticks computed by the loop").add(simulator.ticks_total)
    fam("sim_tick_seconds_total", "counter", "CPU seconds spent in ticks").add(
        round(simulator.tick_seconds_total, 4)
    )
    fam("sim_tick_seconds_max", "gauge", "Slowest recent tick (decays slowly)").add(
        round(simulator.tick_seconds_max, 5)
    )
    fam("sim_loop_lag_seconds", "gauge", "How late the loop's last pass started").add(
        round(simulator.loop_lag, 4)
    )
    fam("sim_loop_age_seconds", "gauge", "Seconds since the loop last ran").add(
        round(time.monotonic() - simulator.loop_heartbeat, 2)
    )
    fam("stream_clients", "gauge", "Browsers on the live stream").add(len(simulator._subscribers))
    rec = simulator.recovery.status()
    fam("instance_active", "gauge", "1 on the instance that runs the warehouse").add(
        int(simulator.role == "active")
    )
    fam("state_snapshot_age_seconds", "gauge", "Seconds since the state was last saved").add(
        rec["age_seconds"]
    )
    fam("state_snapshot_bytes", "gauge", "Size of the last state snapshot").add(rec["size_bytes"])
    fam("state_snapshot_capture_seconds", "gauge", "Event-loop time of the last capture").add(
        rec["capture_ms"] / 1000
    )
    fam("state_snapshot_failures_total", "counter", "State snapshots that failed").add(
        rec["failures"]
    )
    # ----- fleet
    states = Counter(r.status.value for r in eng.robots.values())
    robots = fam("robots", "gauge", "Robots by status")
    for status in sorted(set(states) | {"IDLE", "MOVING", "FAULT", "CHARGING"}):
        robots.add(states.get(status, 0), status=status)
    batteries = [r.battery for r in eng.robots.values()]
    fam("robot_battery_min_percent", "gauge", "Lowest robot battery").add(
        round(min(batteries), 1) if batteries else None
    )
    fam("robot_battery_avg_percent", "gauge", "Average robot battery").add(
        round(sum(batteries) / len(batteries), 1) if batteries else None
    )
    k = eng.kpis.snapshot()
    fam("orders_created_total", "counter", "Orders created this run").add(k["orders_created"])
    fam("orders_completed_total", "counter", "Orders completed this run").add(k["orders_completed"])
    fam("orders_late_percent", "gauge", "Completed orders that were late").add(k["late_percent"])
    fam("throughput_orders_per_hour", "gauge", "Orders per simulated hour").add(
        k["throughput_per_hour"]
    )
    fam("fleet_utilisation_percent", "gauge", "Share of robots working").add(
        k["utilisation_percent"]
    )
    fam("order_cycle_ticks_avg", "gauge", "Average order completion time").add(
        k["avg_completion_ticks"]
    )
    # ----- warehouse (WMS)
    wms = getattr(eng.inventory, "wms", None)
    if wms is not None:
        w = wms.kpis()
        for key, help_text in (
            ("units_on_hand", "Units in stock"),
            ("stockouts", "SKUs with no stock"),
            ("orders_waiting_stock", "Orders waiting for stock"),
            ("fill_rate", "Share of ordered units picked"),
            ("open_purchase_orders", "Purchase orders not yet received"),
            ("trucks_at_dock", "Inbound trucks at the dock"),
            ("on_hold_units", "Units on quality hold"),
            ("counts_pending_approval", "Cycle counts waiting for approval"),
        ):
            fam(f"wms_{key}", "gauge", help_text).add(w.get(key))
        out = Counter(rec.status for rec in wms.out.orders.values())
        outbound = fam("outbound_orders", "gauge", "Outbound orders by status")
        for status, n in sorted(out.items()):
            outbound.add(n, status=status)
    # ----- safety
    safety = fam("safety_state", "gauge", "1 for the current safety state")
    for state in SAFETY_STATES:
        safety.add(int(eng.safety.state == state), state=state)
    fam("safety_near_misses_total", "counter", "Near misses this run").add(
        eng.safety.metrics.get("near_misses", 0)
    )
    # ----- alert centre
    a = alert_centre.summary()
    incidents = fam("alert_incidents", "gauge", "Open alert incidents")
    for key in ("open", "acknowledged", "critical", "escalated"):
        incidents.add(a.get(key, 0), state=key)
    # ----- integrations
    if vda.bus is not None:
        msgs = fam("vda5050_messages_total", "counter", "VDA 5050 messages")
        for direction, n in vda.bus.counts.items():
            msgs.add(n, kind=direction)
        conns = Counter(vda.master.connections.values()) if vda.master else Counter()
        online = fam("vda5050_vehicles", "gauge", "Vehicles by connection state")
        for state in sorted(set(conns) | {"ONLINE"}):
            online.add(conns.get(state, 0), state=state)
    if erp.connector is not None:
        st = erp.connector.status()
        fam("erp_orders_imported_total", "counter", "ERP orders imported").add(st["imported"])
        fam("erp_orders_rejected_total", "counter", "ERP orders rejected").add(st["rejected"])
        box = fam("erp_outbox_messages", "gauge", "ERP outbox by status")
        for status in sorted(set(st["outbox"]) | {"PENDING", "FAILED"}):
            box.add(st["outbox"].get(status, 0), status=status)
        fam("erp_up", "gauge", "1 when the last ERP call worked").add(int(not st["last_error"]))
    pub = events_service.publisher
    if pub is not None:
        ev = fam("events_published_total", "counter", "Platform events by category")
        for cat, n in sorted(pub.counts.items()):
            ev.add(n, category=cat)
        fam("events_subscribers", "gauge", "Live event-stream subscribers").add(
            len(pub.subscribers)
        )
    if limiter is not None:
        fam("rate_limited_total", "counter", "Requests refused by the rate limiter").add(
            limiter.refused
        )
    # ----- AI models (MLOps)
    status_of = fam("model_status", "gauge", "1 for each live model's current drift status")
    error = fam("model_live_error", "gauge", "Live error: ETA MAE (ticks), late-risk recall")
    psi_max = fam("model_input_psi_max", "gauge", "Largest input shift (PSI) vs training data")
    version = fam("model_production_version", "gauge", "Production version number")
    for model, mon in mlops.monitors.items():
        check = mon.last or {}
        for state in ("NOT_ENOUGH_DATA", "OK", "WARN", "DRIFT"):
            status_of.add(int(check.get("status") == state), model=model, status=state)
        perf = check.get("performance") or {}
        error.add(perf.get("live_mae") if model == "eta" else perf.get("live_recall"), model=model)
        psi_max.add(check.get("max_psi"), model=model)
        version.add(int(mlops.registry.production(model)["version"][1:]), model=model)
    retrains = fam("model_retrains_total", "counter", "Retrainings and their outcome")
    for key, n in mlops.counts.items():
        retrains.add(n, result=key)
    kb = knowledge.status()
    fam("knowledge_base_loaded", "gauge", "1 when the knowledge base is loaded").add(
        int(kb["loaded"])
    )
    return render(f)
