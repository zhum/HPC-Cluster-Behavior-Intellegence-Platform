from __future__ import annotations

import time

from tests.test_session import _wait_ready


def _ready_session(app_client, synthetic_client):
    _, start, end, resolution_s = synthetic_client
    resp = app_client.post(
        "/session/create",
        json={"start": start.isoformat(), "end": end.isoformat(), "resolution_s": resolution_s},
    )
    session_id = resp.json()["session_id"]
    status = _wait_ready(app_client, session_id)
    assert status["status"] == "ready"
    return session_id


def test_embedding_returns_cache_key_and_timings(app_client, synthetic_client):
    session_id = _ready_session(app_client, synthetic_client)
    resp = app_client.post("/inter/embedding", json={"session_id": session_id})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["E"]) == 12
    assert len(body["E"][0]) == 2
    assert len(body["inactive_flags"]) == 12
    assert "cache_key" in body and body["cache_key"]
    assert "embedding" in body["timings_ms"]


def test_embedding_warm_call_is_fast_and_same_cache_key(app_client, synthetic_client):
    session_id = _ready_session(app_client, synthetic_client)
    first = app_client.post("/inter/embedding", json={"session_id": session_id}).json()

    t0 = time.perf_counter()
    second = app_client.post("/inter/embedding", json={"session_id": session_id}).json()
    warm_ms = (time.perf_counter() - t0) * 1000

    assert second["cache_key"] == first["cache_key"]
    assert second["E"] == first["E"]
    assert warm_ms < 200


def test_clusters_returns_labels_and_quality(app_client, synthetic_client):
    session_id = _ready_session(app_client, synthetic_client)
    resp = app_client.post("/inter/clusters", json={"session_id": session_id, "k": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["labels"]) == 12
    assert len(body["centroids"]) == 2
    assert set(body["quality_metrics"]) == {"silhouette", "davies_bouldin", "calinski_harabasz"}


def test_clusters_warm_path_under_200ms(app_client, synthetic_client):
    session_id = _ready_session(app_client, synthetic_client)
    app_client.post("/inter/clusters", json={"session_id": session_id, "k": 3})

    t0 = time.perf_counter()
    resp = app_client.post("/inter/clusters", json={"session_id": session_id, "k": 3})
    warm_ms = (time.perf_counter() - t0) * 1000

    assert resp.status_code == 200
    assert warm_ms < 200


def test_explain_returns_ranked_metrics_per_cluster(app_client, synthetic_client):
    """ccPCA's actual statistical correctness (recovering a planted
    discriminative metric) is already covered thoroughly by analysis-core's
    own Phase 3 test suite with a controlled fixture; this integration test
    only checks the API wiring -- shapes, metric-name resolution, non-
    degenerate weights -- since this fixture's single signal metric among 5
    noise metrics isn't guaranteed to survive UMAP+k-means exactly.
    """
    session_id = _ready_session(app_client, synthetic_client)
    resp = app_client.post("/inter/explain", json={"session_id": session_id, "k": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 2
    for result in body["results"]:
        assert set(result["ranked_metrics"]) == {"metric-00", "metric-01", "metric-02", "metric-03", "metric-04", "metric-05"}
        assert len(result["weights"]) == 6
        assert any(abs(w) > 0 for w in result["weights"])
    assert "explain" in body["timings_ms"]


def test_explain_warm_path_under_200ms(app_client, synthetic_client):
    session_id = _ready_session(app_client, synthetic_client)
    app_client.post("/inter/explain", json={"session_id": session_id, "k": 2})

    t0 = time.perf_counter()
    resp = app_client.post("/inter/explain", json={"session_id": session_id, "k": 2})
    warm_ms = (time.perf_counter() - t0) * 1000

    assert resp.status_code == 200
    assert warm_ms < 200


def test_timedomain_groups_null_segments_by_cluster(app_client, synthetic_client):
    session_id = _ready_session(app_client, synthetic_client)
    resp = app_client.post("/inter/timedomain", json={"session_id": session_id, "k": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["clusters"]) <= {"0", "1"}


def test_cluster_means_returns_polylines_for_requested_metrics(app_client, synthetic_client):
    session_id = _ready_session(app_client, synthetic_client)
    resp = app_client.post(
        "/inter/cluster_means",
        json={"session_id": session_id, "k": 2, "metrics": ["metric-00", "metric-01"], "smoothing_w": 3},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["times"]) == 40
    for cluster_polylines in body["polylines"].values():
        assert set(cluster_polylines) == {"metric-00", "metric-01"}
        assert len(cluster_polylines["metric-00"]) == 40
