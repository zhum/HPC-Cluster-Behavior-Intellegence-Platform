from __future__ import annotations

import numpy as np

from analysis_core.inter.incremental import (
    IncrementalInterPipeline,
    RollingWindow,
    hungarian_relabel,
    procrustes_align,
)


def test_rolling_window_bounds_to_window_size():
    window = RollingWindow(window_size=5)
    nodes = ["a", "b"]
    X1 = np.arange(2 * 1 * 3).reshape(2, 1, 3).astype(float)
    out1 = window.append(X1, nodes)
    assert out1.shape == (2, 1, 3)

    X2 = np.arange(2 * 1 * 4).reshape(2, 1, 4).astype(float) + 100
    out2 = window.append(X2, nodes)
    assert out2.shape == (2, 1, 5)  # capped at window_size, not 3+4=7
    # the tail should be the most recent 5 timesteps (last 1 of X1 + all of X2)
    np.testing.assert_allclose(out2[:, :, 1:], X2)


def test_rolling_window_resets_when_node_set_changes():
    window = RollingWindow(window_size=5)
    X1 = np.ones((2, 1, 3))
    window.append(X1, ["a", "b"])

    X2 = np.full((3, 1, 2), 9.0)
    out2 = window.append(X2, ["a", "b", "c"])
    assert out2.shape == (3, 1, 2)  # reset, not concatenated onto the old (2-node) history


def test_procrustes_align_recovers_known_rotation_scale_translation():
    rng = np.random.default_rng(0)
    ref_E = rng.normal(size=(10, 2))
    nodes = [f"n{i}" for i in range(10)]

    theta = 0.7
    R = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    scale = 3.0
    translation = np.array([5.0, -2.0])
    new_E = scale * ref_E @ R + translation

    aligned = procrustes_align(ref_E, new_E, nodes, nodes)
    np.testing.assert_allclose(aligned, ref_E, atol=1e-6)


def test_procrustes_align_uses_only_common_nodes_but_transforms_all_points():
    rng = np.random.default_rng(0)
    ref_E = rng.normal(size=(5, 2))
    ref_nodes = ["a", "b", "c", "d", "e"]

    # new_E has an extra node "f" that ref never saw
    theta = 0.3
    R = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    new_nodes = ["a", "b", "c", "d", "e", "f"]
    new_raw = np.vstack([ref_E, rng.normal(size=(1, 2))])
    new_E = new_raw @ R + np.array([1.0, 1.0])

    aligned = procrustes_align(ref_E, new_E, ref_nodes, new_nodes)
    assert aligned.shape == (6, 2)
    np.testing.assert_allclose(aligned[:5], ref_E, atol=1e-6)


def test_procrustes_align_returns_unchanged_with_fewer_than_2_common_nodes():
    new_E = np.array([[1.0, 2.0], [3.0, 4.0]])
    aligned = procrustes_align(np.zeros((0, 2)), new_E, [], ["x", "y"])
    np.testing.assert_array_equal(aligned, new_E)


def test_hungarian_relabel_recovers_shuffled_labels():
    prev_nodes = ["a", "b", "c", "d"]
    prev_labels = np.array([0, 0, 1, 1])
    new_nodes = ["a", "b", "c", "d"]
    # same clustering, but k-means happened to assign the opposite IDs this time
    new_labels = np.array([1, 1, 0, 0])

    remapped = hungarian_relabel(prev_labels, new_labels, prev_nodes, new_nodes)
    np.testing.assert_array_equal(remapped, prev_labels)


def test_hungarian_relabel_assigns_fresh_id_to_new_cluster():
    prev_nodes = ["a", "b"]
    prev_labels = np.array([0, 0])
    new_nodes = ["a", "b", "c", "d"]
    new_labels = np.array([0, 0, 1, 1])  # a genuinely new cluster (1) appears

    remapped = hungarian_relabel(prev_labels, new_labels, prev_nodes, new_nodes)
    assert remapped[0] == 0 and remapped[1] == 0
    assert remapped[2] == remapped[3]
    assert remapped[2] != 0  # fresh id, not colliding with the matched cluster 0


def _planted_two_cluster_tensor(n_per_group, T, seed):
    rng = np.random.default_rng(seed)
    n = n_per_group * 2
    X = rng.normal(0, 1.0, size=(n, 2, T))
    t = np.arange(T)
    true_labels = np.repeat([0, 1], n_per_group)
    for i in range(n):
        g = true_labels[i]
        X[i, g, :] = np.sin(2 * np.pi * 3 * t / T) + rng.normal(0, 0.1, T)
    return X, true_labels


def test_incremental_pipeline_same_nodes_uses_transform_and_keeps_labels_stable():
    X1, true_labels = _planted_two_cluster_tensor(n_per_group=8, T=60, seed=0)
    nodes = [f"node-{i}" for i in range(len(true_labels))]

    pipeline = IncrementalInterPipeline(window_size=60, n_neighbors=5)
    result1 = pipeline.refresh(X1, nodes, k=2)

    # second refresh: same nodes, slightly perturbed values (simulating new
    # timesteps arriving) -- transform() should be used, not a refit.
    rng = np.random.default_rng(1)
    X2 = X1 + rng.normal(0, 0.01, size=X1.shape)
    result2 = pipeline.refresh(X2, nodes, k=2)

    assert result2.E.shape == result1.E.shape
    # cluster identity persisted: nodes that were together before are still together
    for g in (0, 1):
        members = [i for i, tl in enumerate(true_labels) if tl == g]
        labels_for_group = result2.labels[members]
        assert len(set(labels_for_group)) == 1


def test_incremental_pipeline_new_node_triggers_realign_and_preserves_prior_positions():
    X1, true_labels = _planted_two_cluster_tensor(n_per_group=8, T=60, seed=0)
    nodes1 = [f"node-{i}" for i in range(len(true_labels))]

    pipeline = IncrementalInterPipeline(window_size=60, n_neighbors=5)
    result1 = pipeline.refresh(X1, nodes1, k=2)

    # add one new node -- forces a UMAP refit + Procrustes realignment
    rng = np.random.default_rng(2)
    new_row = rng.normal(0, 1.0, size=(1, 2, 60))
    X2 = np.concatenate([X1, new_row], axis=0)
    nodes2 = nodes1 + ["node-new"]

    result2 = pipeline.refresh(X2, nodes2, k=2)

    assert result2.E.shape == (len(nodes2), 2)
    # existing nodes' cluster identity should persist despite the refit
    for g in (0, 1):
        members = [i for i, tl in enumerate(true_labels) if tl == g]
        labels_for_group = result2.labels[members]
        assert len(set(labels_for_group)) == 1
