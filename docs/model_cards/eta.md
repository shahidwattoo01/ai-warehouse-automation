# Model card · ETA (delivery time) v1

| | |
|---|---|
| **Task** | Regression: ticks from the moment an order is assigned to a robot until it is delivered |
| **Algorithm** | Gradient Boosting (scikit-learn `HistGradientBoostingRegressor`), chosen on validation among Linear Regression, Random Forest, Gradient Boosting and XGBoost |
| **File** | `models/eta_v1.joblib` (report `models/eta_v1_report.json`) · trained in `notebooks/01_eta.ipynb` |
| **Used by** | Live ETA per order (dashboard), late-risk features, Phase 4 assignment (`ai/optimization/eta_estimator.py`) |

## Intended use
Estimate when an assigned order will arrive, and compare candidate robots for an order (Phase 4
assignment strategies E4c/E4d). Not intended for promising delivery times to customers.

## Inputs (known at assignment time only)
Route distance (planned and straight-line), robot battery, motor temperature and current speed,
zone congestion, fleet busy share, waiting orders, time already queued, active aisle closures and
floor hazards, order size (lines, units, weight), priority, main product category, hour (sine /
cosine), weekday, weekend and promotion flags. Leakage guard: outcome columns (moves, waits,
re-routes, delivery time) are asserted not to be features.

## Evaluation (test = last 14 days)

| Metric | ETA v1 | Baseline: training mean |
|---|---|---|
| MAE (ticks) | **38.8** | 65.4 |
| RMSE (ticks) | **55.3** | 85.7 |
| R² | **0.564** | -0.045 |

## Limitations
* Waiting caused by events after assignment (a new closure, a jam) cannot be known in advance; this
  is most of the remaining error (R² 0.56).
* Trained on the baseline dispatcher's behaviour (E2); under other strategies its errors may shift.
* Simulator data only (see the [index](README.md)).
