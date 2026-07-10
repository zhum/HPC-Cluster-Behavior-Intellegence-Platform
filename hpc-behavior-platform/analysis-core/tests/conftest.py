from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture
def planted_clusters():
    """Synthetic (N, M, T) tensor with 4 planted behavioral groups.

    N=40 nodes (10 per group), M=4 metrics, T=60 timesteps. Node n in group g
    carries a clean, shared sinusoid on metric m == g (same frequency/phase
    across all nodes in the group) and pure white noise on every other
    metric. Per-node z-scoring in dr1_pca_over_time strips amplitude/offset,
    so the discriminating signal is purely the *shape* (correlated sinusoid
    vs uncorrelated noise) -- exactly what PCA's first component is designed
    to pick out, and metric m == g should dominate the first-pass DR result
    for group-g nodes, which is also what ccPCA should recover as the
    top-ranked discriminative metric per cluster.
    """
    rng = np.random.default_rng(42)
    n_per_group = 10
    n_groups = 4
    N = n_per_group * n_groups
    M = n_groups
    T = 60

    X = rng.normal(0, 1.0, size=(N, M, T))
    t = np.arange(T)
    true_labels = np.repeat(np.arange(n_groups), n_per_group)

    for node_i in range(N):
        group = true_labels[node_i]
        signal = np.sin(2 * np.pi * 3 * t / T) + rng.normal(0, 0.1, size=T)
        X[node_i, group, :] = signal

    return X, true_labels
