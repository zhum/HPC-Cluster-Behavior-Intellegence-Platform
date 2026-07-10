from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from tensor_store.grid import resample_to_grid
from tensor_store.tensor import bucketed_to_tensor, pivot_tensor


def test_round_trip_exact_values(synthetic_long_df, synthetic_window):
    start, end = synthetic_window
    df_grid = resample_to_grid(synthetic_long_df, start, end, resolution_s=15)
    X, nodes, metrics, times = pivot_tensor(df_grid)

    assert X.shape == (3, 2, 10)
    assert nodes == ["node-0", "node-1", "node-2"]
    assert metrics == ["cpu.utilization", "memory.used"]
    assert len(times) == 10

    for n_i in range(3):
        for m_i in range(2):
            for t_i in range(10):
                expected = n_i * 100 + m_i * 10 + t_i
                assert X[n_i, m_i, t_i] == expected


def test_pivot_stable_shape_with_missing_combo():
    import pandas as pd

    df_grid = pd.DataFrame(
        {
            "ts": pd.to_datetime(["2026-01-01T00:00:00"]),
            "node_id": ["node-0"],
            "metric": ["cpu.utilization"],
            "value": [1.0],
        }
    )
    X, nodes, metrics, times = pivot_tensor(
        df_grid, nodes=["node-0", "node-1"], metrics=["cpu.utilization", "memory.used"]
    )
    assert X.shape == (2, 2, 1)
    assert np.isnan(X[1, 0, 0])
    assert np.isnan(X[0, 1, 0])
    assert X[0, 0, 0] == 1.0


def test_empty_input_produces_zero_length_time_axis():
    import pandas as pd

    empty = pd.DataFrame(columns=["ts", "node_id", "metric", "value"])
    X, nodes, metrics, times = pivot_tensor(empty, nodes=["node-0"], metrics=["cpu.utilization"])
    assert X.shape == (1, 1, 0)
    assert len(times) == 0


def test_bucketed_to_tensor_matches_pivot_tensor(synthetic_long_df, synthetic_window):
    """bucketed_to_tensor (the wide-frame fast path) must produce the same
    tensor as resample_to_grid + pivot_tensor (the long-format path) when fed
    the same already-gridded rows.
    """
    start, end = synthetic_window
    df_grid = resample_to_grid(synthetic_long_df, start, end, resolution_s=15)
    X_slow, nodes, metrics, times_slow = pivot_tensor(df_grid)

    X_fast, nodes_fast, metrics_fast, times_fast = bucketed_to_tensor(
        synthetic_long_df, nodes, metrics, start, end, resolution_s=15
    )

    assert nodes_fast == nodes
    assert metrics_fast == metrics
    np.testing.assert_array_equal(times_fast, times_slow)
    np.testing.assert_allclose(X_fast, X_slow)


def test_bucketed_to_tensor_ffill_limit_stops_at_boundary():
    """Numpy-scatter ffill must reproduce pandas ffill(limit=n) semantics:
    same case as test_ffill_limit_stops_at_boundary in test_grid.py, but
    exercising bucketed_to_tensor's own vectorized forward-fill pass.
    """
    start = datetime(2026, 1, 1)
    end = start + timedelta(seconds=15 * 6)
    df = pd.DataFrame(
        {
            "ts": [start],
            "node_id": ["node-0"],
            "metric": ["cpu.utilization"],
            "value": [42.0],
        }
    )
    X, nodes, metrics, times = bucketed_to_tensor(
        df, nodes=["node-0"], metrics=["cpu.utilization"], start=start, end=end, resolution_s=15, ffill_limit=2
    )
    values = X[0, 0, :]
    assert values[0] == 42.0
    assert values[1] == 42.0
    assert values[2] == 42.0
    assert np.isnan(values[3])
    assert np.isnan(values[4])
    assert np.isnan(values[5])


def test_bucketed_to_tensor_stable_shape_with_missing_combo():
    df = pd.DataFrame(
        {
            "ts": pd.to_datetime(["2026-01-01T00:00:00"]),
            "node_id": ["node-0"],
            "metric": ["cpu.utilization"],
            "value": [1.0],
        }
    )
    start = datetime(2026, 1, 1)
    end = start + timedelta(seconds=15)
    X, nodes, metrics, times = bucketed_to_tensor(
        df, nodes=["node-0", "node-1"], metrics=["cpu.utilization", "memory.used"],
        start=start, end=end, resolution_s=15,
    )
    assert X.shape == (2, 2, 1)
    assert np.isnan(X[1, 0, 0])
    assert np.isnan(X[0, 1, 0])
    assert X[0, 0, 0] == 1.0


def test_bucketed_to_tensor_empty_input():
    empty = pd.DataFrame(columns=["ts", "node_id", "metric", "value"])
    start = datetime(2026, 1, 1)
    end = start + timedelta(seconds=15)
    X, nodes, metrics, times = bucketed_to_tensor(
        empty, nodes=["node-0"], metrics=["cpu.utilization"], start=start, end=end, resolution_s=15
    )
    assert X.shape == (1, 1, 1)
    assert np.isnan(X).all()
