# ADR 003 — Gradient Boosting stays the live demand model; the network is opt-in

**Status:** Accepted · 2026-10-17

## Context

On the offline test weeks (23 Nov - 6 Dec, with Black Friday and Cyber Monday) every neural
network beat the Phase 3 Gradient Boosting forecast: MAE 7.42-7.61 vs 8.51 orders/hour
(`notebooks/08_deep_learning_demand.ipynb`). The reason is extrapolation: trees never forecast
above the busiest hours seen in training (146), while the test weeks reach 179.

The best network (a PatchTST-style Transformer) reads the **last 168 real hours**. A live run in
the app starts with no history: those hours are filled with planning estimates.

## Decision

- **Gradient Boosting v1 remains the default** live demand model.
- The network (`models/demand_dl_v1.pt`, demand v2) is available with
  `WAREHOUSE_DEMAND_MODEL=network`, for runs with about a week of real history.

## Evidence

Same simulated day, first 10 hours live: Gradient Boosting MAE **6.3**, network **7.9**. Offline,
with full history, the network is better (7.44 vs 8.51), and most of its gain is on promotion days.

## Consequences

- The deployed default is the model measured best *in the situation it is used in*, not the one
  with the best offline score; both results are reported (model card, Phase 5 document).
- Revisit when live runs keep a week of history (Phase 10 integration), or train a variant that
  is robust to a short history.
