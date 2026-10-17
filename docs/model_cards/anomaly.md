# Model card · Robot anomaly (fault) detection (v2 live, v1 fallback)

| | v2 (live) | v1 (fallback) |
|---|---|---|
| **Task** | Is a robot developing a fault in its last 20 ticks? (battery spike, speed degradation, stop event, route deviation, overheating) | same |
| **Algorithm** | LSTM (PyTorch): 10 readings × 12 telemetry channels, memory 64, early stopping | XGBoost on 13 window summaries |
| **Threshold** | chosen on validation for the best F1 | 0.674 (validation) |
| **File** | `models/anomaly_lstm_v1.pt` · `notebooks/07_deep_learning_faults.ipynb` | `models/anomaly_v1.joblib` · `notebooks/04_anomaly.ipynb` |
| **Switch** | default when the file exists | `WAREHOUSE_ANOMALY_MODEL=xgboost` |

## Intended use
Flag robots for inspection (dashboard health, `ANOMALY` alerts). It does not stop robots.

## Inputs (per reading, every 2 ticks)
Moved share, busy flag, battery and its step, motor temperature and its step, route length and its
step, blocked ticks, task elapsed, zone congestion, load. The robot status itself is excluded (a
FAULT status would reveal the label). A test asserts that the live inputs equal the training
inputs (`tests/unit/test_deep_learning.py`).

## Evaluation (test = last 14 days, 805,840 windows)

| Model | Precision | Recall | F1 |
|---|---|---|---|
| v1 XGBoost | 0.956 | 0.707 | 0.813 |
| **v2 LSTM** | 0.942 | **0.749** | **0.835** |

* Better on **14 of 14** test days; day-bootstrap 95 % interval of the F1 gain: +0.020 to +0.023.
* Control models: an MLP on the same summaries (0.810) and XGBoost on the raw readings (0.819)
  show that the gain comes from reading the readings in time order.
* Live check (same simulated day, 10 h): precision 0.951 / recall 0.865 (v1: 0.932 / 0.795).

**Recall per fault type (v1 → v2):** overheating 0.98 → 0.99, battery spike 0.69 → 0.76, speed
degradation 0.62 → 0.69, stop event 0.62 → 0.68, route deviation 0.08 → 0.16.

## Limitations
* Route deviations remain hard (16 % caught): a detour looks like normal re-routing.
* Faults come from the simulator's fault model; real robots fail differently and need their own
  labelled telemetry.
* One training seed (the per-day consistency makes the result reliable).
