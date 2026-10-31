"""Model operations from the command line (backlog PR-19; docs/mlops.md).

    python scripts/mlops.py --status                  # versions and which one is in production
    python scripts/mlops.py --build-reference         # training-data profiles of version 1
    python scripts/mlops.py --promote eta v2          # by hand (the gate must have passed)
    python scripts/mlops.py --rollback eta            # back to the previous production version

The live platform monitors drift and retrains on its own (app/services/mlops.py); a running
backend picks up a promotion or rollback made here when it restarts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import joblib  # noqa: E402

from ai.mlops.drift import reference_profile  # noqa: E402
from ai.mlops.registry import MODELS_DIR, V1, Registry  # noqa: E402
from ai.mlops.retrain import load_tasks, pipeline_of  # noqa: E402


def build_reference() -> None:
    tasks = load_tasks()
    train = tasks[tasks["split"] == "train"]
    for model, (file, _, reference) in V1.items():
        features = list(pipeline_of(model, joblib.load(MODELS_DIR / file)).feature_names_in_)
        profile = reference_profile(train, features)
        (MODELS_DIR / reference).write_text(json.dumps(profile, indent=1), encoding="utf-8")
        print(f"{reference}: {len(profile)} features from {len(train):,} training rows")


def status(reg: Registry) -> None:
    for model in V1:
        print(f"{model}: production {reg.data[model]['production']}")
        for v in reg.versions(model):
            print(f"  {v['version']:4s} {v['status']:10s} {v.get('trained_on', '')}  {v['test']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--build-reference", action="store_true")
    ap.add_argument("--promote", nargs=2, metavar=("MODEL", "VERSION"))
    ap.add_argument("--rollback", metavar="MODEL")
    a = ap.parse_args()
    if a.build_reference:
        build_reference()
    reg = Registry()
    if a.promote:
        reg.promote(*a.promote, by="cli")
    if a.rollback:
        print("now in production:", reg.rollback(a.rollback, by="cli")["version"])
    if a.status or a.promote or a.rollback or not a.build_reference:
        status(reg)


if __name__ == "__main__":
    main()
