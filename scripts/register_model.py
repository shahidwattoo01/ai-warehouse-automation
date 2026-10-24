"""Show the trained models and register the live ones in the database.

    python scripts/register_model.py          # list models/: file, version, test result, live?
    python scripts/register_model.py --db     # register the live versions in model_versions

The backend registers the models it loads every time a run starts, so this script is only
needed to inspect the registry or to fill it without starting the app. "Live" follows the same
rules as the app (ai/classical_ml/live_predictor.py): Phase 5 LSTM for anomalies unless
WAREHOUSE_ANOMALY_MODEL=xgboost; the demand network only with WAREHOUSE_DEMAND_MODEL=network.
Registering a version retires the previously active version of that model (it stays in the
table for history). Uses DATABASE_URL from .env.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "apps" / "backend"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from ai.classical_ml.live_predictor import Predictor  # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--db", action="store_true", help="register the live versions in PostgreSQL"
    )
    args = parser.parse_args()

    predictor = Predictor()
    if not predictor.versions:
        raise SystemExit("No trained models in models/ (see python scripts/train.py --list)")
    print(f"{'model':18s} {'version':8s} {'file':34s} test result")
    for v in predictor.versions:
        metrics = json.dumps(v["metrics"].get("test") or v["metrics"].get("test_mae"), default=str)
        print(f"{v['model_name']:18s} {v['version']:8s} {v['artifact_path']:34s} {metrics[:70]}")
    vision = ROOT / "models" / "vision_yolo_v1" / "best.pt"
    print(f"{'vision':18s} {'v1':8s} {'models/vision_yolo_v1/best.pt':34s} "
          f"{'present' if vision.exists() else 'missing'} (served by /api/v1/vision)")  # fmt: skip

    if args.db:
        from sqlalchemy import create_engine

        from app.core.config import get_settings
        from app.services.run_store import SQL_RETIRE_OTHER_VERSIONS, SQL_UPSERT_MODEL

        with create_engine(get_settings().database_url).begin() as conn:
            for v in predictor.versions:
                row = {**v, "metrics": json.dumps(v["metrics"], default=str)}
                conn.execute(SQL_RETIRE_OTHER_VERSIONS, row)
                conn.execute(SQL_UPSERT_MODEL, row)
        print(f"Registered {len(predictor.versions)} live model versions in model_versions.")


if __name__ == "__main__":
    main()
