# Project structure

`__init__.py` and `.gitkeep` files omitted.

```
warehouse-ai-platform/
├── ai/
│   ├── agents/
│   │   ├── specialists/
│   │   │   ├── fleet.py
│   │   │   ├── inventory.py
│   │   │   ├── knowledge.py
│   │   │   ├── maintenance.py
│   │   │   ├── navigation.py
│   │   │   ├── planner.py
│   │   │   └── vision.py
│   │   ├── graph.py
│   │   ├── supervisor.py
│   │   └── tools.py
│   ├── classical_ml/
│   │   ├── anomaly/
│   │   │   ├── features.py
│   │   │   └── model.py
│   │   ├── demand/
│   │   │   ├── features.py
│   │   │   └── model.py
│   │   └── eta/
│   │       ├── features.py
│   │       └── model.py
│   ├── common/
│   │   └── base.py
│   ├── computer_vision/
│   │   ├── detection/
│   │   │   └── detector.py
│   │   └── preprocessing/
│   │       └── frames.py
│   ├── deep_learning/
│   │   ├── forecasting/
│   │   │   ├── lstm.py
│   │   │   └── ts_transformer.py
│   │   └── models/
│   │       └── mlp.py
│   ├── embeddings/
│   │   └── embedder.py
│   ├── nlp/
│   │   └── intent_parser.py
│   ├── optimization/
│   │   ├── assignment.py
│   │   ├── astar.py
│   │   ├── dijkstra.py
│   │   └── reservations.py
│   ├── rag/
│   │   ├── ingest.py
│   │   └── retriever.py
│   ├── reinforcement_learning/
│   │   ├── dqn_agent.py
│   │   ├── env.py
│   │   └── marl.py
│   └── transformers/
│       └── intent_transformer.py
├── apps/
│   ├── backend/
│   │   ├── app/
│   │   │   ├── api/
│   │   │   │   └── v1/
│   │   │   │       ├── _phase.py
│   │   │   │       ├── agents.py
│   │   │   │       ├── analytics.py
│   │   │   │       ├── copilot.py
│   │   │   │       ├── inventory.py
│   │   │   │       ├── navigation.py
│   │   │   │       ├── orders.py
│   │   │   │       ├── prediction.py
│   │   │   │       ├── rag.py
│   │   │   │       ├── robots.py
│   │   │   │       ├── simulation.py
│   │   │   │       ├── tools.py
│   │   │   │       └── vision.py
│   │   │   ├── core/
│   │   │   │   └── config.py
│   │   │   ├── database/
│   │   │   │   ├── migrations/
│   │   │   │   │   ├── versions/
│   │   │   │   │   │   └── 001_initial_schema.py
│   │   │   │   │   ├── env.py
│   │   │   │   │   └── script.py.mako
│   │   │   │   ├── schema.sql
│   │   │   │   └── session.py
│   │   │   ├── schemas/
│   │   │   │   ├── models.py
│   │   │   │   └── simulation.py
│   │   │   ├── services/
│   │   │   │   └── simulator.py
│   │   │   └── main.py
│   │   ├── tests/
│   │   │   └── test_api_smoke.py
│   │   └── alembic.ini
│   └── frontend/
│       ├── app/
│       │   ├── analytics/
│       │   │   └── page.tsx
│       │   ├── copilot/
│       │   │   └── page.tsx
│       │   ├── dashboard/
│       │   │   └── page.tsx
│       │   ├── fleet/
│       │   │   └── page.tsx
│       │   ├── knowledge/
│       │   │   └── page.tsx
│       │   ├── orders/
│       │   │   └── page.tsx
│       │   ├── simulation/
│       │   │   └── page.tsx
│       │   ├── globals.css
│       │   ├── layout.tsx
│       │   └── page.tsx
│       ├── components/
│       │   ├── charts/
│       │   ├── copilot/
│       │   ├── layout/
│       │   │   ├── Header.tsx
│       │   │   ├── Screen.tsx
│       │   │   ├── Sidebar.tsx
│       │   │   ├── SimProvider.tsx
│       │   │   └── StatusBar.tsx
│       │   ├── three/
│       │   │   ├── Building.tsx
│       │   │   ├── Racking.tsx
│       │   │   ├── Robot.tsx
│       │   │   ├── RobotLayer.tsx
│       │   │   ├── Stations.tsx
│       │   │   ├── WarehouseScene.tsx
│       │   │   ├── assets.ts
│       │   │   └── coords.ts
│       │   └── ui/
│       │       ├── KpiCard.tsx
│       │       └── PhasePlaceholder.tsx
│       ├── lib/
│       │   ├── api.ts
│       │   ├── store.ts
│       │   └── types.ts
│       ├── public/
│       │   ├── hdri/
│       │   ├── models/
│       │   │   └── README.md
│       │   └── textures/
│       ├── next-env.d.ts
│       ├── next.config.mjs
│       ├── package.json
│       ├── postcss.config.mjs
│       ├── tailwind.config.ts
│       └── tsconfig.json
├── configs/
│   ├── experiments/
│   │   ├── E1.yaml
│   │   ├── E2.yaml
│   │   ├── E3.yaml
│   │   ├── E4.yaml
│   │   ├── E5.yaml
│   │   ├── E6.yaml
│   │   └── E7.yaml
│   ├── layouts/
│   │   └── default.yaml
│   ├── models.yaml
│   └── simulation.yaml
├── data/
│   ├── documents/
│   │   └── README.md
│   ├── processed/
│   ├── raw/
│   └── synthetic/
├── docker/
│   ├── backend.Dockerfile
│   └── frontend.Dockerfile
├── docs/
│   ├── adr/
│   │   └── 001-web-3d-simulator-rendering.md
│   └── README.md
├── evaluation/
│   ├── agents/
│   │   └── eval.py
│   ├── ml/
│   │   └── compare.py
│   ├── rag/
│   │   └── eval.py
│   ├── reports/
│   ├── simulation/
│   │   └── metrics.py
│   └── harness.py
├── models/
│   └── README.md
├── monitoring/
│   ├── README.md
│   └── model_monitor.py
├── notebooks/
│   ├── cloud/
│   │   └── train_on_gpu.ipynb
│   └── README.md
├── scripts/
│   ├── capture_frames.py
│   ├── generate_data.py
│   ├── register_model.py
│   ├── run_experiments.py
│   ├── seed.py
│   └── train.py
├── simulation/
│   ├── camera/
│   │   └── capture.py
│   ├── environment/
│   │   ├── congestion.py      # robots per zone / capacity
│   │   ├── engine.py          # tick loop: wires the parts below together; commands; state
│   │   ├── faults.py          # labelled fault injection (anomaly training data)
│   │   ├── recorder.py        # turns a run into training tables
│   │   └── workers.py         # pedestrians as dynamic obstacles
│   ├── events/
│   │   └── events.py
│   ├── inventory/
│   │   └── inventory.py       # stock per rack bay, pick faces, restocking
│   ├── navigation/
│   │   └── planner.py
│   ├── orders/
│   │   ├── dispatcher.py      # which robot gets which order (auto / manual)
│   │   └── generator.py       # customer demand + operator orders
│   ├── robots/
│   │   └── controller.py      # robot tasks, movement, traffic, charging, parking
│   └── warehouse/
│       ├── entities.py
│       ├── grid.py
│       └── layout.py
├── tests/
│   ├── integration/
│   ├── scenarios/
│   └── unit/
│       ├── golden_master.py   # behaviour fingerprint for safe refactors
│       ├── test_data_pipeline.py
│       └── test_simulation_core.py
├── .env.example
├── .gitignore
├── README.md
├── docker-compose.yml
├── pyproject.toml
├── requirements-dev.txt
└── requirements.txt
```
