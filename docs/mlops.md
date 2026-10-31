# Model operations (MLOps)

Backlog PR-19. Before this, the models were trained once by the notebooks and then used for
ever. Now the platform watches whether they are still right, retrains them when they are not, and
lets a new version go live only after it passes a set of tests.

Code:

* [`ai/mlops/`](../ai/mlops): `drift.py`, `registry.py`, `retrain.py`.
* [`app/services/mlops.py`](../apps/backend/app/services/mlops.py): runs next to the live
  simulator.
* API `/api/v1/mlops`, and the **AI models** page.
* Settings in [`configs/mlops.yaml`](../configs/mlops.yaml).

Covered: the two order models, **ETA** and **late risk**. Their outcomes are known within minutes,
because every finished order reports its real delivery time. The demand and anomaly models are
scored live on the dashboard but are not retrained here yet.

## How it works

```
finished order ──► window of the last 400 predictions with their real outcome
                        │ every 120 ticks
                        ▼
   input shift (PSI per feature vs the training data)        ──► WARN
   live error vs the test error, and vs the model's own error
   in its first hours in production                          ──► WARN / DRIFT
                        │ DRIFT twice in a row
                        ▼
   retrain (worker thread): clone of the production pipeline, fitted on 40,000 old rows
   + the live outcomes (each counts 3×); the newest 30 % of live outcomes kept out
                        │
                        ▼
   gate: schema · sane output · better now · not worse before · fast enough
        all pass ──► promoted: the live predictor switches between two ticks
        any fails ──► rejected: production stays as it is
```

### Two kinds of drift, and why only one starts retraining

**Input shift (data drift).**

* Each input's live distribution is compared with the training data by the Population Stability
  Index (PSI): below 0.1 is stable, 0.1–0.25 moderate, above 0.25 a major shift. Bins are the
  training deciles, or the categories for text inputs.
* The calendar inputs (hour, weekday, weekend, promo day) are not compared. A window of a few
  hours always has one weekday and one promo state, so they would always "differ".
* An input shift on its own is **WARN**. In the live warehouse, fleet busyness, queues and
  temperatures sit far from the training data (PSI 4–9), yet the ETA model's live error (18–24
  ticks) is lower than on its test set (38.8). Retraining such a model would only risk making it
  worse.

**Error growth (performance drift).**

* ETA: live mean absolute error compared with two references.
  * **Its test error.** This catches a model that is worse than it was shown to be.
  * **Its own error in its first hours in production**, measured over the first 300 outcomes.
    This catches decay even when live conditions are easier than the test set, which they are
    here.
* 1.2× either reference is WARN; 1.4× is **DRIFT**.
* Late risk: recall (the share of late orders it flagged) compared with the same two references.
  It is judged only once at least 30 late orders are in the window, because a handful of late
  orders says nothing.
* DRIFT on two checks in a row starts retraining, with a cooldown of two simulated hours.

### The gate

| Test | Passes when |
|---|---|
| schema | The same 21 input features as production |
| sane output | Finite predictions; ETA above 0; probabilities between 0 and 1 |
| better now | On the newest live outcomes (kept out of training): MAE at least 3 % lower, or F1 at least 0.03 higher |
| not worse before | On the original test split: at most 15 % worse. The model must not forget the warehouse it was built for |
| fast enough | Median of one prediction under 20 ms |

A rejected candidate can never be promoted, even by hand.

### Versions

* **Version 1** of each model is what the notebooks trained (`models/`).
* **Retrained versions** are written by the platform to `data/mlops/models/`, each with its
  report and reference profile. `data/mlops/registry.json` records:
  * every version and its status: candidate, production, archived or rejected;
  * its gate results;
  * its history: who promoted it, when, and why.
* A version promoted while a run is being recorded is registered in `model_versions`, so its
  predictions are stored under it.
* **Rollback** puts the previous production version back.
* **Commands** (they need `models:manage`, which admins and supervisors have; viewing needs
  `analytics:view`):
  * the API: `POST /api/v1/mlops/{model}/retrain`, `.../promote/{version}`, `.../rollback`;
  * the **AI models** page;
  * the command line: `python scripts/mlops.py --status | --promote eta v2 | --rollback eta`.
* **Reference profiles** of version 1 are built from the training data with
  `python scripts/mlops.py --build-reference`. `scripts/train.py` rebuilds them after retraining
  ETA or late risk.

Model events go onto the platform event bus as `warehouse/v1/models/{event}`:

* `status_ok`, `status_warn`, `status_drift`
* `retrain_started`, `retrain_failed`
* `candidate_ready`, `candidate_rejected`
* `promoted`, `rolled_back`

Metrics: `warehouse_model_status{model,status}`, `warehouse_model_live_error`,
`warehouse_model_input_psi_max`, `warehouse_model_production_version`,
`warehouse_model_retrains_total{result}`. Alert rules: `ModelDrift` (30 minutes) and
`ModelCandidateRejected`.

## The experiment

`python scripts/mlops_experiment.py` (default layout, 24,000 ticks, about 2 minutes) uses a
temporary registry:

1. The warehouse runs as trained. ETA live error is 22–26 ticks: status WARN (inputs shifted,
   error fine).
2. At tick 6,000 the site switches to **human-assisted picking at the racks**: 15 s per item
   instead of 2 s (`pick_ticks` 4 → 30). Pick time is not a model input, so deliveries take
   longer than the model expects. With the same robots, the backlog also starts to grow.
3. At tick 8,280 the live error is 33 ticks, 1.44× the model's own error at go-live, so DRIFT is
   confirmed. **v2** is retrained on 40,000 old + 442 live rows. Gate:

   | Test | Result |
   |---|---|
   | better now | MAE 34.7 vs 40.0 (13 % better) |
   | not worse before | test MAE 39.0 vs 38.8 (+0.5 %) |
   | fast enough | 8 ms |

   All tests passed, so v2 was promoted.
4. As the backlog keeps growing, DRIFT is confirmed again. **v3** is trained on 746 live rows.
   Gate: recent MAE 42.0 vs 52.0 (19 % better), test MAE +0.7 %. v3 was promoted.

**Did it help?** For the same orders after the change, here is what v1 would have predicted
compared with what the live version did (a shadow comparison):

| Orders served by | Orders | Live version's error | v1's error on the same orders |
|---|---|---|---|
| v2 | 435 | 49.2 ticks | 54.6 ticks (v2 is 10 % better) |
| v3 | 768 | 45.2 ticks | 55.1 ticks (v3 is 18 % better) |

The absolute errors still rise. Picking slowed while the robot count stayed the same, so queues
keep getting longer: the conditions get harder after each retraining. The shadow comparison shows
what the retraining was worth under those same conditions.

Live, in the platform at 10× speed: after 4,000 ticks both models were WARN with fleet busyness
shifted (PSI about 6). ETA live error was 18 ticks against 38.8 on the test set, so nothing was
retrained.

## Tests

* `tests/unit/test_mlops.py`:
  * PSI on identical and shifted data, and on an unseen category.
  * Growing error becomes DRIFT, which must be confirmed twice.
  * An input shift alone is only WARN, and calendar inputs are ignored.
  * Late-risk recall needs 30 late orders before it is judged.
  * The registry lifecycle: candidate → production → archived; rejected never promoted;
    rollback; survives a restart.
* `apps/backend/tests/test_mlops.py`, with the real ETA model:
  * A 25 %-slower warehouse is learned: the gate passes, the predictor switches to v2, and
    rollback restores v1.
  * When production is already exact, the candidate is rejected ("better now").
  * An over-fitted candidate that forgets the old warehouse is rejected ("not worse before").
  * Too little live data; the API and the metrics.

## Found on the way

* **Restored state from older code.** The dev backend restored a warehouse snapshot written
  before PR-18 changed the route cache. It unpickled fine and then crashed the loop on its first
  tick, silently.
  * The cache now accepts the old format.
  * Recovery runs a copy of a snapshot for three ticks before trusting it; a failing one is set
    aside as `.rejected`.
  * A loop that stops is logged with its traceback.
* **Division by zero in the gate** when the production model was exactly right on the holdout.
* **Two models drifting at once stopped the warehouse.** During the browser tests on the dev
  backend, ETA drift was confirmed for real and retraining started. Late risk then confirmed
  drift too, and its automatic start raised "still running" inside the simulator loop, which
  stopped.
  * Now one retraining runs at a time; the other model waits for its next check.
  * The model service catches its own errors, so it can never stop the loop
    (`test_two_models_drifting_at_once_never_stop_the_loop`).
  * That same live retraining produced an ETA v2 that the gate **rejected**: it was 0.6 % worse
    on recent orders (46.3 vs 46.0), so v1 stayed in production.

## Not yet

* Demand and anomaly models (their outcomes arrive per hour and per injected fault; they need
  longer windows).
* Shadow or canary serving of a candidate on live traffic before promotion; today the gate uses
  a held-out slice of live outcomes.
* Retraining in a separate worker process or on another machine (it runs in a thread, about a
  minute for the ETA model, while the loop keeps ticking).
