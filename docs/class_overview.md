---
doc_id: class_overview
title: Warehouse AI Platform - Technical Overview and Dataset
version: 3.0
effective: 2026-10-12
owner: NetSol training project
---

# Warehouse AI Platform

## Part 1 - Technical implementation (Phases 1-2)

**1. Architecture.** The browser (Next.js + React + Three.js) talks to a FastAPI backend over REST for actions and a WebSocket for live updates. The backend runs the simulation engine in memory and saves a recording to PostgreSQL every 2 seconds. A data pipeline turns simulations into Parquet tables, images and JSONL files.

- Single source of truth: the simulation engine.
- Safety rule: the API and future AI never edit state directly; they send validated commands, applied at the next tick.

**2. Tech stack and why**

| Layer | Technology | Why |
|---|---|---|
| Simulator | Python 3 | Same language as the ML/AI phases |
| API | FastAPI (async) | Fast, validated requests, automatic API docs |
| Live updates | WebSocket | Server pushes each tick; no polling |
| Frontend | Next.js 15, React, Tailwind, Zustand | Standard, component based, one shared store |
| 3D | Three.js / React Three Fiber | Runs in any browser, no install |
| Database | PostgreSQL 16 + Alembic migrations | Relational data; pgvector later for RAG |
| Datasets | Parquet, JSONL, YOLO/COCO | Compact, typed, standard ML formats |
| Quality | pytest, Ruff, TypeScript strict | Automatic checks catch mistakes |

**3. Simulation engine**

- Discrete-time loop: 2 ticks per second, robots move 1 cell (1 m) per tick.
- Fixed order each tick: commands, new orders, hazards, assignment, faults, movement, temperature, workers, KPIs.
- Seeded random generator: the same seed gives exactly the same run (reproducible experiments and tests).
- Modular engine: orders, dispatcher, robot controller, inventory, faults, hazards, temperature, workers, KPIs, recorder.

**4. Algorithms**

- Path planning: breadth-first search on a grid graph with random tie-breaks; respects one-way aisles, destination-only parking bays and closed cells.
- Collision avoidance: one robot per cell; wait, replan after 2 ticks, step aside after 4-7 ticks (deadlock breaker).
- Order assignment (baseline): priority, then age; the nearest free robot with at least 20 % battery.
- Balanced parking: cost = distance + 150 x how full the area is.
- Battery: low-battery charging and top-up charging in quiet periods.
- Temperature model: temperature += heat - 0.01 x (temperature - ambient); above 60 C the robot slows down.
- Fault injection: 5 fault types with true labels (needed for supervised anomaly detection).
- Hazards: aisle closures and floor obstacles, enforced in path planning.

**5. Backend**

- REST endpoints for simulation, robots, orders, inventory and assignment mode.
- Command queue and a single event loop: the earlier race condition is fixed.
- WebSocket stream built once for all viewers: 107 KB down to 40 KB per tick.
- Security: Origin check against cross-site requests (fake requests get 403), WebSocket origin check, CORS without credentials, Docker bound to localhost as a non-root user, secrets in .env outside git.

**6. Database**

- 19 tables: reference data, per-run recordings, and tables ready for later AI phases.
- Background writer saves batches every 2 s on a separate thread, so the simulation never waits.
- Heartbeat: runs left open by a crash are closed automatically on the next start.
- Migrations: 001 creates the schema, 002 adds the hazard event types.

**7. Frontend and 3D**

- Instancing (all 40 robots in one draw call) and static batching of racks: draw calls 1,722 to 336, frame rate 3 to 30 FPS on Intel HD graphics.
- Smooth movement between grid cells, quality presets (High / Balanced / Fast).
- 360 degree camera, zoom to cursor, double-click to fly to a spot, full screen, follow a robot.

**8. Data engineering pipeline (dataset v3)**

- Parallel generator: 91 consecutive calendar days, each with its own load, fault and hazard rates based on weekday, season and promotions (about 45 minutes).
- Recorder turns the event stream into training tables.
- No leakage: features captured at assignment time, past-only lag features, train / validation / test split by date.
- Validation script: 63 automatic checks, all passing.

**9. Datasets for the AI phases**

- Computer vision: a headless browser (Playwright) renders the real 3D scene; a depth-buffer test keeps only the visible part of each object, so boxes are exact. 2,400 images, 6 classes, YOLO and COCO.
- NLP: 5,461 commands with intent, entities (BIO tags) and tool calls; the test split uses unseen phrasings.
- RAG: 7 documents (Markdown and PDF), 178 numbered sections, 119 questions with their source sections.
- Agents: 92 scenarios from real simulator states, replayable from a seed and checked with a state fingerprint.

**10. Quality.** 37 automated tests, a golden-master fingerprint (proves refactors did not change behaviour), Ruff and TypeScript strict both clean.

## Part 2 - The dataset (v3)

All data comes from our own simulator and documents, so every label is exact and the dataset can be rebuilt with one command.

**1. How it was made**

- 91 consecutive simulated days (7 Sep - 6 Dec 2026): 40 robots, an 80 x 50 m warehouse, 1,584 rack bays.
- Each day has its own conditions:
- Order volume from the weekday (Sunday about 64 % of a weekday), the season (end of November 27 % busier) and promotion days (Singles Day, Black Friday, Cyber Monday).
- Robot faults at a different rate each day: battery spike, slowdown, stop, route deviation, overheating.
- Hazards: aisle closures, dropped parcels and fallen pallets.
- Runtime: about 45 minutes using parallel processes.

**2. The six datasets**

| Dataset | Size | Used for | What the model predicts |
|---|---|---|---|
| tasks | 161,221 rows | ML: ETA and late risk | How long an order takes; will it be late? |
| demand_hourly | 2,184 rows | ML / DL: forecasting | Orders in the next hour, by priority, category and zone |
| anomaly_windows | 5.2 million rows (13.6 % faulty) | ML: anomaly detection | Is the robot abnormal, and which fault? |
| Camera images | 2,400 images | Computer vision | Boxes for robots, workers, shelves, parcels, pallets, barriers |
| NLP commands | 5,461 messages | NLP and Transformers | Intent, entities, which tool to call |
| RAG knowledge base | 7 documents, 119 questions | RAG | The correct answer with its source section |

Also included: 92 agent scenarios, reference tables (zones, aisles, shelves, products, robots) and raw logs (telemetry 26 million rows, events 27 million, hazards).

**3. Example rows**

- ETA: inputs route distance 82 m, battery 93 %, motor 24 C, congestion 0.3, Monday 09:00, 2 items, 9.8 kg. Answer: 91 ticks, not late.
- Anomaly: inputs movement rate 0.35, 6 stops, temperature max 71 C. Answer: overheating.
- NLP: "Close aisle 7 for spill cleanup". Answer: intent close_aisle, entities AISLE_07 and spill cleanup, tool close_aisle(AISLE_07).

**4. Rules that make it trustworthy**

- Split by time, not at random: first 9 weeks train, next 2 validation, last 2 test (including Black Friday).
- No leakage: inputs only contain what was known at decision time; values known after delivery are never inputs.
- Vision split by simulation run; NLP test set uses unseen phrasings.
- Versioned: every row carries v3, so old and new data never mix.
- 63 automatic checks pass: demand follows the plan (correlation 0.99), peak hour 6.4 times the quietest hour, overheating windows 56 C vs 34 C normal.

**5. Formats.** Parquet for tables, YOLO / COCO for images, JSONL for NLP, RAG and agents, Markdown and PDF for documents.

**Closing line:** One simulator feeds every AI layer: labelled, versioned, leak-free datasets for ML, deep learning, vision, NLP, RAG and agents, all checked automatically before training.
