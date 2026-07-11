from __future__ import annotations

import time


def _wait_ready(client, session_id, timeout=10.0):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        resp = client.get(f"/session/{session_id}/status")
        assert resp.status_code == 200
        if resp.json()["status"] != "pending":
            return resp.json()
        time.sleep(0.05)
    raise TimeoutError("session never left pending")


def test_session_create_and_status_flow(app_client, synthetic_client):
    _, start, end, resolution_s = synthetic_client
    resp = app_client.post(
        "/session/create",
        json={"start": start.isoformat(), "end": end.isoformat(), "resolution_s": resolution_s},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    session_id = body["session_id"]

    status = _wait_ready(app_client, session_id)
    assert status["status"] == "ready"
    assert status["n_nodes"] == 12
    assert status["n_metrics"] == 6
    assert status["n_timesteps"] == 40


def test_session_status_404_for_unknown_id(app_client):
    resp = app_client.get("/session/does-not-exist/status")
    assert resp.status_code == 404


def test_session_create_rejects_oversized_envelope(app_client, synthetic_client):
    _, start, end, resolution_s = synthetic_client
    resp = app_client.post(
        "/session/create",
        json={
            "start": start.isoformat(),
            "end": end.isoformat(),
            "resolution_s": resolution_s,
            "nodes": [f"node-{i:04d}" for i in range(2001)],  # exceeds envelope N<=2000
        },
    )
    session_id = resp.json()["session_id"]
    status = _wait_ready(app_client, session_id)
    assert status["status"] == "error"
    assert "exceeds envelope" in status["error"]
