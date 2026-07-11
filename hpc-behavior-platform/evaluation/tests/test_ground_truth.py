from __future__ import annotations

import numpy as np

from evaluation.ground_truth import nodes_overlapping_job, precision_at_k, rank_nodes_by_anomaly


def test_rank_nodes_by_anomaly_1d():
    z = np.array([0.5, -4.0, 1.0, 3.5])
    nodes = ["a", "b", "c", "d"]
    assert rank_nodes_by_anomaly(z, nodes) == ["b", "d", "c", "a"]


def test_rank_nodes_by_anomaly_2d_uses_max_abs_across_metrics():
    z = np.array([[0.1, 0.2], [5.0, -1.0], [0.3, -6.0]])
    nodes = ["a", "b", "c"]
    assert rank_nodes_by_anomaly(z, nodes) == ["c", "b", "a"]


def test_precision_at_k():
    ranked = ["a", "b", "c", "d", "e"]
    incidents = {"a", "c", "z"}
    assert precision_at_k(ranked, incidents, k=2) == 0.5  # a hit, b miss
    assert precision_at_k(ranked, incidents, k=5) == 2 / 5


def test_precision_at_k_empty_ranking():
    assert precision_at_k([], {"a"}, k=3) == 0.0


def test_nodes_overlapping_job_matches_time_window():
    jobs = [
        {"job_id": "j1", "node_id": "node-0", "start": "2026-01-01T00:00:00", "end": "2026-01-01T01:00:00"},
        {"job_id": "j2", "node_id": "node-0", "start": "2026-01-01T02:00:00", "end": None},
        {"job_id": "j3", "node_id": "node-1", "start": "2026-01-01T00:00:00", "end": "2026-01-01T01:00:00"},
    ]
    hits = nodes_overlapping_job("node-0", "2026-01-01T00:30:00", jobs)
    assert [h["job_id"] for h in hits] == ["j1"]

    ongoing = nodes_overlapping_job("node-0", "2026-01-01T03:00:00", jobs)
    assert [h["job_id"] for h in ongoing] == ["j2"]

    none_mapped = nodes_overlapping_job("node-0", "2026-01-01T01:30:00", jobs)
    assert none_mapped == []
