"""Drift, retraining and promotion end to end, in a simulated warehouse (docs/mlops.md).

    python scripts/mlops_experiment.py                    # default layout, ~5 min on a laptop
    python scripts/mlops_experiment.py --pick-ticks 20 --layout large

1. The warehouse runs as trained: the ETA model's live error is checked every simulated hour.
2. Then picking gets slower: the site switches to human-assisted picking at the racks, about 15 s
   per item (--pick-ticks 30 instead of 4). The models cannot see this (pick time is not one of
   their inputs), so delivery takes longer than they predict: performance drift.
3. The platform confirms the drift, retrains the ETA model on the old data plus the live
   outcomes, runs the gate tests and promotes the new version if they pass.
4. The warehouse keeps running on the new version: its live error is compared with before.

Uses a temporary registry (the real one in data/mlops/ is not touched). Writes the timeline to
reports/mlops_experiment.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps" / "backend")]
os.environ.setdefault("PERSIST_RUNS", "false")
os.environ.setdefault("STATE_RECOVERY", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ai.classical_ml.live_predictor import Predictor  # noqa: E402
from ai.mlops.registry import Registry  # noqa: E402
from app.services.mlops import MlopsService  # noqa: E402
from simulation.environment.engine import SimulationEngine  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--layout", default="default")
    ap.add_argument("--pick-ticks", type=int, default=30)
    ap.add_argument("--before", type=int, default=6000, help="ticks before the change")
    ap.add_argument("--after", type=int, default=18000, help="ticks after the change")
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()

    engine = SimulationEngine(
        seed=a.seed, overrides={"layout": a.layout, "inventory_model": "simple"}
    )
    predictor = Predictor()
    predictor.attach(engine)
    service = MlopsService(registry=Registry(state_dir=Path(tempfile.mkdtemp())))
    service.attach(predictor)
    timeline, changed_at, eta_records, served = [], None, [], {}
    engine.start()
    began = time.perf_counter()
    for i in range(1, a.before + a.after + 1):
        engine.tick()
        predictor.after_tick()
        records, _ = predictor.drain()
        service.observe(records)
        for rec in records:
            if rec["model"] == "eta":
                rec["served_by"] = service.registry.production("eta")["version"]
                eta_records.append(rec)
        service.after_tick(engine.time)
        if i == a.before:
            engine.config["orders"]["pick_ticks"] = a.pick_ticks
            changed_at = engine.time
            print(f"tick {engine.time}: pick time 4 -> {a.pick_ticks} ticks per item")
        if service._thread is not None and service._thread.is_alive():
            service._thread.join()  # in the live platform the loop keeps ticking meanwhile
        if engine.time % service.cfg["monitor"]["check_every_ticks"] == 0:
            check = service.monitors["eta"].last or {}
            perf = check.get("performance") or {}
            row = {
                "tick": engine.time,
                "eta_version": service.registry.production("eta")["version"],
                "status": check.get("status"),
                "live_mae": perf.get("live_mae"),
                "start_mae": perf.get("start_mae"),
                "samples": check.get("samples"),
            }
            timeline.append(row)
            if engine.time % 1200 == 0:
                print(row)
    # Shadow comparison: what the original v1 would have predicted for the very same orders
    # each later version handled (same inputs, same real outcome).
    v1 = joblib.load(service.registry.path_of(service.registry.get("eta", "v1")))
    for version in sorted({r["served_by"] for r in eta_records}, key=lambda v: int(v[1:])):
        rows = [r for r in eta_records if r["served_by"] == version and r["tick"] >= changed_at]
        if not rows:
            continue
        X = pd.DataFrame([r["input"] for r in rows])[list(v1.feature_names_in_)]
        actual = np.array([r["actual"]["duration_ticks"] for r in rows])
        live = np.array([r["output"]["eta_ticks"] for r in rows])
        served[version] = {
            "orders": len(rows),
            "mae_served": round(float(np.abs(live - actual).mean()), 1),
            "mae_if_v1": round(float(np.abs(v1.predict(X) - actual).mean()), 1),
        }
        print(f"after the change, orders served by {version}: {served[version]}")
    events = list(reversed(service.events))
    for e in events:
        print(f"  {e['event']:18s} {e['model']:5s} {e['text'][:110]}")
    result = {
        "layout": a.layout, "pick_ticks": a.pick_ticks, "changed_at": changed_at,
        "seconds": round(time.perf_counter() - began), "timeline": timeline, "events": events,
        "versions": {m: service.registry.versions(m) for m in ("eta", "late")},
        "shadow": served,
    }  # fmt: skip
    out = ROOT / "reports" / "mlops_experiment.json"
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"written {out.relative_to(ROOT)} in {result['seconds']} s")


if __name__ == "__main__":
    main()
