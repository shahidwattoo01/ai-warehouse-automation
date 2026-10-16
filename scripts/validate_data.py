"""Validate every dataset in data/processed/ (dataset v3) before anyone trains on it.

    python scripts/validate_data.py            # prints PASS/FAIL per check
    python scripts/validate_data.py --quick    # skip the slow checks on the 20M+ row tables

Writes data/processed/validation_report.json. Exit code 1 if any check fails.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "scripts"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

P = ROOT / "data" / "processed"
VERSION = "v3"
results: list[dict] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    results.append({"check": name, "ok": bool(ok), "detail": str(detail)})
    print(
        f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail != "" else ""),
        flush=True,
    )


def path(name: str) -> Path:
    from generate_data import TABLE_DIRS

    return P / TABLE_DIRS[name] / f"{name}.parquet"


def read(name: str, columns: list[str] | None = None) -> pd.DataFrame:
    return pd.read_parquet(path(name), columns=columns)


def simulation_tables(quick: bool) -> None:
    print("Simulation tables")
    manifest = json.loads((P / "manifest.json").read_text())
    days = manifest["days"]
    check("manifest is dataset v3", manifest["dataset_version"] == VERSION)
    tables = [
        "robot_status",
        "events",
        "orders",
        "tasks",
        "demand_hourly",
        "anomaly_windows",
        "hazards",
    ]
    check("all 7 tables exist", all(path(t).exists() for t in tables))
    for t in tables:
        v = pq.read_table(path(t), columns=["dataset_version"]).column(0)
        check(f"{t}: only {VERSION} rows", pc.all(pc.equal(v, VERSION)).as_py(), f"{len(v):,} rows")

    dates = sorted(d["calendar"]["date"] for d in days)
    start = dt.date.fromisoformat(dates[0])
    consecutive = dates == [(start + dt.timedelta(days=i)).isoformat() for i in range(len(dates))]
    check("days are consecutive dates", consecutive, f"{len(dates)} days {dates[0]} .. {dates[-1]}")

    tasks = read("tasks")
    orders = read("orders")
    check("tasks: one run_id per day", tasks["run_id"].nunique() == len(days))
    by_split = tasks.groupby("split")["date"].nunique().to_dict()
    check(
        "splits by date 63/14/14", by_split == {"train": 63, "validation": 14, "test": 14}, by_split
    )
    check("no date in two splits", tasks.groupby("date")["split"].nunique().max() == 1)
    split_order = tasks.groupby("split")["date"].agg(["min", "max"])
    check(
        "train < validation < test in time",
        split_order.loc["train", "max"] < split_order.loc["validation", "min"]
        and split_order.loc["validation", "max"] < split_order.loc["test", "min"],
    )

    # ----- tasks / orders ------------------------------------------------------------
    check(
        "tasks: times ordered",
        (
            (tasks["order_time"] <= tasks["assigned_at"])
            & (tasks["assigned_at"] < tasks["delivered_at"])
        ).all(),
    )
    merged = tasks.merge(orders[["run_id", "order_id", "deadline"]], on=["run_id", "order_id"])
    check(
        "tasks: late == delivered after deadline",
        (merged["late"] == (merged["delivered_at"] > merged["deadline"])).all(),
    )
    check(
        "tasks: route distance >= straight-line distance",
        (tasks["path_distance"] >= tasks["est_distance"]).all(),
    )
    delivered = orders["status"].isin(["DELIVERED", "LATE"]).sum()
    check("tasks == delivered orders", len(tasks) == delivered, f"{len(tasks):,} tasks")
    check("order ids unique per day", not orders.duplicated(["run_id", "order_id"]).any())
    open_share = orders["status"].isin(["PENDING", "ASSIGNED", "IN_PROGRESS"]).mean()
    check("orders still open at midnight < 5 %", open_share < 0.05, f"{open_share:.2%}")
    late = tasks["late"].mean()
    check("late share is realistic (2-30 %)", 0.02 < late < 0.30, f"{late:.1%}")
    corr = tasks[["path_distance", "duration_ticks"]].corr().iloc[0, 1]
    check("ETA signal: route distance correlates with duration", corr > 0.4, f"r = {corr:.2f}")
    leak = {"moves", "waits", "reroutes", "delivered_at", "duration_ticks", "late"}
    check("post-delivery columns present only as labels/diagnostics", leak <= set(tasks.columns))

    # ----- demand --------------------------------------------------------------------
    d = read("demand_hourly")
    check("demand: 24 complete hours per day", len(d) == 24 * len(days), f"{len(d)} rows")
    check(
        "demand: priorities add up",
        (d["orders_total"] == d[["orders_high", "orders_medium", "orders_low"]].sum(axis=1)).all(),
    )
    cat = d[[c for c in d.columns if c.startswith("lines_cat_")]].sum(axis=1)
    zone = d[[c for c in d.columns if c.startswith("lines_zone_")]].sum(axis=1)
    check("demand: category lines == zone lines", (cat == zone).all())
    gen = orders[orders["source"] == "GENERATOR"]
    per_day = gen.groupby("date").size().reindex(sorted(d["date"].unique()))
    check("demand totals match the orders table", int(d["orders_total"].sum()) == len(gen))
    planned = pd.Series({x["calendar"]["date"]: x["target_load"] for x in days}).reindex(
        per_day.index
    )
    r = np.corrcoef(planned, per_day)[0, 1]
    check("recorded demand follows planned load (not capped)", r > 0.97, f"r = {r:.3f}")
    hourly = d.groupby("hour_of_day")["orders_total"].mean()
    ratio = hourly.max() / max(hourly.min(), 1)
    check("daily rhythm: peak hour > 4x the quietest", ratio > 4, f"{ratio:.1f}x")
    dow = (
        d.groupby("day_of_week")["orders_total"].sum() / d.groupby("day_of_week")["date"].nunique()
    )
    sun = dow[6] / dow[[0, 1, 2, 3]].mean()
    check("weekly rhythm: Sunday about two thirds of a weekday", 0.6 < sun < 0.8, f"{sun:.0%}")
    first4 = per_day.iloc[:28].mean()
    last4 = per_day.iloc[-28:].mean()
    check(
        "season: last 4 weeks busier than first 4", last4 > first4 * 1.1, f"{last4 / first4:.2f}x"
    )
    ds = d.sort_values(["date", "hour_index"]).reset_index(drop=True)
    check(
        "lag features shift the past (no future values)",
        ds["lag_24h_orders"].iloc[24:].equals(ds["orders_total"].shift(24).iloc[24:].astype(float))
        and ds["lag_1h_orders"].isna().iloc[0],
    )
    promo = d[d["is_promo_day"]].groupby("date")["orders_total"].sum()
    check("promotion days present", len(promo) == 3, list(promo.index))

    # ----- anomaly windows -----------------------------------------------------------
    a = read("anomaly_windows")
    check(
        "anomaly: flag agrees with fault type",
        ((a["fault_type"] != "none") == (a["is_anomaly"] == 1)).all(),
    )
    share = a["is_anomaly"].mean()
    check("anomaly share 5-30 %", 0.05 < share < 0.30, f"{share:.1%}")
    types = set(a["fault_type"]) - {"none"}
    check("all 5 fault types labelled", len(types) == 5, sorted(types))
    hot = a.loc[a["fault_type"] == "overheating", "temperature_max"].mean()
    normal = a.loc[a["fault_type"] == "none", "temperature_max"].mean()
    check("overheating windows run hotter", hot > normal + 10, f"{hot:.1f} vs {normal:.1f} C")
    slow = a.loc[a["fault_type"] == "speed_degradation", "move_rate_when_busy"].mean()
    ok_speed = a.loc[a["fault_type"] == "none", "move_rate_when_busy"].mean()
    check(
        "speed-degradation windows move slower",
        slow < ok_speed * 0.8,
        f"{slow:.2f} vs {ok_speed:.2f}",
    )
    spike = a.loc[a["fault_type"] == "battery_spike", "battery_min_step"].mean()
    check("battery-spike windows show a battery drop", spike < -5, f"{spike:.1f} %")

    # ----- hazards -------------------------------------------------------------------
    h = read("hazards")
    aisles = set(pd.read_parquet(P / "reference" / "aisles.parquet")["aisle_id"])
    closures = h[h["kind"] == "AISLE_CLOSURE"]
    check(
        "hazards: closures name real aisles",
        set(closures["aisle_id"]) <= aisles,
        f"{len(closures)} closures",
    )
    ended = h.dropna(subset=["end_tick"])
    check(
        "hazards: end after start",
        (ended["end_tick"] >= ended["start_tick"]).all(),
        f"{len(h)} hazards",
    )
    check(
        "hazards: all three kinds occur", set(h["kind"]) == {"AISLE_CLOSURE", "PACKAGE", "DEBRIS"}
    )

    # ----- robot status / events (large) --------------------------------------------
    rs = pq.read_table(path("robot_status"), columns=["battery", "temperature", "x", "y"])
    mm = {c: pc.min_max(rs.column(c)).as_py() for c in rs.column_names}
    check(
        "telemetry: battery within 0-100",
        mm["battery"]["min"] >= 0 and mm["battery"]["max"] <= 100,
        mm["battery"],
    )
    check(
        "telemetry: temperature plausible",
        15 < mm["temperature"]["min"] and mm["temperature"]["max"] < 120,
        mm["temperature"],
    )
    check(
        "telemetry: positions on the grid",
        mm["x"]["min"] >= 0 and mm["x"]["max"] < 80 and mm["y"]["min"] >= 0 and mm["y"]["max"] < 50,
    )
    del rs
    if not quick:
        sample = pq.read_table(
            path("robot_status"),
            columns=["run_id", "tick", "x", "y"],
            filters=[("run_id", "in", [days[i]["run_id"] for i in (0, 45, 90)])],
        ).to_pandas()
        check(
            "no two robots in one cell at the same tick (3 days)",
            not sample.duplicated(["run_id", "tick", "x", "y"]).any(),
            f"{len(sample):,} rows",
        )
        delivered_events = Counter()
        f = pq.ParquetFile(path("events"))
        for batch in f.iter_batches(columns=["type"], batch_size=2_000_000):
            for x in pc.value_counts(batch.column(0)).to_pylist():
                delivered_events[x["values"]] += x["counts"]
        check(
            "events: one ORDER_DELIVERED per task",
            delivered_events["ORDER_DELIVERED"] == len(tasks),
            f"{delivered_events['ORDER_DELIVERED']:,}",
        )
        check(
            "events: closures and hazards logged",
            delivered_events["AISLE_CLOSED"] == len(closures)
            and delivered_events["HAZARD_DETECTED"] == len(h) - len(closures),
        )


def reference_tables() -> None:
    print("Reference tables (Layer 1 entities)")
    r = {
        n: pd.read_parquet(P / "reference" / f"{n}.parquet")
        for n in (
            "zones",
            "aisles",
            "shelves",
            "stations",
            "parking_bays",
            "obstacles",
            "products",
            "robots",
        )
    }
    sizes = {k: len(v) for k, v in r.items()}
    expected = {
        "zones": 5,
        "aisles": 52,
        "shelves": 1584,
        "stations": 10,
        "parking_bays": 88,
        "obstacles": 4,
        "products": 1584,
        "robots": 40,
    }
    check("reference row counts", sizes == expected, sizes)
    check(
        "products: unique ids, all on a shelf",
        r["products"]["product_id"].is_unique
        and set(r["products"]["shelf_id"]) <= set(r["shelves"]["shelf_id"]),
    )
    check(
        "shelves: every pick face in an aisle or on a highway",
        r["shelves"]["pick_face_y"].notna().all(),
    )


def text_datasets() -> None:
    print("NLP / tool calling")
    rows = [json.loads(x) for x in (P / "nlp" / "commands.jsonl").open(encoding="utf-8")]
    spans = all(r["text"][e["start"] : e["end"]] == e["text"] for r in rows for e in r["entities"])
    check("commands: entity spans exact", spans, f"{len(rows):,} commands")
    test_t = {r["template_id"] for r in rows if r["split"] == "test"}
    train_t = {r["template_id"] for r in rows if r["split"] != "test"}
    check("commands: test phrasings unseen in training", not test_t & train_t)
    intents = {
        s: {r["intent"] for r in rows if r["split"] == s} for s in ("train", "validation", "test")
    }
    check(
        "commands: every intent in every split", len({frozenset(v) for v in intents.values()}) == 1
    )
    tools = {t["name"] for t in json.loads((P / "agents" / "tools.json").read_text())}
    used = {c["name"] for r in rows for c in r["tool_calls"]}
    check("commands: tool calls use catalogue tools", used <= tools, f"{len(tools)} tools")

    print("RAG")
    sections = {
        f"{s['doc_id']}#{s['section_id']}"
        for s in map(json.loads, (P / "rag" / "sections.jsonl").open(encoding="utf-8"))
    }
    qs = [json.loads(x) for x in (P / "rag" / "questions.jsonl").open(encoding="utf-8")]
    check(
        "rag: questions cite existing sections",
        all(s in sections for q in qs for s in q["sources"]),
        f"{len(qs)} questions, {len(sections)} sections",
    )
    pdfs = list((ROOT / "data" / "documents" / "pdf").glob("*.pdf"))
    check("rag: 6 source PDFs", len(pdfs) == 6)

    print("Agents")
    from simulation.environment.engine import SimulationEngine

    sys.path.insert(0, str(ROOT / "scripts"))
    from generate_agent_scenarios import fingerprint

    scen = [json.loads(x) for x in (P / "agents" / "scenarios.jsonl").open(encoding="utf-8")]
    check(
        "agents: scenarios present",
        len(scen) >= 80,
        f"{len(scen)} scenarios, {len({s['type'] for s in scen})} types",
    )
    replay = next(s for s in scen if s["replay"])
    eng = SimulationEngine(seed=replay["replay"]["seed"], overrides=replay["replay"]["overrides"])
    eng.start()
    for _ in range(replay["replay"]["ticks"]):
        eng.tick()
    check(
        "agents: replay reproduces the scenario state",
        fingerprint(eng) == replay["replay"]["fingerprint"],
    )


def vision_dataset() -> None:
    print("Vision")
    v = P / "computer_vision"
    if not (v / "frames.csv").exists():
        check("vision: dataset present", False, "run scripts/capture_frames.py")
        return
    frames = pd.read_csv(v / "frames.csv")
    check(
        "vision: every frame has image and label file",
        all(
            (v / "images" / r.split / f"{r.frame}.png").exists()
            and (v / "labels" / r.split / f"{r.frame}.txt").exists()
            for r in frames.itertuples()
        ),
        f"{len(frames):,} frames",
    )
    seeds = frames.groupby("split")["seed"].apply(set)
    check(
        "vision: splits use different seeds",
        not (seeds["train"] & seeds["test"]) and not (seeds["train"] & seeds["validation"]),
    )
    bad = 0
    for lab in (v / "labels").rglob("*.txt"):
        for line in lab.read_text().splitlines():
            c, *box = line.split()
            vals = [float(x) for x in box]
            bad += not (0 <= int(c) <= 5 and all(0 <= x <= 1 for x in vals))
    check("vision: YOLO labels valid", bad == 0, f"{bad} bad lines")
    counts = {
        c: int(frames[f"n_{c}"].sum())
        for c in ("robot", "worker", "shelf", "package", "obstacle", "blocked_path")
    }
    check("vision: every class annotated", all(n > 50 for n in counts.values()), counts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    simulation_tables(args.quick)
    reference_tables()
    text_datasets()
    vision_dataset()
    failed = [r for r in results if not r["ok"]]
    (P / "validation_report.json").write_text(
        json.dumps(
            {
                "dataset_version": VERSION,
                "checks": len(results),
                "failed": len(failed),
                "results": results,
            },
            indent=2,
        )
    )
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
