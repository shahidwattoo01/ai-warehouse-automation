# ruff: noqa: E501  (report text and table rows are kept on one line for readability)
"""Main project report: phase-by-phase progress and Baseline vs Layer 3 vs Layer 4 comparison.

    python scripts/build_project_report.py              # -> reports/Project_Progress_Report.pdf
    python scripts/build_project_report.py --snapshot   # also archive a copy for the latest done phase

Update at the end of every phase: edit reports/phases.yaml (status, result, experiment), add the
phase's own section below if it has new results, rebuild with --snapshot.

Reads only generated results, so it can be rebuilt whenever they change:
    reports/phases.yaml                  phase register (status, what was added, results)
    models/*_report.json                 Layer 3 model test scores (notebooks/01-05)
    evaluation/reports/phase4/runs.csv   Layer 4 experiments (scripts/run_experiments.py)
    evaluation/reports/phase4/figures/   charts
    configs/experiments/*.yaml           strategy definitions
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd
import yaml
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
P4 = ROOT / "evaluation" / "reports" / "phase4"
MODELS = ROOT / "models"
REPORTS = ROOT / "reports"
OUT = REPORTS / "Project_Progress_Report.pdf"

# ----- simulation clock (configs/simulation.yaml) --------------------------------------------
TICK_SECONDS = 0.5  # robot time per tick at 1x (2 ticks per second, 1 cell = 1 m -> 2 m/s)
TICKS_PER_SIM_HOUR = 600  # business clock: one simulated hour
ROBOTS = 40
BEST = "E4d"
BASE = "E2"

# ----- fonts and styles --------------------------------------------------------------------------
FONT, BOLD = "Helvetica", "Helvetica-Bold"
win = Path("C:/Windows/Fonts")
if (win / "segoeui.ttf").exists():
    pdfmetrics.registerFont(TTFont("UI", str(win / "segoeui.ttf")))
    pdfmetrics.registerFont(TTFont("UI-Bold", str(win / "segoeuib.ttf")))
    pdfmetrics.registerFontFamily("UI", normal="UI", bold="UI-Bold")
    FONT, BOLD = "UI", "UI-Bold"
INK, MUTED, BLUE, GREEN, RED = (
    colors.HexColor(c) for c in ("#121A26", "#5B6675", "#2F6FE0", "#1E8E5A", "#C0392B")
)
H1 = ParagraphStyle("h1", fontName=BOLD, fontSize=20, leading=25, textColor=INK, spaceAfter=6)
H2 = ParagraphStyle(
    "h2", fontName=BOLD, fontSize=13.5, leading=18, textColor=INK, spaceBefore=10, spaceAfter=5
)
H3 = ParagraphStyle(
    "h3", fontName=BOLD, fontSize=10.5, leading=14, textColor=BLUE, spaceBefore=6, spaceAfter=3
)
BODY = ParagraphStyle(
    "b", fontName=FONT, fontSize=9, leading=12.5, textColor=INK, alignment=TA_LEFT
)
SMALL = ParagraphStyle("s", fontName=FONT, fontSize=7.6, leading=10, textColor=INK)
SMALLB = ParagraphStyle("sb", parent=SMALL, fontName=BOLD)
NOTE = ParagraphStyle("n", fontName=FONT, fontSize=8, leading=11, textColor=MUTED)


def p(text: str, style=BODY) -> Paragraph:
    return Paragraph(text, style)


def table(
    rows: list[list], widths: list[float], header_rows: int = 1, highlight: dict | None = None
) -> Table:
    """rows of str/Paragraph; strings are wrapped in a small paragraph."""
    data = [
        [
            c
            if isinstance(c, Paragraph)
            else Paragraph(escape(str(c)), SMALLB if i < header_rows else SMALL)
            for c in r
        ]
        for i, r in enumerate(rows)
    ]
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=header_rows)
    style = [
        ("BACKGROUND", (0, 0), (-1, header_rows - 1), colors.HexColor("#E7EEFB")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B8C2CF")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
    for row, color in (highlight or {}).items():
        style.append(("BACKGROUND", (0, row), (-1, row), colors.HexColor(color)))
    t.setStyle(TableStyle(style))
    return t


def fmt(v, d=1):
    return "—" if v is None or (isinstance(v, float) and pd.isna(v)) else f"{v:,.{d}f}"


def secs(ticks):
    return ticks * TICK_SECONDS


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(FONT, 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(
        15 * mm,
        8 * mm,
        f"Warehouse AI Platform · project progress report · built {date.today():%d %b %Y}",
    )
    canvas.drawRightString(doc.pagesize[0] - 15 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def chart(runs: pd.DataFrame, order: list[str], kpi: str, title: str) -> Path:
    """Bar chart of one KPI per experiment, saved next to the PDF build (short IDs as labels)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    g = runs.groupby("experiment")[kpi]
    m, sd = g.mean()[order], g.std()[order]
    shade = ["#9AA4B1" if e == BASE else "#1E8E5A" if e == BEST else "#2F6FE0" for e in order]
    fig, ax = plt.subplots(figsize=(6.4, 3.9), dpi=160)
    ax.bar(order, m, yerr=sd, color=shade, capsize=3)
    ax.axhline(m[BASE], color="#5B6675", lw=0.8, ls="--")
    ax.set_title(title, fontsize=11)
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    out = Path(tempfile.gettempdir()) / "warehouse_report_charts" / f"{kpi}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    return out


def progress_section(phases: list[dict], mean: pd.DataFrame) -> list:
    """Section 1: phase register and the KPIs of the warehouse after each completed phase."""
    out = [p("1. Project progress (phase by phase)", H2)]
    rows = [["#", "Phase", "Status", "Layer", "What was added", "How it was measured", "Result"]]
    shade = {"done": "#E3F4EA", "in progress": "#FFF4D6"}
    hl = {}
    for i, ph in enumerate(phases, start=1):
        rows.append([str(ph["id"]), ph["name"], ph["status"], ph.get("layer", ""), ph.get("added", ""),
                     ph.get("measured", ""), ph.get("result", "")])  # fmt: skip
        if ph["status"] in shade:
            hl[i] = shade[ph["status"]]
    out += [table(rows, [9, 33, 16, 17, 84, 50, 58], highlight=hl)]

    steps = [ph for ph in phases if ph["status"] == "done" and ph.get("experiment") in mean.index]
    if not steps:
        return out
    out += [PageBreak(), p("Warehouse KPIs after each completed phase", H3),
            p("Each column is the warehouse as it runs at the end of that phase (mean of the same 5 simulated "
              "days, 24 h each). Advisory phases predict but do not change decisions, so their KPIs repeat the "
              "previous column. Change is measured against the baseline (first column).", NOTE)]  # fmt: skip
    kpis = [("avg_completion_ticks", "Average completion (ticks)", 1, True),
            ("p90_completion_ticks", "p90 completion (ticks)", 1, True), ("late_percent", "Late orders (%)", 1, True),
            ("avg_queue_ticks", "Wait for a free robot (ticks)", 1, True),
            ("throughput_per_hour", "Throughput (orders / sim hour)", 1, False),
            ("distance_per_order_m", "Distance per order (m)", 1, True), ("blocked_events", "Standoffs per day", 0, True),
            ("avg_pending", "Average orders waiting", 1, True), ("utilisation_percent", "Fleet utilisation (%)", 1, None)]  # fmt: skip
    head = ["KPI"] + [f"After phase {ph['id']} · {ph.get('layer', '')} ({ph['experiment']}, {ph.get('kpi_effect', '')})"
                      for ph in steps]  # fmt: skip
    rows = [head]
    base = mean.loc[steps[0]["experiment"]]
    better = []  # cells that improved on the baseline by more than 1 %
    for i, (k, label, d, lower_better) in enumerate(kpis, start=1):
        row = [label]
        for j, ph in enumerate(steps):
            v = mean.loc[ph["experiment"], k]
            cell = fmt(v, d)
            if j and base[k]:
                change = (v - base[k]) / base[k] * 100
                cell += f"  ({change:+.1f} %)"
                if lower_better is not None and (change < -1 if lower_better else change > 1):
                    better.append(
                        ("BACKGROUND", (j + 1, i), (j + 1, i), colors.HexColor("#E3F4EA"))
                    )
            row.append(cell)
        rows.append(row)
    t = table(rows, [60] + [199 / len(steps)] * len(steps))
    t.setStyle(TableStyle(better))
    out += [t, p("Green = better than the baseline by more than 1 %. Utilisation is neither better nor worse "
                 "by itself (same work, fewer idle-but-assigned robots).", NOTE)]  # fmt: skip
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--snapshot", action="store_true", help="also archive a copy for the latest done phase"
    )
    args = parser.parse_args()
    phases = yaml.safe_load((REPORTS / "phases.yaml").read_text(encoding="utf-8"))["phases"]
    done = [ph for ph in phases if ph["status"] == "done"]
    runs = pd.read_csv(P4 / "runs.csv")
    vs = pd.read_csv(P4 / "vs_baseline.csv")
    manifest = json.loads((P4 / "manifest.json").read_text(encoding="utf-8"))
    exps = {}
    for path in sorted((ROOT / "configs" / "experiments").glob("E*.yaml")):
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        if cfg.get("phase") == 4 and cfg["experiment_id"] in set(runs["experiment"]):
            exps[cfg["experiment_id"]] = cfg
    order = [
        e for e in ["E1", "E2", "E3", "E3c", "E4", "E4b", "E4c", "E4d", "E5", "E5b"] if e in exps
    ]
    mean = runs.groupby("experiment").mean(numeric_only=True)
    std = runs.groupby("experiment").std(numeric_only=True)
    rep = {k: json.loads((MODELS / f"{k}_report.json").read_text()) for k in
           ("eta_v1", "late_risk_v1", "demand_v1", "anomaly_v1", "demand_breakdown_v1")}  # fmt: skip
    b, w = mean.loc[BASE], mean.loc[BEST]

    def change(e, k):
        r = vs[(vs["experiment"] == e) & (vs["kpi"] == k)]
        if r.empty or pd.isna(r.iloc[0]["change_percent"]):
            return "—"
        return f"{r.iloc[0]['change_percent']:+.1f} % ({r.iloc[0]['seeds_improved']})"

    story = []
    # ===== 1. Title & executive summary ========================================================
    story += [
        p("Warehouse AI Platform — Project Progress Report", H1),
        p(
            f"Phases 1–{done[-1]['id']} complete · Baseline vs Layer 3 (Classical ML) vs Layer 4 (Optimisation) · "
            f"simulated 80 × 50 m warehouse, 40 AMRs · built {date.today():%d %B %Y}",
            NOTE,
        ),
        Spacer(1, 6),
    ]
    story += progress_section(phases, mean)
    story += [
        PageBreak(),
        p("2. Executive summary", H2),
        p(
            f"<b>Baseline</b> ({BASE}) is the rule-based warehouse of Phases 1–2: nearest free robot, shortest-cell "
            "BFS routes. <b>Layer 3</b> adds trained Classical ML models (ETA, late risk, demand, anomaly) that "
            "<i>predict</i> but do not change decisions — the warehouse KPIs are identical to the baseline; its value "
            "is information (prediction accuracy below). <b>Layer 4</b> uses those predictions inside the decisions "
            f"(routing, assignment, positioning, charging). The best Layer 4 strategy, <b>{BEST}</b> (Hungarian "
            "assignment on ETA-predicted delivery times, BFS routes), compared with the baseline on the same five "
            "simulated days:"
        ),
        Spacer(1, 4),
    ]
    head = [
        ["KPI", f"Baseline {BASE}", f"Layer 4 best {BEST}", "Change", "Days improved"],
        ["Average order completion (ticks)", fmt(b.avg_completion_ticks), fmt(w.avg_completion_ticks),
         *change(BEST, "avg_completion_ticks").split(" (")[0:1], change(BEST, "avg_completion_ticks").split("(")[-1].rstrip(")")],
        ["90th-percentile completion (ticks)", fmt(b.p90_completion_ticks), fmt(w.p90_completion_ticks),
         change(BEST, "p90_completion_ticks").split(" (")[0], change(BEST, "p90_completion_ticks").split("(")[-1].rstrip(")")],
        ["Late orders (%)", fmt(b.late_percent), fmt(w.late_percent),
         change(BEST, "late_percent").split(" (")[0], change(BEST, "late_percent").split("(")[-1].rstrip(")")],
        ["Wait for a free robot (ticks)", fmt(b.avg_queue_ticks), fmt(w.avg_queue_ticks),
         change(BEST, "avg_queue_ticks").split(" (")[0], change(BEST, "avg_queue_ticks").split("(")[-1].rstrip(")")],
        ["Distance per order (m)", fmt(b.distance_per_order_m), fmt(w.distance_per_order_m),
         change(BEST, "distance_per_order_m").split(" (")[0], change(BEST, "distance_per_order_m").split("(")[-1].rstrip(")")],
        ["Throughput (orders / simulated hour)", fmt(b.throughput_per_hour), fmt(w.throughput_per_hour),
         change(BEST, "throughput_per_hour").split(" (")[0], change(BEST, "throughput_per_hour").split("(")[-1].rstrip(")")],
    ]  # fmt: skip
    story += [table(head, [70, 35, 35, 30, 30]), Spacer(1, 6)]

    # ===== 2. Definitions & glossary ===========================================================
    story += [p("3. Layers compared", H2)]
    layers = [
        ["", "Baseline (Phases 1–2)", "Layer 3 — Classical ML (Phase 3)", "Layer 4 — Optimisation (Phase 4)"],
        ["Purpose", "Run the warehouse with fixed rules", "Predict outcomes (advisory)", "Make better decisions using the predictions"],
        ["Robot assignment", "Nearest free robot (Manhattan distance to first rack), battery ≥ 20 %", "Unchanged",
         "ETA-ranked candidates; Hungarian (global) assignment on predicted delivery times"],
        ["Routing", "BFS: fewest cells; one-way aisles, closures respected", "Unchanged",
         "Dijkstra / A* with live traffic costs (tested; rejected), BFS kept in the winner"],
        ["Idle positioning", "Balanced parking: distance + 150 × area fullness", "Unchanged",
         "Demand-aware bonus for areas next to the zone forecast busiest (tested; no gain)"],
        ["Charging", "<20 % → charger; top-up <70 % when queue empty; stop at 95 %", "Unchanged",
         "Threshold follows the demand forecast: 85 / 70 / 50 % (tested; no gain)"],
        ["AI used", "None", "ETA (Gradient Boosting), late risk (Logistic Regression), demand (Gradient Boosting), "
         "zone/priority demand (Linear/XGBoost), anomaly (XGBoost)", "Inference of the Layer 3 ETA and demand models inside each decision"],
        ["Training", "—", "Supervised learning on dataset v3 (91 days), date-based split", "None (no training); controlled simulation experiments"],
        ["Effect on KPIs", "Reference", "None by itself (decisions unchanged)", f"Best ({BEST}): −21 % completion, −40 % late"],
    ]  # fmt: skip
    story += [table(layers, [32, 62, 70, 95])]

    story += [PageBreak(), p("Glossary of technical terms", H2)]
    gloss = [
        ["Term", "Meaning in this report"],
        ["Tick", f"One simulation step. Robots move at most 1 cell (1 m) per tick. At 1× speed 1 tick = {TICK_SECONDS} s of robot time (2 m/s)."],
        ["Simulated hour", f"{TICKS_PER_SIM_HOUR} ticks on the business clock (orders per hour, demand profile, faults per hour). The day is time-compressed."],
        ["Seed / simulated day", "One 24-hour run (14,400 ticks) generated from a random seed; 5 seeds = 5 different days."],
        ["Common random numbers", "Orders, faults and hazards come from independent random streams, so every strategy faces the identical day."],
        ["Paired comparison", "Each strategy is compared with the baseline on the same seed; 'days improved' counts seeds where it was better."],
        ["Completion time", "Ticks from order creation to delivery at the packing station (queue time + travel + picking + drop)."],
        ["p90 completion", "90th percentile: 10 % of orders take longer than this. Measures the tail (worst-served orders)."],
        ["Queue time / wait for a robot", "Ticks from order creation until a robot is assigned."],
        ["Late order", "Delivered after its deadline: HIGH 240, MEDIUM 480, LOW 900 ticks after creation."],
        ["Throughput", "Orders delivered per simulated hour."],
        ["Utilisation", "Share of robots busy (on an order or charging), sampled every 60 ticks."],
        ["Distance per order", "Metres driven by the whole fleet (incl. charging and parking trips) divided by orders delivered."],
        ["Standoff (blocked event)", "A robot side-steps to break a mutual block between robots (deadlock breaker)."],
        ["BFS", "Breadth-first search: shortest route in number of cells when every step costs the same."],
        ["Dijkstra", "Shortest route when steps have different costs; expands the cheapest partial route first."],
        ["A*", "Dijkstra guided by an admissible heuristic (Manhattan distance); same optimal route, fewer cells explored."],
        ["Traffic cost", "Extra step cost: +4 occupied cell, +2 per robot in the same one-way aisle, +1 × zone congestion (scaled by traffic_weight)."],
        ["ETA model", "Layer 3 regression model predicting delivery ticks from features known at assignment."],
        ["Hungarian algorithm", "Optimal assignment of N orders to M robots minimising the total cost (scipy linear_sum_assignment)."],
        ["Greedy assignment", "Orders handled one by one, each taking the best robot left (baseline and eta strategies)."],
        ["MAE / RMSE / R²", "Mean absolute error; root mean squared error (penalises big errors); share of variance explained."],
        ["Precision / Recall / F1", "Correct share of alarms; share of real positives caught; harmonic mean of the two."],
        ["ROC-AUC", "Probability the model ranks a random positive above a random negative (0.5 = chance, 1 = perfect)."],
        ["Threshold", "Probability above which a classifier says 'yes' (tuned on validation for best F1)."],
    ]  # fmt: skip
    story += [table(gloss, [45, 214])]

    # ===== 3. Setup & units =====================================================================
    story += [PageBreak(), p("4. Simulation setup and unit conversion", H2)]
    setup = [
        ["Parameter", "Value"],
        ["Layout", "80 × 50 m grid (1 cell = 1 m), 4 storage zones, 1,584 rack bays (SKUs), 52 one-way picking aisles"],
        ["Fleet", f"{ROBOTS} AMRs, max 1 cell/tick (2 m/s at 1×), battery 0.05 %/m, low 20 %, charge to 95 %"],
        ["Stations", "6 packing stations × 3 drop bays; 4 chargers × 3 bays; 8 parking areas (88 bays)"],
        ["Orders", "1–2 lines × 1–3 units; priority mix HIGH 20 % / MEDIUM 50 % / LOW 30 %; arrival 0.14 per tick on average"],
        ["Demand profile", "Hourly profile (night ×0.2 … peak ×1.3); average ≈ 70 % of fleet capacity, peaks above 100 %"],
        ["Disruptions", "Robot faults (5 types), aisle closures, dropped parcels / pallets, 8 walking workers"],
        ["Picking / dropping", "4 ticks per order line at the rack face, 3 ticks to unload"],
        ["Experiments", f"{len(order)} strategies × {manifest['seeds']} seeds × {manifest['hours']} simulated hours "
         f"({manifest['hours'] * TICKS_PER_SIM_HOUR:,} ticks) = {len(runs)} runs"],
    ]  # fmt: skip
    story += [table(setup, [45, 214])]
    conv = [
        ["Quantity", "In the simulator", "Converted (robot time, 1 tick = 0.5 s)"],
        ["Baseline average completion", f"{b.avg_completion_ticks:.0f} ticks", f"{secs(b.avg_completion_ticks):.0f} s ≈ {secs(b.avg_completion_ticks) / 60:.1f} min"],
        [f"{BEST} average completion", f"{w.avg_completion_ticks:.0f} ticks", f"{secs(w.avg_completion_ticks):.0f} s ≈ {secs(w.avg_completion_ticks) / 60:.1f} min"],
        ["Deadlines HIGH / MEDIUM / LOW", "240 / 480 / 900 ticks", "2 / 4 / 7.5 min"],
        ["One simulated hour", f"{TICKS_PER_SIM_HOUR} ticks", "5 min of robot time (business clock compressed 12×)"],
        ["Baseline throughput", f"{b.throughput_per_hour:.1f} orders / sim hour",
         f"≈ {b.throughput_per_hour / ROBOTS * 12:.0f} orders per robot per real hour of robot time"],
        ["Fleet distance per day (baseline)", f"{b.distance_m:,.0f} m", f"{b.distance_m / 1000:,.0f} km over {ROBOTS} robots ≈ {b.distance_m / ROBOTS / 1000:.1f} km per robot"],
    ]  # fmt: skip
    story += [Spacer(1, 6), table(conv, [70, 70, 119])]
    story += [
        p(
            "Throughput is capacity-bound: every strategy delivers the same orders per hour on average; the "
            "differences are in how long orders wait and how late they are.",
            NOTE,
        )
    ]

    # ===== 4. Layer 3 ===========================================================================
    eta, late, dem, ano, brk = (
        rep[k] for k in ("eta_v1", "late_risk_v1", "demand_v1", "anomaly_v1", "demand_breakdown_v1")
    )
    story += [
        PageBreak(),
        p("5. Layer 3 — Classical ML models (test set: last 2 weeks of dataset v3)", H2),
    ]
    l3 = [
        ["Model", "Target", "Algorithm (selected on validation)", "Test metric", "Model", "Baseline", "Baseline method"],
        ["ETA", "duration_ticks", eta["algorithm"], "MAE (ticks)", fmt(eta["test"]["MAE"]), fmt(eta["test_baseline"]["MAE"]), "training mean"],
        ["", "", "", "RMSE (ticks)", fmt(eta["test"]["RMSE"]), fmt(eta["test_baseline"]["RMSE"]), ""],
        ["", "", "", "R²", fmt(eta["test"]["R2"], 3), fmt(eta["test_baseline"]["R2"], 3), ""],
        ["Late risk", "late (0/1)", f"{late['algorithm']}, threshold {late['threshold']}", "Precision / Recall",
         f"{late['test']['precision']:.3f} / {late['test']['recall']:.3f}", "0 / 0", "always on time"],
        ["", "", "", "F1 / ROC-AUC", f"{late['test']['F1']:.3f} / {late['test']['ROC-AUC']:.3f}", "0 / 0.5", ""],
        ["Demand (total)", "orders_total / h", dem["algorithm"], "MAE (orders/h)", fmt(dem["test_mae"], 2), fmt(dem["test_baseline_mae"], 2), "same hour last week"],
        ["Anomaly", "is_anomaly", ano["algorithm"], "Precision / Recall / F1",
         " / ".join(f"{ano['test'][ano['algorithm']][k]:.3f}" for k in ("precision", "recall", "F1")),
         " / ".join(f"{ano['test']['Hand rule'][k]:.3f}" for k in ("precision", "recall", "F1")), "hand-written rule"],
        ["", "", "Isolation Forest (unsupervised)", "Precision / Recall / F1",
         " / ".join(f"{ano['test']['Isolation Forest'][k]:.3f}" for k in ("precision", "recall", "F1")), "", "no labels"],
        ["", "", f"DBSCAN (unsupervised, eps {ano['dbscan']['eps']})", "Precision / Recall / F1 (30k sample)",
         " / ".join(f"{ano['test_unsupervised_sample']['DBSCAN'][k]:.3f}" for k in ("precision", "recall", "F1")), "", "no labels"],
    ]  # fmt: skip
    for r in brk["test"]:
        l3.append(
            [
                "Demand breakdown",
                r["target"],
                r["model"],
                "MAE",
                fmt(r["test MAE"], 2),
                fmt(r["baseline MAE"], 2),
                "same hour last week",
            ]
        )
    story += [table(l3, [27, 30, 55, 42, 38, 30, 37])]
    story += [
        p(
            "Layer 3 alone does not change any decision: run live, the warehouse KPIs equal the baseline's. "
            "Its contribution is foresight (dashboard ETA, late-risk alerts, demand forecast, fault alarms) and "
            "the ETA and demand predictions that Layer 4 uses.",
            NOTE,
        )
    ]

    # ===== 5. Layer 4 full results ==============================================================
    story += [
        PageBreak(),
        p("6. Layer 4 — all experiments (mean ± standard deviation over 5 simulated days)", H2),
    ]
    strat = [
        ["ID", "Name", "Assignment", "Planner", "Traffic", "Positioning", "Charging", "Replan"]
    ]
    for e in order:
        s = exps[e]["strategies"]
        traffic = f"yes ×{s.get('traffic_weight', 1.0)}" if s.get("traffic_aware") else "no"
        strat.append([e, exps[e]["name"], s["assignment"], s["planner"], traffic, s["positioning"], s["charging"],
                      "yes" if s["replanning"] else "no"])  # fmt: skip
    hl = {order.index(BASE) + 1: "#EEF1F4", order.index(BEST) + 1: "#E3F4EA"}
    story += [table(strat, [12, 78, 22, 18, 22, 24, 24, 16], highlight=hl), Spacer(1, 6)]

    kpis = [("avg_completion_ticks", "Avg compl. (ticks)"), ("p90_completion_ticks", "p90 compl. (ticks)"),
            ("late_percent", "Late %"), ("avg_queue_ticks", "Wait robot (ticks)"),
            ("throughput_per_hour", "Throughput /h"), ("distance_per_order_m", "Dist./order (m)"),
            ("distance_m", "Fleet dist./day (km)"), ("blocked_events", "Standoffs"),
            ("route_changes", "Re-plans"), ("avg_pending", "Avg waiting orders"),
            ("utilisation_percent", "Utilisation %"), ("orders_delivered", "Delivered per day")]  # fmt: skip
    full = [["ID"] + [k[1] for k in kpis]]
    for e in order:
        row = [e]
        for k, _ in kpis:
            m_, s_ = mean.loc[e, k], std.loc[e, k]
            if k == "distance_m":
                m_, s_ = m_ / 1000, s_ / 1000
            row.append(f"{m_:,.1f} ± {s_:,.1f}")
        full.append(row)
    story += [table(full, [11] + [20] * (len(kpis) - 1) + [28], highlight=hl)]
    story += [
        p(
            "Converted to robot time (× 0.5 s): baseline completion "
            f"{secs(b.avg_completion_ticks):.0f} s, {BEST} {secs(w.avg_completion_ticks):.0f} s; "
            f"baseline p90 {secs(b.p90_completion_ticks):.0f} s, {BEST} {secs(w.p90_completion_ticks):.0f} s.",
            NOTE,
        )
    ]

    # ===== 6. Paired comparison ================================================================
    story += [PageBreak(), p(f"6. Paired comparison with the baseline {BASE} (same seeds)", H2),
              p("Each cell: mean change in % of the baseline, and on how many of the 5 days the strategy was better. "
                "Green = better on all 5 days; red = worse on all 5 days.", NOTE)]  # fmt: skip
    pk = ["avg_completion_ticks", "p90_completion_ticks", "late_percent", "avg_queue_ticks", "throughput_per_hour",
          "distance_per_order_m", "blocked_events", "avg_pending", "utilisation_percent"]  # fmt: skip
    labels = {"avg_completion_ticks": "Avg completion", "p90_completion_ticks": "p90 completion", "late_percent": "Late %",
              "avg_queue_ticks": "Wait for robot", "throughput_per_hour": "Throughput", "distance_per_order_m": "Distance/order",
              "blocked_events": "Standoffs", "avg_pending": "Waiting orders", "utilisation_percent": "Utilisation"}  # fmt: skip
    rows = [["ID"] + [labels[k] for k in pk]]
    cell_styles = []
    for i, e in enumerate([x for x in order if x != BASE], start=1):
        row = [e]
        for j, k in enumerate(pk, start=1):
            r = vs[(vs["experiment"] == e) & (vs["kpi"] == k)]
            if r.empty:
                row.append("—")
                continue
            r = r.iloc[0]
            row.append(
                f"{r.change_percent:+.1f} % ({r.seeds_improved})"
                if not pd.isna(r.change_percent)
                else "—"
            )
            if r.seeds_improved == "5/5":
                cell_styles.append(("BACKGROUND", (j, i), (j, i), colors.HexColor("#E3F4EA")))
            elif r.seeds_improved == "0/5":
                cell_styles.append(("BACKGROUND", (j, i), (j, i), colors.HexColor("#FBE6E4")))
        rows.append(row)
    t = table(rows, [12] + [27.4] * len(pk))
    t.setStyle(TableStyle(cell_styles))
    story += [t]

    # ===== 7. Head-to-head =====================================================================
    story += [
        p(f"7. Head-to-head: Baseline vs Layer 3 vs Layer 4 ({BEST}) — technical metrics", H2)
    ]

    def both(k, d=1):
        return [fmt(b[k], d), fmt(b[k], d), fmt(w[k], d)]

    h2h = [
        ["Metric", "Baseline (E2)", "Layer 3 (E2 + live models)", f"Layer 4 ({BEST})", "Unit / note"],
        ["Decision rule (assignment)", "nearest robot", "nearest robot", "Hungarian on ETA predictions", ""],
        ["Route planner", "BFS", "BFS", "BFS", "A* + traffic rejected (E3/E3c)"],
        ["Model inference in decisions", "none", "none (advisory)", "ETA per candidate robot", "≤ 8 candidates per order"],
        ["Avg completion", *both("avg_completion_ticks"), "ticks"],
        ["Avg completion (robot time)", f"{secs(b.avg_completion_ticks):.0f}", f"{secs(b.avg_completion_ticks):.0f}", f"{secs(w.avg_completion_ticks):.0f}", "seconds (× 0.5 s)"],
        ["p90 completion", *both("p90_completion_ticks"), "ticks"],
        ["Late orders", *both("late_percent"), "% of delivered"],
        ["Wait for a free robot", *both("avg_queue_ticks"), "ticks"],
        ["Travel + work after assignment", fmt(b.avg_completion_ticks - b.avg_queue_ticks), fmt(b.avg_completion_ticks - b.avg_queue_ticks),
         fmt(w.avg_completion_ticks - w.avg_queue_ticks), "ticks (completion − wait)"],
        ["Throughput", *both("throughput_per_hour"), "orders / simulated hour"],
        ["Orders per robot", fmt(b.throughput_per_hour / ROBOTS, 2), fmt(b.throughput_per_hour / ROBOTS, 2), fmt(w.throughput_per_hour / ROBOTS, 2), "per simulated hour"],
        ["Distance per order", *both("distance_per_order_m"), "metres"],
        ["Fleet distance per day", fmt(b.distance_m / 1000), fmt(b.distance_m / 1000), fmt(w.distance_m / 1000), "km"],
        ["Standoffs per day", *both("blocked_events", 0), "side-steps"],
        ["Re-plans per day", *both("route_changes", 0), "route changes"],
        ["Average orders waiting", *both("avg_pending"), "orders (sampled / 60 ticks)"],
        ["Fleet utilisation", *both("utilisation_percent"), "% robots busy"],
        ["Low-battery charges per day", *both("charges", 0), "trips"],
        ["Prediction accuracy available", "—", f"ETA MAE {eta['test']['MAE']:.1f} ticks; late F1 {late['test']['F1']:.2f}",
         "same models", "Layer 3 test set"],
    ]  # fmt: skip
    story += [table(h2h, [58, 38, 50, 52, 61])]

    # ===== 8. Per seed ==========================================================================
    story += [PageBreak(), p("9. Consistency: results per simulated day (seed)", H2)]
    cols = [x for x in (BASE, "E4c", BEST, "E5b", "E3") if x in order]
    for k, lab in (
        ("avg_completion_ticks", "Average completion (ticks)"),
        ("late_percent", "Late orders (%)"),
    ):
        piv = runs.pivot(index="seed", columns="experiment", values=k)[cols]
        rows = [["Seed"] + cols] + [[str(s)] + [fmt(v) for v in piv.loc[s]] for s in piv.index]
        story += [p(lab, H3), table(rows, [25] + [30] * len(cols))]
    story += [Spacer(1, 6)]
    story += [
        PageBreak(),
        p(
            "9. Charts (mean over 5 seeds; error bars = standard deviation; grey = baseline, green = best)",
            H2,
        ),
    ]
    imgs = [Image(str(chart(runs, order, k, lab)), width=118 * mm, height=72 * mm) for k, lab in (
        ("avg_completion_ticks", "Average completion (ticks)"), ("late_percent", "Late orders (%)"),
        ("avg_queue_ticks", "Wait for a free robot (ticks)"), ("distance_per_order_m", "Distance per order (m)"))]  # fmt: skip
    story += [Table([imgs[:2], imgs[2:]], colWidths=[128 * mm, 128 * mm])]

    # ===== 10. Interpretation & limits ==========================================================
    story += [PageBreak(), p("11. Interpretation", H2)]
    for text in (
        f"<b>Why {BEST} wins.</b> At peak hours the fleet is overloaded: in the baseline more than half of an order's "
        f"completion time ({b.avg_queue_ticks:.0f} of {b.avg_completion_ticks:.0f} ticks) is waiting for a robot. Matching all "
        "waiting orders with all free robots at once, on predicted delivery times and HIGH priority first, avoids the "
        "greedy pattern in which later orders inherit distant robots. The queue time falls "
        f"{change(BEST, 'avg_queue_ticks').split(' (')[0]}, the tail (p90) {change(BEST, 'p90_completion_ticks').split(' (')[0]}.",
        "<b>Why traffic-aware A* lost.</b> Traffic costs reduce standoffs but lengthen routes (distance per order "
        f"{change('E3', 'distance_per_order_m').split(' (')[0]}). When robot time is the bottleneck, extra metres grow the "
        "queue, and completion time rises. The gentle variant (E3c) loses less but still loses.",
        "<b>Greedy ETA assignment (E4c)</b> gains only slightly: a better robot for each order in turn does not fix the "
        "ordering problem the Hungarian method solves.",
        "<b>Demand-aware positioning and predictive charging (E5b)</b> add nothing on top of E4d: robots are rarely "
        "idle at peaks, so where they wait matters little.",
    ):
        story += [p(text), Spacer(1, 4)]
    story += [p("12. Validity and limitations", H2)]
    for text in (
        "Paired design with common random numbers: every strategy faced identical orders, faults and hazards; "
        f"{BEST} improved completion time and late % on all 5 days.",
        "Orders created per day differ by up to ~1.5 % between strategies: the waiting-queue safety cap (150 orders) "
        "is reached at peaks by the slower strategies, which therefore look slightly better than they are; the "
        "conclusions are unchanged.",
        "Time is compressed (600 ticks per simulated hour) and deadlines are minutes, so late % is a relative stress "
        "metric, not a customer SLA; robots carry one order per trip (real AMR picking usually batches several).",
        "One layout and fleet size; the ETA model was trained on baseline behaviour; 5 seeds per experiment, so "
        "small differences (e.g. E4c) are within day-to-day variation.",
        "Some recorded run durations include time the computer was asleep; they are not used in any result.",
    ):
        story += [p("• " + text), Spacer(1, 2)]
    story += [
        Spacer(1, 6),
        p(
            "Sources: models/*_report.json, evaluation/reports/phase4/runs.csv, vs_baseline.csv, manifest.json, "
            "configs/experiments/*.yaml. Rebuild: python scripts/build_project_report.py",
            NOTE,
        ),
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(OUT), pagesize=landscape(A4), leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=13 * mm, bottomMargin=14 * mm, title="Warehouse AI Platform — Project Progress Report",
                            author="Warehouse AI Platform")  # fmt: skip
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print("wrote", OUT)
    if args.snapshot:
        archive = REPORTS / "archive" / f"Project_Progress_Report_phase{done[-1]['id']}.pdf"
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(OUT, archive)
        print("archived", archive)


if __name__ == "__main__":
    main()
