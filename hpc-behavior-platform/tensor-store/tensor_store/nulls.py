"""Per-(node, timestamp) all-metrics-null detection -> downtime segments.

Drives the Time Domain view (Phase 6): a node with no reading across every
metric at a timestamp is treated as down/unreachable, not merely missing one
metric.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def all_metric_null_mask(X: np.ndarray) -> np.ndarray:
    """X: (N, M, T) -> (N, T) bool mask, True where ALL metrics are NaN."""
    if X.shape[2] == 0:
        return np.zeros((X.shape[0], 0), dtype=bool)
    return np.all(np.isnan(X), axis=1)


def null_segments(
    X: np.ndarray, nodes: list[str], times: np.ndarray
) -> pd.DataFrame:
    """Returns a dataframe [node_id, seg_start, seg_end] of contiguous
    all-metric-null runs per node. seg_end is exclusive (one grid step past
    the last null timestamp).
    """
    mask = all_metric_null_mask(X)
    rows: list[dict[str, object]] = []
    n_times = mask.shape[1]

    if n_times == 0:
        return pd.DataFrame(columns=["node_id", "seg_start", "seg_end"])

    step = times[1] - times[0] if n_times > 1 else np.timedelta64(0, "s")

    for i, node_id in enumerate(nodes):
        is_null = mask[i]
        # find contiguous True runs
        diff = np.diff(is_null.astype(np.int8), prepend=0, append=0)
        starts = np.where(diff == 1)[0]
        ends = np.where(diff == -1)[0]  # exclusive end index into `times`
        for s, e in zip(starts, ends):
            rows.append(
                {
                    "node_id": node_id,
                    "seg_start": times[s],
                    "seg_end": times[e - 1] + step if e - 1 < n_times else times[e - 1],
                }
            )

    return pd.DataFrame(rows, columns=["node_id", "seg_start", "seg_end"])
