from __future__ import annotations

import numpy as np

from analysis_core.inter.clustering import kmeans_cluster, recluster


def test_kmeans_shapes():
    E = np.random.default_rng(0).normal(size=(20, 2))
    labels, centroids = kmeans_cluster(E, k=3)
    assert labels.shape == (20,)
    assert centroids.shape == (3, 2)
    assert set(labels) <= {0, 1, 2}


def test_kmeans_deterministic():
    E = np.random.default_rng(0).normal(size=(20, 2))
    labels1, _ = kmeans_cluster(E, k=3, random_state=42)
    labels2, _ = kmeans_cluster(E, k=3, random_state=42)
    np.testing.assert_array_equal(labels1, labels2)


def test_recluster_matches_kmeans_cluster():
    E = np.random.default_rng(0).normal(size=(20, 2))
    labels_a, _ = kmeans_cluster(E, k=4, random_state=42)
    labels_b, _ = recluster(E, k=4, random_state=42)
    np.testing.assert_array_equal(labels_a, labels_b)
