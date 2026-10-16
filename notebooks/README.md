# Notebooks

Exploration and model training. Production logic lives in importable modules (TRD TR-ENG-06).

## Phase 3: classical ML (run on a laptop CPU)

Each notebook follows the same 10 steps: understand, explore, choose target and features, split,
preprocess, baseline, train, validate and tune, test once, save and report. Every code cell has a
description cell above it, and the last cell summarises what was predicted, how it was before and the
results.

| Notebook | Model | Algorithms compared | Data | Saves |
| --- | --- | --- | --- | --- |
| `01_eta.ipynb` | Delivery time (regression) | Linear, Random Forest, Gradient Boosting, XGBoost | `tasks.parquet` | `models/eta_v1.joblib` |
| `02_late_risk.ipynb` | Late-order risk (classification) | Logistic, Random Forest, Gradient Boosting, XGBoost | `tasks.parquet` | `models/late_risk_v1.joblib` |
| `03_demand.ipynb` | Orders next hour (time series) | Linear, Random Forest, Gradient Boosting, XGBoost | `demand_hourly.parquet` | `models/demand_v1.joblib` |
| `04_anomaly.ipynb` | Robot faults | Isolation Forest, DBSCAN (unsupervised); Gradient Boosting, XGBoost (supervised) | `anomaly_windows.parquet` | `models/anomaly_v1.joblib`, `models/anomaly_iforest_v1.joblib` |
| `05_demand_breakdown.ipynb` | Next-hour lines per zone and orders per priority | Linear, Gradient Boosting, XGBoost (per target) | `demand_hourly.parquet` | `models/demand_breakdown_v1.joblib` |

## Phase 4: optimisation

| Notebook | Content |
| --- | --- |
| `06_optimization_experiments.ipynb` | Results of the Phase 4 experiments (E1–E5): every decision strategy on the same orders, faults and hazards, compared with the E2 baseline. Run `python scripts/run_experiments.py` first. |

No model is trained in Phase 4: it uses the Phase 3 ETA and demand models inside the decisions
(`ai/optimization/`). Design and method: `docs/phase4_optimization.md`.

All Phase 3 data comes from `data/processed/classical_ml/`. Each model also writes a `*_report.json` with every
validation and test score.

In VS Code, open a notebook, select the `.venv` Python kernel (top right), then use **Run All**.

## Live use

The backend (`apps/backend/app/services/predictor.py`) loads the saved models, predicts on the running
simulation, shows the results on the dashboard, and stores every prediction with its real outcome in
PostgreSQL (`predictions`, `model_versions`, `alerts`).

## Cloud

- `cloud/train_on_gpu.ipynb`: train GPU-heavy models on Colab, Kaggle or Azure ML.
