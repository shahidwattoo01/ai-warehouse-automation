"""Golden messages must validate against the JSON Schemas."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

ROOT = Path(__file__).resolve().parents[2] / "contracts"


@pytest.mark.parametrize("schema,example", [("state_frame", "state_frame"), ("scene", "scene")])
def test_golden_matches_schema(schema: str, example: str) -> None:
    schema_doc = json.loads((ROOT / "schemas" / f"{schema}.schema.json").read_text())
    golden = json.loads((ROOT / "golden" / f"{example}.example.json").read_text())
    jsonschema.validate(golden, schema_doc)
