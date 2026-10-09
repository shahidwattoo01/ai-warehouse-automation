#!/usr/bin/env python3
"""Validate every golden message against its JSON Schema. Exit code 1 on failure."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1] / "contracts"


def main() -> int:
    failures = 0
    for schema_path in sorted((ROOT / "schemas").glob("*.schema.json")):
        name = schema_path.name.replace(".schema.json", "")
        golden_path = ROOT / "golden" / f"{name}.example.json"
        if not golden_path.exists():
            print(f"MISSING golden message for {name}")
            failures += 1
            continue
        try:
            jsonschema.validate(json.loads(golden_path.read_text()), json.loads(schema_path.read_text()))
            print(f"ok  {name}")
        except jsonschema.ValidationError as exc:
            print(f"FAIL {name}: {exc.message}")
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
