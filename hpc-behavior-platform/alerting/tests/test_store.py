from __future__ import annotations

from datetime import datetime

from alerting.store import Anomaly, AnomalyStore


def _anomaly(node_id="node-000", metric="metric-00", band="2h") -> Anomaly:
    return Anomaly(
        id="a1",
        detected_at=datetime(2026, 1, 1),
        cluster_id=0,
        node_id=node_id,
        metric=metric,
        band=band,
        z_score=4.2,
        baseline_window=(0, 100),
    )


def test_insert_and_list_open_anomalies(synthetic_client):
    client, *_ = synthetic_client
    store = AnomalyStore(client)
    store.insert_anomalies([_anomaly()])

    open_anomalies = store.list_open_anomalies()
    assert len(open_anomalies) == 1
    assert open_anomalies[0]["node_id"] == "node-000"
    assert open_anomalies[0]["status"] == "open"


def test_dismiss_marks_dismissed_and_suppresses_future_alerts(synthetic_client):
    client, *_ = synthetic_client
    store = AnomalyStore(client)
    store.insert_anomalies([_anomaly()])

    assert not store.is_suppressed("node-000", "metric-00", "2h")

    store.dismiss("a1", node_id="node-000", metric="metric-00", band="2h", by="alice", reason="known noisy sensor")

    assert store.list_open_anomalies() == []  # no longer open
    assert store.is_suppressed("node-000", "metric-00", "2h")
    assert not store.is_suppressed("node-001", "metric-00", "2h")  # scoped to this node/metric/band only
