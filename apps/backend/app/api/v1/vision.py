"""Vision endpoints (TRD Section 7): the Phase 5 object detector on camera frames."""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ai.computer_vision.live import detector
from app.core.auth import need

router = APIRouter(prefix="/vision", tags=["vision"])

MAX_IMAGE_BYTES = 5_000_000


class DetectRequest(BaseModel):
    image: str = Field(
        description="PNG or JPEG as a data URL or plain base64", max_length=7_000_000
    )


@router.get("/status", dependencies=[need("dashboard:view")])
def status() -> dict:
    """Whether the detector is available, its classes, thresholds and test scores. Also starts
    loading the model in the background, so the first detection does not wait for it."""
    detector.warm_up()
    return detector.status()


@router.post("/detect", dependencies=[need("vision:use")])
def detect(body: DetectRequest) -> dict:
    """Detect robots, workers, shelves, dropped parcels, obstacles and closed-aisle barriers in
    one camera frame. Runs on the CPU (about 0.5-1 s per 640 x 480 frame); safety detections are
    flagged."""
    if not detector.available:
        raise HTTPException(
            503, "No detector: train it with notebooks/cloud/train_yolo_colab.ipynb"
        )
    data = body.image.split(",", 1)[1] if body.image.startswith("data:") else body.image
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as err:
        raise HTTPException(422, "image is not valid base64") from err
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "image too large (max 5 MB)")
    try:
        return detector.detect(raw)
    except ValueError as err:  # OpenCV cannot decode it
        raise HTTPException(422, "image is not a PNG or JPEG") from err
    except TimeoutError as err:
        raise HTTPException(504, "the detector took too long (is the CPU busy?)") from err
