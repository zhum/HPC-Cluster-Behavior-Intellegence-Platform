"""Cluster quality metrics (paper Sec III-C; used in Phase 7 and exposed by
the Phase 5 API).
"""
from __future__ import annotations

import numpy as np
from sklearn.manifold import trustworthiness as _trustworthiness
from sklearn.metrics import calinski_harabasz_score, davies_bouldin_score, silhouette_score


def cluster_quality(E: np.ndarray, labels: np.ndarray) -> dict[str, float]:
    """Silhouette, Davies-Bouldin, Calinski-Harabasz on (E, labels).

    All three require at least 2 clusters with >=2 points total across >1
    label; returns NaN for degenerate inputs (e.g. a single cluster) rather
    than raising, since the UI may call this speculatively while k is small.
    """
    n_unique = len(np.unique(labels))
    if n_unique < 2 or E.shape[0] < 2:
        return {
            "silhouette": float("nan"),
            "davies_bouldin": float("nan"),
            "calinski_harabasz": float("nan"),
        }
    return {
        "silhouette": float(silhouette_score(E, labels)),
        "davies_bouldin": float(davies_bouldin_score(E, labels)),
        "calinski_harabasz": float(calinski_harabasz_score(E, labels)),
    }


def trustworthiness_continuity(V: np.ndarray, E: np.ndarray, n_neighbors: int = 5) -> tuple[float, float]:
    """Trustworthiness/continuity between the first-pass result V and the
    2D embedding E. Continuity is trustworthiness with roles swapped
    (sklearn has no separate continuity implementation).
    """
    n = V.shape[0]
    k = max(1, min(n_neighbors, n - 1)) if n > 1 else 1
    trust = float(_trustworthiness(V, E, n_neighbors=k))
    continuity = float(_trustworthiness(E, V, n_neighbors=k))
    return trust, continuity
