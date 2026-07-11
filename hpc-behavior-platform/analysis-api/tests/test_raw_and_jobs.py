from __future__ import annotations

from tests.test_inter import _ready_session


def test_raw_series_returns_requested_slice(app_client, synthetic_client):
    session_id = _ready_session(app_client, synthetic_client)
    resp = app_client.post(
        "/raw/series",
        json={
            "session_id": session_id,
            "node_ids": ["node-000", "node-001"],
            "metrics": ["metric-00"],
            "t0": 5,
            "t1": 15,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["times"]) == 10
    assert set(body["series"]) == {"node-000", "node-001"}
    assert len(body["series"]["node-000"]["metric-00"]) == 10


def test_raw_series_downsamples_beyond_max_points(app_client, synthetic_client):
    session_id = _ready_session(app_client, synthetic_client)
    resp = app_client.post(
        "/raw/series",
        json={
            "session_id": session_id,
            "node_ids": ["node-000"],
            "metrics": ["metric-00"],
            "t0": 0,
            "t1": 40,
            "max_points": 10,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["times"]) <= 10


def test_jobs_overlay_maps_and_flags_unmapped_nodes(app_client, synthetic_client):
    session_id = _ready_session(app_client, synthetic_client)
    resp = app_client.post(
        "/jobs/overlay",
        json={"session_id": session_id, "node_ids": ["node-000", "node-001", "node-005"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    mapped = {iv["node_id"] for iv in body["intervals"]}
    assert mapped == {"node-000", "node-001"}
    assert body["unmapped_nodes"] == ["node-005"]
    assert body["intervals"][0]["job_id"] == "job-1"
