# RAG knowledge base (Phase 7)

The warehouse documents, written to match the simulator exactly (thresholds from
configs/simulation.yaml, aisle numbers and stations from configs/layouts/large.yaml).

| File | Contents |
| --- | --- |
| `warehouse_manual.md` | layout, zones, aisles 1-52, stations, locations, order flow, traffic rules, KPIs |
| `robot_manual.md` | AMR-500: motion, statuses, battery and charging, temperature, faults, commands |
| `safety_rules.md` | walking on the robot floor, restricted zones (closed aisles, hazards, chargers), emergency stop |
| `maintenance_guides.md` | diagnosing each fault type, preventive maintenance |
| `sops.md` | SOP-01 to SOP-10: low / critical battery, stopped robot, overheating, closing an aisle, dropped parcel, urgent orders, manual assignment, blocked robot, peak days |
| `inventory_policies.md` | product IDs, stock, replenishment, counts, demand planning |
| `eval/rag_questions.yaml` | 94 evaluation questions with answers and cited sections |
| `pdf/` | PDF versions (generated) |

Every section has an ID (WM-2.1, SOP-05, ...) so answers can cite their source. After editing a
document, run `python scripts/build_knowledge_base.py`: it regenerates the PDFs and
`data/processed/rag/`, and fails if a question cites a section that no longer exists.
