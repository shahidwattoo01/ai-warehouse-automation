"""The Phase 5 object detector serving camera frames from the app (Vision page).

The browser renders a frame of the live 3D warehouse (the same scene and camera setup the training
images came from) and sends it to POST /api/v1/vision/detect. This module runs YOLO on it with the
per-class confidence thresholds chosen in notebooks/09_vision_evaluation.ipynb and marks the safety
classes.

YOLO runs in its own worker process: in the backend process the simulator loop holds Python's
interpreter lock most of the time, which made one detection take ~50 s instead of a few seconds.
The worker loads the model once (10-30 s) when the Vision page first asks for the status.
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import Future, ProcessPoolExecutor
from pathlib import Path

import numpy as np

from ai.computer_vision.evaluation import suppress_duplicates

MODEL_DIR = Path(__file__).resolve().parents[2] / "models" / "vision_yolo_v1"
SAFETY = ("worker", "package", "obstacle", "blocked_path")
DEDUPLICATE = ("worker", "package", "obstacle")  # one box per object (see suppress_duplicates)
IMAGE_SIZE = 640  # 3x faster than 960 on a laptop CPU for 3 points less mAP@0.5 (notebook 09)
TIMEOUT_S = 120

# ----- worker process -----------------------------------------------------------------------------
_model = None


def _load(weights: str) -> bool:
    global _model
    if _model is None:
        # No usage analytics or online checks from Ultralytics (it would otherwise send anonymous
        # usage data by default); the model and its settings are all local.
        os.environ.setdefault("YOLO_OFFLINE", "1")
        from ultralytics import YOLO, settings

        settings.update({"sync": False})

        _model = YOLO(weights)
        # The first forward pass is several times slower than the next ones: do it now.
        _model.predict(
            np.zeros((480, 640, 3), dtype=np.uint8), imgsz=IMAGE_SIZE, device="cpu", verbose=False
        )
    return True


def _predict(weights: str, image_bytes: bytes) -> dict:
    """Decode and detect in the worker. Returns raw boxes (all with confidence >= 0.05)."""
    import cv2

    _load(weights)
    image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)  # BGR
    if image is None:
        raise ValueError("not a PNG or JPEG image")
    start = time.perf_counter()
    result = _model.predict(image, imgsz=IMAGE_SIZE, conf=0.05, device="cpu", verbose=False)[0]
    ms = (time.perf_counter() - start) * 1000
    b = result.boxes
    return {
        "width": int(image.shape[1]),
        "height": int(image.shape[0]),
        "ms": ms,
        "names": result.names,
        "boxes": [[*xyxy, conf, cls] for xyxy, conf, cls in
                  zip(b.xyxy.tolist(), b.conf.tolist(), b.cls.tolist(), strict=True)],
    }  # fmt: skip


# ----- backend side -------------------------------------------------------------------------------
class LiveDetector:
    def __init__(self, model_dir: Path = MODEL_DIR) -> None:
        self.model_dir = model_dir
        self.weights = str(model_dir / "best.pt")
        self._pool: ProcessPoolExecutor | None = None
        self._ready: Future | None = None
        self._lock = threading.Lock()
        evaluation = model_dir / "evaluation.json"
        report = model_dir / "report.json"
        self.evaluation = json.loads(evaluation.read_text()) if evaluation.exists() else {}
        self.report = json.loads(report.read_text()) if report.exists() else {}
        self.thresholds: dict[str, float] = self.evaluation.get("thresholds", {})

    @property
    def available(self) -> bool:
        return (self.model_dir / "best.pt").exists()

    @property
    def loaded(self) -> bool:
        return bool(self._ready and self._ready.done() and not self._ready.exception())

    def status(self) -> dict:
        official = self.evaluation.get("test_official", {}).get(str(IMAGE_SIZE), {})
        return {
            "available": self.available,
            "loaded": self.loaded,
            "model": "vision_yolo_v1",
            "algorithm": self.report.get("algorithm"),
            "classes": list(self.thresholds) or None,
            "safety_classes": list(SAFETY),
            "thresholds": self.thresholds,
            "image_size": IMAGE_SIZE,
            "test": {k: official.get(k) for k in ("precision", "recall", "mAP50", "mAP50_95")},
            "test_960_gpu": self.report.get("test"),
        }

    def warm_up(self) -> None:
        """Start the worker process and load the model there (returns at once)."""
        with self._lock:
            if not self.available:
                return
            failed = self._ready is not None and self._ready.done() and self._ready.exception()
            if failed:
                self._shutdown()  # a crashed worker: start again
            if self._pool is None:
                self._pool = ProcessPoolExecutor(max_workers=1)
                self._ready = self._pool.submit(_load, self.weights)

    def _shutdown(self) -> None:
        if self._pool:
            self._pool.shutdown(wait=False, cancel_futures=True)
        self._pool, self._ready = None, None

    def detect(self, image_bytes: bytes) -> dict:
        """Detect objects in one encoded image (PNG or JPEG). Boxes are in pixels of the image."""
        self.warm_up()
        raw = self._pool.submit(_predict, self.weights, image_bytes).result(timeout=TIMEOUT_S)
        names = raw["names"]
        boxes = np.array(
            [b for b in raw["boxes"] if b[4] >= self.thresholds.get(names[int(b[5])], 0.25)],
            dtype=np.float32,
        ).reshape(-1, 6)
        one_box = {int(k) for k, n in names.items() if n in DEDUPLICATE}
        boxes = suppress_duplicates(boxes, one_box)
        detections = []
        for x1, y1, x2, y2, conf, cls in boxes.tolist():
            name = names[int(cls)]
            box = [round(v, 1) for v in (x1, y1, x2, y2)]
            detections.append(
                {"cls": name, "conf": round(conf, 3), "safety": name in SAFETY, "box": box}
            )
        counts: dict[str, int] = {}
        for d in detections:
            counts[d["cls"]] = counts.get(d["cls"], 0) + 1
        return {
            "width": raw["width"],
            "height": raw["height"],
            "inference_ms": round(raw["ms"]),
            "detections": detections,
            "counts": counts,
            "safety_alerts": [d for d in detections if d["safety"]],
        }


detector = LiveDetector()
