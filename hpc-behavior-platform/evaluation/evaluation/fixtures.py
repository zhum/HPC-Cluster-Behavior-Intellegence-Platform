"""Synthetic planted-cluster tensor, shared by the quality benchmark and DR
ablation -- option (a) from Phase 7 item 1 ("synthetic planted-cluster
data"). Options (b) (a licensable public HPC dataset) and (c) (a week of
the platform's own telemetry) are not exercised here: no such dataset is
available/licensed in this environment, and a week of real telemetry would
require a long-running ingest we haven't operated. The benchmark harness
below is dataset-agnostic (works from any (X, true_labels) pair), so wiring
in (b)/(c) later is a matter of a new fixture function, not a rewrite.
"""
from __future__ import annotations

import numpy as np


def planted_cluster_tensor(
    n_per_group: int = 15, n_groups: int = 4, extra_noise_metrics: int = 4, T: int = 60, seed: int = 42
) -> tuple[np.ndarray, np.ndarray]:
    """(N, M, T) tensor with n_groups planted behavioral groups.

    Node n in group g carries a shared sinusoid (same frequency/phase across
    all group members) on metric g, plus `extra_noise_metrics` pure-noise
    metrics with no group structure. This mirrors analysis-core's own Phase 3
    ccPCA fixture: dr1_pca_over_time z-scores each node's own time series
    before PCA, which erases constant offsets, so the planted signal must be
    a shared *shape* (not a level shift) to survive into V.
    """
    rng = np.random.default_rng(seed)
    N = n_per_group * n_groups
    M = n_groups + extra_noise_metrics
    X = rng.normal(0, 1.0, size=(N, M, T))
    t = np.arange(T)
    true_labels = np.repeat(np.arange(n_groups), n_per_group)

    for node_i in range(N):
        group = true_labels[node_i]
        signal = np.sin(2 * np.pi * 3 * t / T) + rng.normal(0, 0.1, size=T)
        X[node_i, group, :] = signal

    return X, true_labels
