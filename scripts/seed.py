"""Seed reference data (zones, shelves, stations, products, robots) from a layout config.

    python scripts/seed.py                    # layout from configs/simulation.yaml (large)
    python scripts/seed.py --layout default   # the small layout
    python scripts/seed.py --reset            # wipe reference data and ALL recorded runs first

Run after the database migrations (`python tasks.py migrate`). Uses DATABASE_URL from .env.
RAG document ingestion arrives with Phase 7.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "apps" / "backend"):  # allow running from the repo root
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from sqlalchemy import create_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.database.reference import reset_reference, seed_reference  # noqa: E402
from simulation.environment.engine import SimulationEngine  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--layout", default=None, help="layout in configs/layouts (default: simulation.yaml)"
    )
    parser.add_argument(
        "--reset", action="store_true", help="delete reference data and recorded runs first"
    )
    args = parser.parse_args()

    overrides = {"layout": args.layout} if args.layout else None
    sim = SimulationEngine(overrides=overrides)
    db = create_engine(get_settings().database_url)
    with db.begin() as conn:
        if args.reset:
            reset_reference(conn)
            print("Reference data and recorded runs deleted.")
        counts = seed_reference(conn, sim)
    print(f"Seeded layout '{sim.layout.name}':")
    for table, n in counts.items():
        print(f"  {table:18s} {n:>6,}")


if __name__ == "__main__":
    main()
