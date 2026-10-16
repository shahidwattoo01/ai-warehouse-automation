"""Analytics endpoints (TRD Section 7): results of the Phase 4 optimisation experiments."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/analytics", tags=["analytics"])

REPORT = Path(__file__).resolve().parents[5] / "evaluation" / "reports" / "phase4"


@router.get("/experiments")
def experiments() -> dict:
    """Phase 4 results written by scripts/run_experiments.py: per-experiment means and spread,
    and the paired change vs the E2 baseline."""
    if not (REPORT / "manifest.json").exists():
        raise HTTPException(404, "No results yet: run python scripts/run_experiments.py")
    manifest = json.loads((REPORT / "manifest.json").read_text(encoding="utf-8"))
    summary = pd.read_csv(REPORT / "summary.csv", header=[0, 1], index_col=0)
    versus = pd.read_csv(REPORT / "vs_baseline.csv")
    results = {
        eid: {kpi: {"mean": float(summary.loc[eid, (kpi, "mean")]),
                    "std": float(summary.loc[eid, (kpi, "std")])}
              for kpi in summary.columns.get_level_values(0).unique()}
        for eid in summary.index
    }  # fmt: skip
    return {
        "manifest": manifest,
        "results": results,
        "vs_baseline": versus.where(versus.notna(), None).to_dict("records"),
    }
