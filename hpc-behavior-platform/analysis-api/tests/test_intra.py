from __future__ import annotations

import time

from tests.test_inter import _ready_session


def test_zscores_returns_matrix_and_flags(app_client, synthetic_client):
    session_id = _ready_session(app_client, synthetic_client)
    resp = app_client.post(
        "/intra/zscores",
        json={
            "session_id": session_id,
            "node_ids": ["node-000", "node-001", "node-006"],
            "metrics": ["metric-00", "metric-02"],
            "band": "2h",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["z"]) == 3
    assert len(body["z"][0]) == 2
    assert body["metrics"] == ["metric-00", "metric-02"]
    assert "zscores" in body["timings_ms"]


def test_zscores_warm_path_under_500ms(app_client, synthetic_client):
    session_id = _ready_session(app_client, synthetic_client)
    payload = {
        "session_id": session_id,
        "node_ids": ["node-000", "node-001"],
        "metrics": ["metric-00"],
        "band": "2h",
    }
    app_client.post("/intra/zscores", json=payload)

    t0 = time.perf_counter()
    resp = app_client.post("/intra/zscores", json=payload)
    warm_ms = (time.perf_counter() - t0) * 1000

    assert resp.status_code == 200
    assert warm_ms < 500


def test_baseline_returns_window_and_iqr(app_client, synthetic_client):
    session_id = _ready_session(app_client, synthetic_client)
    resp = app_client.post(
        "/intra/baseline",
        json={"session_id": session_id, "metric": "metric-00", "node_ids": ["node-000", "node-001"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["window"]) == 2
    assert len(body["iqr"]) == 2
    assert body["iqr"][0] <= body["iqr"][1]


def test_baseline_adjust_warm_path_under_500ms(app_client, synthetic_client):
    session_id = _ready_session(app_client, synthetic_client)
    payload = {"session_id": session_id, "metric": "metric-00", "node_ids": ["node-000", "node-001"]}
    app_client.post("/intra/baseline", json=payload)

    t0 = time.perf_counter()
    resp = app_client.post("/intra/baseline", json=payload)
    warm_ms = (time.perf_counter() - t0) * 1000

    assert resp.status_code == 200
    assert warm_ms < 500
