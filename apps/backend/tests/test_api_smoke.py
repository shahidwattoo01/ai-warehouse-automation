"""Smoke tests: the API boots, the simulator loads the layout and serves state."""

from fastapi.testclient import TestClient

from app.main import app


def test_health_and_state():
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        state = client.get("/api/v1/simulation/state").json()
        layout = client.get("/api/v1/simulation/layout").json()
        assert layout["name"] == "large"  # default layout (configs/simulation.yaml, SIM_LAYOUT)
        assert len(state["robots"]) == 40
        assert layout["width"] == 80 and len(layout["shelves"]) > 0


def test_pause_unknown_robot_404():
    with TestClient(app) as client:
        assert client.post("/api/v1/robots/R999/pause").status_code == 404


def test_future_phase_endpoint_returns_501():
    with TestClient(app) as client:
        assert client.post("/api/v1/rag/query").status_code == 501
