from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from tensor_store.nulls import all_metric_null_mask, null_segments


def _times(n: int, step_s: int = 15) -> np.ndarray:
    start = datetime(2026, 1, 1)
    return np.array(
        [np.datetime64(start + timedelta(seconds=step_s * i)) for i in range(n)]
    )


def test_all_metric_null_mask_requires_every_metric_nan():
    # 2 nodes, 2 metrics, 3 timesteps
    X = np.zeros((2, 2, 3))
    X[0, 0, 1] = np.nan
    X[0, 1, 1] = np.nan  # node 0, t=1: BOTH metrics nan -> null
    X[1, 0, 1] = np.nan  # node 1, t=1: only one metric nan -> not null
    mask = all_metric_null_mask(X)
    assert mask[0, 1] == True  # noqa: E712
    assert mask[1, 1] == False  # noqa: E712
    assert not mask[0, 0] and not mask[0, 2]


def test_injected_gap_produces_expected_segment():
    n_times = 10
    X = np.zeros((1, 2, n_times))
    gap_start, gap_end = 3, 6  # inclusive gap indices [3,4,5]
    X[0, :, gap_start:gap_end] = np.nan

    times = _times(n_times)
    segments = null_segments(X, ["node-0"], times)

    assert len(segments) == 1
    row = segments.iloc[0]
    assert row["node_id"] == "node-0"
    assert row["seg_start"] == times[gap_start]
    # seg_end is exclusive: one grid step past the last null timestamp
    assert row["seg_end"] == times[gap_end - 1] + (times[1] - times[0])


def test_multiple_disjoint_gaps():
    n_times = 12
    X = np.zeros((1, 1, n_times))
    X[0, 0, 2:4] = np.nan
    X[0, 0, 8:9] = np.nan

    times = _times(n_times)
    segments = null_segments(X, ["node-0"], times)

    assert len(segments) == 2
    assert segments.iloc[0]["seg_start"] == times[2]
    assert segments.iloc[1]["seg_start"] == times[8]


def test_no_gap_produces_no_segments():
    X = np.zeros((1, 1, 5))
    times = _times(5)
    segments = null_segments(X, ["node-0"], times)
    assert len(segments) == 0
