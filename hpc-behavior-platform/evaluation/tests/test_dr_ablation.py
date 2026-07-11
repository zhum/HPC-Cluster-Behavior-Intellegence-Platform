from __future__ import annotations

from evaluation.dr_ablation import run_ablation
from evaluation.fixtures import planted_cluster_tensor


def test_ablation_reports_all_methods():
    X, true_labels = planted_cluster_tensor()
    report = run_ablation(X, true_labels, k=4)
    assert set(report) == {"multidr", "pca_only", "umap_direct", "tsne"}
    for method_result in report.values():
        assert "ari" in method_result
        assert "silhouette" in method_result


def test_multidr_beats_naive_flatten_baselines_on_planted_data():
    """The whole point of dr1's per-node z-scoring: flatten-and-DR approaches
    don't normalize away amplitude/offset differences the way dr1 does, so
    they shouldn't recover the planted shape-only structure as well.
    """
    X, true_labels = planted_cluster_tensor()
    report = run_ablation(X, true_labels, k=4)
    assert report["multidr"]["ari"] > report["pca_only"]["ari"]
