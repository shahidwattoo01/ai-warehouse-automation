"""Scale runs: both layouts at several fleet sizes (backlog PR-06; docs/scale.md).

    python scripts/scale_benchmark.py            # ~8 minutes on a laptop
    python scripts/scale_benchmark.py --ticks 6000

Two series per layout:

    fixed demand    the normal order rate: what more robots buy (faster service, less lateness)
    scaled demand   orders grow with the fleet (same orders per robot): does throughput grow
                    with it, or do congestion and the packing stations become the limit?

Measured per run: completed orders per simulated hour, average completion time, late %, robot
utilisation, orders still waiting at the end, collisions, and the compute cost of one tick (how
fast the simulator can run in real time). Writes reports/scale_benchmark.json and .md.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from simulation.environment.engine import SimulationEngine  # noqa: E402
from simulation.events.events import EventType  # noqa: E402
from simulation.warehouse.layout import load_layout  # noqa: E402

BASE_RATE = 0.14  # configs/simulation.yaml orders.arrival_prob_per_tick
RUNS = {  # layout -> (its normal fleet, the fleet sizes to run)
    "default": (12, [6, 12, 18, 24]),
    "large": (40, [20, 40, 60, 88]),
}
TICK_BUDGET_MS = 500  # one tick every 0.5 s at speed 1x (sim_tick_hz 2)


def run(layout: str, fleet: int, rate: float, ticks: int, seed: int, profile: dict | None = None):
    overrides = {"layout": layout, "inventory_model": "simple", "fleet_size": fleet}
    for section, values in (profile or {}).items():
        overrides[section] = dict(values)
    orders = overrides.setdefault("orders", {})
    orders["arrival_prob_per_tick"] = rate
    orders["hourly_profile"] = [1.0] * 24  # steady demand: no night-time lull in the window
    e = SimulationEngine(seed=seed, overrides=overrides)
    e.start()
    tph = e.config.get("ticks_per_hour", 600)
    for _ in range(tph):  # one simulated hour of warm-up, not measured
        e.tick()
    done0, late0 = e.kpis.delivered, e.kpis.late
    collisions, cost, busy = 0, [], 0
    for _ in range(ticks):
        began = time.perf_counter()
        events = e.tick()
        cost.append(time.perf_counter() - began)
        collisions += sum(ev.type == EventType.COLLISION for ev in events)
        busy += sum(not e.controller.available(r) for r in e.robots.values())
    done, late = e.kpis.delivered - done0, e.kpis.late - late0
    k = e.kpis.snapshot()
    cost.sort()
    mean_ms = 1000 * sum(cost) / len(cost)
    return {
        "layout": layout, "robots": len(e.robots), "arrival_rate": round(rate, 4),
        "throughput_per_hour": round(done * tph / ticks, 1), "orders_completed": done,
        "avg_completion_ticks": k["avg_completion_ticks"],
        "late_percent": round(100 * late / done, 1) if done else 0.0,
        "utilisation_percent": round(100 * busy / (ticks * len(e.robots)), 1),
        "waiting_at_end": sum(1 for o in e.orders.values() if o.status.value == "PENDING"),
        "collisions": collisions,
        "tick_ms_mean": round(mean_ms, 2),
        "tick_ms_p99": round(1000 * cost[int(len(cost) * 0.99)], 2),
        "max_speed_realtime": round(TICK_BUDGET_MS / mean_ms, 1),
    }  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ticks", type=int, default=3000, help="per run (600 = 1 simulated hour)")
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--profile", help="configs/profiles/<name>.yaml on top (e.g. realistic_timing)")
    ap.add_argument("--runs", help="only these, e.g. large:40,default:12 (fixed demand)")
    a = ap.parse_args()
    profile = None
    if a.profile:
        profile = yaml.safe_load((ROOT / "configs" / "profiles" / f"{a.profile}.yaml").read_text())
    plan = RUNS
    if a.runs:
        plan = {}
        for item in a.runs.split(","):
            layout, fleet = item.split(":")
            plan.setdefault(layout, (RUNS[layout][0], []))[1].append(int(fleet))
    rows = []
    for layout, (base, fleets) in plan.items():
        capacity = len(load_layout(layout).parking) or None
        for fleet in fleets:
            for mode, rate in (("fixed", BASE_RATE), ("scaled", BASE_RATE * fleet / base)):
                if mode == "scaled" and (fleet == base or a.runs):
                    continue  # the same run as fixed
                t = time.perf_counter()
                row = {"demand": mode, "profile": a.profile or "default",
                       **run(layout, fleet, rate, a.ticks, a.seed, profile)}  # fmt: skip
                row["parking_places"] = capacity
                rows.append(row)
                r = row
                print(
                    f"{layout:7s} {fleet:3d} robots {mode:6s} {r['throughput_per_hour']:6.1f} "
                    f"orders/h  late {r['late_percent']:5.1f} %"
                    f"  util {r['utilisation_percent']:5.1f} %"
                    f"  waiting {r['waiting_at_end']:4d}  {r['tick_ms_mean']:5.1f} ms/tick"
                    f"  ({time.perf_counter() - t:.0f} s)",
                    flush=True,
                )
    out = ROOT / "reports" / ("scale_benchmark" + (f"_{a.profile}" if a.profile else ""))
    out.with_suffix(".json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    lines = [
        f"# Scale benchmark {dt.date.today()}",
        "",
        f"{a.ticks} measured ticks per run ({a.ticks / 600:.0f} simulated hours) after one hour of "
        f"warm-up, seed {a.seed}, simple inventory, steady demand (no daily curve). Fixed: 0.14 "
        "orders per tick (84 per simulated hour). Scaled: in proportion to the fleet. Utilisation "
        "is averaged over every tick.",
        "",
        "| Layout | Robots | Demand | Orders/h | Avg completion (ticks) | Late % | Utilisation % "
        "| Waiting at end | Collisions | ms/tick | Max real-time speed |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {r['layout']} | {r['robots']} | {r['demand']} | {r['throughput_per_hour']} "
        f"| {r['avg_completion_ticks']} | {r['late_percent']} | {r['utilisation_percent']} "
        f"| {r['waiting_at_end']} | {r['collisions']} | {r['tick_ms_mean']} "
        f"| {r['max_speed_realtime']}x |"
        for r in rows
    ]
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written {out.relative_to(ROOT)}.json and .md")


if __name__ == "__main__":
    main()
