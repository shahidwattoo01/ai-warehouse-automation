# Contracts

The messages between simulator, API, 3D twin, n8n and AI layers are defined once in Pydantic
(`src/warehouse_ai/data/contracts.py`) and exported to JSON Schema here.

- `make contracts` regenerates `schemas/` and `apps/twin/src/types/generated.ts`.
- `golden/` holds example messages. CI fails if a golden message no longer validates.
- Adding an optional field is a minor version change. Renaming or removing a field is a major change and needs team agreement.
