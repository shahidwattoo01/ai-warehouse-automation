"""Phase 5 vision helpers: box overlap, matching predictions to labels, safety thresholds and
duplicate suppression (ai/computer_vision/evaluation.py). No model or images needed."""

import numpy as np
import pandas as pd
import pytest

from ai.computer_vision.evaluation import (
    choose_threshold,
    iou,
    match_image,
    prf,
    read_labels,
    size_of,
    suppress_duplicates,
)


def test_iou_of_identical_disjoint_and_half_overlapping_boxes():
    a = np.array([[0, 0, 10, 10]], dtype=float)
    assert iou(a, a)[0, 0] == pytest.approx(1.0)
    assert iou(a, np.array([[20, 20, 30, 30]], dtype=float))[0, 0] == 0.0
    assert iou(a, np.array([[5, 0, 15, 10]], dtype=float))[0, 0] == pytest.approx(50 / 150)


def test_yolo_labels_become_pixel_boxes(tmp_path):
    path = tmp_path / "frame.txt"
    path.write_text("1 0.5 0.5 0.25 0.5\n")  # class cx cy w h (normalised)
    labels = read_labels(path, 640, 480)
    np.testing.assert_allclose(labels, [[1, 240, 120, 400, 360]])
    assert read_labels(tmp_path / "missing.txt", 640, 480).shape == (0, 5)


def test_coco_size_classes():
    boxes = np.array([[0, 0, 20, 20], [0, 0, 50, 50], [0, 0, 120, 120]], dtype=float)
    assert list(size_of(boxes)) == ["small", "medium", "large"]


def test_one_true_box_matches_only_one_prediction():
    truth = np.array([[1, 0, 0, 10, 10]], dtype=float)  # one worker
    pred = np.array(
        [[0, 0, 10, 10, 0.9, 1], [1, 1, 10, 10, 0.6, 1], [0, 0, 10, 10, 0.8, 0]], dtype=float
    )
    tp, found = match_image(pred, truth)
    # The duplicate and the wrong-class box are false positives.
    assert list(tp) == [True, False, False]
    assert found[0] == pytest.approx(0.9)  # matched by the most confident box


def test_safety_threshold_is_the_lowest_with_enough_precision():
    # Confidences of 10 boxes; the lowest ones are false alarms.
    pred = pd.DataFrame(
        {
            "conf": [0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
            "tp": [False, False, True, True, True, True, True, True, True, True],
        }
    )
    truth = pd.DataFrame({"conf_found": [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, np.nan]})
    t = choose_threshold(pred, truth, min_precision=0.8)
    assert prf(pred, truth, t)["precision"] >= 0.8
    assert t <= 0.2  # as low as possible: no real object above it is dropped
    assert prf(pred, truth, t)["recall"] == pytest.approx(8 / 9)


def test_duplicates_are_removed_only_for_the_chosen_classes():
    pred = np.array(
        [
            [10, 10, 50, 90, 0.86, 1],
            [12, 12, 48, 85, 0.25, 1],  # worker + weak duplicate
            [100, 10, 140, 90, 0.9, 2],
            [102, 12, 138, 88, 0.5, 2],  # two overlapping shelves (real)
        ],
        dtype=np.float32,
    )
    kept = suppress_duplicates(pred, classes={1})
    assert len(kept) == 3
    assert (kept[:, 5] == 1).sum() == 1 and kept[kept[:, 5] == 1][0, 4] == pytest.approx(0.86)
    assert (kept[:, 5] == 2).sum() == 2
