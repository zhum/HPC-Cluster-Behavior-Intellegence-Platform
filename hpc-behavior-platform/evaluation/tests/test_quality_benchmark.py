from __future__ import annotations

from evaluation.fixtures import planted_cluster_tensor
from evaluation.quality_benchmark import benchmark_report


def test_synthetic_planted_cluster_gate():
    """Phase 3/7 shipping gate: planted-cluster ARI > 0.9 and quality metrics
    beat the PCA-only baseline.
    """
    X, true_labels = planted_cluster_tensor()
    result = benchmark_report(X, true_labels, k=4, dataset_name="synthetic_planted")

    assert result["gate_ari_pass"], f"ARI {result['ari_multidr']} did not exceed 0.9"
    assert result["gate_beats_pca_baseline"], (
        f"MulTiDR silhouette {result['quality_multidr']['silhouette']} did not beat "
        f"PCA-only silhouette {result['quality_pca_only']['silhouette']}"
    )


def test_report_has_table_i_metric_set():
    X, true_labels = planted_cluster_tensor()
    result = benchmark_report(X, true_labels, k=4, dataset_name="synthetic_planted")
    for key in ("silhouette", "davies_bouldin", "calinski_harabasz"):
        assert key in result["quality_multidr"]
    assert "trustworthiness" in result
    assert "continuity" in result
