"""Cross-site protection: other websites must not control the simulator or read its stream."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app

EVIL = {"Origin": "https://evil.example"}
OURS = {"Origin": "http://localhost:3000"}


@pytest.fixture()
def client():
    yield TestClient(app)  # lifespan off: no background ticks needed


def test_state_changing_requests_from_other_sites_are_refused(client):
    for path in ("/api/v1/simulation/reset", "/api/v1/simulation/pause", "/api/v1/robots/R1/pause"):
        r = client.post(path, headers=EVIL)
        assert r.status_code == 403, path
        assert r.json()["detail"]["code"] == "forbidden_origin"


def test_own_frontend_and_non_browser_clients_are_allowed(client):
    assert client.post("/api/v1/simulation/pause", headers=OURS).status_code == 200
    # curl, scripts and tests send no Origin header.
    assert client.post("/api/v1/simulation/pause").status_code == 200


def test_reads_are_not_blocked(client):
    assert client.get("/health", headers=EVIL).status_code == 200


def test_stream_refuses_other_sites(client):
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/api/v1/simulation/stream", headers=EVIL) as ws:
            ws.receive_text()
    assert closed.value.code == 1008


def test_stream_sends_layout_then_state_without_inventory(client):
    with client.websocket_connect("/api/v1/simulation/stream", headers=OURS) as ws:
        layout = ws.receive_json()
        tick = ws.receive_json()
    assert layout["type"] == "layout" and layout["layout"]["width"] > 0
    assert tick["type"] == "tick" and "inventory" not in tick["state"]
