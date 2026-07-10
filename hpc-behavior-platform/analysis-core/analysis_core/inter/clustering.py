"""k-means clustering over the 2D MulTiDR embedding."""
from __future__ import annotations

import numpy as np
from sklearn.cluster import KMeans


def kmeans_cluster(
    E: np.ndarray, k: int = 4, random_state: int = 42, n_init: int = 10
) -> tuple[np.ndarray, np.ndarray]:
    """E: (N, 2) -> (labels: (N,), centroids: (k, 2))."""
    model = KMeans(n_clusters=k, random_state=random_state, n_init=n_init)
    labels = model.fit_predict(E)
    return labels, model.cluster_centers_


def recluster(E: np.ndarray, k: int, random_state: int = 42, n_init: int = 10) -> tuple[np.ndarray, np.ndarray]:
    """Cheap re-clustering call: operates on an already-computed embedding E
    (e.g. from InterClusterPipeline's cache), so changing k never re-runs
    dr1/dr2.
    """
    return kmeans_cluster(E, k=k, random_state=random_state, n_init=n_init)
