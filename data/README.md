# Datasets (version v3)

Everything here is generated from the simulator and the project's own documents, so every label is
exact and every dataset can be rebuilt. This README is the single reference for what exists, how it
was made, how to split it and which project phase uses it.

Everything in `processed/` is organised by project phase:

```
data/processed/
├── classical_ml/      Phase 3: tasks, demand_hourly, anomaly_windows (.parquet)
├── deep_learning/     Phase 4-5: robot_status.parquet (telemetry sequences; also uses classical_ml/)
├── computer_vision/   Phase 5: images/, labels/, annotations/, data.yaml, frames.csv
├── nlp/               Phase 6: commands.jsonl, labels.json
├── rag/               Phase 7: questions.jsonl, sections.jsonl (documents live in data/documents/)
├── agents/            Phase 8-9: tools.json, scenarios.jsonl, states/
├── raw_logs/          events, orders, hazards (analysis, investigations)
├── reference/         warehouse entities (Layer 1): zones, aisles, shelves, products, robots, ...
├── manifest.json      how the simulation data was generated
└── validation_report.json
```

| Phase (project map) | Dataset | Folder / file | Size |
| --- | --- | --- | --- |
| 1 Data engineering | Warehouse entities | `processed/reference/*.parquet` | 8 tables |
| 3 Classical ML | ETA + late-risk | `processed/classical_ml/tasks.parquet` | 161,221 orders |
| 3 Classical ML | Demand forecasting | `processed/classical_ml/demand_hourly.parquet` | 2,184 hours (91 days) |
| 3 Classical ML | Anomaly detection | `processed/classical_ml/anomaly_windows.parquet` | 5.2 million windows |
| 4 Deep learning | Sequences (LSTM / Transformer) | `processed/deep_learning/robot_status.parquet` + `classical_ml/` | 26 million telemetry rows |
| 5 Computer vision | Object detection | `processed/computer_vision/` | 2,400 labelled 640x480 frames |
| 6 NLP + Transformers | Intent + entities | `processed/nlp/commands.jsonl` | 5,461 operator messages |
| 7 RAG | Knowledge base + eval | `documents/*.md`, `documents/pdf/`, `processed/rag/` | 6 documents, 120 sections, 94 questions |
| 8-9 Agents + tools | Tool catalogue + scenarios | `processed/agents/` | 15 tools, 92 scenarios |
| 9 Reinforcement learning | none needed | the simulator itself | RL learns by acting in the environment |
| 11 Evaluation | every split above | `processed/validation_report.json` | all checks |

Rebuild everything (about 2-3 hours on a 4-core laptop, most of it the 91 simulated days):

```bash
python scripts/generate_data.py            # simulation tables + reference tables
python scripts/build_knowledge_base.py     # RAG sections, PDFs, questions
python scripts/generate_nlp_data.py        # NLP commands + tool catalogue
python scripts/generate_agent_scenarios.py # agent scenarios (needs the RAG step first)
python scripts/capture_frames.py           # camera frames (the frontend must be running)
python scripts/validate_data.py            # check everything
```

Never mix versions: every simulation row carries `dataset_version` and `processed/manifest.json`
records the exact settings.

| Version | What changed |
| --- | --- |
| v1 (deleted) | Order rates above fleet capacity: demand capped all day. |
| v2 (deleted) | Rates from measured capacity, product columns. Independent days, no calendar. |
| **v3** | 91 consecutive calendar days (weekdays, weekends, autumn ramp, 3 promotion days); motor temperature and overheating faults; aisle closures and dropped parcels / fallen pallets; demand by zone; true route distance; reference entity tables; camera, NLP, RAG and agent datasets. |

---

## 1. Simulation tables (`processed/classical_ml/`, `deep_learning/`, `raw_logs/`)

**How they are made.** One simulator run per calendar day, Monday 2026-09-07 to Sunday 2026-12-06
(91 days, 13 weeks), large layout: 80 x 50 m, 52 one-way aisles, 1,584 rack bays, 40 robots,
6 packing stations, 4 chargers (12 bays), 8 parking areas, 8 workers. The clock is compressed:
600 ticks = 1 simulated hour, robots still move 1 cell (1 m) per tick.

Each day gets its own conditions:

- **Order load** = 66 % of measured fleet capacity x weekday factor (Mon 1.00 ... Sat 0.80, Sun
  0.66) x season (0.90 in early September rising to 1.15 in late November) x promotion
  (Singles Day 11 Nov x1.12, Black Friday 27 Nov x1.22, Cyber Monday 30 Nov x1.15) x noise,
  limited to 40-95 %. Weekdays use the configured hourly profile; weekends a later, flatter one.
  Rush hours exceed capacity, so queues and late orders appear naturally.
- **Faults**: 0.3-2.0 per robot per simulated hour of five types (battery_spike,
  speed_degradation, stop_event, route_deviation, overheating), labelled as ground truth.
- **Hazards**: 0.2-0.8 aisle closures and 0.4-1.6 floor hazards (dropped parcel / fallen pallet) per
  simulated hour.

The planned load (`target_load` in the manifest) is a generator setting. **Never use it as a
model feature.**

| Table | One row per | Use |
| --- | --- | --- |
| `tasks` | delivered order | **ETA** (target `duration_ticks`) and **late risk** (target `late`) |
| `demand_hourly` | simulated hour | **demand forecasting** (target `orders_total`, or by priority / category / zone) |
| `anomaly_windows` | 20-tick window per robot | **anomaly detection** (target `is_anomaly` or `fault_type`) |
| `robot_status` | robot every 2 ticks | raw telemetry for custom features and sequence models |
| `orders` | order | order history and outcomes |
| `events` | simulator event | full log (details as JSON) for analysis and agent investigation |
| `hazards` | closure or floor hazard | when and where paths were blocked |

**Calendar columns** on tasks, orders and demand: `date`, `day_index`, `day_of_week` (0 = Monday),
`day_name`, `is_weekend`, `week_of_year`, `month`, `season`, `is_promo_day`, `promo_name`.

**Features vs labels (avoid leakage).**

- `tasks` features (known when the order is assigned): priority, n_items, n_units,
  total_weight_kg, main_category, zones, sim_hour, calendar, start_x/y, battery_start,
  temperature_start, robot_speed, est_distance (straight line), path_distance (legal route),
  zone_congestion, fleet_busy, pending_orders, closures_active, floor_hazards_active, queue_ticks.
  Labels: `duration_ticks`, `late`. Only known afterwards, so **never features**: moves, waits,
  reroutes, delivered_at.
- `demand_hourly` features: calendar, hour_of_day, and the past-only lags `lag_1h_orders`,
  `lag_2h_orders`, `lag_24h_orders`, `lag_168h_orders`, `rolling_24h_mean_orders`,
  `lag_1h_orders_high`. The same-hour counts (orders_high, lines_*) are targets, not features.
- `anomaly_windows` features: move_rate, move_rate_when_busy, stop_count, battery_*,
  temperature_mean/max/delta, blocked_max, route_len_*, task_elapsed_max, congestion_mean.
  Labels: `is_anomaly`, `fault_type`. Raw `status` is deliberately not included (FAULT would give a
  stop away).

**Split (column `split`, by date, never random rows).** Train = first 9 weeks (63 days), validation
= next 2 weeks, test = last 2 weeks. The test weeks contain Black Friday and Cyber Monday: a
realistic, harder test. Forecasting must always train on the past and test on the future.

## 2. Reference tables (`processed/reference/`)

The warehouse as data (project map 4.1): `zones`, `aisles` (Aisle 1-52 with row, x range,
direction, zone), `shelves` (bay, location code, pick face, aisle), `stations` (packing +
charging), `parking_bays`, `obstacles` (structural columns), `products` (1,584: name, category,
weight, shelf, zone, opening stock, reorder point), `robots` (home bay, top speed).

## 3. Camera dataset (`processed/computer_vision/`)

Frames rendered by the real 3D scene (the same one operators see) in a headless browser on a GPU,
from four camera types: fixed CCTV, aisle-end cameras, cameras watching a floor hazard, and the
forward camera of a robot. Every shot varies position, aim, field of view and exposure.

Classes: `0 robot`, `1 worker`, `2 shelf` (rack bay), `3 package` (dropped parcel), `4 obstacle`
(fallen pallet), `5 blocked_path` (closed-aisle barrier).

Boxes are exact: the scene is the ground truth, and each box covers only the visible part of its
object (a depth test removes parts hidden behind racks). Formats: YOLO (`images/`, `labels/`,
`data.yaml`) and COCO (`annotations/<split>.json`, with object ids, visibility and truncation).
`frames.csv` lists every frame's seed, tick, camera type and pose, so detections can be mapped back
to grid cells (vision -> warehouse state). Split by simulation seed (70/15/15).

Built in three batches: 1,536 general frames (seeds 7000-7015, all camera types), then 384 frames
aimed at hazards and closed aisles (seeds 7100-7107) and 480 frames with up to six parcels/pallets
per scene (seeds 7200-7209, `--busy-floor`), because parcels and pallets are rare in normal
operation. Objects: robot 4,573, worker 1,708, shelf 63,442, package 466, obstacle 196,
blocked_path 477. Shelves dominate; weight the classes or sample by class when training.

## 4. NLP dataset (`processed/nlp/`)

`commands.jsonl`: operator messages such as "Close aisle 7 for spill cleanup" or "why is robot 14
delayed", each with the intent (17), entities (13 types, with character spans and canonical values,
e.g. "bot 7" -> R7), tokens with BIO tags, the tool calls the copilot should make, and whether those
need operator approval. `tools.json` is the tool catalogue (15 tools with JSON-schema arguments,
read/write flag) is in `processed/agents/tools.json`. Split by template: about one phrasing in five per intent appears only in the test
split, so the test set measures understanding of new wording.

## 5. RAG knowledge base (`documents/`, `processed/rag/`)

Six documents written to match the simulator exactly (thresholds, aisle numbers, stations, SOPs):
warehouse manual, robot manual, safety rules (with restricted zones), maintenance guide, ten SOPs,
inventory policies. Markdown sources plus PDFs (`documents/pdf/`) for the extraction step.
`processed/rag/sections.jsonl` holds the 120 numbered sections (the ground-truth retrieval units);
`processed/rag/questions.jsonl` holds 94 questions (factual, procedural, multi-hop, unanswerable)
with reference answers and the exact sections they come from: retrieval precision, context recall,
groundedness and citation accuracy can all be scored.

## 6. Agent scenarios and tools (`processed/agents/`)

92 situations found in real simulator runs: a stopped robot, an overheating robot, a robot blocked
in traffic, closing an aisle while a robot is still inside, a late order to explain, an urgent
queue, an assignment to a robot that cannot take it, and knowledge questions. Each has the
operator's request, the exact state (`states/<id>.json`, and a seed + tick to replay it), the facts,
the tools that must / may / must not be called, success conditions and a reference answer citing the
SOP it follows. Metrics: task success, tool-selection accuracy, steps, failures.

## 7. Validation

`python scripts/validate_data.py` runs every check (versions, splits, time order, leakage, demand
vs plan, rhythms, fault signals, hazard integrity, entity counts, NLP spans, RAG citations, agent
replay, vision labels) and writes `processed/validation_report.json`.
