"""Staged, cached inter-cluster pipeline: tensor -> V (dr1) -> E (dr2) ->
labels (kmeans) -> ccpca weights.

Each stage is cached in-process keyed by hash(stage name + params); changing
k re-runs only kmeans + ccpca (recluster()), changing UMAP params re-runs dr2
onward, changing the tensor (a new pipeline instance) invalidates everything.
Redis-backed cross-process caching is added in Phase 5 (analysis-api); this
is the in-process LRU half of that design.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np

from analysis_core.inter.ccpca import CCPCAResult, ccpca_explain
from analysis_core.inter.clustering import kmeans_cluster
from analysis_core.inter.multidr import dr1_pca_over_time, dr2_umap


def _key(stage: str, params: dict[str, Any]) -> str:
    payload = json.dumps({"stage": stage, "params": params}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class InterClusterPipeline:
    def __init__(self, X: np.ndarray) -> None:
        self.X = X
        self._cache: dict[str, Any] = {}

    def get_V(self) -> np.ndarray:
        key = _key("V", {})
        if key not in self._cache:
            self._cache[key] = dr1_pca_over_time(self.X)
        return self._cache[key]

    def get_E(self, n_neighbors: int = 15, min_dist: float = 0.1, random_state: int = 42) -> np.ndarray:
        V = self.get_V()
        key = _key("E", {"n_neighbors": n_neighbors, "min_dist": min_dist, "random_state": random_state})
        if key not in self._cache:
            self._cache[key] = dr2_umap(V, n_neighbors=n_neighbors, min_dist=min_dist, random_state=random_state)
        return self._cache[key]

    def get_labels(
        self,
        k: int = 4,
        n_neighbors: int = 15,
        min_dist: float = 0.1,
        random_state: int = 42,
        n_init: int = 10,
    ) -> tuple[np.ndarray, np.ndarray]:
        E = self.get_E(n_neighbors=n_neighbors, min_dist=min_dist, random_state=random_state)
        key = _key(
            "labels",
            {"k": k, "n_neighbors": n_neighbors, "min_dist": min_dist, "random_state": random_state, "n_init": n_init},
        )
        if key not in self._cache:
            self._cache[key] = kmeans_cluster(E, k=k, random_state=random_state, n_init=n_init)
        return self._cache[key]

    def get_ccpca(
        self,
        k: int = 4,
        n_neighbors: int = 15,
        min_dist: float = 0.1,
        random_state: int = 42,
        n_init: int = 10,
    ) -> list[CCPCAResult]:
        V = self.get_V()
        labels, _ = self.get_labels(
            k=k, n_neighbors=n_neighbors, min_dist=min_dist, random_state=random_state, n_init=n_init
        )
        key = _key(
            "ccpca",
            {"k": k, "n_neighbors": n_neighbors, "min_dist": min_dist, "random_state": random_state, "n_init": n_init},
        )
        if key not in self._cache:
            self._cache[key] = ccpca_explain(V, labels)
        return self._cache[key]

    def recluster(
        self, k: int, n_neighbors: int = 15, min_dist: float = 0.1, random_state: int = 42, n_init: int = 10
    ) -> tuple[np.ndarray, np.ndarray, list[CCPCAResult]]:
        """Cheap: reuses the cached E (dr1+dr2 never re-run), only kmeans and
        ccpca are recomputed for the new k.
        """
        labels, centroids = self.get_labels(
            k=k, n_neighbors=n_neighbors, min_dist=min_dist, random_state=random_state, n_init=n_init
        )
        ccpca = self.get_ccpca(
            k=k, n_neighbors=n_neighbors, min_dist=min_dist, random_state=random_state, n_init=n_init
        )
        return labels, centroids, ccpca
