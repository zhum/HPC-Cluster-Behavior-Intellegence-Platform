"""Ground-truth cross-check (Phase 7 item 3): join detected anomalies
against known incidents (from `jobs` or an operator logbook) and compute
precision@k. Pure functions -- no live ClickHouse dependency -- so this is
testable against synthetic incident labels; wiring a real jobs/logbook query
in is a matter of producing the same (ranked node list, incident set) shape.
"""
from __future__ import annotations

import numpy as np


def rank_nodes_by_anomaly(z: np.ndarray, node_ids: list[str]) -> list[str]:
    """z: (N,) or (N, M) z-scores. Ranks nodes by max |z| across metrics,
    descending (most anomalous first).
    """
    scores = np.max(np.abs(z), axis=1) if z.ndim == 2 else np.abs(z)
    order = np.argsort(-scores)
    return [node_ids[i] for i in order]


def precision_at_k(ranked_node_ids: list[str], known_incident_nodes: set[str], k: int) -> float:
    """Fraction of the top-k ranked nodes that are confirmed incidents."""
    if k <= 0:
        return 0.0
    top_k = ranked_node_ids[:k]
    hits = sum(1 for n in top_k if n in known_incident_nodes)
    return hits / min(k, len(ranked_node_ids)) if ranked_node_ids else 0.0


def nodes_overlapping_job(
    node_id: str, anomaly_time: str, job_intervals: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Jobs from `jobs` (or an operator logbook table with the same shape)
    whose [start, end) window covers `anomaly_time` on `node_id` -- used to
    annotate whether a detected anomaly coincides with a running job, or is
    "not mapped to any jobs" (paper's finding for some Ganglia anomalies).
    """
    hits = []
    for job in job_intervals:
        if job.get("node_id") != node_id:
            continue
        start = job["start"]
        end = job.get("end")
        if start <= anomaly_time and (end is None or anomaly_time < end):
            hits.append(job)
    return hits
