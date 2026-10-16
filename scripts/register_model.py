"""Register a trained artefact in models/ and the model_versions table; optionally mark it active.

Phase 3.
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=None)
    parser.parse_args()
    raise SystemExit("Not implemented yet — scheduled for Phase 3.")


if __name__ == "__main__":
    main()
