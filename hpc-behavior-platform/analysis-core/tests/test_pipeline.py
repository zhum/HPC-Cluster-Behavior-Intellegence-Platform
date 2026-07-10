from __future__ import annotations

import time

from sklearn.metrics import adjusted_rand_score

import analysis_core.inter.pipeline as pipeline_mod
from analysis_core.inter.pipeline import InterClusterPipeline


def test_pipeline_recovers_planted_clusters(planted_clusters):
    X, true_labels = planted_clusters
    pipeline = InterClusterPipeline(X)

    labels, _ = pipeline.get_labels(k=4, n_neighbors=5)
    ari = adjusted_rand_score(true_labels, labels)
    assert ari > 0.9


def test_pipeline_ccpca_matches_planted_metric(planted_clusters):
    X, true_labels = planted_clusters
    pipeline = InterClusterPipeline(X)

    labels, _ = pipeline.get_labels(k=4, n_neighbors=5)
    ccpca = pipeline.get_ccpca(k=4, n_neighbors=5)

    # map each kmeans cluster to the majority true group, then check that
    # cluster's top-ranked metric equals that group's planted signal metric.
    for result in ccpca:
        members = true_labels[labels == result.cluster]
        majority_group = int(round(members.mean())) if len(members) else -1
        assert result.ranked_metric_idx[0] == majority_group


def test_recluster_never_reruns_dr1_or_dr2(planted_clusters, monkeypatch):
    """recluster() must be cheap because it's a cache-hit on V/E, not because
    dr1/dr2 happen to be fast on this tiny fixture -- assert call counts
    directly rather than wall-clock timing (unreliable at N=40 scale, where
    even a "cold" UMAP fit takes single-digit milliseconds).
    """
    X, _ = planted_clusters

    dr1_calls = []
    dr2_calls = []
    real_dr1 = pipeline_mod.dr1_pca_over_time
    real_dr2 = pipeline_mod.dr2_umap

    def spy_dr1(*args, **kwargs):
        dr1_calls.append(1)
        return real_dr1(*args, **kwargs)

    def spy_dr2(*args, **kwargs):
        dr2_calls.append(1)
        return real_dr2(*args, **kwargs)

    monkeypatch.setattr(pipeline_mod, "dr1_pca_over_time", spy_dr1)
    monkeypatch.setattr(pipeline_mod, "dr2_umap", spy_dr2)

    pipeline = InterClusterPipeline(X)
    pipeline.get_labels(k=4, n_neighbors=5)
    pipeline.get_ccpca(k=4, n_neighbors=5)
    assert len(dr1_calls) == 1
    assert len(dr2_calls) == 1

    pipeline.recluster(k=5, n_neighbors=5)
    assert len(dr1_calls) == 1  # unchanged: still just the one cold call
    assert len(dr2_calls) == 1


def test_recluster_measurably_faster_than_cold_pipeline(planted_clusters):
    """Sanity check the timing claim still holds in absolute terms, without
    requiring a strict 100x ratio at this fixture's tiny scale.
    """
    X, _ = planted_clusters

    cold_pipeline = InterClusterPipeline(X)
    t0 = time.perf_counter()
    cold_pipeline.get_labels(k=4, n_neighbors=5)
    cold_pipeline.get_ccpca(k=4, n_neighbors=5)
    cold_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    cold_pipeline.recluster(k=5, n_neighbors=5)
    warm_s = time.perf_counter() - t0

    assert warm_s < cold_s
