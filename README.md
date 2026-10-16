# Warehouse AI Platform

**AI-Powered Autonomous Warehouse Automation & Fleet Intelligence Platform**

A simulated intelligent warehouse — robots, orders, shelves, inventory, workers and packing stations living inside one simulator — with ten AI layers on top: classical ML, deep learning, computer vision, NLP + Transformers, RAG, tool calling, agents and multi-agent coordination, optimization and reinforcement learning. Operators control it through a realistic 3D web Control Center and an AI Operations Copilot.

> Final project — NAVTTC AI/ML training, NetSol Technologies, Lahore.

---

## Core principles

1. **The simulator is the single source of truth.** Every AI component reads the same `warehouse_state` and changes it only through the simulator's command API.
2. **The simulator generates all training data.** ML, DL, CV and RL models train and evaluate on data from simulator runs.
3. **All ten layers are mandatory.** DL, CV, NLP + Transformers, RAG, agents, multi-agent, optimization and RL are core deliverables.
4. **LLMs act only through tools.** Write actions need operator approval; the backend validates everything.
5. **Baselines first.** Classical ML before neural nets, Dijkstra/A\* before RL — every advanced model is measured against its baseline.

## Architecture

```
Next.js Control Center (React Three Fiber 3D view)
        │  REST /api/v1  +  WebSocket /simulation/stream
        ▼
FastAPI backend ──► Copilot + orchestrator (NLP, LangGraph agents)
        │                 │                     │
        │            AI modules            Tool registry (validation + approval)
        │                 │                     │
        └───────────► Simulator engine (single source of truth) ◄──┘
                          │
          PostgreSQL (+pgvector)      models/ (versioned artefacts)
```

The Python simulator owns the logic (grid, tick loop, robots, orders, events). The browser renders it in **realistic 3D** — PBR glTF models of robots, racking, pallets and stations, HDRI lighting and shadows — driven by the live WebSocket stream.

## Repository layout

| Path | Contents |
| --- | --- |
| `apps/backend/` | FastAPI service: `/api/v1` routers, Pydantic schemas, database, services, WebSocket stream |
| `apps/frontend/` | Next.js + Tailwind Control Center; `components/three/` holds the 3D warehouse scene |
| `simulation/` | Simulator engine: warehouse grid, robots, orders, inventory, navigation, events, camera |
| `ai/` | One package per AI layer, all implementing `ai.common.base.AIModule` |
| `configs/` | Warehouse layouts, simulation settings, experiments E1–E7, model registry config |
| `data/` | `raw/`, `processed/`, `synthetic/` (simulator output) and `documents/` (RAG knowledge base) |
| `models/` | Trained model artefacts with version and metrics |
| `evaluation/` | Experiment harness and metric reports (ML, RAG, agents, simulation) |
| `notebooks/cloud/` | Colab / Kaggle / Azure GPU training notebooks |
| `scripts/` | Seed, data generation, training and experiment entry points |
| `tests/` | Unit, integration and agent scenario tests |
| `docs/` | Planning documents and architecture decision records |
| `reports/` | **Main project report** (`Project_Progress_Report.pdf`), updated at the end of every phase |

## Quick start

```bash
cp .env.example .env
docker compose up --build          # postgres + backend + frontend
# Backend:  http://localhost:8000/docs
# Frontend: http://localhost:3000
```

Local development without Docker:

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt -r requirements-dev.txt
cd apps/frontend && npm install && cd ../..

python tasks.py backend   # FastAPI with reload  -> http://localhost:8000/docs
python tasks.py frontend  # Next.js dev server    -> http://localhost:3000
python tasks.py test
```

## Training on cloud GPUs

There is no local GPU requirement. The simulator, API and 3D view run on a normal laptop; heavy training (LSTM, Transformers, vision, RL) runs on **Google Colab, Kaggle or Azure ML**:

1. Generate datasets locally: `python scripts/generate_data.py --runs 50`
2. Open `notebooks/cloud/train_on_gpu.ipynb` in Colab/Kaggle, upload `data/processed/` (or clone the repo).
3. Download the trained artefacts into `models/` and register them: `python scripts/register_model.py`.

## Build phases

| # | Phase | # | Phase |
| --- | --- | --- | --- |
| 1 | Foundation | 7 | RAG |
| 2 | Simulator (realistic 3D) | 8 | Tools + agents |
| 3 | Classical ML | 9 | Multi-agent + RL |
| 4 | Optimization | 10 | Integration |
| 5 | Deep learning + vision | 11 | Evaluation (E1–E7) |
| 6 | NLP + Transformers | 12 | Finalization |

Progress and the phase-by-phase KPI comparison: [`reports/Project_Progress_Report.pdf`](reports/Project_Progress_Report.pdf) (see `reports/README.md`).

See `docs/README.md` for the PRD, TRD, App Flow, UI/UX brief, Backend Schema and Implementation Plan.
