from __future__ import annotations

import numpy as np

from analysis_core.inter.ccpca import ccpca_explain
from analysis_core.inter.multidr import dr1_pca_over_time


def test_ccpca_ranks_discriminative_metric_first(planted_clusters):
    X, true_labels = planted_clusters
    V = dr1_pca_over_time(X)

    results = ccpca_explain(V, true_labels)
    assert len(results) == 4

    # true_labels are already 0..3 matching the signal-metric index by
    # construction, so cluster g's top-ranked metric should be metric g.
    for result in results:
        assert result.ranked_metric_idx[0] == result.cluster


def test_ccpca_weights_shape():
    rng = np.random.default_rng(0)
    V = rng.normal(size=(20, 5))
    labels = rng.integers(0, 3, size=20)
    results = ccpca_explain(V, labels)
    assert len(results) == len(np.unique(labels))
    for r in results:
        assert r.weights.shape == (5,)
        assert r.ranked_metric_idx.shape == (5,)
