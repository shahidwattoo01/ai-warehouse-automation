"""Run the Phase 4 optimisation experiments and write a report.

    python scripts/run_experiments.py                       # E1 E2 E3 E4 E4b E5, 5 seeds x 24 h
    python scripts/run_experiments.py --experiments E2 E4 --seeds 2 --hours 6   # quick check

Each experiment (configs/experiments/<id>.yaml) is a set of strategies. Every experiment runs the
same seeds with `independent_streams`, so all of them receive exactly the same orders, faults and
hazards: any difference in the results comes from the strategies (a paired comparison). Each run
uses the live Phase 3 models (ai/classical_ml/live_predictor.py) and the Phase 4 Optimizer.

Writes evaluation/reports/phase4/:
    runs.csv        one row per (experiment, seed) with every KPI
    summary.csv     mean and standard deviation per experiment
    vs_baseline.csv per experiment and KPI: change vs E2 on the same seeds, seeds improved
    report.md       the tables above, readable
    figures/*.png   bar charts with the spread across seeds
    manifest.json   settings, versions and timing
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPERIMENTS_DIR = ROOT / "configs" / "experiments"
OUT = ROOT / "evaluation" / "reports" / "phase4"
PHASE4 = ["E1", "E2", "E3", "E4", "E4b", "E5"]
BASELINE = "E2"
# KPI -> True if lower is better
KPIS = {
    "avg_completion_ticks": True,
    "p90_completion_ticks": True,
    "late_percent": True,
    "throughput_per_hour": False,
    "avg_queue_ticks": True,
    "distance_per_order_m": True,
    "blocked_events": True,
    "avg_pending": True,
    "utilisation_percent": True,
}
LABELS = {
    "avg_completion_ticks": "Avg completion (ticks)",
    "p90_completion_ticks": "90th pct completion (ticks)",
    "late_percent": "Late orders (%)",
    "throughput_per_hour": "Throughput (orders/h)",
    "avg_queue_ticks": "Avg wait for a robot (ticks)",
    "distance_per_order_m": "Distance per order (m)",
    "blocked_events": "Standoffs (side-steps)",
    "avg_pending": "Avg orders waiting",
    "utilisation_percent": "Fleet utilisation (%)",
}


def load_experiment(eid: str) -> dict:
    return yaml.safe_load((EXPERIMENTS_DIR / f"{eid}.yaml").read_text(encoding="utf-8"))


def run_one(job: dict) -> dict:
    """One experiment on one seed (executed in a worker process)."""
    from ai.classical_ml.live_predictor import Predictor
    from ai.optimization.optimizer import Optimizer
    from evaluation.simulation.metrics import RunMetrics
    from simulation.environment.engine import SimulationEngine

    engine = SimulationEngine(
        seed=job["seed"],
        overrides={"layout": job["layout"], "independent_streams": job["independent_streams"]},
    )
    predictor = Predictor()
    predictor.attach(engine)
    optimizer = Optimizer(engine, predictor, job["strategies"])
    metrics = RunMetrics(engine)
    engine.start()
    started = time.perf_counter()
    for _ in range(job["hours"] * engine.config.get("ticks_per_hour", 600)):
        engine.tick()
        predictor.after_tick()
        predictor.drain()  # records are for the database; not needed here
        optimizer.after_tick()
        metrics.after_tick()
    return {
        "experiment": job["experiment"],
        "seed": job["seed"],
        **metrics.summary(),
        "seconds": round(time.perf_counter() - started, 1),
    }


def compare(runs: pd.DataFrame) -> pd.DataFrame:
    """Paired change vs the baseline experiment on the same seeds."""
    base = runs[runs["experiment"] == BASELINE].set_index("seed")
    rows = []
    for eid, group in runs.groupby("experiment", sort=False):
        if eid == BASELINE:
            continue
        g = group.set_index("seed").loc[base.index]
        for kpi, lower_better in KPIS.items():
            diff = g[kpi] - base[kpi]
            better = (diff < 0) if lower_better else (diff > 0)
            base_mean = base[kpi].mean()
            rows.append(
                {
                    "experiment": eid,
                    "kpi": kpi,
                    "baseline_mean": round(base_mean, 2),
                    "experiment_mean": round(g[kpi].mean(), 2),
                    "change": round(diff.mean(), 2),
                    "change_percent": round(100 * diff.mean() / base_mean, 1)
                    if base_mean
                    else None,
                    "seeds_improved": f"{int(better.sum())}/{len(diff)}",
                }
            )
    return pd.DataFrame(rows)


def figures(summary: pd.DataFrame, names: dict, out: Path) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out.mkdir(parents=True, exist_ok=True)
    files = []
    order = list(summary.index)
    charted = [
        "avg_completion_ticks",
        "late_percent",
        "throughput_per_hour",
        "distance_per_order_m",
        "avg_queue_ticks",
        "blocked_events",
    ]
    for kpi in charted:
        fig, ax = plt.subplots(figsize=(8, 3.6))
        means, stds = summary[(kpi, "mean")], summary[(kpi, "std")]
        colors = ["#9AA5B1" if e == BASELINE else "#2F6FE0" for e in order]
        ax.bar(range(len(order)), means, yerr=stds, color=colors, capsize=4)
        ax.set_xticks(range(len(order)), [f"{e}\n{names[e]}" for e in order], fontsize=7)
        ax.set_title(f"{LABELS[kpi]} — mean over seeds (bars: spread)")
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        path = out / f"{kpi}.png"
        fig.savefig(path, dpi=130)
        plt.close(fig)
        files.append(path.name)
    return files


def write_report(
    runs: pd.DataFrame, summary: pd.DataFrame, versus: pd.DataFrame, names: dict, meta: dict
) -> str:
    lines = [
        "# Phase 4 optimisation experiments",
        "",
        f"Generated {meta['created_utc']} · {meta['seeds']} seeds × {meta['hours']} simulated "
        f"hours per experiment · layout `{meta['layout']}` · identical orders, faults and "
        "hazards in every experiment.",
        "",
        "## Experiments",
        "",
        "| ID | Name | Strategies |",
        "|---|---|---|",
    ]
    for eid in summary.index:
        s = meta["experiments"][eid]["strategies"]
        lines.append(
            f"| {eid} | {names[eid]} | " + ", ".join(f"{k}={v}" for k, v in s.items()) + " |"
        )
    lines += ["", "## Results (mean ± standard deviation over seeds)", ""]
    header = "| Experiment | " + " | ".join(LABELS[k] for k in KPIS) + " |"
    lines += [header, "|" + "---|" * (len(KPIS) + 1)]
    for eid in summary.index:
        cells = [
            f"{summary.loc[eid, (k, 'mean')]:.1f} ± {summary.loc[eid, (k, 'std')]:.1f}"
            for k in KPIS
        ]
        lines.append(f"| {eid} {names[eid]} | " + " | ".join(cells) + " |")
    lines += ["", f"## Change vs {BASELINE} (paired on the same seeds)", ""]
    lines += ["| Experiment | KPI | Baseline | Experiment | Change | Change % | Seeds improved |",
              "|---|---|---|---|---|---|---|"]  # fmt: skip
    for r in versus.itertuples():
        lines.append(
            f"| {r.experiment} | {LABELS[r.kpi]} | {r.baseline_mean} | {r.experiment_mean} | "
            f"{r.change:+} | {'—' if pd.isna(r.change_percent) else f'{r.change_percent:+}%'} | "
            f"{r.seeds_improved} |"
        )
    lines += ["", "Figures: `figures/*.png`. Raw runs: `runs.csv`.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--experiments", nargs="+", default=PHASE4)
    parser.add_argument("--seeds", type=int, default=None, help="use only the first N seeds")
    parser.add_argument("--hours", type=int, default=None, help="override simulated hours per run")
    parser.add_argument("--workers", type=int, default=0, help="processes (0 = CPU count - 1)")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument(
        "--add",
        action="store_true",
        help="add these experiments to the existing results instead of starting over",
    )
    args = parser.parse_args()

    previous = pd.DataFrame()
    if args.add and (args.out / "runs.csv").exists():
        previous = pd.read_csv(args.out / "runs.csv")
        previous = previous[~previous["experiment"].isin(args.experiments)]
    if BASELINE not in args.experiments and BASELINE not in set(previous.get("experiment", [])):
        args.experiments.insert(0, BASELINE)
    configs = {eid: load_experiment(eid) for eid in args.experiments}
    jobs = []
    for eid, cfg in configs.items():
        seeds = cfg["seeds"][: args.seeds] if args.seeds else cfg["seeds"]
        for seed in seeds:
            jobs.append(
                {
                    "experiment": eid,
                    "seed": seed,
                    "layout": cfg["layout"],
                    "hours": args.hours or cfg["hours"],
                    "independent_streams": cfg.get("independent_streams", True),
                    "strategies": cfg["strategies"],
                }
            )
    workers = args.workers or max(1, (os.cpu_count() or 2) - 1)
    print(f"{len(jobs)} runs ({len(configs)} experiments), {workers} processes", flush=True)
    started = time.perf_counter()
    results = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for res in pool.map(run_one, jobs):
            results.append(res)
            print(
                f"  {res['experiment']:4s} seed {res['seed']}: "
                f"avg completion {res['avg_completion_ticks']} "
                f"late {res['late_percent']}% ({res['seconds']} s)",
                flush=True,
            )

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    runs = pd.concat([previous, pd.DataFrame(results)], ignore_index=True)
    kept = list(dict.fromkeys(previous["experiment"])) if len(previous) else []
    order = [e for e in kept + args.experiments if e in set(runs["experiment"])]
    order = list(dict.fromkeys(order))
    configs.update({e: load_experiment(e) for e in order if e not in configs})
    summary = runs.groupby("experiment")[list(KPIS)].agg(["mean", "std"]).reindex(order).round(2)
    versus = compare(runs)
    names = {eid: configs[eid]["name"] for eid in order}
    meta = {
        "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "layout": jobs[0]["layout"],
        "seeds": int(runs["seed"].nunique()),
        "hours": jobs[0]["hours"],
        "baseline": BASELINE,
        "experiments": {
            eid: {"name": names[eid], "strategies": configs[eid]["strategies"]} for eid in order
        },
        "models": sorted(p.name for p in (ROOT / "models").glob("*.joblib")),
        "seconds": round(time.perf_counter() - started),
    }
    runs.to_csv(out / "runs.csv", index=False)
    summary.to_csv(out / "summary.csv")
    versus.to_csv(out / "vs_baseline.csv", index=False)
    meta["figures"] = figures(summary, names, out / "figures")
    (out / "report.md").write_text(
        write_report(runs, summary, versus, names, meta), encoding="utf-8"
    )
    (out / "manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"\nDone in {meta['seconds']} s. Report: {out / 'report.md'}")


if __name__ == "__main__":
    main()
