"""Generate the simulation datasets (dataset v3): one simulated day per run, consecutive dates.

    python scripts/generate_data.py                       # 91 days (13 weeks) -> data/processed/
    python scripts/generate_data.py --days 3 --hours 4    # quick smoke run

Every run simulates one calendar day, starting Monday 2026-09-07, so the runs together form one
continuous 13-week history: weekday/weekend patterns, an autumn ramp-up into the November peak
season, and promotion days. Each day also gets its own fault rate and hazard rates (aisle
closures, dropped parcels), so healthy and troubled days both appear.

The simulated clock is compressed with --ticks-per-hour (default 600 ticks = 1 simulated hour) so
a day takes about a minute, while robots still move 1 cell per tick.

Outputs (Parquet):
    data/synthetic/runs/<run_id>/<table>.parquet   raw per-run tables
    data/processed/<phase>/<table>.parquet         all days combined, with a `split` column:
        classical_ml/   tasks, demand_hourly, anomaly_windows   (Phase 3 training data)
        deep_learning/  robot_status                            (telemetry sequences)
        raw_logs/       events, orders, hazards                 (analysis, agents)
    data/processed/reference/<entity>.parquet      warehouse entities (Layer 1): zones, aisles,
                                                   shelves, stations, parking, obstacles,
                                                   products, robots
    data/processed/manifest.json                   settings, per-day parameters, row counts

Tables: robot_status, events, orders, tasks, demand_hourly, anomaly_windows, hazards.
Every row carries `dataset_version`, so data from different generations can never be mixed.
Splits are by date (never random rows): train = first 9 weeks, validation = next 2 weeks,
test = last 2 weeks (it contains the Black Friday peak: a realistic, harder test).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # allow `python scripts/generate_data.py` from the repo root
    sys.path.insert(0, str(ROOT))

from simulation.environment.calendar import (  # noqa: E402
    PROMOTIONS,
    START_DATE,
    season_name,
)
from simulation.environment.engine import SimulationEngine  # noqa: E402
from simulation.environment.recorder import Recorder  # noqa: E402
from simulation.warehouse.layout import CONFIG_DIR  # noqa: E402

# Where each combined table is stored, by the phase that uses it.
TABLE_DIRS = {
    "tasks": "classical_ml",
    "demand_hourly": "classical_ml",
    "anomaly_windows": "classical_ml",
    "robot_status": "deep_learning",
    "events": "raw_logs",
    "orders": "raw_logs",
    "hazards": "raw_logs",
}
TABLES = [
    "robot_status",
    "events",
    "orders",
    "tasks",
    "demand_hourly",
    "anomaly_windows",
    "hazards",
]

# v1: order rates above fleet capacity (demand capped); no product columns.
# v2: rates from measured capacity; product weight/categories; version column.
# v3: calendar (consecutive dates, weekday/season/promotions), motor temperature + overheating
#     faults, aisle closures and floor hazards, zone demand, route distance, reference tables.
DATASET_VERSION = "v3"

DAYS = 91  # 13 full weeks, to Sunday 2026-12-06

# Orders the large layout completes per robot per tick, measured by flooding it with orders
# (0.00492-0.00499). Re-measure if the layout, robot speed or pick/drop times change.
CAPACITY_PER_ROBOT_PER_TICK = 0.0049
BASE_LOAD = 0.66  # average share of capacity on an ordinary weekday in early September
LOAD_LIMITS = (0.40, 0.95)
WEEKDAY_FACTOR = [1.00, 1.04, 1.03, 1.01, 0.97, 0.80, 0.66]  # Monday .. Sunday
# Weekends: a later, flatter day (people shop from late morning).
WEEKEND_PROFILE = [0.3, 0.2, 0.2, 0.2, 0.2, 0.3, 0.4, 0.6, 0.8, 1.0, 1.2, 1.3,
                   1.4, 1.4, 1.3, 1.2, 1.1, 1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4]  # fmt: skip
FAULT_RATE_RANGE = (0.3, 2.0)  # injected faults per robot per simulated hour
CLOSURE_RATE_RANGE = (0.2, 0.8)  # aisle closures per simulated hour, warehouse-wide
FLOOR_HAZARD_RATE_RANGE = (0.4, 1.6)  # dropped parcels / pallets per simulated hour
MAX_PENDING = 600  # far above any backlog, so peak-day demand is recorded in full
SPLITS = [("train", 63), ("validation", 14), ("test", 14)]  # days, in date order


def season_factor(day_index: int, days: int) -> float:
    """Autumn ramp-up: ~0.90 in early September to ~1.15 at the end of November."""
    x = min(1.0, day_index / max(days - 1, 1))
    return 0.90 + 0.25 * (x * x * (3 - 2 * x))


def split_of(day_index: int) -> str:
    end = 0
    for name, n in SPLITS:
        end += n
        if day_index < end:
            return name
    return SPLITS[-1][0]


def day_specs(args: argparse.Namespace, n_robots: int, base_config: dict) -> list[dict]:
    rng = random.Random(args.seed)
    specs = []
    for i in range(args.days):
        date = START_DATE + dt.timedelta(days=i)
        weekday = date.weekday()
        promo_name, promo = PROMOTIONS.get(date, (None, 1.0))
        load = BASE_LOAD * WEEKDAY_FACTOR[weekday] * season_factor(i, DAYS) * promo
        load = min(max(load * rng.gauss(1.0, 0.04), LOAD_LIMITS[0]), LOAD_LIMITS[1])
        specs.append(
            {
                "run_id": f"day_{date.isoformat()}",
                "seed": args.seed + i,
                "day_index": i,
                "hours": args.hours,
                "ticks_per_hour": args.ticks_per_hour,
                "status_every": args.status_every,
                "layout": args.layout,
                "target_load": round(load, 3),  # generator setting: never a model feature
                "arrival_prob": round(load * CAPACITY_PER_ROBOT_PER_TICK * n_robots, 4),
                "hourly_profile": WEEKEND_PROFILE
                if weekday >= 5
                else base_config["orders"]["hourly_profile"],
                "fault_rate": round(rng.uniform(*FAULT_RATE_RANGE), 2),
                "closure_rate": round(rng.uniform(*CLOSURE_RATE_RANGE), 2),
                "floor_hazard_rate": round(rng.uniform(*FLOOR_HAZARD_RATE_RANGE), 2),
                "calendar": {
                    "date": date.isoformat(),
                    "day_index": i,
                    "day_of_week": weekday,
                    "day_name": date.strftime("%A"),
                    "is_weekend": weekday >= 5,
                    "week_of_year": date.isocalendar().week,
                    "month": date.month,
                    "season": season_name(date),
                    "is_promo_day": promo_name is not None,
                    "promo_name": promo_name,
                    "split": split_of(i),
                },
                "dataset_version": DATASET_VERSION,
                "out_dir": str(args.out / "synthetic" / "runs"),
            }
        )
    return specs


def _typed(df: pd.DataFrame) -> pd.DataFrame:
    """Stable column types across runs (text as string, not 'object' that may be all-null)."""
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].astype("string")
    return df


def run_one(spec: dict) -> dict:
    """Simulate one day and write its tables. Executed in a worker process."""
    overrides = {
        "layout": spec["layout"],
        "ticks_per_hour": spec["ticks_per_hour"],
        "orders": {
            "arrival_prob_per_tick": spec["arrival_prob"],
            "hourly_profile": spec["hourly_profile"],
            "max_pending": MAX_PENDING,
        },
        "faults": {"enabled": True, "probability_per_hour": spec["fault_rate"]},
        "hazards": {
            "enabled": True,
            "closures_per_hour": spec["closure_rate"],
            "floor_hazards_per_hour": spec["floor_hazard_rate"],
        },
    }
    engine = SimulationEngine(seed=spec["seed"], overrides=overrides)
    recorder = Recorder(
        engine, spec["run_id"], status_every=spec["status_every"], calendar=spec["calendar"]
    )
    engine.start()
    started = time.perf_counter()
    for _ in range(spec["hours"] * spec["ticks_per_hour"]):
        engine.tick()
        recorder.after_tick()

    out = Path(spec["out_dir"]) / spec["run_id"]
    out.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, df in recorder.tables().items():
        counts[name] = len(df)
        if df.empty:
            continue
        df.insert(0, "dataset_version", spec["dataset_version"])
        if "split" not in df.columns:
            df.insert(1, "split", spec["calendar"]["split"])
        _typed(df).to_parquet(out / f"{name}.parquet", index=False)
    return {
        **{k: v for k, v in spec.items() if k not in ("out_dir", "hourly_profile")},
        "rows": counts,
        "kpis": engine.kpis.snapshot(),
        "seconds": round(time.perf_counter() - started, 1),
    }


def combine(run_dir: Path, processed: Path, run_ids: list[str]) -> dict[str, int]:
    """Stream this generation's runs (only those) into one Parquet file per table."""
    processed.mkdir(parents=True, exist_ok=True)
    totals = {}
    for name in TABLES:
        files = [run_dir / r / f"{name}.parquet" for r in sorted(run_ids)]
        files = [f for f in files if f.exists()]
        if not files:
            continue
        schema = pa.unify_schemas(
            [pq.read_schema(f) for f in files], promote_options="permissive"
        ).remove_metadata()
        total = 0
        target = processed / TABLE_DIRS[name] / f"{name}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        with pq.ParquetWriter(target, schema, compression="zstd") as w:
            for f in files:
                table = pq.read_table(f).replace_schema_metadata(None)
                table = table.select([c for c in schema.names if c in table.column_names])
                for field in schema:  # add columns a run did not have (all null there)
                    if field.name not in table.column_names:
                        table = table.append_column(field, pa.nulls(len(table), field.type))
                w.write_table(table.select(schema.names).cast(schema))
                total += len(table)
        totals[name] = total
    _add_demand_lags(processed / TABLE_DIRS["demand_hourly"] / "demand_hourly.parquet")
    return totals


def _add_demand_lags(path: Path) -> None:
    """Past-only demand features across consecutive days (hour 0 follows yesterday's hour 23)."""
    if not path.exists():
        return
    df = pd.read_parquet(path).sort_values(["date", "hour_index"]).reset_index(drop=True)
    df.insert(
        df.columns.get_loc("hour_of_day") + 1,
        "timestamp",
        pd.to_datetime(df["date"]) + pd.to_timedelta(df["hour_of_day"], unit="h"),
    )
    y = df["orders_total"]
    df["lag_1h_orders"] = y.shift(1)
    df["lag_2h_orders"] = y.shift(2)
    df["lag_24h_orders"] = y.shift(24)
    df["lag_168h_orders"] = y.shift(168)
    df["rolling_24h_mean_orders"] = y.shift(1).rolling(24).mean().round(3)
    df["lag_1h_orders_high"] = df["orders_high"].shift(1)
    df.to_parquet(path, index=False, compression="zstd")


def write_reference(processed: Path, layout_name: str, seed: int) -> dict[str, int]:
    """Layer 1 entity tables: the warehouse as data (one row per zone, aisle, bay, ...)."""
    engine = SimulationEngine(seed=seed, overrides={"layout": layout_name})
    lay = engine.layout
    inv = engine.inventory
    aisle_of = {c: a.aisle_id for a in lay.aisles for c in a.cells}
    zone_name = {z.zone_id: z.name for z in lay.zones}
    tables: dict[str, pd.DataFrame] = {
        "zones": pd.DataFrame(
            [
                {
                    "zone_id": z.zone_id,
                    "name": z.name,
                    "x_min": z.bounds[0],
                    "y_min": z.bounds[1],
                    "x_max": z.bounds[2],
                    "y_max": z.bounds[3],
                    "capacity_robots": z.capacity,
                }
                for z in lay.zones
            ]
        ),
        "aisles": pd.DataFrame(
            [
                {
                    "aisle_id": a.aisle_id,
                    "name": a.name,
                    "zone_id": a.zone_id,
                    "y": a.y,
                    "x_start": a.x_start,
                    "x_end": a.x_end,
                    "length_m": a.x_end - a.x_start + 1,
                    "direction": a.direction,
                    "width_robots": 1,
                }
                for a in lay.aisles
            ]
        ),
        "shelves": pd.DataFrame(
            [
                {
                    "shelf_id": s.shelf_id,
                    "location": s.shelf_id.removeprefix("SH-"),
                    "zone_id": s.zone_id,
                    "x": s.x,
                    "y": s.y,
                    "levels": s.levels,
                    "pick_face_x": inv.face[f"P-{s.shelf_id[3:]}"][0],
                    "pick_face_y": inv.face[f"P-{s.shelf_id[3:]}"][1],
                    "aisle_id": aisle_of.get(inv.face[f"P-{s.shelf_id[3:]}"]),
                }
                for s in lay.shelves
                if f"P-{s.shelf_id[3:]}" in inv.face
            ]
        ),
        "stations": pd.DataFrame(
            [
                {
                    "station_id": s.station_id,
                    "type": s.type,
                    "x": s.x,
                    "y": s.y,
                    "bays": s.capacity,
                }
                for s in lay.stations
            ]
        ),
        "parking_bays": pd.DataFrame(
            [
                {"area_id": a.area_id, "area_name": a.name, "x": c[0], "y": c[1]}
                for a in lay.parking_areas
                for c in a.cells
            ]
        ),
        "obstacles": pd.DataFrame(
            [
                {"obstacle_id": f"COL-{i:02d}", "type": "COLUMN", "x": x, "y": y, "permanent": True}
                for i, (x, y) in enumerate(
                    sorted(
                        (x, y)
                        for y in range(lay.grid.height)
                        for x in range(lay.grid.width)
                        if lay.grid.get(x, y).value == "#"
                    ),
                    start=1,
                )
            ]
        ),
        "products": pd.DataFrame(
            [
                {
                    "product_id": p.product_id,
                    "name": p.name,
                    "category": p.category,
                    "weight_kg": p.weight_kg,
                    "shelf_id": p.shelf_id,
                    "shelf_location": p.location,
                    "zone_id": next(s.zone_id for s in lay.shelves if s.shelf_id == p.shelf_id),
                    "initial_stock": inv.stock[p.product_id],
                    "reorder_point": 10,
                }
                for p in inv.catalog.values()
                if p.product_id in inv.face
            ]
        ),
        "robots": pd.DataFrame(
            [
                {
                    "robot_id": r.robot_id,
                    "home_x": engine.controller.home[r.robot_id][0],
                    "home_y": engine.controller.home[r.robot_id][1],
                    "home_parking_area": engine.controller.parking_area.get(
                        engine.controller.home[r.robot_id]
                    ),
                    "max_speed_m_per_s": 2.0,
                    "max_speed_cells_per_tick": r.speed,
                }
                for r in engine.robots.values()
            ]
        ),
    }
    tables["zones"]["name"] = tables["zones"]["zone_id"].map(zone_name)
    ref = processed / "reference"
    ref.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.insert(0, "dataset_version", DATASET_VERSION)
        _typed(df).to_parquet(ref / f"{name}.parquet", index=False)
    return {name: len(df) for name, df in tables.items()}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--days", type=int, default=DAYS, help="simulated days (consecutive)")
    parser.add_argument("--hours", type=int, default=24, help="simulated hours per day")
    parser.add_argument("--ticks-per-hour", type=int, default=600, help="clock compression")
    parser.add_argument("--status-every", type=int, default=2, help="telemetry every N ticks")
    parser.add_argument("--seed", type=int, default=3000, help="base seed; day i uses seed+i")
    parser.add_argument("--workers", type=int, default=0, help="processes (0 = CPU count - 1)")
    parser.add_argument("--layout", default=None, help="layout in configs/layouts")
    parser.add_argument("--out", type=Path, default=ROOT / "data")
    args = parser.parse_args()

    base_config = yaml.safe_load((CONFIG_DIR / "simulation.yaml").read_text())
    args.layout = args.layout or base_config["layout"]
    engine = SimulationEngine(overrides={"layout": args.layout})
    n_robots = len(engine.robots)
    specs = day_specs(args, n_robots, base_config)
    run_dir = args.out / "synthetic" / "runs"
    processed = args.out / "processed"

    workers = args.workers or max(1, (os.cpu_count() or 2) - 1)
    print(
        f"Simulating {args.days} day(s) x {args.hours} h "
        f"({args.hours * args.ticks_per_hour} ticks each), {workers} processes",
        flush=True,
    )
    started = time.perf_counter()
    results = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for res in pool.map(run_one, specs):
            results.append(res)
            rows = res["rows"]
            print(
                f"  {res['run_id']} load {res['target_load']:.2f}: {rows['tasks']} tasks, "
                f"{rows['hazards']} hazards ({res['seconds']} s)",
                flush=True,
            )

    totals = combine(run_dir, processed, [s["run_id"] for s in specs])
    reference = write_reference(processed, args.layout, args.seed)
    manifest = {
        "dataset_version": DATASET_VERSION,
        "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "settings": {
            "layout": args.layout,
            "robots": n_robots,
            "start_date": START_DATE.isoformat(),
            "capacity_per_robot_per_tick": CAPACITY_PER_ROBOT_PER_TICK,
            "base_load": BASE_LOAD,
            "load_limits": LOAD_LIMITS,
            "weekday_factor": WEEKDAY_FACTOR,
            "promotions": {d.isoformat(): v for d, v in PROMOTIONS.items()},
            "weekend_profile": WEEKEND_PROFILE,
            "weekday_profile": base_config["orders"]["hourly_profile"],
            "fault_rate_range": FAULT_RATE_RANGE,
            "closure_rate_range": CLOSURE_RATE_RANGE,
            "floor_hazard_rate_range": FLOOR_HAZARD_RATE_RANGE,
            "max_pending": MAX_PENDING,
            "splits": SPLITS,
        },
        "args": {k: str(v) for k, v in vars(args).items()},
        "days": results,
        "totals": totals,
        "reference": reference,
    }
    (processed / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print(f"\nDone in {time.perf_counter() - started:.0f} s. Combined tables in {processed}:")
    for name, n in {**totals, **{f"reference/{k}": v for k, v in reference.items()}}.items():
        print(f"  {name:24s} {n:>12,} rows")


if __name__ == "__main__":
    main()
