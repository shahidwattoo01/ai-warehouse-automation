# ADR 002 — LSTM replaces XGBoost as the live fault detector

**Status:** Accepted · 2026-10-17

## Context

Phase 3 detected robot faults with XGBoost on 13 summary features per 20-tick window (test F1
0.813). It missed most route deviations (8 %) and a third of speed degradations: faults that
unfold over time. Phase 5 tested neural networks on exactly the same windows and test days
(`notebooks/07_deep_learning_faults.ipynb`), with two control models to explain any gain.

## Decision

- The **LSTM** on the raw sequence (10 readings × 12 channels) becomes the live fault detector,
  registered as **anomaly v2** (`models/anomaly_lstm_v1.pt`).
- **XGBoost v1 stays as the fallback**: used automatically if the LSTM file or PyTorch is missing,
  or on request with `WAREHOUSE_ANOMALY_MODEL=xgboost`.
- Live inputs are built by `ai/deep_learning/live.py`; a test asserts they equal the training
  inputs (training/serving skew guard).

## Evidence

| | XGBoost v1 | LSTM v2 |
|---|---|---|
| Test F1 (805,840 windows) | 0.813 | **0.835** (better on 14/14 days, 95 % CI of the gain +0.020…+0.023) |
| Live, same simulated day: precision / recall | 0.932 / 0.795 | **0.951 / 0.865** |

Controls: an MLP on the same summaries (0.810) and XGBoost on the raw readings (0.819) show
that the gain comes from reading the readings in time order.

## Consequences

- PyTorch becomes a runtime dependency of the backend (CPU build; ~10 ms per 1,000 windows).
- The `model_versions` table now holds two anomaly versions; registering v2 retires v1 (it stays
  for history). The run store handles this (`SQL_RETIRE_OTHER_VERSIONS`).
- Route deviations remain hard (16 % caught); a future model could use the planned route itself.
