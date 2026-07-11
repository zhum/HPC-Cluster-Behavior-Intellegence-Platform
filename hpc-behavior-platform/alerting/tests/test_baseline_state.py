from __future__ import annotations

from alerting.baseline_state import BaselineStateStore


def test_get_returns_none_when_unset(synthetic_client):
    client, *_ = synthetic_client
    store = BaselineStateStore(client)
    assert store.get(cluster_id=0, metric="metric-00") is None


def test_set_then_get_roundtrip(synthetic_client):
    client, *_ = synthetic_client
    store = BaselineStateStore(client)
    store.set(cluster_id=0, metric="metric-00", window=(10, 50))
    assert store.get(cluster_id=0, metric="metric-00") == (10, 50)


def test_set_overwrites_previous_window(synthetic_client):
    client, *_ = synthetic_client
    store = BaselineStateStore(client)
    store.set(cluster_id=0, metric="metric-00", window=(10, 50))
    store.set(cluster_id=0, metric="metric-00", window=(20, 60))
    assert store.get(cluster_id=0, metric="metric-00") == (20, 60)
