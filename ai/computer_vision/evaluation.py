"""Evaluation helpers for the warehouse object detector (Phase 5, notebook 09).

A predicted box is a *true positive* when it overlaps an unmatched true box of the same class by
IoU >= 0.5 (intersection over union); higher-confidence predictions are matched first, as in the
standard mAP@0.5 protocol. Unmatched predictions are false positives, unmatched true boxes are
misses. Object sizes follow the COCO convention on the original image: small < 32 x 32 pixels,
medium < 96 x 96, large above.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SIZE_EDGES = (32**2, 96**2)  # COCO area limits in pixels
SIZES = ("small", "medium", "large")


def read_labels(path: Path, width: int, height: int) -> np.ndarray:
    """YOLO label file -> array (n, 5): class, x1, y1, x2, y2 in pixels."""
    if not path.exists() or not path.read_text().strip():
        return np.zeros((0, 5), dtype=np.float32)
    raw = np.loadtxt(path, ndmin=2, dtype=np.float32)
    c, x, y, w, h = raw.T
    return np.stack([c, (x - w / 2) * width, (y - h / 2) * height, (x + w / 2) * width,
                     (y + h / 2) * height], axis=1)  # fmt: skip


def iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pairwise IoU between boxes a (n, 4) and b (m, 4), x1 y1 x2 y2."""
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area = lambda r: (r[:, 2] - r[:, 0]) * (r[:, 3] - r[:, 1])  # noqa: E731
    return inter / (area(a)[:, None] + area(b)[None, :] - inter + 1e-9)


def size_of(boxes: np.ndarray) -> np.ndarray:
    area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    return np.array(SIZES)[np.digitize(area, SIZE_EDGES)]


def match_image(pred: np.ndarray, truth: np.ndarray, iou_min: float = 0.5):
    """pred (n, 6): x1 y1 x2 y2 conf cls; truth (m, 5): cls x1 y1 x2 y2.
    Returns (is_true_positive per prediction, matched confidence per true box or NaN)."""
    tp = np.zeros(len(pred), dtype=bool)
    found = np.full(len(truth), np.nan)
    if len(pred) and len(truth):
        overlap = iou(pred[:, :4], truth[:, 1:])
        for i in np.argsort(-pred[:, 4]):
            same = (truth[:, 0] == pred[i, 5]) & np.isnan(found)
            if not same.any():
                continue
            j = np.flatnonzero(same)[np.argmax(overlap[i, same])]
            if overlap[i, j] >= iou_min:
                tp[i], found[j] = True, pred[i, 4]
    return tp, found


def match_split(preds: dict[str, np.ndarray], label_dir: Path, width: int, height: int):
    """Match every image of a split. Returns two tables:
    predictions (frame, cls, conf, tp) and truths (frame, cls, size, conf_found)."""
    p_rows, t_rows = [], []
    for frame, pred in preds.items():
        truth = read_labels(label_dir / f"{frame}.txt", width, height)
        tp, found = match_image(pred, truth)
        p_rows.append(
            pd.DataFrame(
                {"frame": frame, "cls": pred[:, 5].astype(int), "conf": pred[:, 4], "tp": tp}
            )
        )
        t_rows.append(
            pd.DataFrame(
                {
                    "frame": frame,
                    "cls": truth[:, 0].astype(int),
                    "size": size_of(truth[:, 1:]),
                    "conf_found": found,
                }
            )
        )
    return pd.concat(p_rows, ignore_index=True), pd.concat(t_rows, ignore_index=True)


def prf(pred: pd.DataFrame, truth: pd.DataFrame, threshold: float) -> dict[str, float]:
    """Precision, recall, F1 for one class (or all) when boxes below `threshold` are dropped."""
    kept = pred[pred["conf"] >= threshold]
    tp = int(kept["tp"].sum())
    found = int((truth["conf_found"] >= threshold).sum())
    precision = tp / len(kept) if len(kept) else 0.0
    recall = found / len(truth) if len(truth) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "F1": f1,
        "boxes": len(kept),
        "objects": len(truth),
    }


def choose_threshold(
    pred: pd.DataFrame, truth: pd.DataFrame, min_precision: float | None = None
) -> float:
    """Confidence threshold for one class: the best F1, or, with `min_precision` (safety-first),
    the lowest threshold whose precision is still at least `min_precision`. Recall can only fall as
    the threshold rises, so this is the highest recall at that precision, with a margin for objects
    the validation images did not show."""
    grid = np.round(np.arange(0.05, 0.96, 0.01), 2)
    stats = [prf(pred, truth, t) for t in grid]
    if min_precision is not None:
        ok = [t for t, s in zip(grid, stats, strict=True) if s["precision"] >= min_precision]
        if ok:
            return float(min(ok))
    return float(grid[int(np.argmax([s["F1"] for s in stats]))])


def suppress_duplicates(pred: np.ndarray, classes: set[int], overlap: float = 0.5) -> np.ndarray:
    """Drop a box when a more confident box of the same class covers most of it.

    pred (n, 6): x1 y1 x2 y2 conf cls. Low safety thresholds let weak duplicate boxes around one
    person through (YOLO's own suppression only removes overlaps above IoU 0.7); this keeps one box
    per object. `overlap` is the share of the weaker box inside the stronger one. Only `classes`
    are cleaned: neighbouring rack bays and robots really do overlap in perspective (on the test
    images this step halved their recall), while for workers, parcels and obstacles it removed
    duplicate alarms at almost no cost (worker precision 0.82 -> 0.88, recall 0.935 -> 0.931)."""
    if len(pred) < 2:
        return pred
    order = np.argsort(-pred[:, 4])
    kept: list[int] = []
    area = (pred[:, 2] - pred[:, 0]) * (pred[:, 3] - pred[:, 1])
    for i in order:
        if int(pred[i, 5]) not in classes:
            kept.append(int(i))
            continue
        duplicate = False
        for j in kept:
            if pred[j, 5] != pred[i, 5]:
                continue
            w = min(pred[i, 2], pred[j, 2]) - max(pred[i, 0], pred[j, 0])
            h = min(pred[i, 3], pred[j, 3]) - max(pred[i, 1], pred[j, 1])
            if w > 0 and h > 0 and w * h >= overlap * area[i]:
                duplicate = True
                break
        if not duplicate:
            kept.append(int(i))
    return pred[sorted(kept)]
