"""Vision endpoints (Phase 5): request validation and the response shape, with a stand-in detector
so the tests need neither the trained YOLO model nor the Ultralytics library."""

import base64

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import vision
from app.main import app


class FakeDetector:
    available = True

    def __init__(self, fail: Exception | None = None) -> None:
        self.fail = fail
        self.calls = 0

    def warm_up(self) -> None:
        pass

    def status(self) -> dict:
        return {"available": True, "loaded": True, "thresholds": {"worker": 0.13}}

    def detect(self, image_bytes: bytes) -> dict:
        self.calls += 1
        if self.fail:
            raise self.fail
        return {
            "width": 640,
            "height": 480,
            "inference_ms": 5,
            "detections": [],
            "counts": {},
            "safety_alerts": [],
        }


@pytest.fixture
def client(monkeypatch):
    fake = FakeDetector()
    monkeypatch.setattr(vision, "detector", fake)
    with TestClient(app) as c:
        c.fake = fake
        yield c


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_status_reports_the_detector(client):
    assert client.get("/api/v1/vision/status").json()["available"] is True


def test_a_data_url_frame_is_decoded_and_detected(client):
    res = client.post(
        "/api/v1/vision/detect", json={"image": "data:image/jpeg;base64," + b64(b"fake")}
    )
    assert res.status_code == 200 and res.json()["width"] == 640
    assert client.fake.calls == 1


def test_invalid_base64_is_rejected(client):
    assert client.post("/api/v1/vision/detect", json={"image": "not base64!!"}).status_code == 422
    assert client.fake.calls == 0


def test_too_large_images_are_rejected(client):
    big = b64(b"x" * (vision.MAX_IMAGE_BYTES + 1))
    assert client.post("/api/v1/vision/detect", json={"image": big}).status_code in (413, 422)
    assert client.fake.calls == 0


def test_an_undecodable_image_is_a_clear_422(client, monkeypatch):
    monkeypatch.setattr(
        vision, "detector", FakeDetector(fail=ValueError("not a PNG or JPEG image"))
    )
    assert client.post("/api/v1/vision/detect", json={"image": b64(b"hello")}).status_code == 422


def test_a_busy_detector_times_out_with_504(client, monkeypatch):
    monkeypatch.setattr(vision, "detector", FakeDetector(fail=TimeoutError()))
    assert client.post("/api/v1/vision/detect", json={"image": b64(b"x")}).status_code == 504


def test_no_trained_model_gives_503(client, monkeypatch):
    missing = FakeDetector()
    missing.available = False
    monkeypatch.setattr(vision, "detector", missing)
    assert client.post("/api/v1/vision/detect", json={"image": b64(b"x")}).status_code == 503
