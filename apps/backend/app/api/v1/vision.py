"""Vision endpoints (TRD Section 7)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1._phase import not_yet

router = APIRouter(prefix="/vision", tags=["vision"])


@router.post("/detect")
def post_vision_0() -> dict:
    """Object detection on a camera frame."""
    raise not_yet(5, "Object detection on a camera frame")
