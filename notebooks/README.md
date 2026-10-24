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

## Phase 5: deep learning + vision

| Notebook | Question | Result (test) |
|---|---|---|
| `07_deep_learning_faults.ipynb` | Do neural networks detect robot faults better than XGBoost? MLP on the 13 summaries, LSTM on the raw 10-reading sequence, plus XGBoost on the raw sequence as a control | **LSTM F1 0.835** vs XGBoost 0.813, better on 14/14 test days; the gain comes from the time order |
| `08_deep_learning_demand.ipynb` | Do MLP, LSTM and Transformer (PatchTST-style) forecast hourly orders better than Gradient Boosting? 5 seeds each | **MAE 7.42-7.61** vs 8.51 (-10 to -13 %); trees cannot forecast above the peaks they have seen |
| `cloud/train_yolo_colab.ipynb` | YOLO11s object detector on the 2,400 camera images (Colab GPU) | mAP50 0.908, mAP50-95 0.699 |
| `09_vision_evaluation.ipynb` | Where does the detector fail (class, object size, camera)? Per-class safety thresholds, speed on a laptop CPU | Safety recall 0.90-0.97; small objects are the weak spot; 640 px = 0.75 s per image on CPU |

Shared code: `ai/deep_learning/anomaly.py` (telemetry sequences, MLP, LSTM), `ai/deep_learning/demand.py`
(history windows, MLP, LSTM, Transformer), `ai/computer_vision/evaluation.py` (box matching, sizes, thresholds). Sequences and finished demand runs are cached in
`data/processed/deep_learning/` (rebuilt automatically when missing). PyTorch runs on the laptop CPU.

## Phase 6: NLP + Transformers (operator commands)

| Notebook | Question | Result (test: phrasings never seen in training) |
|---|---|---|
| `10_nlp_commands_baselines.ipynb` | How far do keyword rules + regex entities and TF-IDF + Logistic Regression get? Honest validation split (whole templates held out), typo noise | Exact tool call: rules 0.656, **TF-IDF 0.725**; entities ≈ 1.0 for both; TF-IDF misses out-of-scope requests (recall 0.04) |
| `11_nlp_transformer.ipynb` | Does a fine-tuned DistilBERT (intent head + BIO entity head on one encoder) understand new phrasings better? Confidence calibration | **Exact tool call 0.807**, 0.762 with typos; above 0.99 confidence right 98.5 %; remaining errors are opposites (open/close, resume/pause) |

Data: `python scripts/generate_nlp_data.py` → `data/processed/nlp/commands.jsonl` (5,461 messages, 17 intents,
13 entity types). Shared code: `ai/nlp/commands.py` (canonical values, tool calls, approval: also used to label
the data), `ai/nlp/intent_parser.py` (baselines), `ai/nlp/evaluation.py`, `ai/transformers/intent_transformer.py`.
DistilBERT fine-tunes in about 30 min on a laptop CPU (`python scripts/train.py --phase 6`).

## Live use

The backend (`apps/backend/app/services/predictor.py`) loads the saved models, predicts on the running
simulation, shows the results on the dashboard, and stores every prediction with its real outcome in
PostgreSQL (`predictions`, `model_versions`, `alerts`).

## Cloud

- `cloud/train_on_gpu.ipynb`: train GPU-heavy models on Colab, Kaggle or Azure ML.
- `cloud/train_yolo_colab.ipynb` (Phase 5): trains the YOLO object detector on a free Colab T4 GPU.
  1. On your computer: `python scripts/package_vision_dataset.py` makes `data/exports/warehouse_vision_v3.zip`
     (2,400 images, 265 MB); upload it to the top folder of your Google Drive.
  2. Open the notebook in Colab, choose *Runtime → Change runtime type → T4 GPU*, then *Run all* (about 30-45 min).
  3. Unzip the downloaded `warehouse_yolo_results.zip` into `models/` (gives `models/vision_yolo_v1/best.pt`
     and its test report).
