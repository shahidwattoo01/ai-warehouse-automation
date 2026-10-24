# Phase 5 · Deep learning + vision

Phase 3 made the warehouse **predict** with classical ML; Phase 4 used the predictions to
**decide** better. Phase 5 asks two questions and adds a new sense:

1. Do **neural networks** predict better than the Phase 3 models, and **why**?
2. Can the warehouse **see**: detect robots, people and hazards in camera images?

Every answer is measured on the same held-out test data as Phase 3, against the Phase 3 model,
with control models that explain the result. A beginner-level explanation of every technique is
in [phase4_phase5_explained.md](phase4_phase5_explained.md); model details are in the
[model cards](model_cards/README.md).

## 1. What was built

| Part | What | Where |
|---|---|---|
| Fault detection | LSTM on the raw telemetry sequence (10 readings × 12 channels) | `ai/deep_learning/anomaly.py`, `notebooks/07_deep_learning_faults.ipynb` |
| Demand forecast | MLP, LSTM and Transformer (PatchTST-style) on 168 hours, 5 seeds each | `ai/deep_learning/demand.py`, `notebooks/08_deep_learning_demand.ipynb` |
| Object detector | YOLO11s fine-tuned on 2,400 rendered camera images (Colab T4 GPU) | `notebooks/cloud/train_yolo_colab.ipynb`, `scripts/package_vision_dataset.py` |
| Detector evaluation | Per class, object size and camera; per-class safety thresholds | `notebooks/09_vision_evaluation.ipynb`, `ai/computer_vision/evaluation.py` |
| Live integration | LSTM as live fault detector; demand network opt-in; detector service | `ai/deep_learning/live.py`, `ai/classical_ml/live_predictor.py`, `ai/computer_vision/live.py` |
| API | `GET /api/v1/vision/status`, `POST /api/v1/vision/detect` | `apps/backend/app/api/v1/vision.py` |
| Vision page | Single camera with detection; camera wall (all cameras), detect all, live detection for moving robots | `apps/frontend/app/vision/page.tsx`, `apps/frontend/components/three/CameraFeed.tsx` |

## 2. Results

### Fault detection (test: last 14 days, 805,840 windows)

| Model | Input | Precision | Recall | F1 |
|---|---|---|---|---|
| XGBoost v1 (Phase 3) | 13 summaries | 0.956 | 0.707 | 0.813 |
| XGBoost (control) | raw sequence, flattened | 0.964 | 0.712 | 0.819 |
| MLP (control) | 13 summaries | 0.955 | 0.703 | 0.810 |
| **LSTM** | **raw sequence, in order** | 0.942 | **0.749** | **0.835** |

Better on **14 of 14** test days (95 % interval of the gain +0.020 to +0.023 F1). The controls
show the gain comes from reading the readings **in time order**. Live, on the same simulated day:
precision 0.951 / recall 0.865 (XGBoost 0.932 / 0.795).

### Demand forecast (test: 23 Nov - 6 Dec, includes Black Friday and Cyber Monday)

| Model | Test MAE (orders/hour) |
|---|---|
| Same hour last week | 10.34 |
| Gradient Boosting v1 (Phase 3) | 8.51 |
| **MLP / LSTM / Transformer, 5-seed ensembles** | **7.42 / 7.61 / 7.44** |

Why: tree models cannot forecast above the busiest hours they were trained on (Gradient Boosting
never exceeded 146 orders/hour; the test weeks reach 179). Networks extrapolate; the gain is
largest on promotion days. Controls: Gradient Boosting with absolute-error loss does not improve
(8.49), so the loss is not the reason.

### Object detection (336 test images)

| Setting | Precision | Recall | mAP@0.5 | mAP@0.5:0.95 |
|---|---|---|---|---|
| 960 px (GPU) | 0.926 | 0.846 | **0.908** | 0.699 |
| 640 px (laptop CPU, used live, ~0.75 s per frame) | 0.935 | 0.797 | 0.877 | 0.652 |

Safety recall with the tuned thresholds: workers 0.935, dropped parcels 0.964, closed-aisle
barriers 0.967, obstacles 0.895. Weak spot: small, distant objects.

## 3. Decisions (and why)

| Decision | Reason | Record |
|---|---|---|
| LSTM replaces XGBoost as the live fault detector | Better offline (14/14 days) and live; XGBoost kept as fallback | [ADR 002](adr/002-lstm-live-fault-detector.md) |
| Gradient Boosting stays the live demand model | The network needs a week of real history; at the start of a live run it was worse (MAE 7.9 vs 6.3) | [ADR 003](adr/003-demand-model-live-default.md) |
| YOLO runs in its own worker process | In the API process the simulator loop held the interpreter lock: 52 s per frame instead of 1-3 s | [ADR 004](adr/004-detector-worker-process.md) |
| Safety classes use low confidence thresholds, duplicates merged | A missed person is worse than a false alarm; duplicate merging only where it does not hide real objects (measured) | [ADR 005](adr/005-safety-first-detection-thresholds.md) |

## 4. How to reproduce

```bash
python scripts/train.py --list                 # models, notebooks, current results
python scripts/train.py --model anomaly_lstm   # notebook 07 (~15 min, laptop CPU)
python scripts/train.py --model demand_net     # notebook 08 (~15 min; finished runs are cached)
python scripts/package_vision_dataset.py       # then train YOLO on Colab (notebooks/README.md)
python scripts/train.py --model vision         # notebook 09 (needs models/vision_yolo_v1/best.pt)
```

Seeds are fixed: retraining reproduces the same models (verified for the ETA model: identical
report). Tests: `tests/unit/test_deep_learning.py` (including "live inputs equal training
inputs"), `tests/unit/test_vision.py`, `apps/backend/tests/test_vision_api.py`, and the browser
tests in `tests/e2e/`.

## 5. Limitations

* **Simulator data only.** Faults, demand and camera images come from the simulator; a real site
  needs its own data (and, for vision, domain randomisation plus labelled real footage).
* **Route deviations** remain hard for every fault model (16 % caught by the LSTM).
* **Small data for demand** (1,344 training hours): results are averaged over 5 seeds; the gain
  is concentrated on unusual peak days.
* **Vision on a laptop CPU** analyses about one frame per second; the camera wall therefore
  photographs the cameras in turn rather than streaming video.
* **Ultralytics YOLO is AGPL-3.0** (see `THIRD_PARTY_LICENSES.md`).
