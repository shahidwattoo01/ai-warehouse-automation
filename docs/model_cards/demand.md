# Model card · Demand forecast (v1 live, v2 network opt-in)

| | v1 (live default) | v2 (opt-in) |
|---|---|---|
| **Task** | Orders arriving in the next simulated hour | same |
| **Algorithm** | Gradient Boosting (lr 0.03, min leaf 30) | Transformer, PatchTST-style (14 patches of 12 h), best seed of 5 |
| **Inputs** | 11 features: hour (sin/cos), weekday, weekend, month, promotion, lags 1 h / 2 h / 24 h / 168 h, 24 h mean | last 168 hours of orders (+ hour, weekend, promotion per hour) and the calendar of the forecast hour |
| **File** | `models/demand_v1.joblib` · `notebooks/03_demand.ipynb` | `models/demand_dl_v1.pt` · `notebooks/08_deep_learning_demand.ipynb` |
| **Switch** | default | `WAREHOUSE_DEMAND_MODEL=network` |

Also live: **demand breakdown v1** (`models/demand_breakdown_v1.joblib`, `notebooks/05`): one model
per storage zone (order lines) and per priority (orders); Linear Regression or XGBoost per target,
all 19-27 % better than "same hour last week".

## Intended use
Plan the next hour: robot positioning and charging (Phase 4), staffing, and the dashboard forecast.

## Evaluation (test = 23 Nov - 6 Dec, 336 hours, includes Black Friday and Cyber Monday)

| Model | MAE (orders/hour) |
|---|---|
| Baseline: same hour last week | 10.34 |
| **v1 Gradient Boosting** | **8.51** |
| MLP / LSTM / Transformer, 5-seed ensembles | 7.42 / 7.61 / 7.44 |

Why the networks are better on test: tree models cannot forecast above the busiest hours they were
trained on (v1 never forecast above 146 orders/hour; the test weeks reach 179). Networks
extrapolate. The gain is concentrated on promotion days (Cyber Monday error 13.8 → 9.5).

## Why v1 stays the live default
v2 reads the last 168 real hours. At the start of a live run those hours are mostly planning
estimates, and over a 10-hour live run v1 was better (MAE 6.3 vs 7.9). v2 is meant for runs with
a week of real history.

## Limitations
* 1,344 training hours: small for deep learning (hence 5 seeds and ensembles).
* One simulated season; a real site needs its own history, holidays and promotions.
