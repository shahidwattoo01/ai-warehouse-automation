# Model artefacts

Trained models live here. They are **not committed to Git** (size, and they are reproducible):
retrain them with `python scripts/train.py` (see `--list`), or copy them from another machine.

| File | Model | Version in the app | Written by |
|---|---|---|---|
| `eta_v1.joblib` + `eta_v1_report.json` | ETA (Gradient Boosting) | eta v1 | `notebooks/01_eta.ipynb` |
| `late_risk_v1.joblib` + report | Late risk (Logistic Regression) | late v1 | `notebooks/02_late_risk.ipynb` |
| `demand_v1.joblib` + report | Demand (Gradient Boosting) | demand v1 (live default) | `notebooks/03_demand.ipynb` |
| `anomaly_v1.joblib`, `anomaly_iforest_v1.joblib` + report | Anomaly (XGBoost; Isolation Forest for comparison) | anomaly v1 (fallback) | `notebooks/04_anomaly.ipynb` |
| `demand_breakdown_v1.joblib` + report | Demand per zone / priority | demand_breakdown v1 | `notebooks/05_demand_breakdown.ipynb` |
| `anomaly_lstm_v1.pt`, `anomaly_mlp_v1.pt`, `anomaly_dl_v1_report.json` | Anomaly LSTM (and MLP for comparison) | **anomaly v2 (live)** | `notebooks/07_deep_learning_faults.ipynb` |
| `demand_dl_v1.pt`, `demand_dl_v1_report.json` | Demand network (Transformer) | demand v2 (`WAREHOUSE_DEMAND_MODEL=network`) | `notebooks/08_deep_learning_demand.ipynb` |
| `vision_yolo_v1/` (`best.pt`, `report.json`, `evaluation.json`, training charts) | Object detector (YOLO11s) | vision v1 | Colab: `notebooks/cloud/train_yolo_colab.ipynb`; evaluation: `notebooks/09_vision_evaluation.ipynb` |
| `nlp_tfidf_v1.joblib`, `nlp_baselines_report.json` | Command intents (TF-IDF + Logistic Regression) | copilot fallback | `notebooks/10_nlp_commands_baselines.ipynb` |
| `nlp_distilbert_v1/` (`encoder/`, `heads.pt`, `labels.json`, `report.json`; 254 MB) | Command intents + entities (fine-tuned DistilBERT) | **copilot (live)** | `notebooks/11_nlp_transformer.ipynb` |
| `rag_v1.json` | Knowledge assistant settings and evaluation (chunking, retriever, threshold) | rag v1 (the code defaults equal it) | `notebooks/12_rag.ipynb` |

* Every model has a `*_report.json` with its validation and test results (read by the app, the
  progress report and `scripts/train.py --list`), and a model card in `docs/model_cards/`.
* The app registers the versions it loads in the `model_versions` table when a run starts (one
  active version per model; the previous one is retired, not deleted). To inspect or register
  without starting the app: `python scripts/register_model.py [--db]`.
* PyTorch files are loaded with `weights_only=True` (tensors and plain values only).
