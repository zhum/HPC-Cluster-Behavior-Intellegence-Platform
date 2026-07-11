"""Phase 8 item 1 (optional, beyond the paper): incremental refresh.

Reproducing Phase 3's cluster analysis from scratch on every refresh has two
problems for a live dashboard: (1) it recomputes dr1 over the entire
cumulative history instead of a bounded rolling window, and (2) UMAP has no
fixed coordinate system between independent fits -- points can jump around
and cluster IDs can get reshuffled even when the underlying data barely
changed, which is disorienting for an operator watching the view. This
module addresses both:

- RollingWindow: bounds dr1's input to the last `window_size` timesteps
  instead of an ever-growing history.
- IncrementalInterPipeline: reuses a fitted UMAP model's `.transform()` for
  refreshes where the node set is unchanged (stable, cheap, no coordinate
  jump by construction); when the node set DOES change (nodes added/removed
  -> UMAP must refit), the new embedding is Procrustes-aligned to the
  previous one so coordinates stay visually stable; and k-means labels are
  Hungarian-matched to the previous run's labels so cluster identity/colors
  persist across refreshes even though k-means itself has no notion of
  label continuity.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import umap
from scipy.optimize import linear_sum_assignment

from analysis_core.inter.clustering import kmeans_cluster
from analysis_core.inter.multidr import dr1_pca_over_time


@dataclass
class RollingWindow:
    """Bounds dr1's input to the most recent `window_size` timesteps."""

    window_size: int
    X: np.ndarray | None = field(default=None, repr=False)
    nodes: list[str] | None = field(default=None, repr=False)

    def append(self, X_new: np.ndarray, nodes: list[str]) -> np.ndarray:
        """X_new: (N, M, T_new) newest timesteps for `nodes`. Returns the
        current windowed tensor (N, M, <=window_size), oldest timesteps
        dropped. If the node set differs from the last call (nodes
        added/removed), there's no shared history to merge -- the window
        resets to X_new (still capped at window_size).
        """
        if self.X is None or self.nodes != nodes:
            self.X = X_new[:, :, -self.window_size :]
        else:
            combined = np.concatenate([self.X, X_new], axis=2)
            self.X = combined[:, :, -self.window_size :]
        self.nodes = nodes
        return self.X


def procrustes_align(ref_E: np.ndarray, new_E: np.ndarray, ref_nodes: list[str], new_nodes: list[str]) -> np.ndarray:
    """Similarity-transform (rotation + uniform scale + translation) new_E
    onto ref_E's coordinate system, fit on the nodes common to both, then
    applied to every point in new_E (including nodes ref_E never saw).
    Returns new_E unchanged if there are fewer than 2 common nodes (not
    enough to fit a stable transform).
    """
    ref_idx = {n: i for i, n in enumerate(ref_nodes)}
    common = [n for n in new_nodes if n in ref_idx]
    if len(common) < 2:
        return new_E

    new_idx = {n: i for i, n in enumerate(new_nodes)}
    A = np.array([new_E[new_idx[n]] for n in common])  # to be aligned
    B = np.array([ref_E[ref_idx[n]] for n in common])  # reference

    A_mean, B_mean = A.mean(axis=0), B.mean(axis=0)
    A_c, B_c = A - A_mean, B - B_mean

    U, S, Vt = np.linalg.svd(A_c.T @ B_c)
    R = U @ Vt
    denom = np.sum(A_c**2)
    scale = float(np.sum(S) / denom) if denom > 0 else 1.0

    return scale * (new_E - A_mean) @ R + B_mean


def hungarian_relabel(
    prev_labels: np.ndarray, new_labels: np.ndarray, prev_nodes: list[str], new_nodes: list[str]
) -> np.ndarray:
    """Remaps new_labels' cluster IDs to match prev_labels' IDs by maximum
    overlap on the nodes common to both runs (Hungarian algorithm), so
    cluster identity/colors persist across refreshes. New cluster IDs with
    no good match (e.g. k increased) get fresh IDs beyond the previous max.
    """
    prev_idx = {n: i for i, n in enumerate(prev_nodes)}
    new_idx = {n: i for i, n in enumerate(new_nodes)}
    common = [n for n in new_nodes if n in prev_idx]
    if not common:
        return new_labels

    prev_k = int(prev_labels.max()) + 1
    new_k = int(new_labels.max()) + 1
    overlap = np.zeros((new_k, prev_k))
    for n in common:
        overlap[new_labels[new_idx[n]], prev_labels[prev_idx[n]]] += 1

    row_ind, col_ind = linear_sum_assignment(-overlap)
    mapping = {int(r): int(c) for r, c in zip(row_ind, col_ind) if overlap[r, c] > 0}

    next_id = prev_k
    for nid in range(new_k):
        if nid not in mapping:
            mapping[nid] = next_id
            next_id += 1

    return np.array([mapping[label] for label in new_labels])


@dataclass
class RefreshResult:
    E: np.ndarray
    labels: np.ndarray
    centroids: np.ndarray
    nodes: list[str]


class IncrementalInterPipeline:
    def __init__(self, window_size: int, n_neighbors: int = 15, min_dist: float = 0.1, random_state: int = 42) -> None:
        self.window = RollingWindow(window_size)
        self.n_neighbors = n_neighbors
        self.min_dist = min_dist
        self.random_state = random_state

        self._umap_model: umap.UMAP | None = None
        self._prev_E: np.ndarray | None = None
        self._prev_labels: np.ndarray | None = None
        self._prev_nodes: list[str] | None = None

    def refresh(self, X_new: np.ndarray, nodes: list[str], k: int) -> RefreshResult:
        X = self.window.append(X_new, nodes)
        V = dr1_pca_over_time(X)

        same_nodes = self._prev_nodes is not None and nodes == self._prev_nodes
        if self._umap_model is not None and same_nodes:
            # unchanged node set: transform() is both cheap and stable by
            # construction (no refit, so no coordinate jump at all).
            E = self._umap_model.transform(V)
        else:
            effective_neighbors = max(1, min(self.n_neighbors, len(nodes) - 1)) if len(nodes) > 1 else 1
            self._umap_model = umap.UMAP(
                n_neighbors=effective_neighbors,
                min_dist=self.min_dist,
                n_components=2,
                random_state=self.random_state,
            )
            E = self._umap_model.fit_transform(V)
            if self._prev_E is not None and self._prev_nodes is not None:
                E = procrustes_align(self._prev_E, E, self._prev_nodes, nodes)

        labels, centroids = kmeans_cluster(E, k=k, random_state=self.random_state)
        if self._prev_labels is not None and self._prev_nodes is not None:
            labels = hungarian_relabel(self._prev_labels, labels, self._prev_nodes, nodes)
            # recompute centroids in the now-relabeled order
            centroids = np.array([E[labels == c].mean(axis=0) for c in range(int(labels.max()) + 1)])

        self._prev_E, self._prev_labels, self._prev_nodes = E, labels, nodes
        return RefreshResult(E=E, labels=labels, centroids=centroids, nodes=nodes)
