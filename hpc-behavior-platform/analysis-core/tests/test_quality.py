from __future__ import annotations

import numpy as np

from analysis_core.inter.quality import cluster_quality, trustworthiness_continuity


def test_cluster_quality_well_separated_clusters_score_high():
    rng = np.random.default_rng(0)
    E = np.concatenate(
        [
            rng.normal(loc=[-10, -10], scale=0.3, size=(10, 2)),
            rng.normal(loc=[10, 10], scale=0.3, size=(10, 2)),
        ]
    )
    labels = np.array([0] * 10 + [1] * 10)
    q = cluster_quality(E, labels)
    assert q["silhouette"] > 0.9
    assert q["davies_bouldin"] < 0.5
    assert q["calinski_harabasz"] > 100


def test_cluster_quality_degenerate_single_cluster_returns_nan():
    E = np.random.default_rng(0).normal(size=(10, 2))
    labels = np.zeros(10, dtype=int)
    q = cluster_quality(E, labels)
    assert all(np.isnan(v) for v in q.values())


def test_trustworthiness_continuity_identity_is_perfect():
    rng = np.random.default_rng(0)
    V = rng.normal(size=(30, 4))
    trust, cont = trustworthiness_continuity(V, V.copy())
    assert trust == 1.0
    assert cont == 1.0
