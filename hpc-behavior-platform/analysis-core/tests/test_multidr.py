from __future__ import annotations

import numpy as np

from analysis_core.inter.multidr import dr1_pca_over_time, dr2_umap


def test_dr1_shape():
    X = np.random.default_rng(0).normal(size=(10, 3, 20))
    V = dr1_pca_over_time(X)
    assert V.shape == (10, 3)


def test_dr1_empty_time_axis_returns_zeros():
    X = np.zeros((5, 2, 0))
    V = dr1_pca_over_time(X)
    assert V.shape == (5, 2)
    assert np.all(V == 0)


def test_dr1_constant_row_no_nan():
    X = np.ones((4, 1, 10))  # zero variance per node -> std==0 guard path
    V = dr1_pca_over_time(X)
    assert not np.isnan(V).any()


def test_dr1_signal_metric_dominates_for_planted_group(planted_clusters):
    X, true_labels = planted_clusters
    V = dr1_pca_over_time(X)
    # for nodes in group g, metric g should have larger |V| than a metric
    # carrying pure noise for that node.
    for group in range(4):
        mask = true_labels == group
        signal_col = np.abs(V[mask, group])
        noise_col = np.abs(V[mask, (group + 1) % 4])
        assert signal_col.mean() > noise_col.mean()


def test_dr2_shape_and_neighbor_clamping():
    V = np.random.default_rng(1).normal(size=(6, 4))
    E = dr2_umap(V, n_neighbors=15)  # n_neighbors > N-1, must clamp not raise
    assert E.shape == (6, 2)
