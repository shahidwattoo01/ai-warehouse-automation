"""Run the Phase 9 multi-agent + RL experiments and write a report.

    python scripts/run_experiments_phase9.py                    # E4d E9a E9b E9c E9d, 5 seeds x 24 h
    python scripts/run_experiments_phase9.py --seeds 1 --hours 2  # quick smoke test

Each E9x config enables a Phase 9 feature on top of E4d (global Hungarian + BFS):
  E9a  Batch picking (PR-03) + space-time traffic (PR-04)
  E9b  E9a + tighter physics (PR-05)
  E9c  E9b + demand-driven slotting (PR-10)
  E9d  E9c + MARL navigation policy (trained DQN; falls back to A* if weights absent)

Writes evaluation/reports/phase9/:
    runs.csv        one row per (experiment, seed) with every KPI
    summary.csv     mean and standard deviation per experiment
    vs_baseline.csv change vs E4d on the same seeds, seeds improved
    report.md       the tables above, readable
    figures/*.png   bar charts
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
OUT = ROOT / "evaluation" / "reports" / "phase9"
PHASE9 = ["E4d", "E9a", "E9b", "E9c", "E9d"]
BASELINE = "E4d"

# KPI → True if lower is better
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
    "batch_fill_rate": False,   # Phase 9 — higher is better (tote efficiency)
    "slotting_swaps": False,    # Phase 9 — counts profitable face swaps
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
    "batch_fill_rate": "Batch fill rate",
    "slotting_swaps": "Slotting swaps",
}


def load_experiment(eid: str) -> dict:
    return yaml.safe_load((EXPERIMENTS_DIR / f"{eid}.yaml").read_text(encoding="utf-8"))


def run_one(job: dict) -> dict:
    """One experiment × one seed (executed in a worker process)."""
    from ai.classical_ml.live_predictor import Predictor
    from ai.optimization.optimizer import Optimizer
    from evaluation.simulation.metrics import RunMetrics
    from simulation.environment.engine import SimulationEngine

    # Build overrides: base keys + Phase 9 subsystem configs
    overrides: dict = {
        "layout": job["layout"],
        "independent_streams": job["independent_streams"],
    }
    for key in ("batch_picking", "space_time", "physics", "slotting"):
        if key in job:
            overrides[key] = job[key]

    # E9d uses planner: marl — fall back to astar if the planner or weights are unavailable
    strategies = dict(job["strategies"])
    if strategies.get("planner") == "marl":
        weights_path = ROOT / job.get("marl_weights", "models/navigation_marl/marl_ep300/weights.pt")
        if not weights_path.exists():
            strategies["planner"] = "astar"
            job = {**job, "_marl_fallback": True}

    engine = SimulationEngine(seed=job["seed"], overrides=overrides)
    predictor = Predictor()
    predictor.attach(engine)
    optimizer = Optimizer(engine, predictor, strategies)
    metrics = RunMetrics(engine)

    # Track batch fill rate via dispatcher
    dispatcher = engine.dispatcher
    _batch_trips: list[int] = []  # items per trip

    if getattr(dispatcher, "_batch_enabled", False):
        _orig_start_batch = getattr(engine.controller, "start_batch", None)
        if _orig_start_batch is not None:
            def _patched_start_batch(batch, robot, _orig=_orig_start_batch):
                _batch_trips.append(len(batch))
                return _orig(batch, robot)
            engine.controller.start_batch = _patched_start_batch

    engine.start()
    started = time.perf_counter()
    for _ in range(job["hours"] * engine.config.get("ticks_per_hour", 600)):
        engine.tick()
        predictor.after_tick()
        predictor.drain()
        optimizer.after_tick()
        metrics.after_tick()

    result = {
        "experiment": job["experiment"],
        "seed": job["seed"],
        **metrics.summary(),
        "seconds": round(time.perf_counter() - started, 1),
        "marl_fallback": job.get("_marl_fallback", False),
    }

    # Batch fill rate: mean items per trip / tote capacity
    if _batch_trips:
        tote_cap = job.get("batch_picking", {}).get("tote_capacity", 3)
        result["batch_fill_rate"] = round(sum(_batch_trips) / (len(_batch_trips) * tote_cap), 3)
    else:
        result["batch_fill_rate"] = None

    # Slotting swaps: accessed from SlottingOptimiser's internal counter if present
    slot = getattr(engine, "slotting", None)
    result["slotting_swaps"] = getattr(slot, "_total_swaps", None)

    # MARL metrics (only meaningful when the MARL planner actually ran)
    marl_svc = getattr(engine, "_marl", None)
    if marl_svc is not None:
        hist = getattr(marl_svc, "_training_history", [])
        if hist:
            result["rl_mean_reward"] = round(sum(h["mean_reward"] for h in hist) / len(hist), 3)
            result["rl_orders_per_episode"] = round(
                sum(h.get("mean_deliveries", 0) for h in hist) / len(hist), 1
            )
        else:
            result["rl_mean_reward"] = None
            result["rl_orders_per_episode"] = None
    else:
        result["rl_mean_reward"] = None
        result["rl_orders_per_episode"] = None

    return result


def compare(runs: pd.DataFrame) -> pd.DataFrame:
    base = runs[runs["experiment"] == BASELINE].set_index("seed")
    rows = []
    for eid, group in runs.groupby("experiment", sort=False):
        if eid == BASELINE:
            continue
        g = group.set_index("seed").reindex(base.index)
        for kpi, lower_better in KPIS.items():
            if kpi not in g.columns or kpi not in base.columns:
                continue
            g_vals = g[kpi]
            b_vals = base[kpi]
            # Skip KPIs that are entirely None for this experiment
            if g_vals.isna().all() or b_vals.isna().all():
                continue
            diff = g_vals - b_vals
            better = (diff < 0) if lower_better else (diff > 0)
            base_mean = b_vals.mean()
            rows.append(
                {
                    "experiment": eid,
                    "kpi": kpi,
                    "baseline_mean": round(base_mean, 2),
                    "experiment_mean": round(g_vals.mean(), 2),
                    "change": round(diff.mean(), 2),
                    "change_percent": round(100 * diff.mean() / base_mean, 1)
                    if base_mean
                    else None,
                    "seeds_improved": f"{int(better.sum())}/{int(better.notna().sum())}",
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
        "batch_fill_rate",
    ]
    for kpi in charted:
        if (kpi, "mean") not in summary.columns:
            continue
        means = summary[(kpi, "mean")]
        stds = summary[(kpi, "std")]
        if means.isna().all():
            continue
        fig, ax = plt.subplots(figsize=(8, 3.6))
        colors = ["#9AA5B1" if e == BASELINE else "#2F6FE0" for e in order]
        ax.bar(range(len(order)), means, yerr=stds, color=colors, capsize=4)
        ax.set_xticks(range(len(order)), [f"{e}\n{names.get(e, e)}" for e in order], fontsize=7)
        ax.set_title(f"{LABELS.get(kpi, kpi)} — mean over seeds (bars: spread)")
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
    kpis_present = [k for k in KPIS if (k, "mean") in summary.columns
                    and not summary[(k, "mean")].isna().all()]
    lines = [
        "# Phase 9 multi-agent + RL experiments",
        "",
        f"Generated {meta['created_utc']} · {meta['seeds']} seeds × {meta['hours']} simulated "
        f"hours per experiment · layout `{meta['layout']}` · identical orders, faults and "
        "hazards in every experiment (independent streams).",
        "",
        "Baseline: **E4d** (global Hungarian assignment + BFS planner, Phase 4 best).",
        "",
        "## Experiments",
        "",
        "| ID | Name | Key settings |",
        "|---|---|---|",
    ]
    for eid in summary.index:
        exp = meta["experiments"].get(eid, {})
        s = exp.get("strategies", {})
        extras = []
        for k in ("batch_picking", "space_time", "physics", "slotting"):
            v = exp.get(k, {})
            if v.get("enabled"):
                extras.append(k)
        note = ", ".join(f"{k}={v}" for k, v in s.items())
        if extras:
            note += " | " + " + ".join(extras)
        lines.append(f"| {eid} | {names.get(eid, eid)} | {note} |")

    lines += ["", "## Results (mean ± standard deviation over seeds)", ""]
    header = "| Experiment | " + " | ".join(LABELS.get(k, k) for k in kpis_present) + " |"
    lines += [header, "|" + "---|" * (len(kpis_present) + 1)]
    for eid in summary.index:
        cells = []
        for k in kpis_present:
            m = summary.loc[eid, (k, "mean")]
            s = summary.loc[eid, (k, "std")]
            cells.append("—" if pd.isna(m) else f"{m:.1f} ± {s:.1f}")
        lines.append(f"| {eid} {names.get(eid, eid)} | " + " | ".join(cells) + " |")

    lines += ["", f"## Change vs {BASELINE} (paired on the same seeds)", ""]
    if len(versus):
        lines += [
            "| Experiment | KPI | Baseline | Experiment | Change | Change % | Seeds improved |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in versus.itertuples():
            lines.append(
                f"| {r.experiment} | {LABELS.get(r.kpi, r.kpi)} | {r.baseline_mean} | "
                f"{r.experiment_mean} | {r.change:+} | "
                f"{'—' if pd.isna(r.change_percent) else f'{r.change_percent:+}%'} | "
                f"{r.seeds_improved} |"
            )

    # Note MARL fallback runs
    fallbacks = runs[runs.get("marl_fallback", False) == True]["experiment"].unique() if "marl_fallback" in runs.columns else []  # noqa: E712
    if len(fallbacks):
        lines += ["", f"> **Note**: {', '.join(fallbacks)} ran with A\\* planner because MARL weights were absent."]

    lines += ["", "Figures: `figures/*.png`. Raw runs: `runs.csv`.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--experiments", nargs="+", default=PHASE9)
    parser.add_argument("--seeds", type=int, default=None, help="use only the first N seeds")
    parser.add_argument("--hours", type=int, default=None, help="override simulated hours per run")
    parser.add_argument("--workers", type=int, default=0, help="processes (0 = CPU count - 1)")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument(
        "--add",
        action="store_true",
        help="add these experiments to existing results instead of starting over",
    )
    args = parser.parse_args()

    previous = pd.DataFrame()
    if args.add and (args.out / "runs.csv").exists():
        previous = pd.read_csv(args.out / "runs.csv")
        previous = previous[~previous["experiment"].isin(args.experiments)]

    if BASELINE not in args.experiments and BASELINE not in set(previous.get("experiment", [])):
        args.experiments = [BASELINE] + list(args.experiments)

    configs = {eid: load_experiment(eid) for eid in args.experiments}
    jobs = []
    for eid, cfg in configs.items():
        seeds = cfg["seeds"][: args.seeds] if args.seeds else cfg["seeds"]
        for seed in seeds:
            job: dict = {
                "experiment": eid,
                "seed": seed,
                "layout": cfg["layout"],
                "hours": args.hours or cfg["hours"],
                "independent_streams": cfg.get("independent_streams", True),
                "strategies": cfg["strategies"],
            }
            for key in ("batch_picking", "space_time", "physics", "slotting"):
                if key in cfg:
                    job[key] = cfg[key]
            if "marl_weights" in cfg:
                job["marl_weights"] = cfg["marl_weights"]
            jobs.append(job)

    workers = args.workers or max(1, (os.cpu_count() or 2) - 1)
    print(f"{len(jobs)} runs ({len(configs)} experiments), {workers} processes", flush=True)
    started = time.perf_counter()
    results = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for res in pool.map(run_one, jobs):
            results.append(res)
            fallback = " [A* fallback]" if res.get("marl_fallback") else ""
            print(
                f"  {res['experiment']:4s}{fallback} seed {res['seed']}: "
                f"avg completion {res['avg_completion_ticks']} "
                f"late {res['late_percent']}% ({res['seconds']} s)",
                flush=True,
            )

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    runs = pd.concat([previous, pd.DataFrame(results)], ignore_index=True)
    kept = list(dict.fromkeys(previous.get("experiment", []))) if len(previous) else []
    order = list(dict.fromkeys(kept + args.experiments))
    order = [e for e in order if e in set(runs["experiment"])]
    configs.update({e: load_experiment(e) for e in order if e not in configs})

    kpi_cols = [k for k in KPIS if k in runs.columns]
    summary = runs.groupby("experiment")[kpi_cols].agg(["mean", "std"]).reindex(order).round(2)
    versus = compare(runs)
    names = {eid: configs[eid]["name"] for eid in order}

    # Build experiment metadata including Phase 9 subsystem configs
    exp_meta: dict = {}
    for eid in order:
        cfg = configs[eid]
        entry: dict = {"name": names[eid], "strategies": cfg["strategies"]}
        for k in ("batch_picking", "space_time", "physics", "slotting"):
            if k in cfg:
                entry[k] = cfg[k]
        exp_meta[eid] = entry

    meta = {
        "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "layout": jobs[0]["layout"],
        "seeds": int(runs["seed"].nunique()),
        "hours": jobs[0]["hours"],
        "baseline": BASELINE,
        "experiments": exp_meta,
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
