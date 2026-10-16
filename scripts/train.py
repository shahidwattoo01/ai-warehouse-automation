"""Train one model locally: python scripts/train.py --model eta. GPU-heavy models train via
notebooks/cloud/.

Phase 3.
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=None)
    parser.parse_args()
    raise SystemExit("Not implemented yet — scheduled for Phase 3.")


if __name__ == "__main__":
    main()
