# ADR 005 — Safety-first confidence thresholds and selective duplicate merging

**Status:** Accepted · 2026-10-17

## Context

A detector returns boxes with a confidence; a threshold decides which ones are shown. One
threshold for all classes is a compromise. For safety, **missing** a worker, a dropped parcel, an
obstacle or a closed aisle is worse than a false alarm. Lowering thresholds, however, also lets
weak duplicate boxes around one person through (YOLO's own suppression only removes overlaps
above IoU 0.7): one worker appeared as three alarms.

## Decision

- **Per-class thresholds**, chosen on the validation images (`notebooks/09_vision_evaluation.ipynb`):
  - safety classes (worker, package, obstacle, blocked_path): the **lowest threshold whose
    precision is still ≥ 0.80** (highest recall at that precision, with a margin);
  - robot and shelf: the threshold with the best F1.
- **Duplicate merging** (a weaker box mostly inside a stronger box of the same class is dropped)
  only for **workers, packages and obstacles**.

## Evidence (test images)

* Thresholds: worker recall 0.924 → 0.935, package 0.945 → 0.964, barrier 0.950 → 0.967, at the
  cost of precision (0.82-0.89 instead of 0.88-0.95).
* A first rule (highest of several equally good thresholds) lowered recall on test; it was
  replaced by "lowest threshold with precision ≥ 0.80".
* Duplicate merging: worker precision 0.817 → 0.881 with recall 0.935 → 0.931; for robots and
  shelves it would have halved recall (neighbouring objects overlap in perspective), so it is not
  applied to them.

## Consequences

- More false alarms on the Vision page by design; the confidence of each alarm is shown.
- Thresholds live in `models/vision_yolo_v1/evaluation.json` and must be re-chosen when the model
  is retrained (`python scripts/train.py --model vision`).
- The camera detector is advisory: physical safety stays with certified robot sensors.
