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


def test_pause_and_start_are_sent_to_every_client_at_once():
    """The loop only broadcasts while running, so a pause must be announced explicitly
    (otherwise the Start/Pause button never learns that the run stopped)."""
    import json

    from app.services.simulator import simulator

    with TestClient(app) as client:
        queue = simulator.subscribe()
        try:
            client.post("/api/v1/simulation/start")
            client.post("/api/v1/simulation/pause")
            frames = [json.loads(queue.get_nowait()) for _ in range(queue.qsize())]
        finally:
            simulator.unsubscribe(queue)
    running = [f["state"]["running"] for f in frames if f.get("type") == "tick"]
    assert running and running[-1] is False
    assert True in running  # the start was announced too
