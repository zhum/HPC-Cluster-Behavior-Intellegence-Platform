"""MulTiDR: two-phase dimensionality reduction (paper Sec III-B-1).

Phase 1 (dr1_pca_over_time): per metric, PCA(n_components=1) over the (N, T)
slice compresses each node's temporal pattern into one "temporal variation"
scalar, preserving fine-grained per-metric temporal structure.

Phase 2 (dr2_umap): UMAP over the (N, M) per-metric summary embeds nodes into
2D for clustering/visualization.
"""
from __future__ import annotations

import numpy as np
import umap
from sklearn.decomposition import PCA


def dr1_pca_over_time(X: np.ndarray) -> np.ndarray:
    """X: (N, M, T) -> V: (N, M).

    For each metric m, standardizes X[:, m, :] (N, T) per-node across T
    (z-score each node's own time series), replaces any remaining NaN (from
    zero-variance rows or NaN gaps) with 0, then fits PCA(n_components=1) with
    rows=nodes, features=timesteps. V[:, m] is the first PC score per node.

    svd_solver is left at sklearn's "auto", which already switches to
    randomized SVD when a slice is large; forcing a solver here would perturb
    PC values and every downstream embedding for no runtime gain.
    """
    n, m, t = X.shape
    V = np.zeros((n, m), dtype=np.float64)
    if n == 0 or m == 0 or t == 0:
        return V

    for metric_i in range(m):
        S = X[:, metric_i, :]  # (N, T)
        mean = np.nanmean(S, axis=1, keepdims=True)
        std = np.nanstd(S, axis=1, keepdims=True)
        std_safe = np.where(std == 0, 1.0, std)
        Z = (S - mean) / std_safe
        Z = np.nan_to_num(Z, nan=0.0)

        pca = PCA(n_components=1, random_state=42)
        V[:, metric_i] = pca.fit_transform(Z)[:, 0]

    return V


def dr2_umap(
    V: np.ndarray,
    n_neighbors: int = 15,
    min_dist: float = 0.1,
    random_state: int = 42,
) -> np.ndarray:
    """V: (N, M) -> E: (N, 2).

    Paper defaults n_neighbors=15, min_dist=0.1 (Ganglia dataset); the Theta
    case used n_neighbors=50, min_dist=0.5 -- both are exposed as parameters
    so the UI can switch between them. n_neighbors is clamped to N-1 when N is
    small (UMAP requires n_neighbors < n_samples).
    """
    n = V.shape[0]
    effective_neighbors = max(1, min(n_neighbors, n - 1)) if n > 1 else 1
    reducer = umap.UMAP(
        n_neighbors=effective_neighbors,
        min_dist=min_dist,
        n_components=2,
        random_state=random_state,
    )
    return reducer.fit_transform(V)
